import SwiftUI
import UIKit

/// First-run (and anytime) server connection sheet.
/// Web stays the source of truth; this phone app is a client + HealthKit bridge.
struct SetupView: View {
    @EnvironmentObject private var store: SleepStore
    @Environment(\.dismiss) private var dismiss

    @State private var serverURL: String = ServerConfig.cloudDefaultURL
    @State private var username: String = "sleep"
    @State private var password: String = ""
    @State private var isTesting = false
    @State private var errorMessage: String?
    @State private var successNights: Int?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    header
                    serverCard
                    tips
                }
                .padding(20)
            }
            .background(Color.appPage)
            .navigationTitle("Connect")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Not now") { dismiss() }
                }
            }
            .onAppear {
                serverURL = store.config.baseURL
                username = store.config.username.isEmpty ? "sleep" : store.config.username
                password = store.config.password
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Your phone talks to your server")
                .serifDisplay(.title2)
            Text("The website on Render holds your history. This app shows it here and can sync Apple Watch nights from Health.")
                .font(.subheadline)
                .foregroundStyle(Color.appInk2)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var serverCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Server").microLabel()

            VStack(spacing: 0) {
                field("URL", text: $serverURL, keyboard: .URL, secure: false)
                Divider().background(Color.appBorder)
                field("Username", text: $username, keyboard: .default, secure: false)
                Divider().background(Color.appBorder)
                field("Password", text: $password, keyboard: .default, secure: true)
            }
            .background(Color.appSurface)
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .strokeBorder(Color.appBorder, lineWidth: 1)
            )

            HStack(spacing: 10) {
                Button("Use cloud") {
                    serverURL = ServerConfig.cloudDefaultURL
                    username = "sleep"
                }
                .buttonStyle(.bordered)

                Button("Use local Docker") {
                    serverURL = ServerConfig.localDefaultURL
                    username = "sleep"
                }
                .buttonStyle(.bordered)
            }

            Button {
                testAndSave()
            } label: {
                HStack {
                    if isTesting {
                        ProgressView().tint(.white)
                    }
                    Text(isTesting ? "Connecting…" : "Connect & save")
                        .fontWeight(.semibold)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(Color.appAccent)
                .foregroundStyle(.white)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            .disabled(isTesting || serverURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

            if let successNights {
                Label("Connected — \(successNights) nights on server", systemImage: "checkmark.circle.fill")
                    .font(.subheadline)
                    .foregroundStyle(Color.appGood)
            }
            if let errorMessage {
                Text(errorMessage)
                    .font(.caption)
                    .foregroundStyle(Color.appInk2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .card()
    }

    private var tips: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Tips").microLabel()
            tip("Free Render servers sleep when idle — first connect can take up to a minute.")
            tip("Password is the SLEEP_PASSWORD from your deploy (Settings → or /tmp/sleep-tracker-render.env).")
            tip("After connecting, use Settings → Sync from Apple Health on a real iPhone with Watch data.")
        }
        .card()
    }

    private func tip(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "info.circle")
                .foregroundStyle(Color.appAccent)
            Text(text)
                .font(.caption)
                .foregroundStyle(Color.appInk2)
        }
    }

    private func field(
        _ title: String,
        text: Binding<String>,
        keyboard: UIKeyboardType,
        secure: Bool
    ) -> some View {
        HStack {
            Text(title)
                .foregroundStyle(Color.appInk2)
                .frame(width: 88, alignment: .leading)
            if secure {
                SecureField("", text: text)
                    .textContentType(.password)
            } else {
                TextField("", text: text)
                    .keyboardType(keyboard)
                    .textContentType(keyboard == .URL ? .URL : .username)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
    }

    private func testAndSave() {
        isTesting = true
        errorMessage = nil
        successNights = nil
        var config = store.config
        config.baseURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        config.username = username.trimmingCharacters(in: .whitespacesAndNewlines)
        config.password = password
        let client = APIClient(config: config)
        Task {
            do {
                let stats = try await client.testConnection()
                store.config = config
                successNights = stats.total
                Haptics.success()
                await store.refresh()
                isTesting = false
                try? await Task.sleep(nanoseconds: 600_000_000)
                dismiss()
            } catch {
                errorMessage = (error as? APIError)?.errorDescription ?? error.localizedDescription
                isTesting = false
            }
        }
    }
}
