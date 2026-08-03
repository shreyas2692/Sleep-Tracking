import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var store: SleepStore
    @EnvironmentObject private var health: HealthKitService

    private static let privacyPolicyURL =
        URL(string: "https://github.com/shreyas2692/Sleep-Tracking/blob/main/PRIVACY.md")!

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
                if store.isLocalMode {
                    localModeSection
                }
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

    // MARK: Local mode

    private var localModeSection: some View {
        Section {
            HStack(spacing: 10) {
                Image(systemName: "iphone")
                    .foregroundStyle(Color.appAccent)
                VStack(alignment: .leading, spacing: 3) {
                    Text("On this iPhone")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Color.appInk)
                    Text("Your nights are stored only on this phone. Connect a server below anytime to sync across devices.")
                        .font(.caption)
                        .foregroundStyle(Color.appInk2)
                }
            }
            .padding(.vertical, 2)
        } header: {
            Text("Storage").microLabel()
        }
        .listRowBackground(Color.appSurface)
    }

    // MARK: Server

    private var isPlainHTTP: Bool {
        serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .hasPrefix("http://")
    }

    private var serverSection: some View {
        Section {
            TextField("Server URL", text: $serverURL, prompt: Text(ServerConfig.cloudDefaultURL))
                .keyboardType(.URL)
                .textContentType(.URL)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            TextField("Username", text: $username, prompt: Text("sleep"))
                .textContentType(.username)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            SecureField("Password", text: $password, prompt: Text("SLEEP_PASSWORD from deploy"))
                .textContentType(.password)

            if isPlainHTTP {
                Label {
                    Text("Plain HTTP sends your password and sleep data unencrypted. Only use it with a server on your own home network — use https:// everywhere else.")
                        .font(.caption)
                        .foregroundStyle(Color.appInk2)
                } icon: {
                    Image(systemName: "lock.open")
                        .foregroundStyle(Color.appAccent)
                }
            }

            Button("Fill cloud server (Render)") {
                serverURL = ServerConfig.cloudDefaultURL
                username = "sleep"
            }

            Button {
                testConnection()
            } label: {
                HStack {
                    Text(store.isLocalMode ? "Connect server" : "Test connection")
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

            if !store.isLocalMode {
                Button("Use on this phone only (no server)") {
                    store.enableLocalMode()
                    testState = .idle
                }
            }
        } header: {
            Text(store.isLocalMode ? "Server (Optional)" : "Your Server").microLabel()
        } footer: {
            Text(store.isLocalMode
                ? "Optional: point the app at a Sleep Tracker server (Render or Docker) to keep a copy of your history off the phone and use the web app."
                : "This phone is a client. Your history lives on the web server (Render or Docker). First connect after idle can take ~60s on the free tier.")
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
                store.enableServerMode()
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
                    Label(
                        store.isLocalMode
                            ? "Import \(newNightCount) new nights"
                            : "Send \(newNightCount) new nights to server",
                        systemImage: store.isLocalMode ? "square.and.arrow.down" : "arrow.up.circle"
                    )
                }
                .disabled(newNightCount == 0 || isPushing)
            }
        } header: {
            Text("Apple Health").microLabel()
        } footer: {
            Text(store.isLocalMode
                ? "Reads your sleep analysis from Health, clusters it into nights (the same rules as the web importer), and stores them on this phone. Nothing is read without your permission."
                : "Reads your sleep analysis from Health, clusters it into nights (the same rules as the web importer), and can send new nights to your server. Nothing is read without your permission.")
        }
        .listRowBackground(Color.appSurface)
    }

    /// Dates that already carry an Apple Health record. Manual or Fitbit
    /// records on a date must NOT suppress a Health night — the identity is
    /// (date, source), and the server / local store upsert by it.
    private var appleHealthDates: Set<String> {
        Set(store.records.filter { $0.source == "apple_health" }.map(\.date))
    }

    private var newNightCount: Int {
        let existing = appleHealthDates
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
                statusText("Health data isn't available on this device — nothing is lost, your nights still live in the app.")
            }
        case .unavailable(let message), .failed(let message):
            statusText(message)
        case .requestingPermission:
            statusText("Waiting for Health permission…")
        case .fetching:
            statusText("Reading sleep data from Health…")
        case .fetched(let count):
            statusText(count == 0
                ? "No sleep data found in Health. On a simulator that's expected — you can still log nights by hand."
                : "Found \(count) nights in Health.")
        case .pushing(let done, let total):
            statusText("Sending… \(done) of \(total)")
        case .pushed(let uploaded, let skipped):
            statusText("Done — \(uploaded) imported, \(skipped) already up to date.")
        }
    }

    private func statusText(_ text: String) -> some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(Color.appInk2)
    }

    private func pushNights() {
        if store.isLocalMode {
            health.importLocally(into: store)
            Haptics.success()
            return
        }
        let existing = appleHealthDates
        Task {
            if await health.push(to: store.client, existingDates: existing) != nil {
                await store.refresh()
                if case .failed = health.state {
                    // push set failed state; haptic already not success
                } else {
                    Haptics.success()
                }
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

            Link(destination: Self.privacyPolicyURL) {
                HStack {
                    Label("Privacy Policy", systemImage: "hand.raised")
                    Spacer()
                    Image(systemName: "arrow.up.right")
                        .font(.caption)
                        .foregroundStyle(Color.appMuted)
                }
            }
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
