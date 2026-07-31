import Foundation
import SwiftUI

#if DEBUG

// MARK: - Sample data for SwiftUI Previews & screenshot tooling
// Mirrors the App Store mockup narrative (docs/app-store/mockups).

enum PreviewFixtures {

    static let stagesGood = SleepStages(deep: 102, rem: 114, light: 198, awake: 48)
    static let stagesGreat = SleepStages(deep: 120, rem: 130, light: 190, awake: 30)
    static let stagesOk = SleepStages(deep: 70, rem: 80, light: 220, awake: 55)

    static var records: [SleepRecord] {
        [
            SleepRecord(
                id: 9, date: "2026-07-31", bedtime: "23:12", wake: "07:04",
                quality: 4, notes: "Imported from Apple Health",
                hours: 7.87, source: "apple_health", stages: stagesGood, efficiency: nil
            ),
            SleepRecord(
                id: 8, date: "2026-07-30", bedtime: "22:48", wake: "06:51",
                quality: 5, notes: "Imported from Apple Health",
                hours: 8.05, source: "apple_health", stages: stagesGreat, efficiency: nil
            ),
            SleepRecord(
                id: 7, date: "2026-07-29", bedtime: "00:10", wake: "07:22",
                quality: 3, notes: "Late start",
                hours: 7.2, source: "manual", stages: nil, efficiency: nil
            ),
            SleepRecord(
                id: 6, date: "2026-07-28", bedtime: "23:05", wake: "06:40",
                quality: 4, notes: "Imported from Apple Health",
                hours: 7.58, source: "apple_health", stages: stagesOk, efficiency: nil
            ),
            SleepRecord(
                id: 5, date: "2026-07-27", bedtime: "22:30", wake: "05:55",
                quality: 3, notes: "Imported from Apple Health",
                hours: 7.42, source: "apple_health", stages: stagesOk, efficiency: nil
            ),
            SleepRecord(
                id: 4, date: "2026-07-26", bedtime: "23:40", wake: "08:10",
                quality: 5, notes: "Imported from Apple Health",
                hours: 8.5, source: "apple_health", stages: stagesGreat, efficiency: nil
            ),
            SleepRecord(
                id: 3, date: "2026-07-25", bedtime: "23:00", wake: "07:00",
                quality: 4, notes: "",
                hours: 8.0, source: "apple_health", stages: stagesGood, efficiency: nil
            ),
            SleepRecord(
                id: 2, date: "2026-07-24", bedtime: "22:50", wake: "06:45",
                quality: 4, notes: "",
                hours: 7.92, source: "apple_health", stages: stagesGood, efficiency: nil
            ),
            SleepRecord(
                id: 1, date: "2026-07-23", bedtime: "23:30", wake: "07:15",
                quality: 4, notes: "",
                hours: 7.75, source: "apple_health", stages: stagesOk, efficiency: nil
            ),
        ]
    }

    static var sleepDebt: SleepDebt {
        let days: [SleepDebtDay] = (0..<10).map { i in
            let d = Calendar.current.date(byAdding: .day, value: i - 9, to: Date())!
            let s = DateUtil.string(from: d)
            let debt = i < 8 ? -0.4 : (i == 8 ? 0.2 : -1.2)
            let cum = Double(i) * -0.5 - (i == 9 ? 1.3 : 0)
            return SleepDebtDay(date: s, debtHours: debt, cumulativeDebtHours: cum)
        }
        return SleepDebt(need: 8.0, rolling14d: days, totalDebtHours: -5.8)
    }

    static var stats: Stats {
        let cal = Calendar.current
        let today = Date()
        let series: [StatsSeriesDay] = (0..<30).map { offset in
            let d = cal.date(byAdding: .day, value: offset - 29, to: today)!
            let key = DateUtil.string(from: d)
            if let rec = records.first(where: { $0.date == key }) {
                return StatsSeriesDay(date: key, hours: rec.hours, quality: Double(rec.quality))
            }
            // sparse early month like the live screenshot
            if offset >= 22 {
                return StatsSeriesDay(date: key, hours: 7.5 + Double(offset % 3) * 0.2, quality: 4)
            }
            return StatsSeriesDay(date: key, hours: nil, quality: nil)
        }
        return Stats(
            total: 9,
            avgHours: 7.8,
            avgQuality: 4.4,
            currentStreak: 3,
            bestStreak: 3,
            series: series,
            sleepDebt: sleepDebt
        )
    }

    static var series30: SeriesResponse {
        let nights: [SeriesNight] = records.map {
            SeriesNight(
                date: $0.date,
                hours: $0.hours,
                quality: $0.quality,
                stages: $0.stages,
                source: $0.source
            )
        }.sorted { $0.date < $1.date }
        return SeriesResponse(
            range: "30d",
            nights: nights,
            start: nights.first?.date ?? "2026-07-02",
            end: nights.last?.date ?? "2026-07-31"
        )
    }

