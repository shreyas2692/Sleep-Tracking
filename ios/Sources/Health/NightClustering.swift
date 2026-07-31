import Foundation

// MARK: - Pure night-clustering logic, mirroring importers/apple_health.py.
//
// Rules ported faithfully:
// - gap < 4h between samples = same night; >= 4h starts a new cluster
// - nights shorter than 30m or longer than 36h are dropped
// - at most one night per wake date; the longest cluster wins
// - stage mapping: AsleepDeep -> deep, AsleepREM -> rem, AsleepCore -> light,
//   Awake -> awake; InBed / Asleep(Unspecified) span the night but carry no
//   stage breakdown (a night with only those gets stages == nil)
// - overlapping stage intervals from multiple devices are made exclusive with
//   precedence awake > deep > rem > light, then rounded to minutes while
//   conserving the combined total
// - the night's date is the WAKE date (local wall clock)

enum SleepSampleKind: Equatable, Hashable {
    case stage(StageName)
    case spanOnly // InBed, Asleep, AsleepUnspecified

    enum StageName: String, CaseIterable {
        case deep, rem, light, awake
    }
}

struct SleepSampleInterval: Equatable {
    let start: Date
    let end: Date
    let kind: SleepSampleKind

    init(start: Date, end: Date, kind: SleepSampleKind) {
        self.start = start
        self.end = end
        self.kind = kind
    }
}

struct ClusteredNight: Equatable, Identifiable {
    let date: String     // YYYY-MM-DD, wake date
    let bedtime: String  // HH:mm
    let wake: String     // HH:mm
    let stages: SleepStages?
    let start: Date
    let end: Date

    var id: String { date }
    var durationHours: Double { end.timeIntervalSince(start) / 3600.0 }
}

enum NightClustering {
    static let maxGap: TimeInterval = 4 * 3600
    static let minNightDuration: TimeInterval = 30 * 60
    static let maxNightDuration: TimeInterval = 36 * 3600
    /// Exclusivity precedence for overlapping stage claims (tie-breaker, not
    /// physiology): awake > deep > rem > light.
    static let stagePrecedence: [SleepSampleKind.StageName] = [.awake, .deep, .rem, .light]

    /// Cluster raw sleep samples into normalized nights.
    static func nights(
        from samples: [SleepSampleInterval],
        timeZone: TimeZone = .current
    ) -> [ClusteredNight] {
        let valid = samples.filter {
            $0.end > $0.start && $0.end.timeIntervalSince($0.start) <= maxNightDuration
        }
        guard !valid.isEmpty else { return [] }

        let clusters = cluster(valid)

        // One night per wake date, longest wins.
        var selected: [String: ClusteredNight] = [:]
        for cluster in clusters {
            guard let night = build(cluster: cluster, timeZone: timeZone) else { continue }
            let duration = night.end.timeIntervalSince(night.start)
            guard duration >= minNightDuration, duration <= maxNightDuration else { continue }
            if let existing = selected[night.date],
               existing.end.timeIntervalSince(existing.start) >= duration {
                continue
            }
            selected[night.date] = night
        }
        return selected.keys.sorted().compactMap { selected[$0] }
    }

    /// Group records into clusters: contiguous runs with gaps < 4 hours.
    static func cluster(_ samples: [SleepSampleInterval]) -> [[SleepSampleInterval]] {
        let sorted = samples.sorted {
            ($0.start, $0.end) < ($1.start, $1.end)
        }
        var clusters: [[SleepSampleInterval]] = []
        var current: [SleepSampleInterval] = []
        var currentEnd: Date?
        for sample in sorted {
            if let end = currentEnd, !current.isEmpty,
               sample.start.timeIntervalSince(end) >= maxGap {
                clusters.append(current)
                current = []
                currentEnd = nil
            }
            current.append(sample)
            currentEnd = currentEnd.map { max($0, sample.end) } ?? sample.end
        }
        if !current.isEmpty { clusters.append(current) }
        return clusters
    }

