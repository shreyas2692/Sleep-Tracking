# iOS Release Review

Review date: 2026-07-31  
Scope: read-only review of `ios/`; no iOS source, project, test, screenshot,
or App Store copy was changed.

## Ship Decision

### Current self-hosted web release

**No iOS issue blocks the current web-only release.** The Docker image copies
only the Flask application, importers, static assets, and templates
(`Dockerfile:20-23`); it does not package or execute `ios/`.

The companion-app issues below should not hold the Docker/Render/GitHub ship.
They do block advertising the current iOS project as a working Apple Health
sync client, and the App Store findings block a future App Store submission.

### Future iOS/App Store release

**Not ready.** The project compiles, but the HealthKit-only product path is not
implemented, Health sync loses wearable data, and signing/privacy/network
release requirements remain open.

## Companion Integration Findings

### High: Apple Health sync discards source and stage data

`HealthKitService.push` converts each clustered Health night into
`APIClient.NightFields` and calls the manual `POST /add` endpoint
(`ios/Sources/Health/HealthKitService.swift:66-103`). `NightFields` has only
date, bedtime, wake, quality, and notes
(`ios/Sources/Networking/APIClient.swift:72-100`), so the server necessarily
stores the result as `source="manual"` with `stages=null` and
`efficiency=null`.

The client also builds `existingDates` from every record, regardless of source
(`ios/Sources/Views/Settings/SettingsView.swift:143-145` and `183-186`).
Consequently, a manual or Fitbit record on a date suppresses a valid Apple
Health record even though the server's wearable identity is `(date, source)`.

Impact: the primary Apple Watch workflow loses provenance and the exact stage
data the Wave 1 UI is intended to visualize. Re-import/dedup semantics also
diverge from the server contract.

### Medium: Undo converts imported records to lossy manual records

Undo reconstructs only the five manual fields and calls `/add`
(`ios/Sources/Store/SleepStore.swift:115-135`). Deleting and undoing an Apple
Health or Fitbit record permanently loses `source`, `stages`, and
`efficiency`, and assigns a new identity.

### Medium: switching servers can display another server's cached data

Changing `config` only saves the new config
(`ios/Sources/Store/SleepStore.swift:35-59`). Cached records, stats, and series
use fixed filenames and are neither keyed by server nor cleared on a config
change (`ios/Sources/Store/SleepStore.swift:138-185`). If the new server passes
the single stats probe but the subsequent three-request refresh partly fails,
the UI retains data from the prior server under the new configuration.

## Future App Store Blockers

### Critical: the documented HealthKit-only/offline mode does not exist

HealthKit sync populates only `HealthKitService.nights`
(`ios/Sources/Health/HealthKitService.swift:52-58`). Dashboard, Trends, and
Nights render `SleepStore` server responses
(`ios/Sources/Views/Dashboard/DashboardView.swift:27-34`,
`ios/Sources/Views/Trends/TrendsView.swift:17-18` and `52-81`, and
`ios/Sources/Views/Nights/NightsView.swift:11-35`). The only consumer of
HealthKit nights is the server-push UI in Settings
(`ios/Sources/Views/Settings/SettingsView.swift:127-145` and `183-190`).

With no server, a reviewer sees "Can't reach your server"; syncing HealthKit
does not make those nights, stats, debt, or trends appear. This contradicts
`docs/app-store/APP_STORE_PLAN.md:53-58` and `231-234`, plus the review flow in
`docs/app-store/APP_REVIEW_NOTES.md:13-28`.

### High: the project cannot produce a signed distribution archive

Signing is globally disabled, the development team is empty, and both bundle
identifiers are placeholders (`ios/project.yml:6-11`, `22-30`, and `38-41`).
The generated project confirms `CODE_SIGNING_ALLOWED=NO` in Debug and Release
(`ios/Sleep Tracker.xcodeproj/project.pbxproj:396-400` and `483-487`).

This is expected scaffolding, but it must be replaced before device/TestFlight
or App Store validation.

### High: required privacy declarations are absent

The app reads and writes `UserDefaults`
(`ios/Sources/Store/SleepStore.swift:44-59` and
`ios/Sources/SleepTrackerApp.swift:58-65`), but `ios/` contains no
`PrivacyInfo.xcprivacy`. Apple requires required-reason API declarations for
App Store acceptance; app-only UserDefaults use maps to approved reason
`CA92.1`.

Settings also has no privacy-policy link
(`ios/Sources/Views/Settings/SettingsView.swift:193-227`), while the review
notes claim one exists (`docs/app-store/APP_REVIEW_NOTES.md:28`). Apple's
current review guideline 5.1.1(i) requires the privacy policy to be accessible
inside the app as well as in App Store Connect.

