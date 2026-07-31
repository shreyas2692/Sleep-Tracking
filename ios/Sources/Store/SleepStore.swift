import Foundation
import SwiftUI

/// App-wide state: loads from the server, disk-caches the last good JSON
/// responses in Application Support so the app opens instantly with data
/// even when the server is unreachable.
@MainActor
final class SleepStore: ObservableObject {

    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failed(String)

        var errorMessage: String? {
            if case .failed(let message) = self { return message }
            return nil
        }
    }

    struct PendingUndo: Identifiable, Equatable {
        let id = UUID()
        let record: SleepRecord
    }

    @Published private(set) var records: [SleepRecord] = []
    @Published private(set) var stats: Stats?
    @Published private(set) var series30: SeriesResponse?
    @Published private(set) var insights: InsightsResponse?
    @Published private(set) var seriesByRange: [SeriesRange: SeriesResponse] = [:]
    @Published private(set) var loadState: LoadState = .idle
    @Published private(set) var hasCachedData = false
    @Published var pendingUndo: PendingUndo?

    @Published var config: ServerConfig {
        didSet {
            guard config != oldValue else { return }
            saveConfig()
        }
    }

    var client: APIClient { APIClient(config: config) }

    private static let configKey = "sleeptracker.server.config"

    init() {
        if let data = UserDefaults.standard.data(forKey: Self.configKey),
           var saved = try? JSONDecoder().decode(ServerConfig.self, from: data) {
            if saved.password.isEmpty {
                saved.password = KeychainStore.getPassword() ?? ""
                config = saved
            } else {
                // Legacy install: password still in UserDefaults — move it
                // to the Keychain and rewrite the sanitized blob.
                config = saved
                saveConfig()
            }
        } else {
            config = ServerConfig()
        }
        loadCache()
    }

    /// The password lives in the Keychain; UserDefaults only ever holds
    /// a copy of the config with the password blanked.
    private func saveConfig() {
        KeychainStore.setPassword(config.password)
        var sanitized = config
        sanitized.password = ""
        if let data = try? JSONEncoder().encode(sanitized) {
            UserDefaults.standard.set(data, forKey: Self.configKey)
        }
    }

    // MARK: - Refresh

    func refresh() async {
        if records.isEmpty && stats == nil { loadState = .loading }
        do {
            async let recordsTask = client.records()
            async let statsTask = client.stats()
            async let seriesTask = client.series(range: .d30)
            // Insights are additive: a failure here never fails the refresh.
            async let insightsTask = client.insights()
            let (records, stats, series) = try await (recordsTask, statsTask, seriesTask)
            self.records = records
            self.stats = stats
            self.series30 = series
            self.seriesByRange[.d30] = series
            if let insights = try? await insightsTask {
                self.insights = insights
            }
            self.loadState = .loaded
            persistCache()
        } catch {
            loadState = .failed((error as? APIError)?.errorDescription ?? error.localizedDescription)
        }
    }

    func loadSeries(range: SeriesRange) async {
        do {
            let series = try await client.series(range: range)
            seriesByRange[range] = series
            if range == .d30 { series30 = series }
        } catch {
            // Keep whatever we had; range views surface their own errors
            // through `loadState` when nothing is cached.
            if seriesByRange[range] == nil {
                loadState = .failed((error as? APIError)?.errorDescription ?? error.localizedDescription)
            }
        }
    }

    // MARK: - Mutations

    private func apply(_ response: MutationResponse) {
        records = response.records
        stats = response.stats
        persistCache()
        Task { await loadSeries(range: .d30) }
        Task { await refreshInsights() }
    }

    private func refreshInsights() async {
        // Best-effort: nudges just keep their last value if this fails.
        if let fresh = try? await client.insights() {
            insights = fresh
            persistCache()
        }
    }

    func addNight(_ fields: APIClient.NightFields) async throws {
        apply(try await client.add(fields))
        Haptics.success()
    }

    func editNight(id: Int, fields: APIClient.NightFields) async throws {
        apply(try await client.edit(id: id, fields: fields))
        Haptics.success()
    }

    /// Deletes on the server and stages an undo toast.
    func deleteNight(_ record: SleepRecord) async throws {
        apply(try await client.delete(id: record.id))
        pendingUndo = PendingUndo(record: record)
        Haptics.warning()
    }

    /// Re-adds the last deleted night (a new id is assigned by the server).
    func undoDelete() async {
        guard let undo = pendingUndo else { return }
        pendingUndo = nil
        let r = undo.record
        let fields = APIClient.NightFields(
            date: r.date, bedtime: r.bedtime, wake: r.wake,
            quality: r.quality, notes: r.notes
        )
        do {
            apply(try await client.add(fields))
        } catch {
            loadState = .failed((error as? APIError)?.errorDescription ?? error.localizedDescription)
        }
    }

    // MARK: - Disk cache (Application Support)

    private var cacheDirectory: URL? {
        guard let base = FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask
        ).first else { return nil }
        let dir = base.appendingPathComponent("SleepTracker", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    private func cacheURL(_ name: String) -> URL? {
        cacheDirectory?.appendingPathComponent(name)
    }

    private func persistCache() {
        let encoder = JSONEncoder()
        if let url = cacheURL("records.json"), let data = try? encoder.encode(records) {
            try? data.write(to: url, options: .atomic)
        }
        if let url = cacheURL("stats.json"), let stats, let data = try? encoder.encode(stats) {
            try? data.write(to: url, options: .atomic)
        }
        if let url = cacheURL("series-30d.json"), let series30, let data = try? encoder.encode(series30) {
            try? data.write(to: url, options: .atomic)
        }
        if let url = cacheURL("insights.json"), let insights, let data = try? encoder.encode(insights) {
            try? data.write(to: url, options: .atomic)
        }
    }

    private func loadCache() {
        let decoder = JSONDecoder()
        if let url = cacheURL("records.json"),
           let data = try? Data(contentsOf: url),
           let cached = try? decoder.decode([SleepRecord].self, from: data) {
            records = cached
            hasCachedData = true
        }
        if let url = cacheURL("stats.json"),
           let data = try? Data(contentsOf: url),
           let cached = try? decoder.decode(Stats.self, from: data) {
            stats = cached
        }
        if let url = cacheURL("series-30d.json"),
           let data = try? Data(contentsOf: url),
           let cached = try? decoder.decode(SeriesResponse.self, from: data) {
            series30 = cached
            seriesByRange[.d30] = cached
        }
        if let url = cacheURL("insights.json"),
           let data = try? Data(contentsOf: url),
           let cached = try? decoder.decode(InsightsResponse.self, from: data) {
            insights = cached
        }
    }

    #if DEBUG
    /// Seed store for SwiftUI Previews / screenshot tooling (no network).
    func applyPreviewFixtures(
        records: [SleepRecord],
        stats: Stats?,
        seriesByRange: [SeriesRange: SeriesResponse],
        loadState: LoadState,
        insights: InsightsResponse? = nil
    ) {
        self.records = records
        self.stats = stats
        self.seriesByRange = seriesByRange
        self.series30 = seriesByRange[.d30]
        self.loadState = loadState
        self.insights = insights
        self.hasCachedData = !records.isEmpty || stats != nil
    }
    #endif
}