    private static func build(
        cluster: [SleepSampleInterval], timeZone: TimeZone
    ) -> ClusteredNight? {
        guard let bedtime = cluster.map(\.start).min(),
              let wake = cluster.map(\.end).max()
        else { return nil }

        var stageIntervals: [SleepSampleKind.StageName: [(Date, Date)]] = [
            .deep: [], .rem: [], .light: [], .awake: [],
        ]
        var hasStageData = false
        for sample in cluster {
            if case .stage(let name) = sample.kind {
                stageIntervals[name, default: []].append((sample.start, sample.end))
                hasStageData = true
            }
        }

        var stages: SleepStages?
        if hasStageData {
            var exclusive: [SleepSampleKind.StageName: [(Date, Date)]] = [:]
            var claimed: [(Date, Date)] = []
            for stage in stagePrecedence {
                let own = subtract(intervals: stageIntervals[stage] ?? [], blockers: claimed)
                exclusive[stage] = own
                claimed = merge(claimed + own)
            }
            let minutes = roundStageMinutes(exclusive)
            stages = SleepStages(
                deep: minutes[.deep] ?? 0,
                rem: minutes[.rem] ?? 0,
                light: minutes[.light] ?? 0,
                awake: minutes[.awake] ?? 0
            )
        }

        let dayFormatter = DateFormatter()
        dayFormatter.locale = Locale(identifier: "en_US_POSIX")
        dayFormatter.timeZone = timeZone
        dayFormatter.dateFormat = "yyyy-MM-dd"
        let timeFormatter = DateFormatter()
        timeFormatter.locale = Locale(identifier: "en_US_POSIX")
        timeFormatter.timeZone = timeZone
        timeFormatter.dateFormat = "HH:mm"

        return ClusteredNight(
            date: dayFormatter.string(from: wake),
            bedtime: timeFormatter.string(from: bedtime),
            wake: timeFormatter.string(from: wake),
            stages: stages,
            start: bedtime,
            end: wake
        )
    }

    /// Merge overlapping/touching intervals (multi-device de-duplication).
    static func merge(_ intervals: [(Date, Date)]) -> [(Date, Date)] {
        var merged: [(Date, Date)] = []
        for (start, end) in intervals.sorted(by: { ($0.0, $0.1) < ($1.0, $1.1) }) {
            if let last = merged.last, start <= last.1 {
                if end > last.1 { merged[merged.count - 1] = (last.0, end) }
            } else {
                merged.append((start, end))
            }
        }
        return merged
    }

    /// Remove `blockers` from `intervals`; both inputs may overlap internally.
    static func subtract(
        intervals: [(Date, Date)], blockers: [(Date, Date)]
    ) -> [(Date, Date)] {
        var result: [(Date, Date)] = []
        let mergedBlockers = merge(blockers)
        for (start, end) in merge(intervals) {
            var cursor = start
            for (blockStart, blockEnd) in mergedBlockers {
                if blockEnd <= cursor { continue }
                if blockStart >= end { break }
                if blockStart > cursor {
                    result.append((cursor, min(blockStart, end)))
                }
                cursor = max(cursor, blockEnd)
                if cursor >= end { break }
            }
            if cursor < end { result.append((cursor, end)) }
        }
        return result
    }

    /// Round exclusive stage seconds to minutes while conserving the total.
    static func roundStageMinutes(
        _ exclusive: [SleepSampleKind.StageName: [(Date, Date)]]
    ) -> [SleepSampleKind.StageName: Int] {
        var seconds: [SleepSampleKind.StageName: Double] = [:]
        for (stage, intervals) in exclusive {
            seconds[stage] = intervals.reduce(0) { $0 + $1.1.timeIntervalSince($1.0) }
        }
        var minutes = seconds.mapValues { Int($0 / 60.0) }
        let roundedTotal = Int(seconds.values.reduce(0, +) / 60.0 + 0.5)
        let remaining = roundedTotal - minutes.values.reduce(0, +)
        guard remaining > 0 else { return minutes }
        let rank = Dictionary(
            uniqueKeysWithValues: stagePrecedence.enumerated().map { ($1, $0) }
        )
        let byRemainder = seconds.keys.sorted { a, b in
            let ra = seconds[a]!.truncatingRemainder(dividingBy: 60)
            let rb = seconds[b]!.truncatingRemainder(dividingBy: 60)
            if ra != rb { return ra > rb }
            return (rank[a] ?? 99) < (rank[b] ?? 99)
        }
        for stage in byRemainder.prefix(remaining) {
            minutes[stage, default: 0] += 1
        }
        return minutes
    }
}
