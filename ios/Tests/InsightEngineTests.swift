import XCTest
@testable import Sleep_Tracker

final class InsightEngineTests: XCTestCase {

    // MARK: - Fixture builders

    private func stats(total: Int, streak: Int = 0) -> Stats {
        Stats(
            total: total, avgHours: 7.4, avgQuality: 3.8,
            currentStreak: streak, bestStreak: max(streak, 5),
            series: [], sleepDebt: nil
        )
    }

    private func week(_ label: String, hours: Double, count: Int) -> WeeklyAverage {
        WeeklyAverage(label: label, avgHours: hours, avgQuality: 3.5, count: count)
    }

    private func day(_ name: String, hours: Double, count: Int) -> DayOfWeekStat {
        DayOfWeekStat(day: name, avgHours: hours, avgQuality: 3.5, count: count)
    }

    private func insights(
        total: Int = 90,
        streak: Int = 0,
        consistency: Int = 55,
        weekly: [WeeklyAverage] = [],
        dayOfWeek: [DayOfWeekStat] = []
    ) -> InsightsResponse {
        InsightsResponse(
            stats: stats(total: total, streak: streak),
            streak: streak,
            consistency: consistency,
            weekly: weekly,
            dayOfWeek: dayOfWeek,
            bestWorst: BestWorstNights(best: [], worst: []),
            monthly: []
        )
    }

    /// Seven days averaging `base` hours except one short day.
    private func weekdays(base: Double, shortDay: String, shortHours: Double, count: Int = 10) -> [DayOfWeekStat] {
        ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map {
            day($0, hours: $0 == shortDay ? shortHours : base, count: count)
        }
    }

    // MARK: - Sparse gate

    func testFewerThanSevenNightsProducesNoNudges() {
        let sparse = insights(
            total: 6, streak: 6, consistency: 90,
            weekly: (0..<12).map { week("w\($0)", hours: 7.5, count: 5) },
            dayOfWeek: weekdays(base: 7.5, shortDay: "Sun", shortHours: 6.0)
        )
        XCTAssertTrue(InsightEngine.nudges(from: sparse).isEmpty,
                      "below \(InsightEngine.minimumNights) nights we say nothing rather than guess")
    }

    // MARK: - Day-of-week gap

    func testSundayDeficitProducesDayGapNudge() {
        let result = InsightEngine.nudges(
            from: insights(dayOfWeek: weekdays(base: 7.5, shortDay: "Sun", shortHours: 6.7))
        )
        let nudge = result.first { $0.id == "day-gap-Sun" }
        XCTAssertEqual(nudge?.text, "You tend to sleep about 50 min less on Sundays.")
    }

    func testSmallDayGapStaysQuiet() {
        let result = InsightEngine.nudges(
            from: insights(dayOfWeek: weekdays(base: 7.5, shortDay: "Sun", shortHours: 7.2))
        )
        XCTAssertFalse(result.contains { $0.id.hasPrefix("day-gap") },
                       "under 30 min of gap is noise, not a pattern")
    }

    func testLowSampleDaysAreIgnored() {
        // Sunday is dramatically low but only logged twice — below the count guard.
        var days = weekdays(base: 7.5, shortDay: "Mon", shortHours: 7.5)
        days = days.map { $0.day == "Sun" ? day("Sun", hours: 4.0, count: 2) : $0 }
        let result = InsightEngine.nudges(from: insights(dayOfWeek: days))
        XCTAssertFalse(result.contains { $0.id.hasPrefix("day-gap") })
    }

    // MARK: - Best week

    func testBestRecentWeekIsCelebrated() {
        var weeks = (0..<11).map { week("w\($0)", hours: 7.0, count: 5) }
        weeks.append(week("This week", hours: 8.1, count: 5))
        let result = InsightEngine.nudges(from: insights(weekly: weeks))
        XCTAssertTrue(result.contains { $0.id == "best-week" })
        XCTAssertEqual(result.first?.id, "best-week", "best week is the top-priority nudge")
    }

