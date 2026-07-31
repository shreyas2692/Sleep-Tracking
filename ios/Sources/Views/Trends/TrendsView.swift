import SwiftUI
import Charts

struct TrendsView: View {
    @EnvironmentObject private var store: SleepStore
    // Screenshot tooling: `-initialRange 1y|30d|90d|all`
    @State private var range: SeriesRange = {
        if let i = ProcessInfo.processInfo.arguments.firstIndex(of: "-initialRange"),
           i + 1 < ProcessInfo.processInfo.arguments.count,
           let r = SeriesRange(rawValue: ProcessInfo.processInfo.arguments[i + 1]) {
            return r
        }
        return .d30
    }()
    @State private var isLoading = false

    private var series: SeriesResponse? { store.seriesByRange[range] }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Picker("Range", selection: $range) {
                        ForEach(SeriesRange.allCases) { r in
                            Text(r.label).tag(r)
                        }
                    }
                    .pickerStyle(.segmented)
                    .padding(.top, 4)

                    content
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 24)
            }
            .background(Color.appPage)
            .navigationTitle("Trends")
            .toolbarTitleDisplayMode(.large)
            .refreshable {
                await store.loadSeries(range: range)
            }
            .task(id: range) {
                if store.seriesByRange[range] == nil {
                    isLoading = true
                    await store.loadSeries(range: range)
                    isLoading = false
                }
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if let series {
            summaryRow(series)
            TrendChartCard(series: series, range: range)
            InsightsSection(insights: store.insights, summary: store.aiSummary?.summary)
        } else if isLoading {
            VStack(spacing: 12) {
                ProgressView()
                Text("Loading \(range.label) of nights…")
                    .font(.subheadline)
                    .foregroundStyle(Color.appInk2)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 60)
        } else if let message = store.loadState.errorMessage {
            EmptyStateCard(
                icon: "antenna.radiowaves.left.and.right.slash",
                title: "Can't reach your server",
                message: message,
                actionTitle: "Try again",
                action: { Task { await store.loadSeries(range: range) } }
            )
        } else {
            EmptyStateCard(
                icon: "chart.xyaxis.line",
                title: "Nothing here yet",
                message: "Trends appear once you have nights in this range. Your whole history is always yours to explore — never paywalled.",
                actionTitle: nil, action: nil
            )
        }
    }

    private func summaryRow(_ series: SeriesResponse) -> some View {
        let nights = series.nights
        let avg = nights.isEmpty ? 0 : nights.map(\.hours).reduce(0, +) / Double(nights.count)
        return HStack(spacing: 12) {
            summaryTile(caption: "Nights", value: "\(nights.count)")
            summaryTile(caption: "Avg Hours", value: nights.isEmpty ? "—" : Format.hours(avg))
        }
    }

    private func summaryTile(caption: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(caption).microLabel()
            Text(value).serifDisplay(.title2)
        }
        .card(padding: 14)
    }
}

// MARK: - The trend chart

private struct TrendPoint: Identifiable {
    let id: String
    let day: Date
    let hours: Double
    let segment: Int // contiguous-run id so lines never bridge gaps
}

struct TrendChartCard: View {
    let series: SeriesResponse
    let range: SeriesRange

    private var points: [TrendPoint] {
        var result: [TrendPoint] = []
        var segment = 0
        var previous: Date?
        for night in series.nights {
            guard let day = DateUtil.date(from: night.date) else { continue }
            if let prev = previous, day.timeIntervalSince(prev) > 86_400 * 1.5 {
                segment += 1 // honest gap: break the line, no interpolation
            }
            result.append(TrendPoint(id: night.date, day: day, hours: night.hours, segment: segment))
            previous = day
        }
        return result
    }

    /// 7-night rolling average (over recorded nights, not calendar days).
    private var rollingAverage: [TrendPoint] {
        let pts = points
        guard pts.count >= 2 else { return [] }
        return pts.indices.map { i in
            let window = pts[max(0, i - 6)...i]
            let avg = window.map(\.hours).reduce(0, +) / Double(window.count)
            return TrendPoint(id: "avg-\(pts[i].id)", day: pts[i].day, hours: avg, segment: pts[i].segment)
        }
    }

