import Foundation

// MARK: - Codable models matching the server API contract (AGENTS.md) exactly.

struct SleepStages: Codable, Equatable, Hashable {
    var deep: Int
    var rem: Int
    var light: Int
    var awake: Int

    var totalMinutes: Int { deep + rem + light + awake }
    var asleepMinutes: Int { deep + rem + light }
}

struct SleepRecord: Codable, Identifiable, Equatable, Hashable {
    let id: Int
    var date: String
    var bedtime: String
    var wake: String
    var quality: Int
    var notes: String
    var hours: Double
    var source: String
    var stages: SleepStages?
    var efficiency: Double?

    var isImported: Bool { source != "manual" }

    var sourceLabel: String? {
        switch source {
        case "apple_health": return "Watch"
        case "fitbit": return "Fitbit"
        case "manual": return nil
        default: return source.isEmpty ? nil : source.capitalized
        }
    }
}

/// One day of the 30-day dashboard series inside the stats object.
/// Days with no record have `hours: null`.
struct StatsSeriesDay: Codable, Equatable {
    let date: String
    let hours: Double?
    let quality: Double?
}

struct SleepDebtDay: Codable, Equatable {
    let date: String
    let debtHours: Double
    let cumulativeDebtHours: Double

    enum CodingKeys: String, CodingKey {
        case date
        case debtHours = "debt_hours"
        case cumulativeDebtHours = "cumulative_debt_hours"
    }
}

struct SleepDebt: Codable, Equatable {
    let need: Double
    let rolling14d: [SleepDebtDay]
    let totalDebtHours: Double

    enum CodingKeys: String, CodingKey {
        case need
        case rolling14d = "rolling_14d"
        case totalDebtHours = "total_debt_hours"
    }
}

struct Stats: Codable, Equatable {
    let total: Int
    let avgHours: Double?
    let avgQuality: Double?
    let currentStreak: Int
    let bestStreak: Int
    let series: [StatsSeriesDay]
    let sleepDebt: SleepDebt?

    enum CodingKeys: String, CodingKey {
        case total
        case avgHours = "avg_hours"
        case avgQuality = "avg_quality"
        case currentStreak = "current_streak"
        case bestStreak = "best_streak"
        case series
        case sleepDebt = "sleep_debt"
    }
}

// MARK: - /api/insights

struct WeeklyAverage: Codable, Equatable {
    let label: String
    let avgHours: Double
    let avgQuality: Double
    let count: Int

    enum CodingKeys: String, CodingKey {
        case label
        case avgHours = "avg_hours"
        case avgQuality = "avg_quality"
        case count
    }
}

struct DayOfWeekStat: Codable, Equatable {
    let day: String
    let avgHours: Double
    let avgQuality: Double
    let count: Int

    enum CodingKeys: String, CodingKey {
        case day
        case avgHours = "avg_hours"
        case avgQuality = "avg_quality"
        case count
    }
}

struct MonthlyTrendPoint: Codable, Equatable {
    let label: String
    let avgHours: Double
    let count: Int

    enum CodingKeys: String, CodingKey {
        case label
        case avgHours = "avg_hours"
        case count
    }
}

struct BestWorstNights: Codable, Equatable {
    let best: [SleepRecord]
    let worst: [SleepRecord]
}

/// Full payload of GET /api/insights. `weekly` is oldest-first with 12
/// buckets; `count == 0` buckets are gaps, not zero-hour weeks.
/// `consistency` is 0–100 where 0 means "not enough data", not "poor".
struct InsightsResponse: Codable, Equatable {
    let stats: Stats
    let streak: Int
    let consistency: Int
    let weekly: [WeeklyAverage]
    let dayOfWeek: [DayOfWeekStat]
    let bestWorst: BestWorstNights
    let monthly: [MonthlyTrendPoint]

    enum CodingKeys: String, CodingKey {
        case stats
        case streak
        case consistency
        case weekly
        case dayOfWeek = "day_of_week"
        case bestWorst = "best_worst"
        case monthly
    }
}

// MARK: - /api/series

enum SeriesRange: String, CaseIterable, Identifiable {
    case d30 = "30d"
    case d90 = "90d"
    case y1 = "1y"
    case all = "all"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .d30: return "30d"
        case .d90: return "90d"
        case .y1: return "1y"
        case .all: return "All"
        }
    }
}

struct SeriesNight: Codable, Equatable, Identifiable {
    let date: String
    let hours: Double
    let quality: Int?
    let stages: SleepStages?
    let source: String?

    var id: String { date }
}

struct SeriesResponse: Codable, Equatable {
    let range: String
    let nights: [SeriesNight]
    let start: String
    let end: String
}

/// Shape returned by POST /add, /edit/<id>, /delete/<id> (AJAX).
struct MutationResponse: Codable {
    let ok: Bool
    let records: [SleepRecord]
    let stats: Stats
}

struct APIErrorBody: Codable {
    let error: String
}

// MARK: - Date helpers (contract dates are zero-padded YYYY-MM-DD local days)

enum DateUtil {
    static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        f.timeZone = .current
        return f
    }()

    static func date(from string: String) -> Date? {
        dayFormatter.date(from: string)
    }

    static func string(from date: Date) -> String {
        dayFormatter.string(from: date)
    }

    static func display(_ string: String, format: String) -> String {
        guard let date = date(from: string) else { return string }
        let f = DateFormatter()
        f.locale = .current
        f.setLocalizedDateFormatFromTemplate(format)
        return f.string(from: date)
    }

    static func monthKey(_ string: String) -> String {
        String(string.prefix(7))
    }

    static func monthTitle(_ key: String) -> String {
        guard let date = date(from: key + "-01") else { return key }
        let f = DateFormatter()
        f.locale = .current
        f.setLocalizedDateFormatFromTemplate("MMMM yyyy")
        return f.string(from: date)
    }
}

enum Format {
    static func hours(_ value: Double, decimals: Int = 1) -> String {
        String(format: "%.\(decimals)f", value)
    }

    static func minutes(_ minutes: Int) -> String {
        let h = minutes / 60
        let m = minutes % 60
        if h > 0 && m > 0 { return "\(h)h \(m)m" }
        if h > 0 { return "\(h)h" }
        return "\(m)m"
    }

    /// Neutral sleep-debt phrasing: never alarming, oversleep reads as rest.
    static func debtHeadline(_ totalDebtHours: Double) -> String {
        if totalDebtHours > 0.05 {
            return "\(hours(totalDebtHours))h behind"
        } else if totalDebtHours < -0.05 {
            return "Rested +\(hours(-totalDebtHours))h"
        }
        return "On balance"
    }
}
