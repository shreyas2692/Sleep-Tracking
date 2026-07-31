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
}
