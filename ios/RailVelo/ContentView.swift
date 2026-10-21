import SwiftUI
import RailVeloRecording

struct ContentView: View {
    @ObservedObject var model: RideViewModel
    @State private var showingHistory = false
    @State private var confirmFinish = false
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private var running: Bool { model.state == "recording" || model.state == "paused" }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 18) {
                    sourceSelection
                    if let message = model.message {
                        Label(message, systemImage: "exclamationmark.circle.fill")
                            .font(.callout)
                            .foregroundStyle(.orange)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding()
                            .background(.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 16))
                            .accessibilityIdentifier("ride.message")
                    }
                    speedCard
                    routeCard
                    VStack(alignment: .leading, spacing: 14) {
                        Label("速度の記録", systemImage: "chart.xyaxis.line")
                            .font(.headline)
                        SpeedHistoryChart(points: model.points, allPoints: model.sessionOverview)
                    }
                    .monitorCard()
                    Text("路線・駅間情報はGPSと線路データによる推定です。次に通る駅は、列車の停車予定駅とは異なります。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Text(versionText)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier("ride.version")
                }
                .padding()
            }
            .accessibilityIdentifier("ride.scroll")
            .background(Color(uiColor: .systemGroupedBackground))
            .safeAreaInset(edge: .bottom) {
                recordingControls
                    .padding(.horizontal)
                    .padding(.vertical, 10)
                    .background(.ultraThinMaterial)
            }
            .navigationTitle("鉄道走行モニター")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        model.refreshHistory()
                        showingHistory = true
                    } label: {
                        Label("走行履歴", systemImage: "clock.arrow.circlepath")
                    }
                    .accessibilityIdentifier("ride.history")
                }
            }
            .sheet(isPresented: $showingHistory) {
                RideHistoryView(model: model)
            }
            .confirmationDialog("走行の記録を終了しますか？", isPresented: $confirmFinish, titleVisibility: .visible) {
                Button("記録を終了", role: .destructive) { model.finish() }
                    .accessibilityIdentifier("ride.confirmFinish")
            } message: {
                Text("この走行は履歴に保存されます。")
            }
        }
    }

    private var sourceSelection: some View {
        VStack(alignment: .leading, spacing: 10) {
            if running {
                Label(model.mode == .live ? "実GPSを記録中" : "テストデータを再生中", systemImage: model.mode == .live ? "location.fill" : "play.rectangle.fill")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(model.mode == .live ? Color.secondary : Color.orange)
            } else {
                Picker("記録モード", selection: $model.mode) {
                    Text("実GPS").tag(RideMode.live)
                    Text("リプレイ（テスト）").tag(RideMode.replay)
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("ride.mode")
            }
            if model.mode == .replay {
                Text("リプレイは門司港〜博多の合成GPSデータです。履歴にもテストとして保存されます。")
                    .font(.footnote)
                    .foregroundStyle(.orange)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var speedCard: some View {
        VStack(spacing: 15) {
            HStack {
                Label(model.signalText, systemImage: "antenna.radiowaves.left.and.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                Text(travelState)
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(.cyan.opacity(0.12), in: Capsule())
                    .accessibilityIdentifier("ride.state")
            }
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(model.speedKmh.map { String(format: "%.1f", $0) } ?? "—")
                    .font(.system(size: 76, weight: .medium, design: .rounded))
                    .monospacedDigit()
                    .minimumScaleFactor(0.5)
                    .lineLimit(1)
                Text("km/h").font(.title3).foregroundStyle(.secondary)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("現在速度")
            .accessibilityValue(model.speedKmh.map { String(format: "時速 %.1f キロメートル", $0) } ?? "有効な速度なし")
            .accessibilityIdentifier("ride.speed")
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 12) {
                    speedMetrics
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                HStack(alignment: .top, spacing: 14) { speedMetrics }
            }
        }
        .monitorCard()
    }

    @ViewBuilder private var speedMetrics: some View {
        metric("最高速度", value: String(format: "%.1f km/h", model.maximumSpeedKmh))
        metric("位置精度", value: model.horizontalAccuracyM.map { String(format: "±%.0f m", $0) } ?? "—")
        metric("速度精度", value: model.speedAccuracyMps.map { String(format: "±%.1f km/h", $0 * 3.6) } ?? "—")
    }

    private var routeCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("走行路線").font(.caption).foregroundStyle(.secondary)
                    Text(model.routeName).font(.title3.weight(.bold))
                        .accessibilityIdentifier("ride.route")
                }
                Spacer()
                Text(model.directionText)
                    .font(.subheadline.weight(.medium))
                    .multilineTextAlignment(.trailing)
                    .foregroundStyle(.secondary)
            }
            HStack(alignment: .top, spacing: 12) {
                station(model.previousStation, caption: "直前に通過した駅", alignment: .leading)
                Image(systemName: "arrow.right").foregroundStyle(.secondary).padding(.top, 21)
                station(model.nextStation, caption: "次に通る駅", alignment: .trailing)
            }
            VStack(spacing: 7) {
                ProgressView(value: min(1, max(0, model.progress ?? 0)))
                    .accessibilityLabel("駅間進捗")
                    .accessibilityValue(model.progress.map { String(format: "%.0f パーセント", $0 * 100) } ?? "判定中")
                HStack {
                    Text(model.progress.map { String(format: "駅間進捗 %.0f%%", $0 * 100) } ?? "駅間進捗 判定中")
                    Spacer()
                    Text("次駅まで \(distanceText(model.distanceToNextM))")
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            if !model.lastSectionText.isEmpty {
                Text(model.lastSectionText).font(.subheadline).foregroundStyle(.secondary)
            }
            Divider()
            HStack {
                Text("路線・方向の候補支持度")
                Spacer()
                Text(String(format: "%.0f%%", model.confidence * 100)).monospacedDigit()
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            Text("支持度は候補同士の相対値です。位置の正確さを保証する確率ではありません。")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .monitorCard()
    }

    private var recordingControls: some View {
        HStack(spacing: 12) {
            if model.state == "recording" {
                Button { model.pause() } label: {
                    Label("一時停止", systemImage: "pause.fill").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("ride.pause")
            } else if model.state == "paused" {
                Button { model.resume() } label: {
                    Label("再開", systemImage: "play.fill").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("ride.resume")
            } else {
                Button { model.start() } label: {
                    Label(model.mode == .live ? "記録を開始" : "リプレイを開始", systemImage: "record.circle")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("ride.start")
            }
            if running {
                Button(role: .destructive) { confirmFinish = true } label: {
                    Label("終了", systemImage: "stop.fill").frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("ride.finish")
            }
        }
        .controlSize(.large)
        .disabled(!model.ready || model.transitioning)
    }

    private var travelState: String {
        switch model.state {
        case "paused": return "記録を一時停止"
        case "finished": return "記録終了"
        case "recording":
            guard let speed = model.speedKmh else { return "測位待機" }
            return speed < 3 ? "停車・低速" : "走行中"
        default: return "開始待ち"
        }
    }

    private var versionText: String {
        let info = Bundle.main.infoDictionary ?? [:]
        return "RailVelo \(info["CFBundleShortVersionString"] as? String ?? "—")（\(info["CFBundleVersion"] as? String ?? "—")）"
    }

    private func metric(_ name: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(name).font(.caption2).foregroundStyle(.secondary)
            Text(value).font(.caption.weight(.semibold)).monospacedDigit()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private func station(_ name: String, caption: String, alignment: HorizontalAlignment) -> some View {
        VStack(alignment: alignment, spacing: 5) {
            Text(caption).font(.caption2).foregroundStyle(.secondary)
            Text(name).font(.title3.weight(.semibold))
                .multilineTextAlignment(alignment == .leading ? .leading : .trailing)
        }
        .frame(maxWidth: .infinity, alignment: alignment == .leading ? .leading : .trailing)
        .accessibilityElement(children: .combine)
    }
}

private struct RideHistoryView: View {
    @ObservedObject var model: RideViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var pendingDeletion: RideSummary?
    @State private var confirmDeletion = false

    var body: some View {
        NavigationStack {
            Group {
                if model.history.isEmpty {
                    VStack(spacing: 15) {
                        Image(systemName: "clock").font(.largeTitle).foregroundStyle(.secondary)
                        Text("走行履歴はありません").font(.headline)
                        Text("記録した走行は、この端末に保存されます。")
                            .font(.subheadline).foregroundStyle(.secondary)
                    }
                    .padding()
                } else {
                    List {
                        ForEach(model.history, id: \.id) { ride in
                            NavigationLink {
                                RideHistoryDetailView(model: model, ride: ride)
                            } label: {
                                VStack(alignment: .leading, spacing: 7) {
                                    HStack {
                                        Text(Date(timeIntervalSince1970: ride.startedAt), style: .date)
                                        Text(Date(timeIntervalSince1970: ride.startedAt), style: .time)
                                        Spacer()
                                        if ride.mode == .replay {
                                            Text("テスト").foregroundStyle(.orange)
                                        }
                                    }
                                    .font(.subheadline.weight(.semibold))
                                    HStack {
                                        Text(rideStatus(ride.status))
                                        Spacer()
                                        Text(String(format: "最高 %.1f km/h", ride.maximumSpeedKmh))
                                    }
                                    .font(.caption).foregroundStyle(.secondary)
                                }
                                .padding(.vertical, 4)
                            }
                            .accessibilityIdentifier("history.row.\(ride.id)")
                            .accessibilityValue("\(ride.mode == .replay ? "リプレイのテスト記録" : "実GPSの走行記録")、\(rideStatus(ride.status))")
                            .swipeActions {
                                if ride.status != "recording" && ride.status != "paused" {
                                    Button(role: .destructive) {
                                        pendingDeletion = ride
                                        confirmDeletion = true
                                    } label: {
                                        Label("削除", systemImage: "trash")
                                    }
                                    .accessibilityIdentifier("history.delete.\(ride.id)")
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("走行履歴")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("閉じる") { dismiss() }
                        .accessibilityIdentifier("history.close")
                }
            }
            .confirmationDialog("この走行履歴を削除しますか？", isPresented: $confirmDeletion, titleVisibility: .visible) {
                Button("位置情報と走行履歴を削除", role: .destructive) {
                    if let ride = pendingDeletion { model.deleteHistory(ride) }
                    pendingDeletion = nil
                }
                .accessibilityIdentifier("history.confirmDelete")
            } message: {
                Text("削除した履歴は復元できません。共有先へ渡したCSVは削除されません。")
            }
            .onAppear { model.refreshHistory() }
        }
    }
}

private struct RideHistoryDetailView: View {
    @ObservedObject var model: RideViewModel
    let ride: RideSummary

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 10) {
                    Label(ride.mode == .live ? "実GPSの走行記録" : "リプレイのテスト記録", systemImage: ride.mode == .live ? "location.fill" : "play.rectangle.fill")
                        .font(.headline)
                    LabeledContent("開始", value: Date(timeIntervalSince1970: ride.startedAt).formatted(date: .abbreviated, time: .standard))
                    LabeledContent("終了", value: ride.endedAt.map { Date(timeIntervalSince1970: $0).formatted(date: .abbreviated, time: .standard) } ?? "—")
                    LabeledContent("記録状態", value: rideStatus(ride.status))
                    LabeledContent("最高速度", value: String(format: "%.1f km/h", ride.maximumSpeedKmh))
                }
                .font(.subheadline)
                .monitorCard()
                VStack(alignment: .leading, spacing: 14) {
                    Text("速度履歴").font(.headline)
                    SpeedHistoryChart(points: model.historyPoints, initialRange: .all, accessibilityPrefix: "history.chart")
                }
                .monitorCard()
                if let url = model.exportURL {
                    ShareLink(item: url) {
                        Label("CSVを共有", systemImage: "square.and.arrow.up").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .accessibilityIdentifier("history.shareCSV")
                    Text("CSVには観測時刻と位置情報が含まれます。共有先をご確認ください。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                if let message = model.message {
                    Text(message).font(.callout).foregroundStyle(.orange)
                }
            }
            .padding()
        }
        .accessibilityIdentifier("history.detail.scroll")
        .background(Color(uiColor: .systemGroupedBackground))
        .navigationTitle("走行の詳細")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            model.loadHistory(ride)
            model.export(ride)
        }
    }
}

private func distanceText(_ meters: Double?) -> String {
    guard let meters else { return "—" }
    return meters >= 1000 ? String(format: "%.1f km", meters / 1000) : String(format: "%.0f m", meters)
}

private func rideStatus(_ status: String) -> String {
    switch status {
    case "recording": return "記録中"
    case "paused": return "一時停止中"
    case "finished", "completed": return "記録終了"
    case "interrupted": return "中断して保存"
    default: return status
    }
}

private struct MonitorCard: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(18)
            .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 20))
    }
}

extension View {
    fileprivate func monitorCard() -> some View { modifier(MonitorCard()) }
}
