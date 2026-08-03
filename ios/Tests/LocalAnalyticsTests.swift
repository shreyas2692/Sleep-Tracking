import XCTest
@testable import Sleep_Tracker

/// The on-device analytics must mirror the server's `database.py` formulas
/// so no-server mode shows the same numbers a server would.
final class LocalAnalyticsTests: XCTestCase {

    // MARK: - Fixtures

    private func record(
        id: Int,
        date: String,
        bedtime: String = "23:00",
        wake: String = "07:00",
        quality: Int = 3,
        source: String = "manual",
        stages: SleepStages? = nil
    ) -> SleepRecord {
        SleepRecord(
            id: id, date: date, bedtime: bedtime, wake: wake,
            quality: quality, notes: "",
            hours: LocalAnalytics.hours(bedtime: bedtime, wake: wake),
            source: source, stages: stages, efficiency: nil
        )
    }

    private func day(_ offset: Int, from today: Date) -> String {
        LocalAnalytics.dayString(daysBefore: offset, of: today)
    }

    private let today = DateUtil.date(from: "2026-07-30")!

    // MARK: - Hours (server calc_sleep_hours)

    func testHoursOvernightWraparound() {
        XCTAssertEqual(LocalAnalytics.hours(bedtime: "23:00", wake: "07:00"), 8.0)
        XCTAssertEqual(LocalAnalytics.hours(bedtime: "01:30", wake: "09:00"), 7.5)
        XCTAssertEqual(LocalAnalytics.hours(bedtime: "22:15", wake: "05:45"), 7.5)
        // Same time = 0, matching the server (diff < 0 wraps, 0 does not).
        XCTAssertEqual(LocalAnalytics.hours(bedtime: "23:00", wake: "23:00"), 0)
        XCTAssertEqual(LocalAnalytics.hours(bedtime: "bad", wake: "07:00"), 0)
    }

    // MARK: - Stats

    func testStatsAveragesAndTotals() {
        let records = [
            record(id: 1, date: day(1, from: today), wake: "07:00", quality: 4), // 8h
            record(id: 2, date: day(0, from: today), wake: "05:00", quality: 2), // 6h
        ]
        let stats = LocalAnalytics.stats(records: records, today: today)
        XCTAssertEqual(stats.total, 2)
        XCTAssertEqual(stats.avgHours, 7.0)
        XCTAssertEqual(stats.avgQuality, 3.0)
        XCTAssertEqual(stats.series.count, 30)
        XCTAssertEqual(stats.series.last?.hours, 6.0)
        // A day without a record is null, not zero.
        XCTAssertNil(stats.series[27].hours)
    }

    func testStreaksConsecutiveDays() {
        let records = [
            record(id: 1, date: day(2, from: today)),
            record(id: 2, date: day(1, from: today)),
            record(id: 3, date: day(0, from: today)),
            // An older separate run of 1
            record(id: 4, date: day(10, from: today)),
        ]
        let stats = LocalAnalytics.stats(records: records, today: today)
        XCTAssertEqual(stats.currentStreak, 3)
        XCTAssertEqual(stats.bestStreak, 3)
    }

    func testStreakBrokenWhenLatestOlderThanYesterday() {
        let records = [
            record(id: 1, date: day(3, from: today)),
            record(id: 2, date: day(2, from: today)),
        ]
        let stats = LocalAnalytics.stats(records: records, today: today)
        XCTAssertEqual(stats.currentStreak, 0)
        XCTAssertEqual(stats.bestStreak, 2)
    }

    func testEmptyRecords() {
        let stats = LocalAnalytics.stats(records: [], today: today)
        XCTAssertEqual(stats.total, 0)
        XCTAssertNil(stats.avgHours)
        XCTAssertEqual(stats.currentStreak, 0)
        XCTAssertEqual(stats.series.count, 30)
        XCTAssertEqual(stats.sleepDebt?.rolling14d.count, 0)
    }

    // MARK: - Sleep debt

