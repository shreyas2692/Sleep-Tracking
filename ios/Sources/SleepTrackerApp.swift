import SwiftUI

@main
struct SleepTrackerApp: App {
    @StateObject private var store: SleepStore
    @StateObject private var health = HealthKitService()

    init() {
        // Editorial serif (New York) for screen titles, matching the web app.
        if let large = UIFontDescriptor
            .preferredFontDescriptor(withTextStyle: .largeTitle)
            .withDesign(.serif) {
            UINavigationBar.appearance().largeTitleTextAttributes = [
                .font: UIFont(descriptor: large.withSymbolicTraits(.traitBold) ?? large, size: 0)
            ]
        }
        if let inline = UIFontDescriptor
            .preferredFontDescriptor(withTextStyle: .headline)
            .withDesign(.serif) {
            UINavigationBar.appearance().titleTextAttributes = [
                .font: UIFont(descriptor: inline, size: 0)
            ]
        }

        // Screenshot / preview tooling: `-previewFixtures` seeds sample nights
        // without a server (see docs/app-store + Sources/Preview).
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("-previewFixtures") {
            _store = StateObject(wrappedValue: .previewPopulated)
        } else {
            _store = StateObject(wrappedValue: SleepStore())
        }
        #else
        _store = StateObject(wrappedValue: SleepStore())
        #endif
    }

    var body: some Scene {
        WindowGroup {
            RootTabView()
                .environmentObject(store)
                .environmentObject(health)
                .tint(.appAccent)
        }
    }
}

struct RootTabView: View {
    @EnvironmentObject private var store: SleepStore

    enum Tab: String {
        case today, trends, nights, settings
    }

    // Launch-argument hooks for headless screenshots:
    //   -initialTab trends|nights|settings|today
    //   -previewFixtures  (DEBUG) seed sample data, skip network refresh
    @State private var selection: Tab = {
        if let argIndex = ProcessInfo.processInfo.arguments.firstIndex(of: "-initialTab"),
           argIndex + 1 < ProcessInfo.processInfo.arguments.count,
           let tab = Tab(rawValue: ProcessInfo.processInfo.arguments[argIndex + 1]) {
            return tab
        }
        return Tab(rawValue: UserDefaults.standard.string(forKey: "initialTab") ?? "") ?? .today
    }()

    @State private var showSetup = false

    private var usePreviewFixtures: Bool {
        ProcessInfo.processInfo.arguments.contains("-previewFixtures")
    }

    private static let setupShownKey = "sleeptracker.setup.completed"

    var body: some View {
        TabView(selection: $selection) {
            DashboardView()
                .tabItem { Label("Today", systemImage: "sun.horizon") }
                .tag(Tab.today)
            TrendsView()
                .tabItem { Label("Trends", systemImage: "chart.xyaxis.line") }
                .tag(Tab.trends)
            NightsView()
                .tabItem { Label("Nights", systemImage: "moon.stars") }
                .tag(Tab.nights)
            SettingsView()
                .tabItem { Label("Settings", systemImage: "gearshape") }
                .tag(Tab.settings)
        }
        .sheet(isPresented: $showSetup) {
            SetupView()
                .environmentObject(store)
                .presentationDetents([.large])
        }
        .task {
            #if DEBUG
            if usePreviewFixtures { return }
            #endif
            // First run with no saved credentials: show sign-in right away
            // instead of blocking on a (possibly cold-starting) server.
            // Small delay so the presentation isn't dropped while the tab
            // view is still appearing.
            if !UserDefaults.standard.bool(forKey: Self.setupShownKey),
               !store.config.hasCredentials {
                try? await Task.sleep(nanoseconds: 350_000_000)
                showSetup = true
            }
            await store.refresh()
            // Missing password or hard connection failure → setup sheet.
            let needsSetup = !UserDefaults.standard.bool(forKey: Self.setupShownKey)
                || !store.config.hasCredentials
                || store.loadState.errorMessage != nil
            if needsSetup {
                showSetup = true
            } else {
                UserDefaults.standard.set(true, forKey: Self.setupShownKey)
            }
        }
        .onChange(of: store.config) { _, newValue in
            if newValue.hasCredentials {
                UserDefaults.standard.set(true, forKey: Self.setupShownKey)
            }
        }
    }
}
