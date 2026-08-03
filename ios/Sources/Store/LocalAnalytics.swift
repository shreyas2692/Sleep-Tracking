import Foundation

/// Pure on-device analytics for HealthKit-only / no-server mode.
///
/// Mirrors the server's `database.py` formulas (stats, series, insights,
/// sleep debt) so the app shows the same numbers whether nights live on a
/// server or only on this phone. No SwiftUI, no networking — unit-testable.
enum LocalAnalytics {

    /// Default nightly need when no server goal exists (server: `sleep_goal`
    /// setting else 8.0).
    static let defaultSleepNeed = 8.0

    // MARK: - Hours (server `calc_sleep_hours`)

    /// Hours bedtime → wake with overnight wraparound (23:00→07:00 = 8.0).
    /// Rounded to 2 decimals; 0 if unparseable.
    static func hours(bedtime: String, wake: String) -> Double {
        guard let bed = minutes(bedtime), let wk = minutes(wake) else { return 0 }
        var diff = Double(wk - bed) / 60.0
        if diff < 0 { diff += 24 }
        return round2(diff)
    }

    /// "HH:mm" → minutes since midnight, or nil.
    static func minutes(_ time: String) -> Int? {
        let parts = time.split(separator: ":")
        guard parts.count == 2,
              let h = Int(parts[0]), let m = Int(parts[1]),
              (0...23).contains(h), (0...59).contains(m)
        else { return nil }
        return h * 60 + m
    }

    // MARK: - Stats (server `get_stats`)

    static func stats(records: [SleepRecord], today: Date = Date()) -> Stats {
        let todayString = DateUtil.string(from: today)
        let total = records.count
        let avgHours = total > 0
            ? round2(records.map(\.hours).reduce(0, +) / Double(total)) : nil
        let avgQuality = total > 0
            ? round2(records.map { Double($0.quality) }.reduce(0, +) / Double(total)) : nil

        let (current, best) = streaks(records: records, todayString: todayString)

        // Last 30 calendar days ending today, ascending; latest record
        // (highest id) wins when a date has multiple records.
        let latest = latestByDate(records)
        var series: [StatsSeriesDay] = []
        for offset in stride(from: 29, through: 0, by: -1) {
            let day = dayString(daysBefore: offset, of: today)
            let record = latest[day]
            series.append(StatsSeriesDay(
                date: day,
                hours: record?.hours,
                quality: record.map { Double($0.quality) }
            ))
        }

        return Stats(
            total: total,
            avgHours: avgHours,
            avgQuality: avgQuality,
            currentStreak: current,
            bestStreak: best,
            series: series,
            sleepDebt: sleepDebt(records: records, today: today)
        )
    }

    /// (current, best) over consecutive calendar days (server `_streaks`).
    static func streaks(records: [SleepRecord], todayString: String) -> (current: Int, best: Int) {
        let dates = Set(records.map(\.date).filter { $0 <= todayString })
            .compactMap { DateUtil.date(from: $0) }
            .sorted()
        guard !dates.isEmpty else { return (0, 0) }

        let calendar = Calendar.current
        var best = 1
        var run = 1
        for (prev, cur) in zip(dates, dates.dropFirst()) {
            let gap = calendar.dateComponents([.day], from: prev, to: cur).day ?? 99
            run = gap == 1 ? run + 1 : 1
            best = max(best, run)
        }

        guard let latest = dates.last, let today = DateUtil.date(from: todayString) else {
            return (0, best)
        }
        let sinceLatest = calendar.dateComponents([.day], from: latest, to: today).day ?? 99
        if sinceLatest > 1 { return (0, best) }
        var current = 1
        var index = dates.count - 1
        while index > 0 {
            let gap = calendar.dateComponents(
                [.day], from: dates[index - 1], to: dates[index]
            ).day ?? 99
            guard gap == 1 else { break }
            current += 1
            index -= 1
        }
        return (current, best)
    }

    // MARK: - Sleep debt (server `_sleep_debt`, simplified sessions)

