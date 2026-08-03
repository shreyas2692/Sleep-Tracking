import Foundation
import SwiftUI

/// A local-mode mutation that couldn't be validated.
enum LocalStoreError: LocalizedError, Equatable {
    case invalid(String)
    case notFound

    var errorDescription: String? {
        switch self {
        case .invalid(let message): return message
        case .notFound: return "That night no longer exists."
        }
    }
}

/// App-wide state. Two modes:
///
/// - **Server** (default): loads from the configured server, disk-caches the
///   last good JSON responses so the app opens instantly with data even when
///   the server is unreachable.
/// - **Local** (no server): nights persist in a JSON file in Application
///   Support; stats, series, and insights are computed on device by
///   `LocalAnalytics`. Apple Health imports land here too, so the app is
///   fully functional without any server.
@MainActor
final class SleepStore: ObservableObject {

    enum Mode: String {
        case server
        case local
    }

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
    @Published private(set) var aiSummary: AISummary?
    @Published private(set) var seriesByRange: [SeriesRange: SeriesResponse] = [:]
    @Published private(set) var loadState: LoadState = .idle
    @Published private(set) var hasCachedData = false
    @Published var pendingUndo: PendingUndo?

    @Published private(set) var mode: Mode {
        didSet {
            guard mode != oldValue else { return }
            UserDefaults.standard.set(mode.rawValue, forKey: Self.modeKey)
        }
    }

    var isLocalMode: Bool { mode == .local }

    @Published var config: ServerConfig {
        didSet {
            guard config != oldValue else { return }
            // A different server must never show the previous server's data:
            // drop the in-memory state and the disk cache before anything
            // refreshes against the new base URL.
            if config.normalizedBase != oldValue.normalizedBase {
                clearServerData()
            }
            saveConfig()
        }
    }

    var client: APIClient { APIClient(config: config) }

    /// Claude-written weekly narrative, only when the server has it enabled
    /// (`{available: false}` must hide the card).
    var weeklySummaryText: String? {
        guard mode == .server,
              let aiSummary, aiSummary.available,
              let text = aiSummary.summary, !text.isEmpty
        else { return nil }
        return text
    }

    private static let configKey = "sleeptracker.server.config"
    private static let modeKey = "sleeptracker.mode"

    /// Nights stored on this phone (local mode). Persisted separately from
    /// the server response cache so switching modes never mixes datasets.
    private var localRecords: [SleepRecord] = []

    init() {
        mode = Mode(rawValue: UserDefaults.standard.string(forKey: Self.modeKey) ?? "") ?? .server
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
        if mode == .local {
            loadLocalRecords()
            recomputeLocal()
        } else {
            loadCache()
        }
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

    // MARK: - Mode switching

    /// Run entirely on this phone: nights live in Application Support and
    /// analytics are computed locally. A server can be connected later.
    func enableLocalMode() {
        guard mode != .local else { return }
        mode = .local
        pendingUndo = nil
        loadLocalRecords()
        recomputeLocal()
    }

    /// Back to a server as the source of truth (called after a successful
    /// connection test). Local nights stay on disk untouched.
    func enableServerMode() {
        guard mode != .server else { return }
        mode = .server
        pendingUndo = nil
        records = []
        stats = nil
        series30 = nil
        insights = nil
        aiSummary = nil
        seriesByRange = [:]
        hasCachedData = false
        loadState = .idle
        loadCache()
    }

    // MARK: - Refresh

    func refresh() async {
        if mode == .local {
            recomputeLocal()
            return
        }
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
            // Claude summary can take seconds server-side — fetch after the
            // main refresh so it never delays the dashboard.
            Task {
                if let summary = try? await self.client.aiSummary() {
                    self.aiSummary = summary
                }
            }
        } catch {
            loadState = .failed((error as? APIError)?.errorDescription ?? error.localizedDescription)
        }
    }

    func loadSeries(range: SeriesRange) async {
        if mode == .local {
            seriesByRange[range] = LocalAnalytics.series(records: localRecords, range: range)
            if range == .d30 { series30 = seriesByRange[range] }
            return
        }
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
        if mode == .local {
            try addLocal(fields)
        } else {
            apply(try await client.add(fields))
        }
        Haptics.success()
    }

