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

    /// Push clustered nights to the server via POST /add, skipping dates the
    /// server already has. Returns after updating `state`.
    func push(to client: APIClient, existingDates: Set<String>, defaultQuality: Int = 3) async -> MutationResponse? {
        guard !nights.isEmpty else { return nil }
        var uploaded = 0
        var skipped = 0
        var lastResponse: MutationResponse?
        let todo = nights
        state = .pushing(done: 0, total: todo.count)
        for night in todo {
            if existingDates.contains(night.date) {
                skipped += 1
            } else {
                let stageNote: String
                if let stages = night.stages {
                    stageNote = " (\(Format.minutes(stages.deep)) deep, \(Format.minutes(stages.rem)) REM)"
                } else {
                    stageNote = ""
                }
                let fields = APIClient.NightFields(
                    date: night.date,
                    bedtime: night.bedtime,
                    wake: night.wake,
                    quality: defaultQuality,
                    notes: "Synced from Apple Health\(stageNote)"
                )
                do {
                    lastResponse = try await client.add(fields)
                    uploaded += 1
                } catch {
                    state = .failed("Upload stopped after \(uploaded) nights. \((error as? APIError)?.errorDescription ?? error.localizedDescription)")
                    return lastResponse
                }
            }
            state = .pushing(done: uploaded + skipped, total: todo.count)
        }
        state = .pushed(uploaded: uploaded, skipped: skipped)
        return lastResponse
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
