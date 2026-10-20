import Foundation
import SwiftUI
import CoreLocation
import RailVeloCore
import RailVeloSQLite
import RailVeloLocation
import RailVeloRecording

/// All inference and database I/O stay on this queue, including pause/end barriers.
private final class RideWorker {
    let queue = DispatchQueue(label: "jp.kb-dev.railvelo.recording", qos: .userInitiated)
    var network: Network!
    var store: RideStore!
    var processor: RideProcessor?

    func perform<T>(_ operation: @escaping (RideWorker) throws -> T,
                    completion: @escaping (Result<T, Error>) -> Void) {
        queue.async {
            let result = Result { try operation(self) }
            DispatchQueue.main.async { completion(result) }
        }
    }
}

@MainActor final class RideViewModel: ObservableObject {
    @Published var mode: RideMode = .live
    @Published var state = "idle"
    @Published var speedKmh: Double?
    @Published var maximumSpeedKmh = 0.0
    @Published var horizontalAccuracyM: Double?
    @Published var speedAccuracyMps: Double?
    @Published var signalText = "記録を開始してください"
    @Published var routeName = "判定待機"
    @Published var directionText = "判定待機"
    @Published var previousStation = "—"
    @Published var nextStation = "—"
    @Published var distanceToNextM: Double?
    @Published var progress: Double?
    @Published var confidence = 0.0
    @Published var lastSectionText = ""
    @Published var message: String?
    @Published var points: [SpeedPoint] = []
    @Published var historyPoints: [SpeedPoint] = []
    @Published var history: [RideSummary] = []
    @Published var exportURL: URL?
    private let worker = RideWorker()
    private let live = CoreLocationSource()
    private var source: (any ObservationSource)?
    private var sessionID: String?
    private var sourceMode: RideMode = .live
    private var replay: ReplayObservationSource?
    private var generation = UUID()
    private var ready = false
    private var transitioning = false
    private var permissionPending = false
    private var lastReceipt = Date.distantPast
    private var lastObservationTime: Double?
    private var watchdog: Timer?
    private var segment = 0
    private var previousPoint: SpeedPoint?
    private var historySelection: String?
    private var lastGraphRefresh = 0.0