    private var isLineChart: Bool { range == .y1 || range == .all }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title).microLabel()
            if points.isEmpty {
                Text("No nights recorded in this range.")
                    .font(.subheadline)
                    .foregroundStyle(Color.appInk2)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, 32)
            } else {
                chart
                    .frame(height: 230)
                if isLineChart {
                    HStack(spacing: 14) {
                        legendSwatch("Nightly", color: .chartBar.opacity(0.45))
                        legendSwatch("7-night average", color: .chartBarStrong)
                    }
                }
            }
        }
        .card()
    }

    private var title: String {
        switch range {
        case .d30: return "Nightly Hours · 30 Days"
        case .d90: return "Nightly Hours · 90 Days"
        case .y1: return "Nightly Hours · Year"
        case .all: return "Nightly Hours · All Time"
        }
    }

    private func legendSwatch(_ name: String, color: Color) -> some View {
        HStack(spacing: 5) {
            Capsule().fill(color).frame(width: 14, height: 3)
            Text(name)
                .font(.caption2)
                .foregroundStyle(Color.appInk2)
        }
    }

    @ViewBuilder
    private var chart: some View {
        if isLineChart {
            lineChart
        } else {
            barChart
        }
    }

    private var barChart: some View {
        Chart {
            ForEach(points) { point in
                BarMark(
                    x: .value("Day", point.day, unit: .day),
                    y: .value("Hours", point.hours),
                    width: range == .d90 ? .fixed(2.5) : .ratio(0.6)
                )
                .foregroundStyle(Color.chartBar)
                .cornerRadius(1.5)
            }
            goalRule
        }
        .chartXAxis { xAxis }
        .chartYAxis { yAxis }
    }

    private var lineChart: some View {
        Chart {
            ForEach(points) { point in
                LineMark(
                    x: .value("Day", point.day, unit: .day),
                    y: .value("Hours", point.hours),
                    series: .value("Series", "nightly-\(point.segment)")
                )
                .foregroundStyle(Color.chartBar.opacity(0.35))
                .lineStyle(StrokeStyle(lineWidth: 1))
                PointMark(
                    x: .value("Day", point.day, unit: .day),
                    y: .value("Hours", point.hours)
                )
                .foregroundStyle(Color.chartBar.opacity(0.25))
                .symbolSize(10)
            }
            ForEach(rollingAverage) { point in
                LineMark(
                    x: .value("Day", point.day, unit: .day),
                    y: .value("Hours", point.hours),
                    series: .value("Series", "avg-\(point.segment)")
                )
                .foregroundStyle(Color.chartBarStrong)
                .lineStyle(StrokeStyle(lineWidth: 2, lineCap: .round))
            }
            goalRule
        }
        .chartXAxis { xAxis }
        .chartYAxis { yAxis }
    }

    private var goalRule: some ChartContent {
        RuleMark(y: .value("Goal", 8))
            .foregroundStyle(Color.appBaseline)
            .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
    }

    private var xAxis: some AxisContent {
        AxisMarks(values: xAxisValues) { _ in
            AxisGridLine().foregroundStyle(Color.appGrid.opacity(0.6))
            AxisValueLabel(format: xAxisFormat)
                .foregroundStyle(Color.appMuted)
        }
    }

    private var xAxisValues: AxisMarkValues {
        switch range {
        case .d30: return .stride(by: .day, count: 7)
        case .d90: return .stride(by: .month, count: 1)
        case .y1: return .stride(by: .month, count: 2)
        case .all: return .automatic(desiredCount: 5)
        }
    }

    private var xAxisFormat: Date.FormatStyle {
        switch range {
        case .d30: return .dateTime.month(.abbreviated).day()
        case .d90: return .dateTime.month(.abbreviated)
        case .y1: return .dateTime.month(.narrow)
        case .all: return .dateTime.month(.abbreviated).year(.twoDigits)
        }
    }

    private var yAxis: some AxisContent {
        AxisMarks(position: .leading, values: [0, 4, 8, 12]) { value in
            AxisGridLine().foregroundStyle(Color.appGrid.opacity(0.6))
            AxisValueLabel {
                if let v = value.as(Int.self) {
                    Text("\(v)h").foregroundStyle(Color.appMuted)
                }
            }
        }
    }
}