    /// Rolling 14-day debt vs. need. Days with no record are skipped (an
    /// unlogged night is not evidence of no sleep). Multi-source dates count
    /// the max per-source total once; same-source records (naps) sum.
    static func sleepDebt(
        records: [SleepRecord], today: Date = Date(), need: Double = defaultSleepNeed
    ) -> SleepDebt {
        let windowStart = dayString(daysBefore: 13, of: today)
        let todayString = DateUtil.string(from: today)

        // date → max over sources of (sum of that source's hours).
        var bySource: [String: [String: Double]] = [:]
        for r in records where r.date >= windowStart && r.date <= todayString {
            bySource[r.date, default: [:]][r.source, default: 0] += r.hours
        }
        let hoursByDate = bySource.mapValues { $0.values.max() ?? 0 }

        var rolling: [SleepDebtDay] = []
        var total = 0.0
        for offset in stride(from: 13, through: 0, by: -1) {
            let day = dayString(daysBefore: offset, of: today)
            guard let slept = hoursByDate[day] else { continue }
            let debt = round2(need - slept)
            total += debt
            rolling.append(SleepDebtDay(
                date: day, debtHours: debt, cumulativeDebtHours: round2(total)
            ))
        }
        return SleepDebt(need: need, rolling14d: rolling, totalDebtHours: round2(total))
    }

    // MARK: - Series (server `get_series`)

    static func series(
        records: [SleepRecord], range: SeriesRange, today: Date = Date()
    ) -> SeriesResponse {
        let end = DateUtil.string(from: today)
        let days: Int?
        switch range {
        case .d30: days = 30
        case .d90: days = 90
        case .y1: days = 365
        case .all: days = nil
        }

        var start = days.map { dayString(daysBefore: $0 - 1, of: today) } ?? end
        let inRange = records.filter { $0.date <= end && (days == nil || $0.date >= start) }
        let latest = latestByDate(inRange)
        let nights = latest.keys.sorted().compactMap { date -> SeriesNight? in
            guard let record = latest[date] else { return nil }
            return SeriesNight(
                date: record.date,
                hours: record.hours,
                quality: record.quality,
                stages: record.stages,
                source: record.source
            )
        }
        if days == nil, let first = nights.first { start = first.date }
        return SeriesResponse(range: range.rawValue, nights: nights, start: start, end: end)
    }

    // MARK: - Insights (server `/api/insights`)

    static func insights(records: [SleepRecord], today: Date = Date()) -> InsightsResponse {
        let stats = Self.stats(records: records, today: today)
        return InsightsResponse(
            stats: stats,
            streak: stats.currentStreak,
            consistency: consistency(records: records),
            weekly: weeklyAverages(records: records, today: today),
            dayOfWeek: dayOfWeekStats(records: records),
            bestWorst: bestWorst(records: records),
            monthly: monthlyTrend(records: records, today: today)
        )
    }

    /// 0–100 over the last 30 records; 0h std dev = 100, 3h = 0
    /// (server `get_consistency_score`).
    static func consistency(records: [SleepRecord]) -> Int {
        let recent = records
            .sorted { ($0.date, $0.id) > ($1.date, $1.id) }
            .prefix(30)
            .map(\.hours)
        guard recent.count >= 2 else { return 0 }
        let mean = recent.reduce(0, +) / Double(recent.count)
        let variance = recent.map { ($0 - mean) * ($0 - mean) }.reduce(0, +) / Double(recent.count)
        let stdDev = variance.squareRoot()
        return max(0, min(100, Int((100 - stdDev / 3 * 100).rounded())))
    }

    /// Last 12 weeks oldest-first (server `get_weekly_averages`).
    static func weeklyAverages(
        records: [SleepRecord], today: Date = Date(), weeks: Int = 12
    ) -> [WeeklyAverage] {
        guard !records.isEmpty else { return [] }
        var result: [WeeklyAverage] = []
        for i in 0..<weeks {
            let weekEnd = dayString(daysBefore: i * 7, of: today)
            let weekStart = dayString(daysBefore: i * 7 + 6, of: today)
            let weekRecords = records.filter { $0.date >= weekStart && $0.date <= weekEnd }
            let label: String
            if weekRecords.isEmpty {
                label = shortDate(weekStart)
            } else if i == 0 {
                label = "This week"
            } else if i == 1 {
                label = "Last week"
            } else {
                label = shortDate(weekStart)
            }
            result.append(WeeklyAverage(
                label: label,
                avgHours: weekRecords.isEmpty
                    ? 0 : round1(weekRecords.map(\.hours).reduce(0, +) / Double(weekRecords.count)),
                avgQuality: weekRecords.isEmpty
                    ? 0 : round1(weekRecords.map { Double($0.quality) }.reduce(0, +) / Double(weekRecords.count)),
                count: weekRecords.count
            ))
        }
        return result.reversed()
    }

