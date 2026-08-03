# Play Store Submission Kit — Sleep Tracker (Android)

Everything to fill into Play Console. Facts verified against the code on
2026-08-03: `android/app/src/main/AndroidManifest.xml` (INTERNET +
ACCESS_NETWORK_STATE only; no Health Connect, no other permissions; backup
disabled; cleartext blocked), `android/app/build.gradle.kts`
(`io.github.shreyas2692.sleeptracker`, minSdk 28, targetSdk 36, 1.0.0),
`SecureConfigStorage.kt` (Keystore-encrypted credentials), and
`ai_summary.py` (AI payload). Unlike iOS, the Android app ships **no default
server URL** — the user types their own — which keeps the data story clean.

Process, signing, testing tracks, and account requirements live in
`docs/android-deployment.md` — this doc is the listing/declarations content.

---

## 1. App details

| Field | Value |
|---|---|
| App name (30 chars max — this is 28) | **Sleep Tracker: Sleep History** ("Sleep Tracker" alone will collide; Play names need not be unique but search does) |
| Category | **Health & Fitness** |
| Tags | Sleep, Health |
| Free/paid | Free, no ads, no in-app purchases |
| Contains ads | **No** |
| Package | `io.github.shreyas2692.sleeptracker` — owner must approve before first upload (permanent) |

## 2. Listing copy (final)

**Short description** (80 chars max — this is 76):

> Your sleep history, years deep — trends, sleep debt, and stages. No
> paywall.

**Full description:**

```text
Sleep Tracker turns your sleep history into one calm, long-horizon
dashboard — years of nights, sleep debt, and stage breakdowns, with
nothing locked behind a paywall.

Most sleep apps show you last night and charge you for last year. Sleep
Tracker starts from the idea that your history is the whole point.

WHAT YOU GET
• Today — nights logged, average hours and quality, your streak, and
  rolling sleep debt at a glance
• Trends — 30 days, 90 days, 1 year, or everything. Never paywalled.
• Nights — deep, REM, light, and awake time for every night your
  tracker recorded stages
• Insights — weekly patterns, consistency, and an optional AI-written
  weekly summary in plain, kind language
• Log by hand — bedtime, wake time, quality, and notes in seconds

YOUR DATA, YOUR SERVER
Sleep Tracker connects to a small personal server that you control —
run it at home with Docker or deploy it free in a click. Import years
of Apple Health or Fitbit history and watch the charts go deep. No
account with us, no cloud we control, no subscription. Export
everything, any time: CSV, JSON, or the database itself.

PRIVATE BY ARCHITECTURE
• No ads, no analytics, no tracking — the app talks only to the server
  you configure, over HTTPS
• Your password is encrypted on-device with the Android Keystore
• Delete any record — or everything — whenever you like

A Sleep Tracker server (free, open source) is required. Setup takes a
few minutes and the app walks you through it.

NOT A MEDICAL DEVICE
Sleep Tracker does not diagnose or treat any condition. It visualizes
data your devices already collected. Talk to a professional about
medical concerns.
```

Note the honesty line "A Sleep Tracker server is required" — Play reviewers
reject apps that appear broken at first run; saying it up front plus the
app-access instructions in §7 covers this.

## 3. Data safety questionnaire

Architecture facts driving the answers: the app transmits sleep records and
credentials **only** to the user-configured server; the developer operates no
default backend for Android; release builds enforce HTTPS
(`network_security_config.xml`, `usesCleartextTraffic="false"`); no SDKs
that collect anything; deletion is available in-app.

Google counts data "collected" when it leaves the device, so the safe,
honest declaration is:

| Question | Answer |
|---|---|
| Does your app collect or share any of the required user data types? | **Yes** |
| **Health info → Health info** (sleep records incl. stages, quality) | Collected: **Yes**. Shared: **No**. Processed ephemerally: No. Required: Yes (core function). Purpose: **App functionality** |
| **Personal info → Other info** (free-text sleep notes) | Collected: **Yes**. Shared: **No**. Optional: **Yes** (notes are optional). Purpose: App functionality |
| All other data types (location, contacts, identifiers, financial, messages, photos, files, app activity, browsing, diagnostics…) | **Not collected** |
| Is all user data encrypted in transit? | **Yes** (HTTPS enforced in release builds) |
| Do you provide a way for users to request deletion? | **Yes** — delete individual records in-app; clear all records via the server's settings; self-hosters can delete the database. Deletion-request URL: use the privacy policy URL (its Retention and deletion section) |
| Account creation | App does not allow account creation (server password is infrastructure auth, not an account) |
| Data collected by SDKs/libraries | None — no third-party data-collecting SDKs |

