import SwiftUI
import Charts

struct DashboardView: View {
    @EnvironmentObject private var store: SleepStore

    private var greeting: String {
        let hour = Calendar.current.component(.hour, from: Date())
        switch hour {
        case 5..<12: return "Good morning"
        case 12..<17: return "Good afternoon"
        case 17..<22: return "Good evening"
        default: return "Good night"
        }
    }

    private var todayLine: String {
        Date().formatted(.dateTime.weekday(.wide).month(.wide).day())
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    header

                    if let stats = store.stats, stats.total > 0 {
                        statGrid(stats)
                        if let debt = stats.sleepDebt {
                            SleepDebtCard(debt: debt)
                        }
                        ThirtyDayChartCard(series: store.series30)
                    } else {
                        stateBody
                    }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 24)
            }
            .background(Color.appPage)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) { Wordmark() }
            }
            .refreshable { await store.refresh() }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(greeting)
                .serifDisplay(.largeTitle)
            Text(todayLine)
                .font(.subheadline)
                .foregroundStyle(Color.appInk2)
        }
        .padding(.top, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private var stateBody: some View {
        switch store.loadState {
        case .loading, .idle:
            VStack(spacing: 12) {
                ProgressView()
                Text("Loading your nights…")
                    .font(.subheadline)
                    .foregroundStyle(Color.appInk2)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 60)
        case .failed(let message):
            EmptyStateCard(
                icon: "antenna.radiowaves.left.and.right.slash",
                title: "Can't reach your server",
                message: "\(message)\n\nYour data stays on your machine — check the server address in Settings.",
                actionTitle: "Try again",
                action: { Task { await store.refresh() } }
            )
        case .loaded:
            EmptyStateCard(
                icon: "moon.zzz",
                title: "No nights yet",
                message: "Log a night from the Nights tab, or sync your history from Apple Health in Settings. Your data is yours — no cloud, no account.",
                actionTitle: nil,
                action: nil
            )
        }
    }

    private func statGrid(_ stats: Stats) -> some View {
        LazyVGrid(
            columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)],
            spacing: 12
        ) {
            StatCard(
                caption: "Nights",
                value: "\(stats.total)",
                subtext: "logged"
            )
            StatCard(
                caption: "Avg Hours",
                value: stats.avgHours.map { Format.hours($0) } ?? "—",
                subtext: "per night"
            )
            StatCard(
                caption: "Avg Quality",
                value: stats.avgQuality.map { Format.hours($0) } ?? "—",
                subtext: "out of 5"
            )
            StatCard(
                caption: "Streak",
                value: "\(stats.currentStreak)",
                subtext: "best \(stats.bestStreak)"
            )
        }
    }
}

// MARK: - Stat card

struct StatCard: View {
    let caption: String
    let value: String
    let subtext: String

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(caption).microLabel()
            Text(value)
                .serifDisplay(.title)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
            Text(subtext)
                .font(.caption)
                .foregroundStyle(Color.appMuted)
        }
        .card(padding: 14)
    }
}

// MARK: - Sleep debt card (neutral framing, tiny 14-day sparkline)

struct SleepDebtCard: View {
    let debt: SleepDebt

    private var sparkPoints: [(Date, Double)] {
        debt.rolling14d.compactMap { day in
            DateUtil.date(from: day.date).map { ($0, day.cumulativeDebtHours) }
        }
    }

    var body: some View {
        HStack(alignment: .center, spacing: 14) {
            VStack(alignment: .leading, spacing: 5) {
                Text("Sleep Debt · 14 Days").microLabel()
                Text(Format.debtHeadline(debt.totalDebtHours))
                    .serifDisplay(.title2)
                Text("vs your \(Format.hours(debt.need))h need · one night never tells the story")
                    .font(.caption)
                    .foregroundStyle(Color.appMuted)
            }
            Spacer(minLength: 8)
            sparkline
                .frame(width: 96, height: 40)
        }
        .card()
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private var sparkline: some View {
        if sparkPoints.count >= 2 {
            Chart {
                RuleMark(y: .value("Balance", 0))
                    .foregroundStyle(Color.appBaseline)
                    .lineStyle(StrokeStyle(lineWidth: 1, dash: [2, 3]))
                ForEach(sparkPoints, id: \.0) { point in
                    LineMark(
                        x: .value("Day", point.0),
                        y: .value("Debt", point.1)
                    )
                    .foregroundStyle(Color.chartBar)
                    .lineStyle(StrokeStyle(lineWidth: 2, lineCap: .round))
                    .interpolationMethod(.monotone)
                }
            }
            .chartXAxis(.hidden)
            .chartYAxis(.hidden)
            .chartLegend(.hidden)
            .accessibilityHidden(true)
        }
    }
}

// MARK: - 30-day stacked stage chart

private struct StageSegment: Identifiable {
    let id: String
    let day: Date
    let stage: String
    let hours: Double
}

struct ThirtyDayChartCard: View {
    let series: SeriesResponse?
    @State private var selectedDate: String?

    private static let stageOrder = ["Deep", "REM", "Light", "Awake"]

    private var nights: [SeriesNight] { series?.nights ?? [] }

    private var hasStagedNights: Bool {
        nights.contains { $0.stages != nil }
    }