    func editNight(id: Int, fields: APIClient.NightFields) async throws {
        if mode == .local {
            try editLocal(id: id, fields: fields)
        } else {
            apply(try await client.edit(id: id, fields: fields))
        }
        Haptics.success()
    }

    /// Deletes (server or local) and stages an undo toast.
    func deleteNight(_ record: SleepRecord) async throws {
        if mode == .local {
            guard let index = localRecords.firstIndex(where: { $0.id == record.id }) else {
                throw LocalStoreError.notFound
            }
            localRecords.remove(at: index)
            recomputeLocal()
        } else {
            apply(try await client.delete(id: record.id))
        }
        pendingUndo = PendingUndo(record: record)
        Haptics.warning()
    }

    /// Restores the last deleted night faithfully. Local mode reinserts the
    /// exact record. On a server, manual nights go through `/add`; imported
    /// nights (apple_health / fitbit) go through `/api/ingest` so `source`,
    /// `stages`, and `efficiency` survive the round trip.
    func undoDelete() async {
        guard let undo = pendingUndo else { return }
        pendingUndo = nil
        let r = undo.record

        if mode == .local {
            localRecords.append(r)
            recomputeLocal()
            return
        }

        do {
            if r.isImported {
                let night = APIClient.IngestNight(
                    date: r.date, bedtime: r.bedtime, wake: r.wake,
                    quality: r.quality, notes: r.notes, source: r.source,
                    stages: r.stages, efficiency: r.efficiency
                )
                _ = try await client.ingest([night])
                await refresh()
            } else {
                let fields = APIClient.NightFields(
                    date: r.date, bedtime: r.bedtime, wake: r.wake,
                    quality: r.quality, notes: r.notes
                )
                apply(try await client.add(fields))
            }
        } catch {
            loadState = .failed((error as? APIError)?.errorDescription ?? error.localizedDescription)
        }
    }

    // MARK: - Local mode: CRUD + Health import

    private func nextLocalID() -> Int {
        (localRecords.map(\.id).max() ?? 0) + 1
    }

    /// Mirror of the server's validation (`YYYY-MM-DD`, `HH:MM`, no future
    /// dates, quality 1–5, notes ≤ 500 chars).
    private func validate(_ fields: APIClient.NightFields) throws {
        guard DateUtil.date(from: fields.date) != nil else {
            throw LocalStoreError.invalid("The date isn't valid.")
        }
        guard fields.date <= DateUtil.string(from: Date()) else {
            throw LocalStoreError.invalid("Nights can't be in the future.")
        }
        guard LocalAnalytics.minutes(fields.bedtime) != nil,
              LocalAnalytics.minutes(fields.wake) != nil else {
            throw LocalStoreError.invalid("Bedtime and wake must be valid times.")
        }
        guard (1...5).contains(fields.quality) else {
            throw LocalStoreError.invalid("Quality must be between 1 and 5.")
        }
        guard fields.notes.count <= 500 else {
            throw LocalStoreError.invalid("Notes are limited to 500 characters.")
        }
    }

    private func addLocal(_ fields: APIClient.NightFields) throws {
        try validate(fields)
        localRecords.append(SleepRecord(
            id: nextLocalID(),
            date: fields.date,
            bedtime: fields.bedtime,
            wake: fields.wake,
            quality: fields.quality,
            notes: fields.notes,
            hours: LocalAnalytics.hours(bedtime: fields.bedtime, wake: fields.wake),
            source: "manual",
            stages: nil,
            efficiency: nil
        ))
        recomputeLocal()
    }

    private func editLocal(id: Int, fields: APIClient.NightFields) throws {
        try validate(fields)
        guard let index = localRecords.firstIndex(where: { $0.id == id }) else {
            throw LocalStoreError.notFound
        }
        // Same rule as the server: manual fields update; source, stages,
        // and efficiency are retained.
        var record = localRecords[index]
        record.date = fields.date
        record.bedtime = fields.bedtime
        record.wake = fields.wake
        record.quality = fields.quality
        record.notes = fields.notes
        record.hours = LocalAnalytics.hours(bedtime: fields.bedtime, wake: fields.wake)
        localRecords[index] = record
        recomputeLocal()
    }

