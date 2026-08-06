# Release Runbook — from today to both stores

One ordered checklist. Steps tagged **[OWNER]** need the owner's accounts,
keys, or sign-off and cannot be done by an agent or CI. Detailed per-topic
docs are cited rather than duplicated:

- iOS archive/upload: `ios/RELEASE.md` (in progress by the iOS lane; until
  it lands, `ios/APP_STORE_NEXT.md` is the click-path) 
- Android build/signing/tracks: `docs/android-deployment.md`
- Server ops: `docs/DEPLOY.md`, `render.yaml`
- Listing content: `docs/store/APP_STORE_SUBMISSION.md`,
  `docs/store/PLAY_STORE_SUBMISSION.md`
- Assets: `docs/store/SCREENSHOTS.md`
- Policy: `docs/store/PRIVACY_POLICY.md`

---

## Phase 0 — Accounts & decisions (start now; longest lead time)

- [ ] **[OWNER]** Apple Developer Program membership active ($99/yr); team
      visible in Xcode → Settings → Accounts.
- [ ] **[OWNER]** Play Console account — note the 2026-09-30 Organization-
      account requirement for health apps and developer-verification/package
      registration deadlines (`docs/android-deployment.md` §Owner-only).
      This is the longest pole; begin immediately.
- [ ] **[OWNER]** Approve permanent identifiers:
      iOS `com.shreyas2692.sleeptracker`, Android
      `io.github.shreyas2692.sleeptracker` (permanent once uploaded).
- [ ] **[OWNER]** Decide: keep or remove the developer-run default server
      URL in the iOS build — determines the App Privacy label
      (`APP_STORE_SUBMISSION.md` §3, blocker 7).
- [ ] **[OWNER]** Confirm public contact (email/GitHub issues) for the
      privacy policy and both store listings.

## Phase 1 — Privacy policy live (blocks both stores)

- [ ] Finalize `docs/store/PRIVACY_POLICY.md` (contact confirmed, effective
      date checked).
- [ ] **[OWNER]** Host it over HTTPS — GitHub Pages instructions are in the
      HTML comment at the bottom of the policy file. Public, non-geofenced,
      not a PDF.
- [ ] Record the final URL; it goes in ASC, Play Console, and the iOS
      Settings screen.

## Phase 2 — Backend deployed (demo/review server)

- [ ] Deploy the server: Render Blueprint (`render.yaml`) or Docker
      (`docs/DEPLOY.md`); exact demo commands in
      `APP_STORE_SUBMISSION.md` §6.
- [ ] Set a temporary review `SLEEP_PASSWORD`; leave `ANTHROPIC_API_KEY`
      unset on the review server (keeps data-safety answers simple).
- [ ] Seed 60–90 nights of realistic demo data (CSV import or
      `POST /api/ingest`), including some nights with stages.
- [ ] Verify from a phone on cellular: HTTPS login, dashboard, trends,
      nights, `/healthz`.

## Phase 3 — Code readiness (app lanes, not this doc's lane)

iOS (tracked in `reports/ios-release-review.md`; execution per
`ios/RELEASE.md` when it lands):

- [ ] Signing: real team + bundle ID, `CODE_SIGNING_ALLOWED` removed.
- [ ] `PrivacyInfo.xcprivacy` added (UserDefaults → reason `CA92.1`).
- [ ] Privacy-policy link added to Settings (Apple 5.1.1).
- [ ] `NSLocalNetworkUsageDescription` added or ATS local-networking
      exception dropped for release.
- [ ] Review-path decision executed: HealthKit-offline mode **or**
      demo-server review story (submission kit §6 assumes the latter).
- [ ] Health sync fidelity fixes if in scope (stages/source loss — High
      finding).

Android (per `docs/android-deployment.md`):

- [ ] `./gradlew testDebugUnitTest lintDebug assembleDebug bundleRelease`
      green locally and in CI.
- [ ] **[OWNER]** Create upload keystore (outside the repo), enroll Play App
      Signing.
- [ ] Manual pass against the HTTPS demo server (checklist in
      `docs/android-deployment.md` §Local release gate).

## Phase 4 — Store assets

- [ ] Re-capture the five iOS screenshots (stale set + mock shot 04) —
      shot list in `docs/store/SCREENSHOTS.md` §4.
