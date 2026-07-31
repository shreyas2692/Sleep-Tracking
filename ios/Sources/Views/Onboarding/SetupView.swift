import SwiftUI
import UIKit

/// First-run (and anytime) sign-in sheet.
/// Consumer path: just a password + Sign In (cloud server, default account).
/// Self-hosters: everything else lives under Advanced.
struct SetupView: View {
    @EnvironmentObject private var store: SleepStore
    @Environment(\.dismiss) private var dismiss

    @State private var serverURL: String = ServerConfig.cloudDefaultURL
    @State private var username: String = "sleep"
    @State private var password: String = ""
    @State private var showAdvanced = false
    @State private var isTesting = false
    @State private var errorMessage: String?
    @State private var successNights: Int?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    hero
                    signInCard
                    advanced
                }
                .padding(20)
                .padding(.top, 24)
            }
            .background(Color.appPage)
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
                // A changed URL or username means this is a self-hoster.
                showAdvanced = serverURL != ServerConfig.cloudDefaultURL || username != "sleep"
            }
        }
    }

    // MARK: - Hero

    private var hero: some View {
        VStack(spacing: 10) {
            Image(systemName: "moon.stars.fill")
                .font(.system(size: 44))
                .foregroundStyle(Color.appAccent)
            Text("Welcome to Sleep Tracker")
                .serifDisplay(.title)
                .multilineTextAlignment(.center)
            Text("Sign in to see your nights, trends, and insights.")
                .font(.subheadline)
                .foregroundStyle(Color.appInk2)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Sign in

    private var signInCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            fieldGroup {
                field("Password", text: $password, keyboard: .default, secure: true)
            }

            Button {
                testAndSave()
            } label: {
                HStack {
                    if isTesting {
                        ProgressView().tint(.white)
                    }
                    Text(isTesting ? "Signing in…" : "Sign In")
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
                Label("Signed in — \(successNights) nights synced", systemImage: "checkmark.circle.fill")
                    .font(.subheadline)
                    .foregroundStyle(Color.appGood)
            }
            if let errorMessage {
                Text(errorMessage)
                    .font(.caption)
                    .foregroundStyle(Color.appInk2)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Text("Your data stays on your own server — no accounts, no tracking.")
                .font(.caption)
                .foregroundStyle(Color.appMuted)
                .frame(maxWidth: .infinity, alignment: .center)
        }
        .card()
    }

    // MARK: - Advanced (self-hosting)

    private var advanced: some View {
        VStack(alignment: .leading, spacing: 14) {
            Button {
                withAnimation(.easeOut(duration: 0.15)) { showAdvanced.toggle() }
            } label: {
                HStack(spacing: 6) {
                    Text("Advanced")
                        .font(.subheadline.weight(.medium))
                    Image(systemName: "chevron.right")
                        .font(.caption.weight(.semibold))
                        .rotationEffect(.degrees(showAdvanced ? 90 : 0))
                }
                .foregroundStyle(Color.appInk2)
            }

            if showAdvanced {
                fieldGroup {
                    field("Server", text: $serverURL, keyboard: .URL, secure: false)
                    Divider().background(Color.appBorder)
                    field("Username", text: $username, keyboard: .default, secure: false)
                }

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

                tip("Point this at any Sleep Tracker server — the password is its SLEEP_PASSWORD.")
                tip("Free Render servers sleep when idle — first sign-in can take up to a minute.")
                tip("After signing in, use Settings → Sync from Apple Health on an iPhone with Watch data.")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
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

    // MARK: - Fields

    private func fieldGroup<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(spacing: 0, content: content)
            .background(Color.appSurface)
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .strokeBorder(Color.appBorder, lineWidth: 1)
            )
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