    /// Mon…Sun averages (server `get_day_of_week_stats`).
    static func dayOfWeekStats(records: [SleepRecord]) -> [DayOfWeekStat] {
        let order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        var buckets: [String: (hours: [Double], quality: [Int])] = [:]
        for r in records {
            guard let date = DateUtil.date(from: r.date) else { continue }
            let day = Self.weekdayFormatter.string(from: date)
            buckets[day, default: ([], [])].hours.append(r.hours)
            buckets[day, default: ([], [])].quality.append(r.quality)
        }
        return order.map { day in
            guard let data = buckets[day], !data.hours.isEmpty else {
                return DayOfWeekStat(day: day, avgHours: 0, avgQuality: 0, count: 0)
            }
            return DayOfWeekStat(
                day: day,
                avgHours: round1(data.hours.reduce(0, +) / Double(data.hours.count)),
                avgQuality: round1(data.quality.map(Double.init).reduce(0, +) / Double(data.quality.count)),
                count: data.hours.count
            )
        }
    }

    /// Top/bottom 5 by hours (server `get_best_worst_nights`).
    static func bestWorst(records: [SleepRecord], count: Int = 5) -> BestWorstNights {
        let ascending = records.sorted { ($0.date, $0.id) < ($1.date, $1.id) }
        return BestWorstNights(
            best: Array(ascending.sorted { $0.hours > $1.hours }.prefix(count)),
            worst: Array(ascending.sorted { $0.hours < $1.hours }.prefix(count))
        )
    }

    /// Last 6 calendar months oldest-first (server `get_monthly_trend`).
    static func monthlyTrend(
        records: [SleepRecord], today: Date = Date(), months: Int = 6
    ) -> [MonthlyTrendPoint] {
        let calendar = Calendar.current
        let startOfThisMonth = calendar.date(
            from: calendar.dateComponents([.year, .month], from: today)
        ) ?? today
        var result: [MonthlyTrendPoint] = []
        for i in stride(from: months - 1, through: 0, by: -1) {
            guard let monthStart = calendar.date(byAdding: .month, value: -i, to: startOfThisMonth)
            else { continue }
            let key = String(DateUtil.string(from: monthStart).prefix(7)) // YYYY-MM
            let monthHours = records
                .filter { DateUtil.monthKey($0.date) == key }
                .map(\.hours)
            result.append(MonthlyTrendPoint(
                label: Self.monthFormatter.string(from: monthStart),
                avgHours: monthHours.isEmpty
                    ? 0 : round1(monthHours.reduce(0, +) / Double(monthHours.count)),
                count: monthHours.count
            ))
        }
        return result
    }

    // MARK: - Helpers

    /// Latest record per date: highest id wins (server iterates date ASC,
    /// id ASC and lets later rows overwrite).
    static func latestByDate(_ records: [SleepRecord]) -> [String: SleepRecord] {
        var result: [String: SleepRecord] = [:]
        for record in records.sorted(by: { ($0.date, $0.id) < ($1.date, $1.id) }) {
            result[record.date] = record
        }
        return result
    }

    static func dayString(daysBefore offset: Int, of date: Date) -> String {
        let day = Calendar.current.date(byAdding: .day, value: -offset, to: date) ?? date
        return DateUtil.string(from: day)
    }

    private static func round2(_ value: Double) -> Double {
        (value * 100).rounded() / 100
    }

    private static func round1(_ value: Double) -> Double {
        (value * 10).rounded() / 10
    }

    private static let weekdayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "EEE"
        f.timeZone = .current
        return f
    }()

    private static let monthFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "MMM yyyy"
        f.timeZone = .current
        return f
    }()

    private static func shortDate(_ dayString: String) -> String {
        guard let date = DateUtil.date(from: dayString) else { return dayString }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "MMM dd"
        f.timeZone = .current
        return f.string(from: date)
    }
}
