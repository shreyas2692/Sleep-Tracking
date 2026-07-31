import XCTest
@testable import Sleep_Tracker

final class NightClusteringTests: XCTestCase {

    private let utc = TimeZone(identifier: "UTC")!

    private func date(_ y: Int, _ m: Int, _ d: Int, _ h: Int, _ min: Int, _ sec: Int = 0) -> Date {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = utc
        return cal.date(from: DateComponents(year: y, month: m, day: d, hour: h, minute: min, second: sec))!
    }

    private func sample(
        _ start: Date, _ end: Date, _ kind: SleepSampleKind = .spanOnly
    ) -> SleepSampleInterval {
        SleepSampleInterval(start: start, end: end, kind: kind)
    }

    // MARK: Clustering: gap < 4h = same night

    func testGapUnderFourHoursStaysOneCluster() {
        let a = sample(date(2026, 1, 14, 23, 0), date(2026, 1, 15, 1, 0))
        let b = sample(date(2026, 1, 15, 4, 59), date(2026, 1, 15, 7, 0))
        let clusters = NightClustering.cluster([a, b])
        XCTAssertEqual(clusters.count, 1)
    }

    func testGapOfFourHoursSplitsClusters() {
        let a = sample(date(2026, 1, 14, 23, 0), date(2026, 1, 15, 1, 0))
        let b = sample(date(2026, 1, 15, 5, 0), date(2026, 1, 15, 7, 0))
        let clusters = NightClustering.cluster([a, b])
        XCTAssertEqual(clusters.count, 2)
    }

    func testGapMeasuredFromClusterMaxEnd() {
        // The cluster end must track the MAX end seen, not the last sample's
        // end. Sorted by start the last sample is `inner` (ends 00:30); a
        // sample at 05:00 is >= 4h past 00:30 but still inside `long`'s span,
        // so it belongs to the same night.
        let long = sample(date(2026, 1, 14, 23, 0), date(2026, 1, 15, 7, 0))
        let inner = sample(date(2026, 1, 14, 23, 30), date(2026, 1, 15, 0, 30))
        let late = sample(date(2026, 1, 15, 5, 0), date(2026, 1, 15, 6, 0))
        let clusters = NightClustering.cluster([late, inner, long])
        XCTAssertEqual(clusters.count, 1)
        XCTAssertEqual(clusters[0].count, 3)
    }

    // MARK: Night building

    func testWakeDateAssignmentAndTimes() {
        let night = NightClustering.nights(
            from: [sample(date(2026, 1, 14, 23, 15), date(2026, 1, 15, 7, 5))],
            timeZone: utc
        )
        XCTAssertEqual(night.count, 1)
        XCTAssertEqual(night[0].date, "2026-01-15")
        XCTAssertEqual(night[0].bedtime, "23:15")
        XCTAssertEqual(night[0].wake, "07:05")
        XCTAssertNil(night[0].stages, "span-only records carry no stage breakdown")
    }

    func testShortClusterDropped() {
        let nights = NightClustering.nights(
            from: [sample(date(2026, 1, 15, 3, 0), date(2026, 1, 15, 3, 20))],
            timeZone: utc
        )
        XCTAssertTrue(nights.isEmpty, "clusters under 30 minutes are not nights")
    }

    func testOverlongSampleFiltered() {
        let nights = NightClustering.nights(
            from: [sample(date(2026, 1, 14, 0, 0), date(2026, 1, 16, 0, 0))],
            timeZone: utc
        )
        XCTAssertTrue(nights.isEmpty, "samples longer than 36h are invalid")
    }

    func testLongestClusterWinsPerWakeDate() {
        let mainSleep = sample(date(2026, 1, 14, 23, 0), date(2026, 1, 15, 7, 0))
        let nap = sample(date(2026, 1, 15, 12, 0), date(2026, 1, 15, 13, 0))
        let nights = NightClustering.nights(from: [nap, mainSleep], timeZone: utc)
        XCTAssertEqual(nights.count, 1)
        XCTAssertEqual(nights[0].bedtime, "23:00")
        XCTAssertEqual(nights[0].wake, "07:00")
    }

    // MARK: Stage mapping + exclusivity

    func testStageMinutesComputed() {
        let samples = [
            sample(date(2026, 1, 15, 0, 0), date(2026, 1, 15, 1, 0), .stage(.deep)),
            sample(date(2026, 1, 15, 1, 0), date(2026, 1, 15, 2, 30), .stage(.rem)),
            sample(date(2026, 1, 15, 2, 30), date(2026, 1, 15, 6, 0), .stage(.light)),
            sample(date(2026, 1, 15, 6, 0), date(2026, 1, 15, 6, 10), .stage(.awake)),
        ]
        let nights = NightClustering.nights(from: samples, timeZone: utc)
        XCTAssertEqual(nights.count, 1)
        let stages = try! XCTUnwrap(nights[0].stages)
        XCTAssertEqual(stages.deep, 60)
        XCTAssertEqual(stages.rem, 90)
        XCTAssertEqual(stages.light, 210)
        XCTAssertEqual(stages.awake, 10)
    }

