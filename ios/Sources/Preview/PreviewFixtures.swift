import Foundation
import SwiftUI

#if DEBUG

// MARK: - Sample data for SwiftUI Previews & screenshot tooling
// Mirrors the App Store mockup narrative (docs/app-store/mockups).

enum PreviewFixtures {

    static let stagesGood = SleepStages(deep: 102, rem: 114, light: 198, awake: 48)
    static let stagesGreat = SleepStages(deep: 120, rem: 130, light: 190, awake: 30)
    static let stagesOk = SleepStages(deep: 70, rem: 80, light: 220, awake: 55)

    /// ~5 weeks of nights ending yesterday. Deterministic weekday rhythm —
    /// weekend lie-ins, short Sundays, two rough nights, a few manual logs —
    /// so screenshots always show realistic, coherent history relative to
    /// whenever they are captured.
    static var records: [SleepRecord] {
        let cal = Calendar.current
        let today = cal.startOfDay(for: Date())
        let count = 36
        var out: [SleepRecord] = []
        for i in 0..<count {
            let day = cal.date(byAdding: .day, value: -(i + 1), to: today)!
            let date = DateUtil.string(from: day)
            let weekday = cal.component(.weekday, from: day) // 1 = Sunday
            let j = Double((i * 17 + weekday * 5) % 10) / 10.0 // 0.0…0.9 jitter

            // Hours: weekday ~7.3–8.0, Fri/Sat ~7.9–8.6, Sunday short.
            var hours: Double
            switch weekday {
            case 1: hours = 6.5 + j * 0.5 // Sunday deficit
            case 6, 7: hours = 7.9 + j * 0.7 // weekend lie-in
            default: hours = 7.3 + j * 0.7
            }
            if i == 0 { hours = 7.87 } // hero night for Today + night detail
            if i == 9 { hours = 5.9 } // one rough night
            if i == 23 { hours = 6.2 } // and another
            hours = (hours * 100).rounded() / 100

            // Bedtime later on weekends; wake = bedtime + asleep + awake.
            let bedMinutes = (weekday == 6 || weekday == 7 ? 23 * 60 + 20 : 22 * 60 + 40) + Int(j * 40)
            let awake = 24 + Int(j * 30) + (hours < 6.5 ? 22 : 0)
            let wakeMinutes = bedMinutes + Int(hours * 60) + awake
            func clock(_ m: Int) -> String { String(format: "%02d:%02d", (m / 60) % 24, m % 60) }

            // Every sixth night is a manual log without stages.
            let manual = i % 6 == 4
            var stages: SleepStages?
            if !manual {
                let asleep = Int(hours * 60)
                let deep = Int(Double(asleep) * (0.19 + j * 0.04))
                let rem = Int(Double(asleep) * (0.22 + j * 0.05))
                stages = SleepStages(deep: deep, rem: rem, light: asleep - deep - rem, awake: awake)
            }

            let quality = hours >= 8.1 ? 5 : hours >= 7.4 ? 4 : hours >= 6.6 ? 3 : 2
            let notes: String
            if manual {
                notes = ["Late start", "", "Travel day", ""][i % 4]
            } else {
                notes = i % 5 == 0 ? "Imported from Apple Health" : ""
            }

            out.append(
                SleepRecord(
                    id: count - i, date: date, bedtime: clock(bedMinutes), wake: clock(wakeMinutes),
                    quality: quality, notes: notes, hours: hours,
                    source: manual ? "manual" : "apple_health", stages: stages, efficiency: nil
                )
            )
        }
        return out
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
        let today = cal.startOfDay(for: Date())
        let recs = records
        let byDate = Dictionary(uniqueKeysWithValues: recs.map { ($0.date, $0) })
        let series: [StatsSeriesDay] = (0..<30).map { offset in
            let d = cal.date(byAdding: .day, value: offset - 29, to: today)!
            let key = DateUtil.string(from: d)
            guard let rec = byDate[key] else {
                return StatsSeriesDay(date: key, hours: nil, quality: nil)
            }
            return StatsSeriesDay(date: key, hours: rec.hours, quality: Double(rec.quality))
        }
        let avg = recs.map(\.hours).reduce(0, +) / Double(recs.count)
        let avgQ = Double(recs.map(\.quality).reduce(0, +)) / Double(recs.count)
        return Stats(
            total: recs.count,
            avgHours: (avg * 10).rounded() / 10,
            avgQuality: (avgQ * 10).rounded() / 10,
            currentStreak: recs.count,
            bestStreak: recs.count,
            series: series,
            sleepDebt: sleepDebt
        )
    }

    static var series30: SeriesResponse {
        let cal = Calendar.current
        let start = cal.date(byAdding: .day, value: -30, to: cal.startOfDay(for: Date()))!
        let startKey = DateUtil.string(from: start)
        let nights: [SeriesNight] = records
            .filter { $0.date >= startKey }
            .map {
                SeriesNight(
                    date: $0.date,
                    hours: $0.hours,
                    quality: $0.quality,
                    stages: $0.stages,
                    source: $0.source
                )
            }
            .sorted { $0.date < $1.date }
        return SeriesResponse(
            range: "30d",
            nights: nights,
            start: nights.first?.date ?? startKey,
            end: nights.last?.date ?? startKey
        )
    }

    /// Weekly narrative for the Trends AI-summary card (a server-side
    /// feature; fixture text mirrors the tone of `ai_summary.py` output).
    static var aiSummary: AISummary {
        AISummary(
            available: true,
            summary: "A steady week — you averaged 7h 41m, about 20 minutes more than the week before, and deep sleep held near two hours a night. Sundays are still your shortest nights; an earlier wind-down tonight would start the week ahead of your sleep debt instead of behind it."
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
    /// Populated store for canvas previews (no network). Screenshot
    /// tooling: `-localMode` presents the phone-only storage state instead
    /// of a configured server (the AI summary is server-only, so it is
    /// omitted there).
    static var previewPopulated: SleepStore {
        let store = SleepStore()
        let localMode = ProcessInfo.processInfo.arguments.contains("-localMode")
        store.applyPreviewFixtures(
            records: PreviewFixtures.records,
            stats: PreviewFixtures.stats,
            seriesByRange: [
                .d30: PreviewFixtures.series30,
                .y1: PreviewFixtures.series1y,
            ],
            loadState: .loaded,
            insights: PreviewFixtures.insights,
            aiSummary: localMode ? nil : PreviewFixtures.aiSummary,
            mode: localMode ? .local : .server
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