Primary references:

- <https://developer.apple.com/documentation/bundleresources/describing-use-of-required-reason-api>
- <https://developer.apple.com/app-store/review/guidelines/>
- <https://developer.apple.com/documentation/healthkit/protecting-user-privacy>

### High: LAN access lacks its required purpose string

The app is explicitly a self-hosted client, but `Info.plist` contains only the
ATS local-network exception and HealthKit purpose string
(`ios/Support/Info.plist:34-40`). It omits
`NSLocalNetworkUsageDescription`. Apple states that direct unicast LAN
connections, including URLSession, should declare this purpose string.

The default URL is also `http://127.0.0.1:5002`
(`ios/Sources/Networking/APIClient.swift:5-8`), which addresses the iPhone
itself on a physical device rather than the owner's server.

Primary reference:

- <https://developer.apple.com/documentation/bundleresources/information-property-list/nslocalnetworkusagedescription>

### High: server credentials are stored and can be transmitted insecurely

`ServerConfig` includes the password (`ios/Sources/Networking/APIClient.swift:5-8`)
and the complete Codable value is stored in UserDefaults
(`ios/Sources/Store/SleepStore.swift:46-59`). The client accepts arbitrary
`http` URLs and sends Basic auth on them
(`ios/Sources/Networking/APIClient.swift:104-116`).

Impact: the password is not protected by Keychain, and a working HTTP LAN
configuration transmits credentials and sleep mutations without transport
encryption. Use Keychain for the secret and require HTTPS outside an explicit,
clearly scoped local-development mode.

## Build And Test Evidence

Environment:

- Xcode 26.6, build `17F113`
- Swift 6.3.3 toolchain, project language mode Swift 5
- Project deployment target iOS 17.0
- CoreSimulator has an iOS 17.0 iPhone 15 Pro Max booted, but Xcode 26.6 has
  no matching iOS 26.5 simulator platform installed

The Xcode license initially blocked `xcodebuild` and `xcrun` with:

```text
You have not agreed to the Xcode license agreements.
Please run 'sudo xcodebuild -license' ...
```

The owner accepted it during this review; `xcodebuild -version` subsequently
returned exit 0. The license is no longer the blocker.

Application target build, with artifacts under `/private/tmp`:

```sh
xcodebuild -project 'ios/Sleep Tracker.xcodeproj' \
  -target 'Sleep Tracker' -configuration Debug \
  -sdk iphonesimulator -arch arm64 CODE_SIGNING_ALLOWED=NO \
  SYMROOT=/private/tmp/sleep-ios-target-build/products \
  OBJROOT=/private/tmp/sleep-ios-target-build/intermediates \
  SHARED_PRECOMPS_DIR=/private/tmp/sleep-ios-target-build/precompiled build
```

Result: `** BUILD SUCCEEDED **`.

The same target-only build for `SleepTrackerTests` succeeded and produced an
arm64 `SleepTrackerTests.xctest` bundle. All 22 XCTest methods compile and
link:

```text
/private/tmp/sleep-ios-tests-build/products/Debug-iphonesimulator/
  Sleep Tracker.app/PlugIns/SleepTrackerTests.xctest
```

Actual test execution was attempted with:

```sh
xcodebuild -project 'ios/Sleep Tracker.xcodeproj' \
  -scheme 'Sleep Tracker' \
  -destination 'platform=iOS Simulator,id=600BD7C6-778C-4782-9E00-581B3ADBED67' \
  -derivedDataPath /private/tmp/sleep-ios-xcode-derived-test \
  CODE_SIGNING_ALLOWED=NO test
```

Result: exit 70 before test launch. Xcode reports no eligible destination and
`iOS 26.5 is not installed`. `simctl` can see the older booted iOS 17 runtime,
but Xcode 26.6 will not select it. Install the matching iOS 26.5 simulator
platform in Xcode Settings > Components, then rerun the command. This is an
environment/runtime gap, not a test compile failure.

As an additional startup check, a directly compiled, ad-hoc-signed arm64
simulator app installed and launched on the booted iOS 17 iPhone 15 Pro Max;
`simctl launch` returned PID 2842 with no immediate launch error.

## Screenshot Check

No screenshot was regenerated.

- The eight light/dark development captures are valid, distinct PNGs at
  1179 x 2556.
- The five App Store captures are valid, distinct PNGs at 1290 x 2796.
- App icon is a valid 1024 x 1024 PNG with no alpha.
- Visual inspection of Dashboard light/dark, Trends dark, and Settings light
  found plausible light/dark rendering with no blank canvas or incoherent
  overlap.