    private var segments: [StageSegment] {
        nights.flatMap { night -> [StageSegment] in
            guard let day = DateUtil.date(from: night.date) else { return [] }
            if let s = night.stages {
                // Emit bottom-up: deep (darkest) first — terracotta ramp dark -> light.
                let parts: [(String, Int)] = [
                    ("Deep", s.deep), ("REM", s.rem), ("Light", s.light), ("Awake", s.awake),
                ]
                return parts.compactMap { name, minutes in
                    guard minutes > 0 else { return nil }
                    return StageSegment(
                        id: "\(night.date)-\(name)",
                        day: day,
                        stage: name,
                        hours: Double(minutes) / 60.0
                    )
                }
            }
            return [StageSegment(id: "\(night.date)-Asleep", day: day, stage: "Asleep", hours: night.hours)]
        }
    }

    private var domain: ClosedRange<Date>? {
        guard let series,
              let start = DateUtil.date(from: series.start),
              let end = DateUtil.date(from: series.end)
        else { return nil }
        return start.addingTimeInterval(-43_200)...end.addingTimeInterval(43_200)
    }

    private var selectedNight: SeriesNight? {
        guard let selectedDate else { return nil }
        return nights.first { $0.date == selectedDate }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Last 30 Nights").microLabel()

            if nights.isEmpty {
                Text("No nights in the last 30 days.")
                    .font(.subheadline)
                    .foregroundStyle(Color.appInk2)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, 28)
            } else {
                chart
                    .frame(height: 190)

                if hasStagedNights {
                    StageLegend()
                }

                if let night = selectedNight {
                    NightPeek(night: night)
                        .transition(.opacity)
                } else {
                    Text("Tap a bar for that night's details")
                        .font(.caption)
                        .foregroundStyle(Color.appMuted)
                }
            }
        }
        .card()
        .animation(.easeOut(duration: 0.15), value: selectedDate)
    }

    private var chart: some View {
        Chart {
            ForEach(segments) { segment in
                BarMark(
                    x: .value("Day", segment.day, unit: .day),
                    y: .value("Hours", segment.hours),
                    width: .ratio(0.62)
                )
                .foregroundStyle(by: .value("Stage", segment.stage))
                .cornerRadius(2)
                .opacity(selectedDate == nil || selectedDate == DateUtil.string(from: segment.day) ? 1 : 0.35)
            }
            RuleMark(y: .value("Goal", 8))
                .foregroundStyle(Color.appBaseline)
                .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
        }
        .chartForegroundStyleScale([
            "Deep": Color.stageDeep,
            "REM": Color.stageRem,
            "Light": Color.stageLight,
            "Awake": Color.stageAwake,
            "Asleep": Color.chartBar,
        ])
        .chartLegend(.hidden)
        .modifier(OptionalXDomain(domain: domain))
        .chartXAxis {
            AxisMarks(values: .stride(by: .day, count: 7)) { _ in
                AxisGridLine().foregroundStyle(Color.appGrid.opacity(0.6))
                AxisValueLabel(format: .dateTime.month(.abbreviated).day())
                    .foregroundStyle(Color.appMuted)
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading, values: [0, 4, 8, 12]) { value in
                AxisGridLine().foregroundStyle(Color.appGrid.opacity(0.6))
                AxisValueLabel {
                    if let v = value.as(Int.self) {
                        Text("\(v)h")
                            .foregroundStyle(Color.appMuted)
                    }
                }
            }
        }
        .chartOverlay { proxy in
            GeometryReader { geo in
                Rectangle()
                    .fill(Color.clear)
                    .contentShape(Rectangle())
                    .onTapGesture(coordinateSpace: .local) { location in
                        guard let plotFrame = proxy.plotFrame else { return }
                        let x = location.x - geo[plotFrame].origin.x
                        guard let tapped: Date = proxy.value(atX: x) else { return }
                        select(near: tapped)
                    }
            }
        }
    }

    private func select(near date: Date) {
        let candidates = nights.compactMap { night -> (String, TimeInterval)? in
            guard let d = DateUtil.date(from: night.date) else { return nil }
            return (night.date, abs(d.timeIntervalSince(date)))
        }
        guard let closest = candidates.min(by: { $0.1 < $1.1 }),
              closest.1 < 86_400 * 1.5
        else {
            selectedDate = nil
            return
        }
        selectedDate = selectedDate == closest.0 ? nil : closest.0
        Haptics.tap()
    }
}

/// Applies a chartXScale domain only when one exists.
private struct OptionalXDomain: ViewModifier {
    let domain: ClosedRange<Date>?

    func body(content: Content) -> some View {
        if let domain {
            content.chartXScale(domain: domain)
        } else {
            content
        }
    }
}

// MARK: - Tapped-night detail strip

struct NightPeek: View {
    let night: SeriesNight

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 8) {
                Text(DateUtil.display(night.date, format: "EEE MMM d"))
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Color.appInk)
                Spacer()
                if let quality = night.quality {
                    StarRating(quality: quality, compact: true)
                }
                Text("\(Format.hours(night.hours))h")
                    .font(.system(.subheadline, design: .serif).weight(.semibold))
                    .foregroundStyle(Color.appInk)
            }
            if let stages = night.stages {
                StageMiniBar(stages: stages)
                HStack(spacing: 12) {
                    stageMinutes("Deep", stages.deep)
                    stageMinutes("REM", stages.rem)
                    stageMinutes("Light", stages.light)
                    stageMinutes("Awake", stages.awake)
                }
            }
        }
        .padding(11)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Color.appInset)
        )
    }

    private func stageMinutes(_ name: String, _ minutes: Int) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(name)
                .font(.caption2)
                .foregroundStyle(Color.appMuted)
            Text(Format.minutes(minutes))
                .font(.caption.weight(.medium))
                .foregroundStyle(Color.appInk2)
        }
    }
}