    init() {
        live.onAuthorizationChange = { [weak self] status in
            guard let self else { return }
            if status == .authorizedWhenInUse || status == .authorizedAlways {
                if self.permissionPending { self.permissionPending = false; self.start() }
            } else if status == .denied || status == .restricted {
                self.permissionPending = false
                self.message = "位置情報を利用できません。設定アプリでRailVeloの位置情報を許可してください。"
                if self.sourceMode == .live && self.state == "recording" { self.pause() }
            }
        }
        let database = Bundle.main.url(forResource: "railway", withExtension: "sqlite")
        worker.perform({ worker in
            guard let database else { throw AppError.missingResource("railway.sqlite") }
            worker.network = try SQLiteNetworkLoader.load(url: database)
            let root = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                                    appropriateFor: nil, create: true).appendingPathComponent("RailVelo", isDirectory: true)
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
            try FileManager.default.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: root.path)
            var directory = root
            var values = URLResourceValues(); values.isExcludedFromBackup = true
            try directory.setResourceValues(values)
            worker.store = try RideStore(url: root.appendingPathComponent("rides.sqlite"))
            try worker.store.recoverInterrupted(at: Date().timeIntervalSince1970)
            return try worker.store.summaries()
        }, completion: { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let summaries):
                self.ready = true; self.history = summaries
                if ProcessInfo.processInfo.arguments.contains("--replay-smoke") {
                    self.mode = .replay; self.start()
                }
            case .failure(let error): self.message = "初期化に失敗しました: \(error.localizedDescription)"
            }
        })
    }

    func start() {
        guard ready, !transitioning, state == "idle" || state == "finished" else { return }
        message = nil
        if mode == .live {
            if live.authorizationStatus == .notDetermined {
                permissionPending = true; live.requestWhenInUseAuthorization(); return
            }
            guard live.authorizationStatus == .authorizedAlways || live.authorizationStatus == .authorizedWhenInUse else {
                message = "設定アプリで位置情報を許可してください。リプレイは許可なしでも利用できます。"; return
            }
        }
        sourceMode = mode
        if sourceMode == .replay {
            do {
                guard let url = Bundle.main.url(forResource: "corridor_full", withExtension: "jsonl") else {
                    throw AppError.missingResource("corridor_full.jsonl")
                }
                replay = try ReplayObservationSource(url: url)
                source = replay
            } catch { message = "リプレイを読み込めません: \(error.localizedDescription)"; return }
        } else { source = live }
        transitioning = true
        let currentMode = sourceMode
        generation = UUID()
        let token = generation
        worker.perform({ worker in
            try worker.store.recoverInterrupted(at: Date().timeIntervalSince1970)
            worker.processor = RideProcessor(network: worker.network)
            return try worker.store.begin(mode: currentMode, at: Date().timeIntervalSince1970)
        }, completion: { [weak self] result in
            guard let self, self.generation == token else { return }
            self.transitioning = false
            switch result {
            case .success(let id):
                self.mode = currentMode
                self.sessionID = id; self.points = []; self.previousPoint = nil; self.segment = 0
                self.sessionOverview = []; self.lastGraphRefresh = 0
                self.maximumSpeedKmh = 0; self.speedKmh = nil; self.lastObservationTime = nil
                self.lastSectionText = ""; self.clearMatch(); self.state = "recording"
                self.connectSource(token: token); self.refreshHistory()
            case .failure(let error): self.storageFailure(error)
            }
        })
    }

    private func connectSource(token: UUID) {
        lastReceipt = Date()
        source?.onObservations = { [weak self] observations in
            guard let self, self.generation == token, self.state == "recording" else { return }
            self.lastReceipt = Date()
            for observation in observations { self.ingest(observation, token: token) }
        }
        source?.onFailure = { [weak self] detail in
            guard let self, self.state == "recording", self.generation == token else { return }
            self.message = "GPS: \(detail)"
            self.insertGap(token: token)
        }
        replay?.onCompletion = { [weak self] in self?.finish() }
        source?.start()
        if sourceMode == .live {
            signalText = live.hasPreciseLocation ? "測位待機" : "概算位置（正確な位置情報を推奨）"
            watchdog?.invalidate()
            watchdog = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
                Task { @MainActor in
                    guard let self, self.state == "recording", Date().timeIntervalSince(self.lastReceipt) >= 5 else { return }
                    self.insertGap(token: token)
                }
            }
        } else { signalText = "リプレイ・合成GPS（25倍速）" }
    }

    private func insertGap(token: UUID) {
        guard sourceMode == .live else { return }
        let time = Date().timeIntervalSince1970
        if let lastObservationTime, time <= lastObservationTime { return }
        speedKmh = nil; clearMatch(); signalText = "測位不能・速度取得なし"
        ingest(Observation(timestamp: time, lat: nil, lon: nil, horizontalAccuracyM: -1), token: token)
    }

    private func ingest(_ observation: Observation, token: UUID) {
        guard let id = sessionID else { return }
        let receivedAt = sourceMode == .live ? Date().timeIntervalSince1970 : nil
        if observation.timestamp.isFinite,
           receivedAt == nil || (observation.timestamp <= receivedAt! + 5 && observation.timestamp >= receivedAt! - 10) {
            lastObservationTime = max(lastObservationTime ?? observation.timestamp, observation.timestamp)
        }
        worker.perform({ worker -> (RecordedSample, Double, String?, String?, String?) in
            guard let processor = worker.processor else { throw AppError.notRecording }
            let sample = processor.process(observation, receivedAt: receivedAt)
            try worker.store.append(sample, to: id, recordedAt: Date().timeIntervalSince1970)
            return (sample, processor.maximumSpeedKmh,
                    sample.result.routeId.flatMap { worker.network.routes[$0]?.name },
                    sample.result.previousStationId.flatMap { worker.network.stations[$0]?.name },
                    sample.result.nextStationId.flatMap { worker.network.stations[$0]?.name })
        }, completion: { [weak self] result in
            guard let self, self.generation == token else { return }
            switch result {
            case .failure(let error): self.storageFailure(error)
            case .success(let value):
                let (sample, maximum, route, previous, next) = value
                self.maximumSpeedKmh = maximum
                if self.state == "recording" {
                    self.speedKmh = sample.speedKmh
                    self.horizontalAccuracyM = observation.horizontalAccuracyM >= 0 ? observation.horizontalAccuracyM : nil
                    self.speedAccuracyMps = observation.speedAccuracyMps
                    let prefix = self.sourceMode == .replay ? "リプレイ・" : ""
                    if sample.speedKmh == nil { self.signalText = prefix + "速度取得なし（\(sample.exclusionReason ?? sample.result.reason)）" }
                    else { self.signalText = prefix + (sample.speedKmh! < 2 ? "停車" : "走行") }
                    if self.sourceMode == .live && !self.live.hasPreciseLocation { self.signalText += "・概算位置" }
                    if sample.result.status == "matched" || sample.result.status == "predicted" {
                        self.routeName = (route ?? "判定中") + (sample.result.status == "predicted" ? "（予測）" : "")
                        self.directionText = sample.result.directionLabel ?? "方面判定中"
                        self.previousStation = previous ?? "—"; self.nextStation = next ?? "—"
                        self.distanceToNextM = sample.result.distanceToNextM; self.progress = sample.result.progress
                        self.confidence = sample.result.confidence
                        if sample.result.status == "matched", let previous, let next {
                            self.lastSectionText = "最終確認区間: \(previous) → \(next)"
                        }
                    } else { self.clearMatch() }
                }
                // Recent samples stay bounded. Entire-session history is queried/downsampled from SQLite.
                guard observation.timestamp.isFinite,
                      !["stale_fix", "future_fix", "non_monotonic_timestamp", "invalid_timestamp", "invalid_receipt_timestamp"].contains(sample.exclusionReason ?? ""),
                      self.previousPoint == nil || observation.timestamp > self.previousPoint!.timestamp else { return }
                if let previous = self.previousPoint,
                   (previous.speedKmh == nil && sample.speedKmh != nil || observation.timestamp - previous.timestamp > 10) { self.segment += 1 }
                let point = SpeedPoint(id: UUID().uuidString, timestamp: observation.timestamp,
                                       speedKmh: sample.speedKmh, reason: sample.exclusionReason, segment: self.segment)
                self.points.append(point); self.previousPoint = point
                if self.points.count > 2400 { self.points.removeFirst(self.points.count - 2400) }
                if self.points.count > 1, observation.timestamp.isFinite {
                    let cutoff = observation.timestamp - 300
                    self.points.removeAll { $0.timestamp < cutoff }
                }
                if observation.timestamp - self.lastGraphRefresh > 10 || self.lastGraphRefresh == 0 {
                    self.lastGraphRefresh = observation.timestamp
                    self.refreshCurrentOverview()
                }
            }
        })
    }

    private func clearMatch() {
        routeName = "判定中"; directionText = "判定中"; previousStation = "—"; nextStation = "—"
        distanceToNextM = nil; progress = nil; confidence = 0
    }

    func pause() {
        guard !transitioning, state == "recording", let id = sessionID else { return }
        source?.stop(); watchdog?.invalidate(); watchdog = nil
        state = "paused"; speedKmh = nil; signalText = "一時停止"
        clearMatch(); segment += 1; transitioning = true
        let time = Date().timeIntervalSince1970
        worker.perform({ worker in try worker.store.setStatus("paused", session: id, at: time) }, completion: { [weak self] result in
            self?.transitioning = false
            if case .failure(let error) = result { self?.storageFailure(error) }
            self?.refreshHistory(); self?.refreshCurrentOverview()
        })
    }

    func resume() {
        guard !transitioning, state == "paused", let id = sessionID else { return }
        if sourceMode == .live && live.authorizationStatus != .authorizedAlways && live.authorizationStatus != .authorizedWhenInUse {
            message = "位置情報の許可を確認してから再開してください。"; return
        }
        transitioning = true; message = nil
        worker.perform({ worker in
            try worker.store.setStatus("recording", session: id, at: Date().timeIntervalSince1970)
            worker.processor?.resetContinuity()
        }, completion: { [weak self] result in
            guard let self else { return }; self.transitioning = false
            switch result {
            case .success: self.state = "recording"; self.connectSource(token: self.generation); self.refreshHistory()
            case .failure(let error): self.storageFailure(error)
            }
        })
    }

    func finish() {
        guard !transitioning, state == "recording" || state == "paused", let id = sessionID else { return }
        source?.stop(); watchdog?.invalidate(); watchdog = nil
        state = "finished"; speedKmh = nil; signalText = "記録終了"; clearMatch(); transitioning = true
        worker.perform({ worker in try worker.store.setStatus("completed", session: id, at: Date().timeIntervalSince1970) }, completion: { [weak self] result in
            self?.transitioning = false
            if case .failure(let error) = result { self?.storageFailure(error) }
            self?.refreshHistory(); self?.refreshCurrentOverview()
        })
    }

    private func storageFailure(_ error: Error) {
        source?.stop(); watchdog?.invalidate(); watchdog = nil
        state = "finished"; speedKmh = nil; signalText = "保存エラー・記録停止"
        clearMatch(); transitioning = false
        message = "履歴の保存に失敗しました。保存済みデータは履歴から確認できます。\(error.localizedDescription)"
    }

    func refreshHistory() {
        guard ready else { return }
        worker.perform({ try $0.store.summaries() }, completion: { [weak self] result in
            switch result { case .success(let rows): self?.history = rows; case .failure(let error): self?.message = error.localizedDescription }
        })
    }

    // All-session graph is a separate collection so it never increases the live buffer.
    @Published var sessionOverview: [SpeedPoint] = []
    private func refreshCurrentOverview() {
        guard let id = sessionID else { return }
        worker.perform({ try $0.store.points(session: id, limit: 1200) }, completion: { [weak self] result in
            guard self?.sessionID == id else { return }
            if case .success(let points) = result { self?.sessionOverview = points }
        })
    }

    func loadHistory(_ ride: RideSummary) {
        historySelection = ride.id; historyPoints = []; exportURL = nil
        worker.perform({ try $0.store.points(session: ride.id, limit: 1200) }, completion: { [weak self] result in
            guard self?.historySelection == ride.id else { return }
            switch result { case .success(let points): self?.historyPoints = points; case .failure(let error): self?.message = error.localizedDescription }
        })
    }

    func export(_ ride: RideSummary) {
        guard UUID(uuidString: ride.id) != nil else { return }
        worker.perform({ worker -> URL in
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent("RailVeloExports", isDirectory: true)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            // Old exported location files are removed after 24 hours, never uploaded automatically.
            for old in try FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: [.contentModificationDateKey]) {
                if let date = try old.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate,
                   Date().timeIntervalSince(date) > 86400 { try FileManager.default.removeItem(at: old) }
            }
            let url = folder.appendingPathComponent("RailVelo-\(ride.mode.rawValue)-\(ride.id).csv")
            try worker.store.exportCSV(session: ride.id, to: url)
            try FileManager.default.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: url.path)
            return url
        }, completion: { [weak self] result in
            guard self?.historySelection == ride.id else { return }
            switch result { case .success(let url): self?.exportURL = url; case .failure(let error): self?.message = error.localizedDescription }
        })
    }

    func deleteHistory(_ ride: RideSummary) {
        guard ride.id != sessionID || state == "finished" else { return }
        worker.perform({ worker in
            try worker.store.delete(session: ride.id)
            let file = FileManager.default.temporaryDirectory.appendingPathComponent("RailVeloExports")
                .appendingPathComponent("RailVelo-\(ride.mode.rawValue)-\(ride.id).csv")
            if FileManager.default.fileExists(atPath: file.path) { try FileManager.default.removeItem(at: file) }
        }, completion: { [weak self] result in
            switch result { case .success: self?.historyPoints = []; self?.exportURL = nil; self?.refreshHistory()
            case .failure(let error): self?.message = error.localizedDescription }
        })
    }

    func showCurrent() { refreshCurrentOverview() }
    private enum AppError: LocalizedError {
        case missingResource(String), notRecording
        var errorDescription: String? {
            switch self { case .missingResource(let name): return "同梱ファイルがありません: \(name)"
            case .notRecording: return "記録セッションがありません" }
        }
    }
}