    func testOverlappingStagesResolvedByPrecedence() {
        // Two devices disagree: light claims 00:00-02:00, deep claims 01:00-02:00.
        // Precedence awake > deep > rem > light means deep keeps its hour and
        // light is trimmed to the hour deep didn't claim.
        let samples = [
            sample(date(2026, 1, 15, 0, 0), date(2026, 1, 15, 2, 0), .stage(.light)),
            sample(date(2026, 1, 15, 1, 0), date(2026, 1, 15, 2, 0), .stage(.deep)),
        ]
        let nights = NightClustering.nights(from: samples, timeZone: utc)
        let stages = try! XCTUnwrap(nights.first?.stages)
        XCTAssertEqual(stages.deep, 60)
        XCTAssertEqual(stages.light, 60)
        XCTAssertEqual(stages.totalMinutes, 120, "no double counting of the same instant")
    }

    func testDuplicateIntervalsFromTwoDevicesCountOnce() {
        let samples = [
            sample(date(2026, 1, 15, 0, 0), date(2026, 1, 15, 3, 0), .stage(.light)),
            sample(date(2026, 1, 15, 0, 0), date(2026, 1, 15, 3, 0), .stage(.light)),
        ]
        let nights = NightClustering.nights(from: samples, timeZone: utc)
        XCTAssertEqual(nights.first?.stages?.light, 180)
    }

    func testRoundingConservesTotalMinutes() {
        // 90s deep + 90s rem = 180s = exactly 3 minutes; naive flooring loses one.
        let samples = [
            sample(date(2026, 1, 15, 0, 0), date(2026, 1, 15, 0, 1, 30), .stage(.deep)),
            sample(date(2026, 1, 15, 0, 1, 30), date(2026, 1, 15, 0, 3, 0), .stage(.rem)),
            // pad the cluster over the 30-minute night minimum
            sample(date(2026, 1, 15, 0, 3, 0), date(2026, 1, 15, 1, 0), .spanOnly),
        ]
        let nights = NightClustering.nights(from: samples, timeZone: utc)
        let stages = try! XCTUnwrap(nights.first?.stages)
        XCTAssertEqual(stages.deep + stages.rem, 3, "rounding must conserve the combined total")
        XCTAssertEqual(stages.deep, 2, "tie on remainder goes to the higher-precedence stage")
        XCTAssertEqual(stages.rem, 1)
    }

    // MARK: Interval helpers

    func testSubtractIntervals() {
        let intervals = [(date(2026, 1, 1, 0, 0), date(2026, 1, 1, 10, 0))]
        let blockers = [
            (date(2026, 1, 1, 2, 0), date(2026, 1, 1, 3, 0)),
            (date(2026, 1, 1, 5, 0), date(2026, 1, 1, 6, 0)),
        ]
        let result = NightClustering.subtract(intervals: intervals, blockers: blockers)
        XCTAssertEqual(result.count, 3)
        XCTAssertEqual(result[0].0, date(2026, 1, 1, 0, 0))
        XCTAssertEqual(result[0].1, date(2026, 1, 1, 2, 0))
        XCTAssertEqual(result[1].0, date(2026, 1, 1, 3, 0))
        XCTAssertEqual(result[1].1, date(2026, 1, 1, 5, 0))
        XCTAssertEqual(result[2].0, date(2026, 1, 1, 6, 0))
        XCTAssertEqual(result[2].1, date(2026, 1, 1, 10, 0))
    }

    func testMergeIntervals() {
        let merged = NightClustering.merge([
            (date(2026, 1, 1, 3, 0), date(2026, 1, 1, 4, 0)),
            (date(2026, 1, 1, 0, 0), date(2026, 1, 1, 2, 0)),
            (date(2026, 1, 1, 1, 0), date(2026, 1, 1, 3, 0)),
        ])
        XCTAssertEqual(merged.count, 1)
        XCTAssertEqual(merged[0].0, date(2026, 1, 1, 0, 0))
        XCTAssertEqual(merged[0].1, date(2026, 1, 1, 4, 0))
    }

    func testNightsSortedByDate() {
        let samples = [
            sample(date(2026, 1, 20, 23, 0), date(2026, 1, 21, 7, 0)),
            sample(date(2026, 1, 14, 23, 0), date(2026, 1, 15, 7, 0)),
        ]
        let nights = NightClustering.nights(from: samples, timeZone: utc)
        XCTAssertEqual(nights.map(\.date), ["2026-01-15", "2026-01-21"])
    }
}