- [ ] Capture 4+ Android phone screenshots (1080×2400 class).
- [ ] Produce the Play feature graphic 1024×500 and 512×512 icon.
- [ ] iOS 1024 icon: already ready (`docs/app-store/assets/AppIcon-1024.png`).

## Phase 5 — iOS: archive, TestFlight, listing

- [ ] **[OWNER]** Archive → validate → upload per `ios/RELEASE.md`
      (interim: `ios/APP_STORE_NEXT.md` §E). Bump build number each upload.
- [ ] **[OWNER]** ASC app record: name, bundle ID, SKU
      (`APP_STORE_SUBMISSION.md` §1).
- [ ] TestFlight internal: owner's device, real multi-year Health data,
      several crash-free days.
- [ ] Fill listing: copy §7, screenshots, age rating §2, App Privacy §3,
      export compliance §5 (plist flag already set).
- [ ] Paste review notes §6 with live demo URL + temporary password;
      sign-in info: demo credentials.

## Phase 6 — Android: bundle, testing tracks, listing

- [ ] **[OWNER]** Play app created with approved package; upload signed AAB
      to **Internal testing** (`docs/android-deployment.md` §Signing and
      internal testing).
- [ ] Test the Play-delivered build via opt-in link, not just local APK.
- [ ] App content tasks: Data safety (`PLAY_STORE_SUBMISSION.md` §3),
      Health apps declaration §4, content rating §5, target audience §6
      (18+), App access credentials §7, privacy policy URL.
- [ ] Listing: copy §2 + assets §8.
- [ ] Closed testing round; resolve all pre-launch report blockers.

## Phase 7 — Submit

- [ ] **[OWNER]** iOS: Add for Review → Submit. Typical Health-app review
      24–48 h; watch Resolution Center; keep the demo server up the whole
      window.
- [ ] **[OWNER]** Android: apply for production when eligible → staged
      rollout (10–20% first) with crash/ANR monitoring.
- [ ] Phased release on iOS (7-day) recommended for 1.0.

## Phase 8 — After approval

- [ ] Rotate/disable the review `SLEEP_PASSWORD`; tear down or repurpose the
      demo server.
- [ ] Tag releases: `ios-1.0.0`, `android-1.0.0`.
- [ ] Never reuse an Android `versionCode`; bump iOS build number for any
      re-upload.
- [ ] Keep privacy policy URL stable; any data-practice change updates the
      policy **before** the build that changes behavior ships (Health
      Connect addendum: `PLAY_STORE_SUBMISSION.md` §4).

---

## Blocker snapshot (2026-08-06)

Resolved since the 2026-08-03 audit:

- ~~Privacy policy not hosted~~ — **live** at
  https://shreyas2692.github.io/Sleep-Tracking/store/PRIVACY_POLICY.html
  (GitHub Pages), wired into the app (`SettingsView.swift`) and the
  submission docs (commit `58bf904`).
- ~~No `PrivacyInfo.xcprivacy` / in-app policy link / LAN purpose string~~ —
  all three shipped (commit `ff7f7a5`); the privacy manifest now also
  declares Other User Content (night notes) conservatively.
- ~~HealthKit-offline mode absent~~ — offline local mode with
  `LocalAnalytics` shipped; the app works with no server, and the
  demo-server review story remains as belt-and-suspenders.
- ~~All 5 iOS screenshots stale; shot 04 a mock~~ — re-captured 2026-08-04
  from the live app at 1320×2868 (`docs/store/SCREENSHOTS.md`).
- ~~No feature graphic~~ — `android/screenshots/feature-graphic.png`
  (1024×500) ready.

Still open:

| # | Blocker | Store | Lane |
|---|---|---|---|
| 1 | iOS signing: owner team + `Signing.xcconfig`, archive & upload (`ios/RELEASE.md`) | Apple | **[OWNER]** |
| 2 | ASC app record + listing not created; nothing submitted yet | Apple | **[OWNER]** |
| 3 | Play account (Organization, verification) not confirmed | Play | **[OWNER]** |
| 4 | No upload keystore / Play App Signing | Play | **[OWNER]** |
| 5 | Android phone screenshots missing (placeholders in `android/screenshots/` are empty files) | Play | assets |
| 6 | Demo server not yet seeded with review data + temp password | Both | backend + **[OWNER]** |
