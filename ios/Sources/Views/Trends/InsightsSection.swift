import SwiftUI
import Charts

/// Insights block under the trend chart: nudge sentences plus the
/// day-of-week and weekly-rhythm charts. Range-independent — always
/// derived from the full /api/insights payload.
struct InsightsSection: View {
    let insights: InsightsResponse?
    var summary: String?

    private var nudges: [Nudge] {
        guard let insights else { return [] }
        return Array(InsightEngine.nudges(from: insights).prefix(3))
    }

    var body: some View {
        if let insights {
            VStack(alignment: .leading, spacing: 14) {
                Text("Insights")
                    .microLabel()
                    .padding(.top, 6)

                if nudges.isEmpty {
                    unlockCard
                } else {
                    if let summary, !summary.isEmpty {
                        AISummaryCard(text: summary)
                    }
                    VStack(spacing: 10) {
                        ForEach(nudges) { nudge in
                            NudgeRow(nudge: nudge)
                        }
                    }
                    DayOfWeekChartCard(days: insights.dayOfWeek)
                    WeeklyRhythmCard(weeks: insights.weekly)
                }
            }
        }
    }

    private var unlockCard: some View {
        HStack(spacing: 12) {
            Image(systemName: "lightbulb")
                .font(.title3)
                .foregroundStyle(Color.appMuted)
            Text("Insights unlock as your history grows — about a week of nights is enough to start.")
                .font(.subheadline)
                .foregroundStyle(Color.appInk2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card(padding: 14)
    }
}

/// Claude-written weekly narrative (only when the server has it enabled).
struct AISummaryCard: View {
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("This Week · Written by Claude").microLabel()
            Text(text)
                .font(.system(.subheadline, design: .serif))
                .foregroundStyle(Color.appInk)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
        .accessibilityElement(children: .combine)
    }
}

struct NudgeRow: View {
    let nudge: Nudge

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: nudge.icon)
                .font(.subheadline)
                .foregroundStyle(Color.chartBarStrong)
                .frame(width: 22)
                .padding(.top, 2)
            Text(nudge.text)
                .font(.system(.subheadline, design: .serif))
                .foregroundStyle(Color.appInk)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card(padding: 14)
        .accessibilityElement(children: .combine)
    }
}

// MARK: - Day-of-week chart

struct DayOfWeekChartCard: View {
    let days: [DayOfWeekStat]

    private var loggedDays: [DayOfWeekStat] {
        days.filter { $0.count > 0 }
    }

    var body: some View {
        if loggedDays.count >= 3 {
            VStack(alignment: .leading, spacing: 12) {
                Text("Average by Day of Week").microLabel()
                chart
                    .frame(height: 170)
            }
            .card()
        }
    }

    private var chart: some View {
        Chart {
            ForEach(loggedDays, id: \.day) { day in
                BarMark(
                    x: .value("Day", day.day),
                    y: .value("Hours", day.avgHours),
                    width: .ratio(0.6)
                )
                .foregroundStyle(Color.chartBar)
                .cornerRadius(1.5)
            }
            RuleMark(y: .value("Goal", 8))
                .foregroundStyle(Color.appBaseline)
                .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
        }
        .chartXScale(domain: days.map(\.day))
        .chartXAxis {
            AxisMarks { _ in
                AxisValueLabel().foregroundStyle(Color.appMuted)
            }
        }
        .chartYAxis {
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
}

// MARK: - Weekly rhythm chart

struct WeeklyRhythmCard: View {
    let weeks: [WeeklyAverage]

    private var loggedWeeks: [WeeklyAverage] {
        weeks.filter { $0.count > 0 }
    }

    var body: some View {
        if loggedWeeks.count >= 4 {
            VStack(alignment: .leading, spacing: 12) {
                Text("Weekly Average · 12 Weeks").microLabel()
                chart
                    .frame(height: 150)
            }
            .card()
        }
    }

    private var chart: some View {
        Chart {
            ForEach(loggedWeeks, id: \.label) { week in
                BarMark(
                    x: .value("Week", week.label),
                    y: .value("Hours", week.avgHours),
                    width: .ratio(0.55)
                )
                .foregroundStyle(Color.chartBar)
                .cornerRadius(1.5)
            }
            RuleMark(y: .value("Goal", 8))
                .foregroundStyle(Color.appBaseline)
                .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
        }
        // Keep the calendar order the server sent (oldest-first).
        .chartXScale(domain: weeks.filter { $0.count > 0 }.map(\.label))
        .chartXAxis {
            AxisMarks { value in
                if let label = value.as(String.self),
                   label == loggedWeeks.first?.label || label == loggedWeeks.last?.label {
                    AxisValueLabel().foregroundStyle(Color.appMuted)
                }
            }
        }
        .chartYAxis {
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
}
