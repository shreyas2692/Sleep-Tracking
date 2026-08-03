# Android deployment

The native Android client lives in `android/`. The current build identity is:

- Application ID: `io.github.shreyas2692.sleeptracker`
- Minimum Android version: Android 9 (API 28)
- Target Android version: Android 16 (API 36)
- Version: `versionCode 1`, `versionName 1.0.0`

The application ID is provisional until the owner approves it. A package name
is permanent once it is used to create or upload a Play app, so do not create
the Play listing before that decision.

## Local release gate

Install Android Studio with Android SDK Platform 36 and use JDK 21. The app is
compiled to JVM 17 bytecode. From the repository root, run:

```sh
cd android
./gradlew --version
./gradlew --no-daemon testDebugUnitTest lintDebug assembleDebug bundleRelease
```

Expected outputs:

```text
app/build/outputs/apk/debug/app-debug.apk
app/build/outputs/bundle/release/app-release.aab
```

Install the debug APK on an emulator or test device with:

```sh
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

GitHub Actions runs the same tests, lint, and build tasks in
`.github/workflows/android.yml`. Its debug APK uses the standard debug key. Its
release AAB is intentionally **unsigned**: CI contains no upload keystore or
signing passwords, and that artifact is not a Play release candidate.

Before signing, verify the app against an HTTPS Sleep Tracker server. Exercise
initial setup, valid and invalid Basic authentication, dashboard refresh,
manual add/edit/delete, details, all trend ranges, settings validation,
credential clearing, offline and TLS failures, process recreation, and a
device rotation. Use disposable server data for destructive checks.

## Owner-only decisions and accounts

These items cannot be completed by CI or a coding agent:

1. Approve a permanent package ID. The current candidate is
   `io.github.shreyas2692.sleeptracker`; check ownership and registration
   eligibility before first upload.
2. Use a verified Organization Play account and keep it in good standing.
   Effective September 30, 2026, Play classifies health apps as services that
   must use an Organization account; organization onboarding requires legal
   details that match a D-U-N-S profile.
3. Complete Android developer identity verification and register the package
   name. Effective September 30, 2026, unregistered Play packages are subject
   to removal.
4. Create and protect the upload key outside this repository. Enroll in Play
   App Signing so Google holds the app-signing key and the owner retains the
   separate upload key.
5. Approve a public, non-geofenced privacy-policy URL and complete Data Safety
   and Health Apps declarations based on the released binary and its backend.
6. Supply the store listing, support contact, screenshots, graphics, content
   rating, target-audience answers, and app-access instructions. App review
   needs a reachable HTTPS server and working review credentials.
7. Recruit representative internal and closed testers and retain the evidence
   Play asks for before production review. The 12-testers-for-14-days rule
   specifically applies to new personal accounts, but it is not a substitute
   for the Organization-account requirement for health apps.
8. Increment `versionCode` for every uploaded build. Never reuse a Play
   `versionCode`, including one used on a testing track.

## Signing and internal testing

Create the upload keystore interactively in Android Studio under **Build >
Generate Signed Bundle / APK > Android App Bundle > Create new**, and store it
outside the repository. A command-line alternative that prompts for secrets is:

```sh
install -d -m 700 "$HOME/.config/sleep-tracker"
keytool -genkeypair -v \
  -keystore "$HOME/.config/sleep-tracker/android-upload.jks" \
  -alias sleep-tracker-upload \
  -keyalg RSA -keysize 4096 -validity 10000
