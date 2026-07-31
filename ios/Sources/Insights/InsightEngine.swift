import Foundation

/// One plain-language observation derived from /api/insights.
/// Copy rules: trends over single nights, "tend to" language, never
/// alarming, never a numeric score (see PRODUCT.md on orthosomnia).
struct Nudge: Identifiable, Equatable {
    let id: String
    let icon: String
    let text: String
    /// Lower is more important; Today shows only the top nudge.
    let priority: Int
}

/// Pure rule engine — no SwiftUI, no networking — so it is trivially
/// unit-testable and could later move server-side without changing shape.
enum InsightEngine {

    /// Below this many logged nights we say nothing rather than guess.
    static let minimumNights = 7

    static func nudges(from insights: InsightsResponse) -> [Nudge] {
        guard insights.stats.total >= minimumNights else { return [] }

        var result: [Nudge] = []
        if let n = bestWeek(insights) { result.append(n) }
        if let n = monthTrend(insights) { result.append(n) }
        if let n = dayOfWeekGap(insights) { result.append(n) }
        if let n = consistency(insights) { result.append(n) }
        if let n = streak(insights) { result.append(n) }
        return result.sorted { $0.priority < $1.priority }
    }

    // MARK: - Rules

    /// The most recent full-ish week is the best of the last 12.
    private static func bestWeek(_ insights: InsightsResponse) -> Nudge? {
        let qualifying = insights.weekly.filter { $0.count >= 4 }
        guard qualifying.count >= 4,
              let latest = insights.weekly.last(where: { $0.count >= 4 }),
              let best = qualifying.max(by: { $0.avgHours < $1.avgHours }),
              latest == best, latest.avgHours > 0
        else { return nil }
        return Nudge(
            id: "best-week",
            icon: "sparkles",
            text: "This is your best week of sleep in the last three months.",
            priority: 1
        )
    }

    /// Recent four non-empty weeks vs the four before them.
    private static func monthTrend(_ insights: InsightsResponse) -> Nudge? {
        let weeks = insights.weekly.filter { $0.count > 0 }
        guard weeks.count >= 8 else { return nil }
        let recent = weeks.suffix(4).map(\.avgHours)
        let prior = weeks.suffix(8).prefix(4).map(\.avgHours)
        let delta = average(recent) - average(prior)
        guard abs(delta) >= 0.25 else { return nil }
        if delta > 0 {
            return Nudge(
                id: "month-up",
                icon: "chart.line.uptrend.xyaxis",
                text: "You're averaging about \(minutesPhrase(delta)) more sleep than last month.",
                priority: 2
            )
        }
        return Nudge(
            id: "month-down",
            icon: "moon.zzz",
            text: "Sleep has run a little shorter than last month — a trend worth noticing, not a verdict.",
            priority: 2
        )
    }

    /// One weekday consistently shorter than the rest.
    private static func dayOfWeekGap(_ insights: InsightsResponse) -> Nudge? {
        let days = insights.dayOfWeek.filter { $0.count >= 3 }
        guard days.count >= 3,
              let lowest = days.min(by: { $0.avgHours < $1.avgHours })
        else { return nil }
        let others = days.filter { $0.day != lowest.day }
        guard !others.isEmpty else { return nil }
        let delta = average(others.map(\.avgHours)) - lowest.avgHours
        guard delta >= 0.5 else { return nil }
        return Nudge(
            id: "day-gap-\(lowest.day)",
            icon: "calendar",
            text: "You tend to sleep about \(minutesPhrase(delta)) less on \(plural(lowest.day)).",
            priority: 3
        )
    }

    /// Consistency feeds a sentence, never a number.
    private static func consistency(_ insights: InsightsResponse) -> Nudge? {
        guard insights.stats.total >= 14, insights.consistency > 0 else { return nil }
        if insights.consistency >= 70 {
            return Nudge(
                id: "steady",
                icon: "metronome",
                text: "Your sleep schedule has a steady rhythm — consistency matters more than any single night.",
                priority: 4
            )
        }
        if insights.consistency <= 40 {
            return Nudge(
                id: "varied",
                icon: "moon.stars",
                text: "Your nights vary a fair amount — that's normal. The weekly average is what counts.",
                priority: 4
            )
        }
        return nil
    }

    private static func streak(_ insights: InsightsResponse) -> Nudge? {
        let streak = insights.stats.currentStreak
        guard streak >= 7 else { return nil }
        return Nudge(
            id: "streak",
            icon: "checkmark.seal",
            text: "\(streak) nights logged in a row — the habit is the win.",
            priority: 5
        )
    }

    // MARK: - Helpers

    private static func average(_ values: [Double]) -> Double {
        guard !values.isEmpty else { return 0 }
        return values.reduce(0, +) / Double(values.count)
    }

    /// 0.83h -> "50 min", 1.2h -> "1h 10m" (rounded to 5-minute steps).
    static func minutesPhrase(_ hours: Double) -> String {
        let rounded = max(5, Int((hours * 60 / 5).rounded()) * 5)
        if rounded < 60 { return "\(rounded) min" }
        return Format.minutes(rounded)
    }

    /// "Sun" -> "Sundays" for nudge copy.
    static func plural(_ shortDay: String) -> String {
        let names = [
            "Mon": "Mondays", "Tue": "Tuesdays", "Wed": "Wednesdays",
            "Thu": "Thursdays", "Fri": "Fridays", "Sat": "Saturdays",
            "Sun": "Sundays",
        ]
        return names[shortDay] ?? "\(shortDay)s"
    }
}