    func testSleepDebtSkipsMissingDaysAndCountsMaxPerSource() {
        let d0 = day(0, from: today)
        let records = [
            record(id: 1, date: day(2, from: today), bedtime: "23:00", wake: "05:00"), // 6h -> debt 2
            // Same date from two sources: the max per-source total counts once.
            record(id: 2, date: d0, bedtime: "23:00", wake: "06:00"),                   // manual 7h
            record(id: 3, date: d0, bedtime: "23:00", wake: "08:00", source: "apple_health"), // 9h wins
        ]
        let debt = LocalAnalytics.sleepDebt(records: records, today: today)
        XCTAssertEqual(debt.need, 8.0)
        XCTAssertEqual(debt.rolling14d.count, 2) // missing days skipped
        XCTAssertEqual(debt.rolling14d[0].debtHours, 2.0)
        XCTAssertEqual(debt.rolling14d[1].debtHours, -1.0) // oversleep is negative
        XCTAssertEqual(debt.totalDebtHours, 1.0)
    }

    // MARK: - Series

    func testSeriesLatestRecordPerDateWins() {
        let d = day(0, from: today)
        let records = [
            record(id: 5, date: d, wake: "06:00"),
            record(id: 9, date: d, wake: "08:00", source: "apple_health"),
        ]
        let series = LocalAnalytics.series(records: records, range: .d30, today: today)
        XCTAssertEqual(series.nights.count, 1)
        XCTAssertEqual(series.nights[0].hours, 9.0) // id 9 is latest
        XCTAssertEqual(series.nights[0].source, "apple_health")
        XCTAssertEqual(series.end, d)
    }

    func testSeriesRangeFiltersAndAllRange() {
        let records = [
            record(id: 1, date: "2024-01-01"),
            record(id: 2, date: day(0, from: today)),
        ]
        let d30 = LocalAnalytics.series(records: records, range: .d30, today: today)
        XCTAssertEqual(d30.nights.count, 1)
        let all = LocalAnalytics.series(records: records, range: .all, today: today)
        XCTAssertEqual(all.nights.count, 2)
        XCTAssertEqual(all.start, "2024-01-01")
    }

    // MARK: - Insights

    func testConsistencyBounds() {
        // Identical hours = perfectly consistent.
        let steady = (1...10).map { record(id: $0, date: day($0, from: today)) }
        XCTAssertEqual(LocalAnalytics.consistency(records: steady), 100)
        // Fewer than 2 records = 0 (not enough data).
        XCTAssertEqual(LocalAnalytics.consistency(records: [steady[0]]), 0)
    }

    func testWeeklyTwelveBucketsOldestFirst() {
        let records = [record(id: 1, date: day(0, from: today))]
        let weekly = LocalAnalytics.weeklyAverages(records: records, today: today)
        XCTAssertEqual(weekly.count, 12)
        XCTAssertEqual(weekly.last?.label, "This week")
        XCTAssertEqual(weekly.last?.count, 1)
        XCTAssertEqual(weekly.first?.count, 0) // empty bucket is a gap, not zero
    }

    func testDayOfWeekAlwaysSevenDays() {
        let result = LocalAnalytics.dayOfWeekStats(records: [record(id: 1, date: day(0, from: today))])
        XCTAssertEqual(result.count, 7)
        XCTAssertEqual(result.map(\.day), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        XCTAssertEqual(result.map(\.count).reduce(0, +), 1)
    }

    func testInsightsFeedsInsightEngineShape() {
        let records = (0..<14).map { record(id: $0 + 1, date: day($0, from: today), quality: 4) }
        let insights = LocalAnalytics.insights(records: records, today: today)
        XCTAssertEqual(insights.stats.total, 14)
        XCTAssertEqual(insights.streak, insights.stats.currentStreak)
        XCTAssertEqual(insights.weekly.count, 12)
        XCTAssertEqual(insights.monthly.count, 6)
        XCTAssertEqual(insights.bestWorst.best.count, 5)
        // The nudge engine consumes the local payload without crashing.
        _ = InsightEngine.nudges(from: insights)
    }
}