    func testBestWeekRequiresEnoughLoggedNights() {
        // The record week only has 2 nights — too thin to celebrate.
        var weeks = (0..<11).map { week("w\($0)", hours: 7.0, count: 5) }
        weeks.append(week("This week", hours: 9.0, count: 2))
        let result = InsightEngine.nudges(from: insights(weekly: weeks))
        XCTAssertFalse(result.contains { $0.id == "best-week" })
    }

    // MARK: - Month trend

    func testMonthOverMonthImprovementIsReported() {
        let weeks = (0..<4).map { week("p\($0)", hours: 7.0, count: 5) }
            + (0..<4).map { week("r\($0)", hours: 7.6, count: 5) }
        let result = InsightEngine.nudges(from: insights(weekly: weeks))
        let nudge = result.first { $0.id == "month-up" }
        XCTAssertEqual(nudge?.text, "You're averaging about 35 min more sleep than last month.")
    }

    func testMonthOverMonthDeclineStaysNeutral() {
        let weeks = (0..<4).map { week("p\($0)", hours: 7.6, count: 5) }
            + (0..<4).map { week("r\($0)", hours: 7.0, count: 5) }
        let result = InsightEngine.nudges(from: insights(weekly: weeks))
        let nudge = result.first { $0.id == "month-down" }
        XCTAssertNotNil(nudge)
        for banned in ["bad", "worst", "warning", "poor"] {
            XCTAssertFalse(nudge!.text.lowercased().contains(banned),
                           "decline copy must stay neutral (orthosomnia)")
        }
    }

    func testEmptyWeeksAreGapsNotZeroHourWeeks() {
        // 8 real weeks interleaved with empty buckets; averages must ignore
        // the empties instead of treating them as 0-hour weeks.
        var weeks: [WeeklyAverage] = []
        for i in 0..<4 { weeks.append(week("p\(i)", hours: 7.0, count: 5)) }
        weeks.append(week("gap", hours: 0, count: 0))
        for i in 0..<4 { weeks.append(week("r\(i)", hours: 7.6, count: 5)) }
        let result = InsightEngine.nudges(from: insights(weekly: weeks))
        XCTAssertTrue(result.contains { $0.id == "month-up" })
        XCTAssertFalse(result.contains { $0.id == "month-down" },
                       "an empty bucket must never read as a 0-hour week")
    }

    // MARK: - Consistency and streak

    func testSteadyRhythmNeverExposesTheNumber() {
        let result = InsightEngine.nudges(from: insights(consistency: 84))
        let nudge = result.first { $0.id == "steady" }
        XCTAssertNotNil(nudge)
        XCTAssertFalse(nudge!.text.contains("84"), "the score is an input, never copy")
    }

    func testZeroConsistencyMeansNoDataNotChaos() {
        let result = InsightEngine.nudges(from: insights(consistency: 0))
        XCTAssertFalse(result.contains { $0.id == "varied" },
                       "consistency 0 means not enough data, not a varied schedule")
    }

    func testLongStreakIsAcknowledged() {
        let result = InsightEngine.nudges(from: insights(streak: 12))
        XCTAssertTrue(result.contains { $0.text.contains("12 nights logged in a row") })
    }

    // MARK: - Phrasing helpers

    func testMinutesPhraseRounding() {
        XCTAssertEqual(InsightEngine.minutesPhrase(0.8), "50 min")
        XCTAssertEqual(InsightEngine.minutesPhrase(0.5), "30 min")
        XCTAssertEqual(InsightEngine.minutesPhrase(1.2), "1h 10m")
        XCTAssertEqual(InsightEngine.minutesPhrase(0.02), "5 min", "never rounds to zero")
    }

    func testDayPluralization() {
        XCTAssertEqual(InsightEngine.plural("Sun"), "Sundays")
        XCTAssertEqual(InsightEngine.plural("Wed"), "Wednesdays")
    }
}