    /// Upsert clustered Apple Health nights into the on-phone store with the
    /// same `(date, source)` identity as the server's ingest endpoint.
    /// Future-dated nights are skipped, not rejected.
    @discardableResult
    func importHealthNights(_ nights: [ClusteredNight]) -> (imported: Int, replaced: Int, skipped: Int) {
        let today = DateUtil.string(from: Date())
        var imported = 0
        var replaced = 0
        var skipped = 0
        for night in nights {
            guard night.date <= today else {
                skipped += 1
                continue
            }
            let payload = HealthKitService.ingestPayload(from: night)
            let hours = LocalAnalytics.hours(bedtime: payload.bedtime, wake: payload.wake)
            if let index = localRecords.firstIndex(where: {
                $0.date == payload.date && $0.source == payload.source
            }) {
                var record = localRecords[index]
                record.bedtime = payload.bedtime
                record.wake = payload.wake
                record.quality = payload.quality ?? record.quality
                record.notes = payload.notes ?? record.notes
                record.hours = hours
                record.stages = payload.stages
                record.efficiency = payload.efficiency
                localRecords[index] = record
                replaced += 1
            } else {
                localRecords.append(SleepRecord(
                    id: nextLocalID(),
                    date: payload.date,
                    bedtime: payload.bedtime,
                    wake: payload.wake,
                    quality: payload.quality ?? 3,
                    notes: payload.notes ?? "",
                    hours: hours,
                    source: payload.source,
                    stages: payload.stages,
                    efficiency: payload.efficiency
                ))
                imported += 1
            }
        }
        if imported + replaced > 0 { recomputeLocal() }
        return (imported, replaced, skipped)
    }

    /// Recompute every published value from the on-phone records.
    private func recomputeLocal() {
        let today = Date()
        records = localRecords.sorted { ($0.date, $0.id) > ($1.date, $1.id) }
        stats = LocalAnalytics.stats(records: localRecords, today: today)
        let s30 = LocalAnalytics.series(records: localRecords, range: .d30, today: today)
        series30 = s30
        var ranges = seriesByRange
        for range in ranges.keys where range != .d30 {
            ranges[range] = LocalAnalytics.series(records: localRecords, range: range, today: today)
        }
        ranges[.d30] = s30
        seriesByRange = ranges
        insights = LocalAnalytics.insights(records: localRecords, today: today)
        aiSummary = nil
        loadState = .loaded
        persistLocalRecords()
    }

    // MARK: - Disk persistence (Application Support)

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

    private static let serverCacheFiles = [
        "records.json", "stats.json", "series-30d.json", "insights.json",
    ]

    /// The on-phone night store — NOT part of the server cache and never
    /// cleared by a server switch.
    private static let localRecordsFile = "local-records.json"

    private func persistLocalRecords() {
        guard let url = cacheURL(Self.localRecordsFile),
              let data = try? JSONEncoder().encode(localRecords) else { return }
        try? data.write(to: url, options: .atomic)
    }

    private func loadLocalRecords() {
        guard let url = cacheURL(Self.localRecordsFile),
              let data = try? Data(contentsOf: url),
              let saved = try? JSONDecoder().decode([SleepRecord].self, from: data)
        else {
            localRecords = []
            return
        }
        localRecords = saved
    }

    private func clearServerData() {
        pendingUndo = nil
        aiSummary = nil
        if mode == .server {
            records = []
            stats = nil
            series30 = nil
            insights = nil
            seriesByRange = [:]
            hasCachedData = false
            loadState = .idle
        }
        for name in Self.serverCacheFiles {
            if let url = cacheURL(name) {
                try? FileManager.default.removeItem(at: url)
            }
        }
    }

    private func persistCache() {
        guard mode == .server else { return }
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
