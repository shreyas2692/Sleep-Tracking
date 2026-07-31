import XCTest
@testable import Sleep_Tracker

/// Fixtures are verbatim captures from the live server (curl on 2026-07-31),
/// so decoding here proves the app matches the real wire contract.
final class APIDecodingTests: XCTestCase {

    private let decoder = APIClient.decoder

    // MARK: /api/stats — exact live capture

    private let liveStatsJSON = #"""
    {"avg_hours":7.65,"avg_quality":4.0,"best_streak":3,"current_streak":3,"series":[{"date":"2026-07-02","hours":null,"quality":null},{"date":"2026-07-27","hours":7.25,"quality":4},{"date":"2026-07-28","hours":null,"quality":null},{"date":"2026-07-29","hours":7.5,"quality":4},{"date":"2026-07-30","hours":8.0,"quality":5},{"date":"2026-07-31","hours":8.0,"quality":3}],"sleep_debt":{"need":8.0,"rolling_14d":[{"cumulative_debt_hours":0.75,"date":"2026-07-27","debt_hours":0.75},{"cumulative_debt_hours":1.25,"date":"2026-07-29","debt_hours":0.5},{"cumulative_debt_hours":1.25,"date":"2026-07-30","debt_hours":0.0},{"cumulative_debt_hours":-6.25,"date":"2026-07-31","debt_hours":-7.5}],"total_debt_hours":-6.25},"total":5}
    """#

    func testDecodeLiveStats() throws {
        let stats = try decoder.decode(Stats.self, from: Data(liveStatsJSON.utf8))
        XCTAssertEqual(stats.total, 5)
        XCTAssertEqual(stats.avgHours, 7.65)
        XCTAssertEqual(stats.avgQuality, 4.0)
        XCTAssertEqual(stats.currentStreak, 3)
        XCTAssertEqual(stats.bestStreak, 3)
        XCTAssertEqual(stats.series.count, 6)
        XCTAssertNil(stats.series[0].hours, "days without a record have hours: null")
        XCTAssertEqual(stats.series[1].hours, 7.25)

        let debt = try XCTUnwrap(stats.sleepDebt)
        XCTAssertEqual(debt.need, 8.0)
        XCTAssertEqual(debt.rolling14d.count, 4)
        XCTAssertEqual(debt.rolling14d[0].date, "2026-07-27")
        XCTAssertEqual(debt.rolling14d[0].debtHours, 0.75)
        XCTAssertEqual(debt.rolling14d[3].cumulativeDebtHours, -6.25)
        XCTAssertEqual(debt.totalDebtHours, -6.25, "oversleep is negative debt")
        XCTAssertTrue(Format.debtHeadline(debt.totalDebtHours).hasPrefix("Rested +"), "oversleep reads as rest, never alarm")
    }

    // MARK: /api/records — live shape incl. HTML in notes and null stages

    private let recordsJSON = #"""
    [{"bedtime":"23:00","date":"2026-07-31","efficiency":null,"hours":8.0,"id":4,"notes":"","quality":3,"source":"manual","stages":null,"wake":"07:00"},{"bedtime":"23:30","date":"2026-07-31","efficiency":92.5,"hours":7.5,"id":3,"notes":"night 31 <script>x</script>","quality":4,"source":"apple_health","stages":{"deep":80,"rem":110,"light":240,"awake":20},"wake":"07:00"}]
    """#

    func testDecodeRecords() throws {
        let records = try decoder.decode([SleepRecord].self, from: Data(recordsJSON.utf8))
        XCTAssertEqual(records.count, 2)

        let manual = records[0]
        XCTAssertEqual(manual.id, 4)
        XCTAssertEqual(manual.date, "2026-07-31")
        XCTAssertEqual(manual.bedtime, "23:00")
        XCTAssertEqual(manual.wake, "07:00")
        XCTAssertEqual(manual.hours, 8.0)
        XCTAssertEqual(manual.quality, 3)
        XCTAssertNil(manual.stages)
        XCTAssertNil(manual.efficiency)
        XCTAssertNil(manual.sourceLabel, "manual records show no source chip")

        let imported = records[1]
        XCTAssertEqual(imported.source, "apple_health")
        XCTAssertEqual(imported.sourceLabel, "Watch")
        XCTAssertEqual(imported.efficiency, 92.5)
        let stages = try XCTUnwrap(imported.stages)
        XCTAssertEqual(stages.deep, 80)
        XCTAssertEqual(stages.rem, 110)
        XCTAssertEqual(stages.light, 240)
        XCTAssertEqual(stages.awake, 20)
        XCTAssertEqual(stages.totalMinutes, 450)
        XCTAssertEqual(imported.notes, "night 31 <script>x</script>", "notes pass through untouched — SwiftUI Text never interprets HTML")
    }

    // MARK: /api/series — live shape

    private let seriesJSON = #"""
    {"end":"2026-07-31","nights":[{"date":"2026-07-27","hours":7.25,"quality":4,"source":"manual","stages":null},{"date":"2026-07-29","hours":7.5,"quality":4,"source":"fitbit","stages":{"deep":60,"rem":90,"light":270,"awake":30}}],"range":"30d","start":"2026-07-02"}
    """#

    func testDecodeSeries() throws {
        let series = try decoder.decode(SeriesResponse.self, from: Data(seriesJSON.utf8))
        XCTAssertEqual(series.range, "30d")
        XCTAssertEqual(series.start, "2026-07-02")
        XCTAssertEqual(series.end, "2026-07-31")
        XCTAssertEqual(series.nights.count, 2)
        XCTAssertNil(series.nights[0].stages)
        XCTAssertEqual(series.nights[1].source, "fitbit")
        XCTAssertEqual(series.nights[1].stages?.light, 270)
    }

    // MARK: POST responses ({ok, records, stats})

    func testDecodeMutationResponse() throws {
        let json = #"""
        {"ok":true,"records":\#(recordsJSON),"stats":\#(liveStatsJSON)}
        """#
        let response = try decoder.decode(MutationResponse.self, from: Data(json.utf8))
        XCTAssertTrue(response.ok)
        XCTAssertEqual(response.records.count, 2)
        XCTAssertEqual(response.stats.total, 5)
    }

    func testDecodeErrorBody() throws {
        let body = try decoder.decode(
            APIErrorBody.self,
            from: Data(#"{"error":"date must be YYYY-MM-DD"}"#.utf8)
        )
        XCTAssertEqual(body.error, "date must be YYYY-MM-DD")
    }

    // MARK: Stats with an empty database (defensive nullables)

    func testDecodeEmptyStats() throws {
        let json = #"""
        {"avg_hours":null,"avg_quality":null,"best_streak":0,"current_streak":0,"series":[],"total":0,"sleep_debt":{"need":8.0,"rolling_14d":[],"total_debt_hours":0.0}}
        """#
        let stats = try decoder.decode(Stats.self, from: Data(json.utf8))
        XCTAssertEqual(stats.total, 0)
        XCTAssertNil(stats.avgHours)
    }

    // MARK: Form encoding for POST /add etc.

    func testFormEncoding() {
        let fields = APIClient.NightFields(
            date: "2026-07-31", bedtime: "23:00", wake: "07:00",
            quality: 4, notes: "late tea & a walk"
        )
        let encoded = APIClient.encodeForm(fields.formItems)
        XCTAssertEqual(
            encoded,
            "date=2026-07-31&bedtime=23%3A00&wake=07%3A00&quality=4&notes=late%20tea%20%26%20a%20walk"
        )
    }

    func testDebtHeadlinePhrasing() {
        XCTAssertEqual(Format.debtHeadline(6.5), "6.5h behind")
        XCTAssertEqual(Format.debtHeadline(-2.1), "Rested +2.1h")
        XCTAssertEqual(Format.debtHeadline(0.0), "On balance")
    }

    // MARK: /api/insights — exact live capture (seeded 86-night DB, Sunday deficit)

    private let liveInsightsJSON = #"""
    {"best_worst":{"best":[{"bedtime":"23:00","date":"2026-05-07","efficiency":null,"hours":7.75,"id":9,"notes":"","quality":4,"source":"apple_health","stages":{"awake":27,"deep":83,"light":253,"rem":102},"wake":"06:45"},{"bedtime":"23:00","date":"2026-05-11","efficiency":null,"hours":7.75,"id":13,"notes":"","quality":5,"source":"apple_health","stages":{"awake":27,"deep":83,"light":253,"rem":102},"wake":"06:45"},{"bedtime":"23:00","date":"2026-05-15","efficiency":null,"hours":7.75,"id":17,"notes":"","quality":3,"source":"apple_health","stages":{"awake":27,"deep":83,"light":253,"rem":102},"wake":"06:45"},{"bedtime":"23:00","date":"2026-05-19","efficiency":null,"hours":7.75,"id":21,"notes":"","quality":4,"source":"apple_health","stages":{"awake":27,"deep":83,"light":253,"rem":102},"wake":"06:45"},{"bedtime":"23:00","date":"2026-05-23","efficiency":null,"hours":7.75,"id":24,"notes":"","quality":5,"source":"apple_health","stages":{"awake":27,"deep":83,"light":253,"rem":102},"wake":"06:45"}],"worst":[{"bedtime":"00:20","date":"2026-05-03","efficiency":null,"hours":6.67,"id":5,"notes":"","quality":3,"source":"apple_health","stages":{"awake":24,"deep":72,"light":216,"rem":88},"wake":"07:00"},{"bedtime":"00:20","date":"2026-05-10","efficiency":null,"hours":6.67,"id":12,"notes":"","quality":4,"source":"apple_health","stages":{"awake":24,"deep":72,"light":216,"rem":88},"wake":"07:00"},{"bedtime":"00:20","date":"2026-05-17","efficiency":null,"hours":6.67,"id":19,"notes":"","quality":5,"source":"apple_health","stages":{"awake":24,"deep":72,"light":216,"rem":88},"wake":"07:00"},{"bedtime":"00:20","date":"2026-05-24","efficiency":null,"hours":6.67,"id":25,"notes":"","quality":3,"source":"apple_health","stages":{"awake":24,"deep":72,"light":216,"rem":88},"wake":"07:00"},{"bedtime":"00:20","date":"2026-05-31","efficiency":null,"hours":6.67,"id":32,"notes":"","quality":4,"source":"apple_health","stages":{"awake":24,"deep":72,"light":216,"rem":88},"wake":"07:00"}]},"consistency":88,"day_of_week":[{"avg_hours":7.3,"avg_quality":3.9,"count":13,"day":"Mon"},{"avg_hours":7.4,"avg_quality":4.2,"count":12,"day":"Tue"},{"avg_hours":7.3,"avg_quality":3.8,"count":12,"day":"Wed"},{"avg_hours":7.4,"avg_quality":4.0,"count":13,"day":"Thu"},{"avg_hours":7.4,"avg_quality":4.0,"count":12,"day":"Fri"},{"avg_hours":7.4,"avg_quality":4.0,"count":11,"day":"Sat"},{"avg_hours":6.7,"avg_quality":3.9,"count":13,"day":"Sun"}],"monthly":[{"avg_hours":0,"count":0,"label":"Feb 2026"},{"avg_hours":0,"count":0,"label":"Mar 2026"},{"avg_hours":0,"count":0,"label":"Apr 2026"},{"avg_hours":7.2,"count":28,"label":"May 2026"},{"avg_hours":7.3,"count":28,"label":"Jun 2026"},{"avg_hours":7.3,"count":30,"label":"Jul 2026"}],"stats":{"avg_hours":7.26,"avg_quality":3.98,"best_streak":21,"current_streak":21,"series":[{"date":"2026-07-02","hours":7.75,"quality":3},{"date":"2026-07-03","hours":7.5,"quality":4},{"date":"2026-07-04","hours":7.25,"quality":5},{"date":"2026-07-05","hours":6.67,"quality":3},{"date":"2026-07-06","hours":7.75,"quality":4},{"date":"2026-07-07","hours":7.5,"quality":5},{"date":"2026-07-08","hours":7.25,"quality":3},{"date":"2026-07-09","hours":7.0,"quality":4},{"date":"2026-07-10","hours":null,"quality":null},{"date":"2026-07-11","hours":7.5,"quality":3},{"date":"2026-07-12","hours":6.67,"quality":4},{"date":"2026-07-13","hours":7.0,"quality":5},{"date":"2026-07-14","hours":7.75,"quality":3},{"date":"2026-07-15","hours":7.5,"quality":4},{"date":"2026-07-16","hours":7.25,"quality":5},{"date":"2026-07-17","hours":7.0,"quality":3},{"date":"2026-07-18","hours":7.75,"quality":4},{"date":"2026-07-19","hours":6.67,"quality":5},{"date":"2026-07-20","hours":7.25,"quality":3},{"date":"2026-07-21","hours":7.0,"quality":4},{"date":"2026-07-22","hours":7.75,"quality":5},{"date":"2026-07-23","hours":7.5,"quality":3},{"date":"2026-07-24","hours":7.25,"quality":4},{"date":"2026-07-25","hours":7.0,"quality":5},{"date":"2026-07-26","hours":6.67,"quality":3},{"date":"2026-07-27","hours":7.0,"quality":3},{"date":"2026-07-28","hours":7.25,"quality":5},{"date":"2026-07-29","hours":7.0,"quality":3},{"date":"2026-07-30","hours":7.75,"quality":4},{"date":"2026-07-31","hours":7.5,"quality":5}],"sleep_debt":{"need":8.0,"rolling_14d":[{"cumulative_debt_hours":0.25,"date":"2026-07-18","debt_hours":0.25},{"cumulative_debt_hours":1.58,"date":"2026-07-19","debt_hours":1.33},{"cumulative_debt_hours":2.33,"date":"2026-07-20","debt_hours":0.75},{"cumulative_debt_hours":3.33,"date":"2026-07-21","debt_hours":1.0},{"cumulative_debt_hours":3.58,"date":"2026-07-22","debt_hours":0.25},{"cumulative_debt_hours":4.08,"date":"2026-07-23","debt_hours":0.5},{"cumulative_debt_hours":4.83,"date":"2026-07-24","debt_hours":0.75},{"cumulative_debt_hours":5.83,"date":"2026-07-25","debt_hours":1.0},{"cumulative_debt_hours":7.16,"date":"2026-07-26","debt_hours":1.33},{"cumulative_debt_hours":8.16,"date":"2026-07-27","debt_hours":1.0},{"cumulative_debt_hours":8.91,"date":"2026-07-28","debt_hours":0.75},{"cumulative_debt_hours":9.91,"date":"2026-07-29","debt_hours":1.0},{"cumulative_debt_hours":10.16,"date":"2026-07-30","debt_hours":0.25},{"cumulative_debt_hours":10.66,"date":"2026-07-31","debt_hours":0.5}],"total_debt_hours":10.66},"total":86},"streak":21,"weekly":[{"avg_hours":7.3,"avg_quality":3.9,"count":7,"label":"May 09"},{"avg_hours":7.2,"avg_quality":3.8,"count":6,"label":"May 16"},{"avg_hours":7.3,"avg_quality":4.1,"count":7,"label":"May 23"},{"avg_hours":7.2,"avg_quality":3.9,"count":7,"label":"May 30"},{"avg_hours":7.3,"avg_quality":4.0,"count":6,"label":"Jun 06"},{"avg_hours":7.2,"avg_quality":4.1,"count":7,"label":"Jun 13"},{"avg_hours":7.4,"avg_quality":4.0,"count":6,"label":"Jun 20"},{"avg_hours":7.2,"avg_quality":4.0,"count":7,"label":"Jun 27"},{"avg_hours":7.2,"avg_quality":4.0,"count":6,"label":"Jul 04"},{"avg_hours":7.2,"avg_quality":3.9,"count":7,"label":"Jul 11"},{"avg_hours":7.3,"avg_quality":4.0,"count":7,"label":"Last week"},{"avg_hours":7.2,"avg_quality":4.0,"count":7,"label":"This week"}]}
    """#

    func testDecodeLiveInsights() throws {
        let insights = try decoder.decode(InsightsResponse.self, from: Data(liveInsightsJSON.utf8))

        XCTAssertEqual(insights.stats.total, 86)
        XCTAssertEqual(insights.consistency, 88)
        XCTAssertEqual(insights.streak, 21)

        XCTAssertEqual(insights.weekly.count, 12, "always 12 weekly buckets")
        XCTAssertEqual(insights.weekly.last?.label, "This week")
        XCTAssertEqual(insights.dayOfWeek.count, 7, "always all 7 days Mon–Sun")
        XCTAssertEqual(insights.dayOfWeek.first?.day, "Mon")
        XCTAssertEqual(insights.dayOfWeek.last?.day, "Sun")

        let empty = insights.monthly.first
        XCTAssertEqual(empty?.count, 0, "months before history are gaps")
        XCTAssertEqual(empty?.avgHours, 0, "integer 0 must decode as Double")

        XCTAssertEqual(insights.bestWorst.best.count, 5)
        XCTAssertEqual(insights.bestWorst.worst.count, 5)
        XCTAssertEqual(insights.bestWorst.best.first?.source, "apple_health")
        XCTAssertNotNil(insights.bestWorst.best.first?.stages)

        // The seeded Sunday deficit flows through to a day-gap nudge.
        let nudges = InsightEngine.nudges(from: insights)
        XCTAssertTrue(nudges.contains { $0.id == "day-gap-Sun" })
    }
}
