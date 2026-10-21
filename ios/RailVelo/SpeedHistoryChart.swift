import SwiftUI
import Charts
import RailVeloRecording

enum ChartRange: String, CaseIterable, Identifiable {
    case minute = "60秒"
    case fiveMinutes = "5分"
    case all = "全体"
    var id: String { rawValue }
    var seconds: Double? {
        switch self {
        case .minute: return 60
        case .fiveMinutes: return 300
        case .all: return nil
        }
    }
}

struct SpeedHistoryChart: View {
    let points: [SpeedPoint]
    let allPoints: [SpeedPoint]?
    let accessibilityPrefix: String
    @State private var range: ChartRange
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(points: [SpeedPoint], allPoints: [SpeedPoint]? = nil, initialRange: ChartRange = .minute, accessibilityPrefix: String = "ride.chart") {
        self.points = points
        self.allPoints = allPoints
        self.accessibilityPrefix = accessibilityPrefix
        _range = State(initialValue: initialRange)
    }

    private var visiblePoints: [SpeedPoint] {
        if range == .all { return allPoints ?? points }
        guard let last = points.lazy.map(\.timestamp).filter({ $0.isFinite }).max(), let seconds = range.seconds else { return points }
        return points.filter { $0.timestamp >= last - seconds }
    }

    private var timeDomain: ClosedRange<Date> {
        let timestamps = (range == .all ? allPoints ?? points : points).lazy.map(\.timestamp).filter { $0.isFinite }
        let last = timestamps.max() ?? Date().timeIntervalSince1970
        let first = range.seconds.map { last - $0 } ?? timestamps.min() ?? last - 60
        return Date(timeIntervalSince1970: min(first, last - 1))...Date(timeIntervalSince1970: last)
    }

    private var axisDates: [Date] {
        let domain = timeDomain
        let count = dynamicTypeSize.isAccessibilitySize ? 2 : 3
        let duration = domain.upperBound.timeIntervalSince(domain.lowerBound)
        return (0..<count).map { domain.lowerBound.addingTimeInterval(duration * Double($0) / Double(count - 1)) }
    }

    private func axisLabelAnchor(at index: Int) -> UnitPoint {
        if index == 0 { return .topLeading }
        if index == axisDates.count - 1 { return .topTrailing }
        return .top
    }

    private func axisTime(_ date: Date) -> String {
        let components = Calendar.current.dateComponents([.hour, .minute, .second], from: date)
        return String(format: "%02d:%02d:%02d", components.hour ?? 0, components.minute ?? 0, components.second ?? 0)
    }

    var body: some View {
        VStack(spacing: 12) {
            Picker("グラフの表示期間", selection: $range) {
                ForEach(ChartRange.allCases) { value in
                    Text(value.rawValue).tag(value)
                }
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("\(accessibilityPrefix).range")
            Chart(visiblePoints.filter { $0.speedKmh != nil }, id: \.id) { point in
                if let speed = point.speedKmh {
                    LineMark(
                        x: .value("観測日時", Date(timeIntervalSince1970: point.timestamp)),
                        y: .value("速度 km/h", speed),
                        series: .value("連続観測区間", point.segment)
                    )
                    .foregroundStyle(.cyan)
                    .lineStyle(StrokeStyle(lineWidth: 2.5, lineCap: .round))
                    .interpolationMethod(.linear)
                    .accessibilityLabel("速度")
                    .accessibilityValue("\(Date(timeIntervalSince1970: point.timestamp).formatted(date: .omitted, time: .standard))、\(String(format: "%.1f", speed)) km/h")
                    PointMark(
                        x: .value("観測日時", Date(timeIntervalSince1970: point.timestamp)),
                        y: .value("速度 km/h", speed)
                    )
                    .foregroundStyle(.cyan)
                    .symbolSize(9)
                    .accessibilityHidden(true)
                }
            }
            .chartXScale(domain: timeDomain)
            .chartYScale(domain: .automatic(includesZero: true))
            .chartXAxis {
                AxisMarks(values: axisDates) { value in
                    AxisGridLine()
                    if let date = value.as(Date.self) {
                        AxisValueLabel(anchor: axisLabelAnchor(at: value.index)) {
                            Text(axisTime(date)).monospacedDigit()
                        }
                    }
                }
            }
            .chartYAxisLabel("km/h", position: .topLeading)
            .frame(height: 190)
            .accessibilityLabel("速度グラフ")
            .accessibilityValue("\(range.rawValue)、有効な速度 \(visiblePoints.filter { $0.speedKmh != nil }.count) 件")
            .accessibilityIdentifier(accessibilityPrefix)
            .overlay {
                if visiblePoints.allSatisfy({ $0.speedKmh == nil }) {
                    Text("有効な速度を待っています")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            Text("測位失敗・速度無効・一時停止の区間では線が途切れます。")
                .font(.caption2)
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
