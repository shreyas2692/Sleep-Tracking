import Foundation
import HealthKit

/// Reads HKCategoryTypeIdentifierSleepAnalysis samples and clusters them into
/// nights with the same rules as the server's Apple Health importer.
///
/// The whole feature degrades gracefully: when Health data is unavailable
/// (no permission, no data, or an unsupported device) the app simply reports
/// that state — the primary data path is always the server API.
@MainActor
final class HealthKitService: ObservableObject {

    enum SyncState: Equatable {
        case idle
        case unavailable(String)
        case requestingPermission
        case fetching
        case fetched(nightCount: Int)
        case pushing(done: Int, total: Int)
        case pushed(uploaded: Int, skipped: Int)
        case failed(String)
    }

    @Published private(set) var state: SyncState = .idle
    @Published private(set) var nights: [ClusteredNight] = []

    private let store = HKHealthStore()

    var isAvailable: Bool { HKHealthStore.isHealthDataAvailable() }

    /// Request read permission and fetch + cluster all sleep samples.
    func sync() async {
        guard isAvailable else {
            state = .unavailable("Health data isn't available on this device.")
            return
        }
        guard let sleepType = HKObjectType.categoryType(
            forIdentifier: .sleepAnalysis
        ) else {
            state = .unavailable("Sleep analysis isn't available on this device.")
            return
        }

        state = .requestingPermission
        do {
            try await store.requestAuthorization(toShare: [], read: [sleepType])
        } catch {
            state = .unavailable("Health permission couldn't be requested. \(error.localizedDescription)")
            return
        }

        state = .fetching
        do {
            let samples = try await fetchSamples(of: sleepType)
            let intervals = samples.compactMap(Self.interval(from:))
            let clustered = NightClustering.nights(from: intervals)
            nights = clustered
            state = .fetched(nightCount: clustered.count)
        } catch {
            // An empty read (no permission granted) surfaces here too; keep calm.
            nights = []
            state = .failed("Couldn't read sleep data from Health. \(error.localizedDescription)")
        }
    }

    /// Push clustered nights via `POST /api/ingest` (source `apple_health`).
    /// Re-posts update in place by (date, source). Returns ingest summary.
    @discardableResult
    func push(to client: APIClient, existingDates: Set<String> = []) async -> APIClient.IngestResponse? {
        guard !nights.isEmpty else { return nil }

        // Prefer new nights, but allow re-sync of all if everything already exists
        // (ingest upserts by date+source).
        let newOnly = nights.filter { !existingDates.contains($0.date) }
        let todo = newOnly.isEmpty ? nights : newOnly

        state = .pushing(done: 0, total: todo.count)
        var batch: [APIClient.IngestNight] = []
        for night in todo {
            batch.append(Self.ingestPayload(from: night))
        }

        // Chunk to stay under server max (100 nights / call).
        let chunkSize = 50
        var imported = 0
        var replaced = 0
        var skipped = 0
        var last: APIClient.IngestResponse?
        var done = 0
        do {
            for start in stride(from: 0, to: batch.count, by: chunkSize) {
                let end = min(start + chunkSize, batch.count)
                let chunk = Array(batch[start..<end])
                let response = try await client.ingest(chunk)
                last = response
                imported += response.imported
                replaced += response.replaced
                skipped += response.skipped
                if let errors = response.errors, !errors.isEmpty, response.imported + response.replaced == 0 {
                    let msg = errors.prefix(2).map(\.error).joined(separator: "; ")
                    state = .failed("Server rejected Health sync: \(msg)")
                    return response
                }
                done = end
                state = .pushing(done: done, total: batch.count)
            }
            // Nights we intentionally left out as "already present" (when we filtered newOnly).
            if !newOnly.isEmpty {
                skipped += nights.count - newOnly.count
            }
            state = .pushed(uploaded: imported + replaced, skipped: skipped)
            return last
        } catch {
            state = .failed(
                "Upload stopped after \(done) nights. "
                + ((error as? APIError)?.errorDescription ?? error.localizedDescription)
            )
            return last
        }
    }

    /// Import clustered nights into the on-phone store (no-server mode).
    /// Same `(date, source)` upsert identity as the server's ingest.
    func importLocally(into store: SleepStore) {
        guard !nights.isEmpty else { return }
        let result = store.importHealthNights(nights)
        state = .pushed(uploaded: result.imported + result.replaced, skipped: result.skipped)
    }

    /// Map a clustered night to ingest JSON. Stages only when totals are
    /// close to the night length (server validates that relationship).
    static func ingestPayload(from night: ClusteredNight) -> APIClient.IngestNight {
        let quality = deriveQuality(stages: night.stages)
        var stages = night.stages
        if let s = stages {
            let nightMinutes = max(1, Int((night.durationHours * 60).rounded()))
            if abs(s.totalMinutes - nightMinutes) > 120 {
                stages = nil // avoid hard reject; times still upload
            }
        }
        let note: String
        if let s = stages {
            note = "Synced from Apple Health (\(Format.minutes(s.deep)) deep, \(Format.minutes(s.rem)) REM)"
        } else {
            note = "Synced from Apple Health"
        }
        return APIClient.IngestNight(
            date: night.date,
            bedtime: night.bedtime,
            wake: night.wake,
            quality: quality,
            notes: note,
            source: "apple_health",
            stages: stages,
            efficiency: nil
        )
    }

    /// Same thresholds as server `derive_quality` / wearable import.
    static func deriveQuality(stages: SleepStages?) -> Int {
        guard let stages else { return 3 }
        let total = stages.totalMinutes
        guard total > 0 else { return 3 }
        let fraction = Double(stages.deep + stages.rem) / Double(total)
        if fraction >= 0.35 { return 5 }
        if fraction >= 0.28 { return 4 }
        if fraction >= 0.20 { return 3 }
        if fraction >= 0.12 { return 2 }
        return 1
    }

    // MARK: - HealthKit plumbing

    private func fetchSamples(of type: HKCategoryType) async throws -> [HKCategorySample] {
        try await withCheckedThrowingContinuation { continuation in
            let sort = NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: true)
            let query = HKSampleQuery(
                sampleType: type,
                predicate: nil,
                limit: HKObjectQueryNoLimit,
                sortDescriptors: [sort]
            ) { _, samples, error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: (samples as? [HKCategorySample]) ?? [])
                }
            }
            store.execute(query)
        }
    }

    /// Map one HealthKit sample to a clustering interval.
    /// Deep/REM/Core(->light)/Awake carry stages; InBed and Asleep(Unspecified)
    /// span the night without a stage breakdown; anything else is ignored.
    static func interval(from sample: HKCategorySample) -> SleepSampleInterval? {
        guard let value = HKCategoryValueSleepAnalysis(rawValue: sample.value) else {
            return nil
        }
        let kind: SleepSampleKind
        switch value {
        case .asleepDeep: kind = .stage(.deep)
        case .asleepREM: kind = .stage(.rem)
        case .asleepCore: kind = .stage(.light)
        case .awake: kind = .stage(.awake)
        case .inBed, .asleepUnspecified: kind = .spanOnly
        @unknown default: return nil
        }
        return SleepSampleInterval(start: sample.startDate, end: sample.endDate, kind: kind)
    }
}