**About the AI summary:** the Anthropic call is made by the *user's own
server*, server-side, with aggregate statistics (verified payload in
`docs/store/PRIVACY_POLICY.md`). The Android app only fetches the finished
text. Because the developer ships no Android backend and the transfer is
performed by the user-operated server, this is not developer "sharing" under
Data safety — but it **must** be (and is) disclosed in the privacy policy.
If the owner ever ships a developer-operated default server for Android with
the AI key enabled, revisit this and declare Health info → Shared with
service provider.

## 4. Health apps declaration

Required for every app on closed/open/production tracks. Sleep Tracker
provides sleep tracking, so:

- Declare **Health & Fitness features: Yes → Sleep management**.
- **Health Connect: Not used.** The manifest requests no
  `android.permission.health.*` permissions and there is no Health Connect
  client code. Do not mention Health Connect anywhere in the listing,
  screenshots, or Data safety answers.
- No medical-device, diagnosis, or treatment claims in the listing (the copy
  in §2 complies), so no regulatory declarations apply.

### Addendum — when Health Connect is added later (Wave 2+)

Before uploading that build: ship the in-app integration first; request only
`READ_SLEEP` (and nothing else); add the manifest permission +
`ACTION_SHOW_PERMISSIONS_RATIONALE` activity; update the Health apps
declaration to "Health Connect: reads sleep"; add Health Connect data types
to Data safety; add a permission rationale screen and in-app access
management; and update `docs/store/PRIVACY_POLICY.md` (its Health Connect
section currently — correctly — says "not used").

## 5. Content rating (IARC questionnaire)

Answers: no violence, no sexuality, no profanity, no controlled substances,
no gambling (simulated or real), no user interaction/sharing features (no
chat, no content shared with other users), no user location sharing, no
personal-info sharing with third parties, not a web browser, no digital
purchases.

Expected result: **Everyone / PEGI 3** across rating authorities.

## 6. Target audience and content

**Recommendation: 18 and over only.** Justification:

- The app handles health data and requires configuring a personal server
  with credentials — an adult use case; nothing in the design targets or
  appeals to children.
- Selecting any under-18 age group pulls the app toward Families/Teacher
  Approved review obligations and stricter data-handling scrutiny for zero
  product benefit.
- The privacy policy already states the app is not directed at children
  under 13; an 18+ target-audience answer is the consistent, lowest-risk
  declaration ("Appeals to children: No").

(Content *rating* stays Everyone — that measures content, not audience.)

## 7. App access (review credentials)

Play review needs to get past the first-run server screen. In App content →
App access, choose "All or some functionality is restricted" and provide:

```text
Sleep Tracker requires a personal server (open source). A demo server is
provided for review:
  Server URL: https://REVIEW-DEMO.example
  Username:  sleep
  Password:  TEMPORARY_PASSWORD
On first launch, enter the URL, username, and password on the setup
screen, then tap the connect/sign-in button. All features are then
available: dashboard, trends, nights, insights, settings.
Credentials remain valid for the entire review period.
```

Use the same demo server as the iOS review (setup instructions in
`docs/store/APP_STORE_SUBMISSION.md` §6). Keep `ANTHROPIC_API_KEY` unset on
it so the Data safety "Shared: No" answer is unambiguous.

## 8. Store assets checklist

| Asset | Spec | Status |
|---|---|---|
| App icon | 512×512 PNG, ≤1 MB | Missing at Play spec — downscale `docs/app-store/assets/AppIcon-1024.png` |
| Feature graphic | 1024×500 JPG/PNG, required | **Missing** — see `docs/store/SCREENSHOTS.md` |
| Phone screenshots | 2–8; PNG/JPG; each side 320–3840 px; for promotion eligibility ≥4 at ≥1080 px, 9:16 | **Missing** — must be captures of the *Android* app (Material UI), not iOS |
| 7"/10" tablet screenshots | Only if claiming tablet support | Skip — phone-focused v1 |
| Video | Optional YouTube URL | Skip |

## 9. Submission blockers (honest list)

1. **BLOCKER — account:** verified Play account required; from
   2026-09-30 health apps must use an Organization account
   (`docs/android-deployment.md` §Owner-only). Start this first — it has
   lead time.
2. **BLOCKER — package ID approval:** permanent once uploaded; owner must
   confirm `io.github.shreyas2692.sleeptracker`.
3. **BLOCKER — signing:** upload keystore + Play App Signing enrollment
   (owner-only; commands in `docs/android-deployment.md`).
4. **RESOLVED (2026-08-03) — privacy policy URL:** live at https://shreyas2692.github.io/Sleep-Tracking/store/PRIVACY_POLICY.html. Was: host `docs/store/PRIVACY_POLICY.md`
   (public, non-geofenced, not a PDF).
5. **BLOCKER — Android screenshots + feature graphic:** none exist.
6. **BLOCKER — demo server** live with review credentials (shared with iOS).
7. Testing gate: internal → closed testing with real testers before
   production (12-testers/14-days rule applies to new personal accounts;
   Organization accounts still need a closed test pass).