    /// Sunday-deficit + steady rhythm so previews/screenshots show nudges.
    static var insights: InsightsResponse {
        var weekly: [WeeklyAverage] = []
        for i in 0..<12 {
            let label: String
            if i == 11 {
                label = "This week"
            } else if i == 10 {
                label = "Last week"
            } else {
                label = "Wk \(i)"
            }
            let hours: Double = 6.9 + Double(i) * 0.06
            weekly.append(
                WeeklyAverage(label: label, avgHours: hours, avgQuality: 3.6, count: i == 2 ? 0 : 6)
            )
        }
        let dayHours: [(String, Double)] = [
            ("Mon", 7.6), ("Tue", 7.5), ("Wed", 7.4), ("Thu", 7.5),
            ("Fri", 7.2), ("Sat", 7.8), ("Sun", 6.6),
        ]
        let dayOfWeek: [DayOfWeekStat] = dayHours.map { pair in
            DayOfWeekStat(day: pair.0, avgHours: pair.1, avgQuality: 3.8, count: 11)
        }
        return InsightsResponse(
            stats: stats,
            streak: stats.currentStreak,
            consistency: 78,
            weekly: weekly,
            dayOfWeek: dayOfWeek,
            bestWorst: BestWorstNights(best: Array(records.prefix(5)), worst: []),
            monthly: []
        )
    }

    static var series1y: SeriesResponse {
        let cal = Calendar.current
        let end = Date()
        var nights: [SeriesNight] = []
        for i in 0..<52 {
            let d = cal.date(byAdding: .day, value: -i * 7, to: end)!
            let h = 6.5 + sin(Double(i) / 4.0) * 0.8 + Double(i % 5) * 0.1
            nights.append(
                SeriesNight(
                    date: DateUtil.string(from: d),
                    hours: (h * 100).rounded() / 100,
                    quality: 3 + (i % 3),
                    stages: i % 4 == 0 ? nil : stagesOk,
                    source: "apple_health"
                )
            )
        }
        nights.sort { $0.date < $1.date }
        return SeriesResponse(
            range: "1y",
            nights: nights,
            start: nights.first?.date ?? "2025-08-01",
            end: nights.last?.date ?? "2026-07-31"
        )
    }
}

// MARK: - Store seeders

extension SleepStore {
    /// Populated store for canvas previews (no network).
    static var previewPopulated: SleepStore {
        let store = SleepStore()
        store.applyPreviewFixtures(
            records: PreviewFixtures.records,
            stats: PreviewFixtures.stats,
            seriesByRange: [
                .d30: PreviewFixtures.series30,
                .y1: PreviewFixtures.series1y,
            ],
            loadState: .loaded,
            insights: PreviewFixtures.insights
        )
        return store
    }

    /// Empty but successfully loaded — empty-state cards.
    static var previewEmpty: SleepStore {
        let store = SleepStore()
        let emptySeries = SeriesResponse(
            range: "30d", nights: [], start: "2026-07-02", end: "2026-07-31"
        )
        store.applyPreviewFixtures(
            records: [],
            stats: Stats(
                total: 0, avgHours: nil, avgQuality: nil,
                currentStreak: 0, bestStreak: 0, series: [], sleepDebt: nil
            ),
            seriesByRange: [.d30: emptySeries],
            loadState: .loaded
        )
        return store
    }

    /// Failed connection state.
    static var previewFailed: SleepStore {
        let store = SleepStore()
        store.applyPreviewFixtures(
            records: [],
            stats: nil,
            seriesByRange: [:],
            loadState: .failed("Can't reach your server — connection refused.")
        )
        return store
    }
}

extension HealthKitService {
    static var preview: HealthKitService {
        HealthKitService()
    }
}

// MARK: - Screen previews (App Store mockup parity)

#Preview("Today · populated") {
    DashboardView()
        .environmentObject(SleepStore.previewPopulated)
        .environmentObject(HealthKitService.preview)
}

#Preview("Today · empty") {
    DashboardView()
        .environmentObject(SleepStore.previewEmpty)
        .environmentObject(HealthKitService.preview)
}

#Preview("Today · offline") {
    DashboardView()
        .environmentObject(SleepStore.previewFailed)
        .environmentObject(HealthKitService.preview)
}

#Preview("Trends · 1y") {
    TrendsView()
        .environmentObject(SleepStore.previewPopulated)
        .environmentObject(HealthKitService.preview)
}

#Preview("Nights · list") {
    NightsView()
        .environmentObject(SleepStore.previewPopulated)
        .environmentObject(HealthKitService.preview)
}

#Preview("Night detail") {
    NightDetailView(record: PreviewFixtures.records[0])
        .environmentObject(SleepStore.previewPopulated)
        .environmentObject(HealthKitService.preview)
}

#Preview("Settings") {
    SettingsView()
        .environmentObject(SleepStore.previewPopulated)
        .environmentObject(HealthKitService.preview)
}

#Preview("Root tabs") {
    RootTabView()
        .environmentObject(SleepStore.previewPopulated)
        .environmentObject(HealthKitService.preview)
        .tint(.appAccent)
}

#endif
