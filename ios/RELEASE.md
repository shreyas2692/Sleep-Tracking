# iOS Release — clean checkout to App Store

Everything below runs from `ios/` on a Mac with Xcode 15+ and
[XcodeGen](https://github.com/yonaskolb/XcodeGen) (`brew install xcodegen`).

## 0. One-time setup (owner)

1. **Team ID** — the only thing not in the repo:

   ```bash
   cd ios
   cp Signing.xcconfig.example Signing.xcconfig
   # edit Signing.xcconfig: DEVELOPMENT_TEAM = <your 10-char Team ID>
   ```

   Find the Team ID in Xcode → Settings → Accounts → your team, or
   <https://developer.apple.com/account> → Membership details.
   `Signing.xcconfig` is gitignored.

2. **App Store Connect record** — at <https://appstoreconnect.apple.com>
   create the app once: platform iOS, bundle id `com.shreyas2692.sleeptracker`
   (must match `project.yml`; register the id at
   <https://developer.apple.com/account/resources/identifiers> first if
   needed), SKU anything (e.g. `sleeptracker-ios`).

## 1. Generate and verify

```bash
cd ios
xcodegen generate
xcodebuild -project "Sleep Tracker.xcodeproj" -scheme "Sleep Tracker" \
  -destination 'generic/platform=iOS Simulator' build
xcodebuild -project "Sleep Tracker.xcodeproj" -scheme "Sleep Tracker" \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test
```

(Any installed iPhone simulator works; `xcrun simctl list devices available`
shows the names.)

## 2. Archive

```bash
./scripts/archive-for-appstore.sh
```

or by hand:

```bash
xcodebuild -project "Sleep Tracker.xcodeproj" -scheme "Sleep Tracker" \
  -destination 'generic/platform=iOS' \
  -archivePath /tmp/SleepTracker.xcarchive \
  -xcconfig Signing.xcconfig \
  -allowProvisioningUpdates \
  archive
```

`CODE_SIGN_STYLE` is Automatic; `-allowProvisioningUpdates` lets Xcode mint
the App Store provisioning profile on first run (sign into your Apple ID in
Xcode → Settings → Accounts beforehand).

## 3. Upload

1. The script opens the `.xcarchive`; Xcode's **Organizer** appears
   (Window → Organizer if not).
2. Select the archive → **Distribute App** → **App Store Connect** →
   **Upload** → accept defaults (automatic signing, upload symbols).
3. Wait for the "processing" email (~5–15 min).

## 4. App Store Connect submission

1. **TestFlight** tab — the build appears when processing finishes; add
   yourself as an internal tester for a device sanity pass.
2. **App Store** tab → version 1.0.0:
   - Screenshots: `ios/screenshots/store-*.png` (1290×2796, iPhone 6.7").
   - Description / keywords / review notes: `docs/app-store/`.
   - Privacy policy URL:
     `https://github.com/shreyas2692/Sleep-Tracking/blob/main/PRIVACY.md`
     (also linked inside the app: Settings → About).
   - **App Privacy** questionnaire: collects **Health & Fitness → Health**
     data, linked to identity: No, tracking: No — matching
     `Support/PrivacyInfo.xcprivacy`.
   - Export compliance: uses only standard HTTPS — answered by
     `ITSAppUsesNonExemptEncryption = NO` in the Info.plist (no question
     appears at submit time).
3. Select the build, **Add for Review** → **Submit**.

### Review notes (important)

The app works with **no demo server**: on the first-run sheet tap
**"Use without a server"** — nights are stored on the phone, and manual
logging, Apple Health import, dashboard, trends, and insights all work
offline. Optionally include the demo server URL + password from
`docs/app-store/APP_REVIEW_NOTES.md` so reviewers can also test server sync.

## What's already handled in the repo

- `Support/PrivacyInfo.xcprivacy` — privacy manifest (health data,
  no tracking, UserDefaults reason CA92.1), bundled via `project.yml`.
- `Support/Info.plist` — HealthKit share/update purpose strings,
  `NSLocalNetworkUsageDescription` (self-hosted LAN servers), ATS with
  `NSAllowsLocalNetworking` only (no arbitrary loads: plain HTTP works
  solely for local-network addresses).
- Server password is stored in the iOS Keychain, never UserDefaults; the
  UI warns when a plain-`http://` server URL is entered.
- Version bumps: edit `MARKETING_VERSION` / `CURRENT_PROJECT_VERSION` in
  `project.yml`, rerun `xcodegen generate`.
