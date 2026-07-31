import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var store: SleepStore
    @EnvironmentObject private var health: HealthKitService

    enum TestState: Equatable {
        case idle
        case testing
        case success(nights: Int)
        case failure(String)
    }

    @State private var serverURL = ""
    @State private var username = ""
    @State private var password = ""
    @State private var testState: TestState = .idle

    var body: some View {
        NavigationStack {
            Form {
                serverSection
                healthSection
                aboutSection
            }
            .scrollContentBackground(.hidden)
            .background(Color.appPage)
            .navigationTitle("Settings")
            .toolbarTitleDisplayMode(.large)
            .onAppear {
                serverURL = store.config.baseURL
                username = store.config.username
                password = store.config.password
            }
        }
    }

    // MARK: Server

    private var serverSection: some View {
        Section {
            TextField("Server URL", text: $serverURL, prompt: Text("http://127.0.0.1:5002"))
                .keyboardType(.URL)
                .textContentType(.URL)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            TextField("Username (optional)", text: $username)
                .textContentType(.username)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            SecureField("Password (optional)", text: $password)
                .textContentType(.password)
            Button {
                testConnection()
            } label: {
                HStack {
                    Text("Test connection")
                    Spacer()
                    switch testState {
                    case .idle:
                        EmptyView()
                    case .testing:
                        ProgressView()
                    case .success(let nights):
                        Label("\(nights) nights", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(Color.appGood)
                            .font(.subheadline)
                    case .failure:
                        Image(systemName: "xmark.circle")
                            .foregroundStyle(Color.appMuted)
                    }
                }
            }
            .disabled(testState == .testing)
            if case .failure(let message) = testState {
                Text(message)
                    .font(.caption)
                    .foregroundStyle(Color.appInk2)
            }
        } header: {
            Text("Your Server").microLabel()
        } footer: {
            Text("The app talks only to your own self-hosted Sleep Tracker. Changes apply as soon as the connection test succeeds.")
        }
        .listRowBackground(Color.appSurface)
    }

    private func testConnection() {
        testState = .testing
        var config = store.config
        config.baseURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        config.username = username
        config.password = password
        let client = APIClient(config: config)
        Task {
            do {
                let stats = try await client.testConnection()
                store.config = config
                testState = .success(nights: stats.total)
                Haptics.success()
                await store.refresh()
            } catch {
                testState = .failure((error as? APIError)?.errorDescription ?? error.localizedDescription)
            }
        }
    }

    // MARK: Apple Health

    private var healthSection: some View {
        Section {
            Button {
                Task { await health.sync() }
            } label: {
                HStack {
                    Label("Sync from Apple Health", systemImage: "heart")
                    Spacer()
                    if health.state == .fetching || health.state == .requestingPermission {
                        ProgressView()
                    }
                }
            }
            .disabled(!health.isAvailable || health.state == .fetching || health.state == .requestingPermission)

            healthStatus

            if !health.nights.isEmpty {
                Button {
                    pushNights()
                } label: {
                    Label("Send \(newNightCount) new nights to server", systemImage: "arrow.up.circle")
                }
                .disabled(newNightCount == 0 || isPushing)
            }
        } header: {
            Text("Apple Health").microLabel()
        } footer: {
            Text("Reads your sleep analysis from Health, clusters it into nights (the same rules as the web importer), and can send new nights to your server. Nothing is read without your permission.")
        }
        .listRowBackground(Color.appSurface)
    }

    private var newNightCount: Int {
        let existing = Set(store.records.map(\.date))
        return health.nights.filter { !existing.contains($0.date) }.count
    }

    private var isPushing: Bool {
        if case .pushing = health.state { return true }
        return false
    }

    @ViewBuilder
    private var healthStatus: some View {
        switch health.state {
        case .idle:
            if !health.isAvailable {
                statusText("Health data isn't available on this device — the server is the primary data path, so nothing is lost.")
            }
        case .unavailable(let message), .failed(let message):
            statusText(message)
        case .requestingPermission:
            statusText("Waiting for Health permission…")
        case .fetching:
            statusText("Reading sleep data from Health…")
        case .fetched(let count):
            statusText(count == 0
                ? "No sleep data found in Health. On a simulator that's expected — the app runs fully from your server."
                : "Found \(count) nights in Health.")
        case .pushing(let done, let total):
            statusText("Sending… \(done) of \(total)")
        case .pushed(let uploaded, let skipped):
            statusText("Done — \(uploaded) uploaded, \(skipped) already on the server.")
        }
    }

    private func statusText(_ text: String) -> some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(Color.appInk2)
    }

    private func pushNights() {
        let existing = Set(store.records.map(\.date))
        Task {
            if await health.push(to: store.client, existingDates: existing) != nil {
                await store.refresh()
                Haptics.success()
            }
        }
    }

    // MARK: About

    private var aboutSection: some View {
        Section {
            VStack(alignment: .leading, spacing: 10) {
                Wordmark()
                Text("Import everything. Merge it. Keep it forever. Analyze years, not weeks. No subscription, no account, no cloud.")
                    .font(.system(.subheadline, design: .serif))
                    .foregroundStyle(Color.appInk)
                VStack(alignment: .leading, spacing: 6) {
                    principle("Your history and trends are never paywalled, time-limited, or cloud-gated.")
                    principle("No account required. Runs on your machine. Data never leaves it.")
                    principle("Export always: CSV and JSON out, and the SQLite file is yours.")
                    principle("Scores explain themselves. One bad night is never presented as failure.")
                }
            }
            .padding(.vertical, 4)
        } header: {
            Text("About").microLabel()
        }
        .listRowBackground(Color.appSurface)
    }

    private func principle(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Circle()
                .fill(Color.appAccent)
                .frame(width: 5, height: 5)
                .padding(.top, 6)
            Text(text)
                .font(.caption)
                .foregroundStyle(Color.appInk2)
        }
    }
}