chmod 600 "$HOME/.config/sleep-tracker/android-upload.jks"
```

Back up the keystore and credentials in an owner-controlled secret manager. Do
not place them in `android/gradle.properties`, `local.properties`, source
control, CI logs, or repository secrets until a separately reviewed signing
workflow exists.

### Sign with Gradle via keystore.properties

The build reads optional signing configuration from
`android/keystore.properties` (gitignored; a template lives at
`android/keystore.properties.example`):

```sh
cp android/keystore.properties.example android/keystore.properties
# edit android/keystore.properties: set storeFile to the absolute keystore
# path created above, plus storePassword, keyAlias, and keyPassword
cd android
./gradlew :app:bundleRelease
```

When `keystore.properties` exists, `app/build/outputs/bundle/release/app-release.aab`
is signed with the upload key and ready for Play Console. When the file is
absent (for example in CI), `bundleRelease` still succeeds and produces an
**unsigned** bundle that cannot be uploaded. Never commit
`keystore.properties` or any `.jks`/`.keystore` file; keep the keystore
outside the repository.

Alternatively, use Android Studio's signed-bundle flow. Either way, verify the
bundle before upload:

```sh
jarsigner -verify -verbose -certs /path/to/app-release.aab
```

In Play Console:

1. Create the app only after the package ID decision, accept Play App Signing,
   and retain the app-signing and upload certificate fingerprints.
2. Complete the dashboard and App content tasks, then create an Internal
   testing release and upload the signed AAB.
3. Add a tester list, publish the internal release, and use the Play opt-in URL
   to install it. Test the Play-delivered build, not only the local APK.
4. Resolve every pre-launch report, policy, crash, ANR, and accessibility
   blocker before promoting to closed testing.
5. Run the required closed test, apply for production access when eligible,
   and use a staged production rollout with crash and ANR monitoring.

## Play declarations and Health Connect

Data Safety is required for closed, open, and production tracks, including
when the correct answer is that the developer does not collect or share data.
Internal-testing-only apps are currently exempt. The declaration must reflect
the actual deployment model: sleep records and credentials are sent to the
user-configured Sleep Tracker server, so the owner must determine whether that
server is operated by the developer or solely by the user. Do not infer the
answer from the client code alone.

Every Play app on a closed, open, or production track must also complete the
Health Apps declaration. Sleep Tracker provides sleep tracking, so declare
**Sleep Management** even though the current Android client does not read from
Health Connect.

### Expected Data Safety answers

These reflect the shipped client behavior; the owner must re-verify them
against the released binary and the actual server deployment model:

- **Data collected**: Health info — "Health information" (sleep records:
  date, bedtime, wake time, quality rating, free-text notes). Collected, not
  shared with third parties by the app. Collection is required for the app to
  function. Data is sent only to the user-configured Sleep Tracker server.
- **App activity / device IDs / location / financial info**: not collected.
- **Account credentials**: the server username and password are stored only
  on-device (password encrypted with an Android Keystore AES-GCM key, never
  synced or backed up — `allowBackup=false` and empty extraction rules) and
  transmitted to the user's own server as HTTP Basic auth over TLS.
- **Encryption in transit**: Yes. Release builds refuse cleartext HTTP
  (`usesCleartextTraffic=false` plus a network security config); the app
  enforces HTTPS server URLs in release builds.
- **Data deletion**: users can delete individual nights or clear all records
  in-app (Settings > Clear all records), and can clear credentials by
  reinstalling or clearing app storage.
- **Tracking / advertising**: none. The app contains no analytics, ads, or
  third-party SDKs; it talks exclusively to the configured server.

### Health Connect status

The Android client does not integrate Health Connect. The server currently
accepts only `apple_health` and `fitbit` as `/api/ingest` sources
(`INGEST_SOURCES` in `app.py`), so an Android Health Connect sync has no
truthful source value to use. Before implementing Health Connect, the server
needs a `health_connect` source added to `INGEST_SOURCES` (a server-side
change, out of scope for the Android client).

The current client intentionally does **not** request Health Connect
permissions and must not claim Health Connect syncing in its listing,
screenshots, privacy policy, or Data Safety answers. If Health Connect is
implemented later, ship the user-facing integration first, request only the
sleep data types it actually uses, add matching manifest and Play declarations,
provide a clear permission rationale and in-app access management, and update
the privacy policy before uploading that build.

Keep the product positioned as a personal sleep log and analysis client, not a
medical device. Do not add diagnostic, treatment, or disease-prevention claims
without a separate regulatory and Play policy review.

## Official references

- [Target API requirements](https://developer.android.com/google/play/requirements/target-sdk)
- [Create and set up a Play app](https://support.google.com/googleplay/android-developer/answer/9859152)
- [Play Console account requirements](https://support.google.com/googleplay/android-developer/answer/10788890)
- [Register Play package names](https://support.google.com/googleplay/android-developer/answer/16984799)
- [Android developer verification and package registration](https://developer.android.com/developer-verification/guides/android-developer-console)
- [Sign an Android app](https://developer.android.com/studio/publish/app-signing)
- [Play App Signing](https://support.google.com/googleplay/android-developer/answer/9842756)
- [Set up Play testing tracks](https://support.google.com/googleplay/android-developer/answer/9845334)
- [Testing gate for new personal accounts](https://support.google.com/googleplay/android-developer/answer/14151465)
- [Data Safety](https://support.google.com/googleplay/android-developer/answer/10787469)
- [Health Apps declaration](https://support.google.com/googleplay/android-developer/answer/14738291)
- [Health content and services policy](https://support.google.com/googleplay/android-developer/answer/16679511)
- [Publishing with Health Connect](https://developer.android.com/health-and-fitness/health-connect/publish)
- [Health Connect permission UX](https://developer.android.com/health-and-fitness/health-connect/ui/permissions)
