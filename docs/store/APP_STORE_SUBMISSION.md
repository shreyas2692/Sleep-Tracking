# App Store Submission Kit — Sleep Tracker (iOS)

Everything to fill into App Store Connect (ASC), in the order ASC asks for
it. Facts below were verified against the code on 2026-08-03 (`ios/Support/
Info.plist`, `ios/Sources/`, `ai_summary.py`). Blocking gaps are marked
**BLOCKER** — see the list at the end.

Companion docs: `docs/app-store/APP_STORE_PLAN.md` (strategy),
`ios/APP_STORE_NEXT.md` (owner's Xcode click-path),
`docs/store/RELEASE_RUNBOOK.md` (ordered checklist),
`docs/store/SCREENSHOTS.md` (screenshot status).

---

## 1. App record basics

| Field | Value |
|---|---|
| Platform | iOS, iPhone only (`TARGETED_DEVICE_FAMILY: 1`) — do **not** opt into iPad/Mac |
| Name | **Sleep Tracker** (if taken: "Sleep Tracker — Years of Nights") |
| Primary language | English (U.S.) |
| Bundle ID | `com.shreyas2692.sleeptracker` (per `ios/APP_STORE_NEXT.md`) |
| SKU | `sleeptracker-ios-1` |
| Primary category | **Health & Fitness** |
| Secondary category | Lifestyle (optional) |
| Price | Free — no IAP, no subscription |
| Sign-in required | Yes in practice (see §6) — provide the demo server credentials |

## 2. Age rating

Apple's questionnaire — answer **None / No** to every content category:
violence, sexual content, profanity, horror, gambling, alcohol/tobacco/drugs,
unrestricted web access, user-generated content*, and **medical/treatment
information: None** (the app shows the user's own sleep statistics and makes
no medical or treatment claims — the description and AI prompt both forbid
diagnosis language).

Result: **4+** (lowest tier). If ASC's current questionnaire offers the newer
tiers (4+/9+/13+/16+/18+), the same all-None answers still land on 4+.

\* Notes fields are private to the user's own server and never shown to other
users, so "user-generated content" in Apple's shared-content sense is No.

## 3. App Privacy questionnaire (nutrition label)

The honest answers for this architecture. Key fact: the app transmits sleep
data off-device — but only to the server the user configures. However, the
build ships a **default server URL operated by the developer**
(`https://sleep-tracker-n4cs.onrender.com` in
`ios/Sources/Networking/APIClient.swift`), so "we never receive data" is not
strictly true for the shipped binary. Declare conservatively:

| Question | Answer |
|---|---|
| Do you collect data from this app? | **Yes** |
| Data type | **Health & Fitness → Health** (sleep records; includes HealthKit-derived sleep analysis) |
| Also declare | **Other User Content** if you want to be maximally careful (notes field synced to the server); defensible to omit if you treat the server as user-controlled — recommended: declare it |
| Purpose | **App Functionality** only |
| Linked to the user's identity? | **No** — no account system, no user identifier; Basic-auth username is a shared label ("sleep"), not an identity |
| Used for tracking? | **No** (no ATT prompt needed) |
| Data types NOT collected | Contact info, identifiers, location, browsing, purchases, diagnostics, usage data — the app has no analytics or crash SDKs |

Cleaner alternative (owner decision): remove/blank the developer-run default
URL from the store build so every byte goes only to a server the user typed
in. Then "Data Not Collected" becomes defensible for all types. Until that
change ships, use the table above.

The optional AI summary does not change this questionnaire: the Anthropic
call is made by the *server*, server-side, using aggregate statistics (see
the payload description in `docs/store/PRIVACY_POLICY.md`, verified against
`ai_summary.py`). The iOS app itself only fetches the finished text from
`/api/summary`.

| Privacy field | Value |
|---|---|
| Privacy Policy URL | your hosted copy of `docs/store/PRIVACY_POLICY.md` — **BLOCKER: not hosted yet** |
| Privacy choices URL | leave blank |

## 4. HealthKit review notes

- Entitlement: `com.apple.developer.healthkit` is present
  (`ios/Support/SleepTracker.entitlements`). Read-only; no write types
  requested, no Clinical Records.
- Purpose string (`NSHealthShareUsageDescription`, already in Info.plist):
  "Sleep Tracker reads your sleep analysis data from Apple Health so it can
  show your nights here and, if you choose, sync them to your self-hosted
  server. Your data never leaves your devices otherwise."
  Keep the UI consistent with this string.
- Health data is never used for advertising/marketing and never shared with
  third parties — required by Apple guideline 5.1.3 and true here.
- No diagnosis/treatment claims anywhere in copy, screenshots, or the AI
  summary (the system prompt in `ai_summary.py` explicitly forbids medical
  claims).

## 5. Export compliance

`ITSAppUsesNonExemptEncryption` is already `false` in Info.plist. The app
uses only standard TLS (HTTPS/ATS) — no custom or proprietary cryptography.

ASC questions: **Uses encryption: Yes → Exempt (standard encryption only /
HTTPS)**. With the plist key set, ASC usually skips the prompt entirely. No
French declaration or annual self-classification report needed for the
standard exemption.

## 6. App Review notes (paste into ASC → App Review Information)

Important correction to the older `docs/app-store/APP_REVIEW_NOTES.md`: that
draft tells the reviewer a HealthKit-only path works with no server.
**It does not** — Dashboard/Trends/Nights render server data, and per
`reports/ios-release-review.md` the offline HealthKit mode is not
implemented. Until it is, the review notes must lead with the demo server.

```text
Sleep Tracker — App Review guide

SUMMARY
Sleep Tracker is a personal sleep-history viewer. It shows multi-year
trends, sleep debt, and per-night sleep stages from a small personal
server that each user runs or controls (open source; also deployable in
one click). There is no account system, no subscription, no ads, and no
third-party analytics. The app can also read Sleep Analysis from Apple
Health (with permission) and sync those nights to the user's server.

DEMO SERVER (use this to review)
The app's first-run screen asks for a server password.
  URL:      [https://REVIEW-DEMO.example  — pre-filled by default]
  Username: sleep
  Password: [TEMPORARY_PASSWORD]
1. Launch the app. On the sign-in screen enter the password above
   (URL and username are pre-filled) and tap Sign In.
2. Today tab: stats, sleep debt, last-30-nights chart.
3. Trends tab: switch 30d / 90d / 1y / All — never paywalled. The
   Insights section may include a short AI-written weekly summary
   (generated server-side from aggregate statistics).
4. Nights tab: open a night for its deep/REM/light/awake breakdown.
5. Settings: server connection, Apple Health sync, goals.

APPLE HEALTH (optional to exercise)
Settings → Apple Health → grant Sleep read access. If the review device
has sleep samples in the Health app, they can be synced to the demo
server and will appear alongside existing data.

WHAT WE DO NOT DO
- No medical diagnosis or treatment claims.
- No write access to HealthKit (read Sleep Analysis only).
- No account creation, IAP, ads, or tracking (ATT not used).
- Demo credentials are valid only during review and rotated after.

CONTACT
[NAME] — [EMAIL] — [PHONE]
```

### Demo server: exact setup (do this before submitting)

Option A — Render (recommended; the app's default URL already points to the
owner's Render service): deploy via `render.yaml` (repo → Render Blueprint),
set a temporary `SLEEP_PASSWORD` for the review window, and load 60–90 nights
of realistic demo data (CSV import or `POST /api/ingest`). Rotate the
password after approval.

Option B — any Docker host with a public HTTPS URL:

```bash
docker build -t sleep-tracker .
docker run -d -p 443-terminated-proxy:10000 \
  -v sleep-tracker-data:/data \
  -e SECRET_KEY='long-random-string' \
  -e SLEEP_USERNAME=sleep \
  -e SLEEP_PASSWORD='temporary-review-password' \
  sleep-tracker
```

Notes: leave `ANTHROPIC_API_KEY` **unset** on the demo server unless you
want reviewers to see the AI card (unset = the card simply hides, and the
"no data shared with third parties" story stays maximally simple). The demo
server must stay up for the entire review window; `/healthz` is public for
uptime checks.

### What the reviewer will see

First-run sign-in sheet (password field, pre-filled URL under "Advanced") →
Today dashboard with greeting, stat tiles, sleep-debt card, 30-day bars →
Trends with range selector and Insights section → Nights list with stage
strips and provenance → night detail with stage composition → Settings with
Apple Health sync and server connection.

## 7. Listing copy (final)

**Subtitle** (30 chars max — this is 26):

> Years of sleep, no paywall

**Promotional text** (170 chars max — this is 159; updatable without review):

> See every night your watch ever recorded — sleep debt, stages, and
> multi-year trends in one calm dashboard. No subscription, no account.
> Your data stays yours.

**Description:**

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
• Nights — deep, REM, light, and awake time for every night your watch
  recorded stages
• Insights — weekly patterns, consistency, and an optional AI-written
  weekly summary in plain, kind language
• Apple Health — with your permission, bring in the sleep your Apple
  Watch already recorded

WHAT WE BELIEVE
• Your data belongs to you. No account with us, no cloud we control,
  no subscription. Nights live on a small personal server you control.
• One bad night is never a failure. Weekly and multi-year context first.
• Export everything, any time — CSV, JSON, or the database itself.

FOR TINKERERS
The server is open source. Run it at home with Docker or deploy it free
in a click — then import years of Apple Health or Fitbit history and
watch the charts go deep.

NOT A MEDICAL DEVICE
Sleep Tracker does not diagnose or treat any condition. It visualizes
data your devices already collected. Talk to a professional about
medical concerns.
```

**Keywords** (100 chars max — this is 76):

```text
sleep,healthkit,apple watch,sleep debt,stages,rem,trends,history,journal,log
```

**What's New (1.0.0):**

```text
First release: your nights from Apple Health, multi-year trends, sleep
debt, per-night stages, weekly insights, and optional sync to your own
server.
```

**Support URL:** the GitHub repo. **Marketing URL:** optional, same repo.

## 8. Screenshots & icon

See `docs/store/SCREENSHOTS.md`. Summary: five 1290×2796 captures exist but
are stale (pre-date the sign-in screen and the Trends Insights/AI-summary
section) and shot 04 is a design mock, which Apple prohibits — re-capture
before submit. Icon `docs/app-store/assets/AppIcon-1024.png` is a valid
1024×1024 PNG, no alpha: ready.

## 9. Submission blockers (honest list)

1. **BLOCKER — signing:** `ios/project.yml` still has
   `CODE_SIGNING_ALLOWED: NO` and an empty `DEVELOPMENT_TEAM`; archive is
   impossible until the owner signs in (see `ios/APP_STORE_NEXT.md`).
2. **BLOCKER — privacy policy URL:** not hosted yet. Host
   `docs/store/PRIVACY_POLICY.md` (GitHub Pages note inside it).
3. **BLOCKER — in-app privacy link:** Settings has no privacy-policy link;
   Apple 5.1.1 requires one inside the app. (iOS lane change.)
4. **BLOCKER — privacy manifest:** no `PrivacyInfo.xcprivacy` in `ios/`;
   required for UserDefaults use (required-reason API, category `CA92.1`).
   (iOS lane change.)
5. **BLOCKER — review path:** either implement the HealthKit-only offline
   mode the old plan promised, or (faster) submit with the demo-server story
   in §6 and copy that never promises offline use. §6/§7 above are written
   for the second path.
6. High — `NSLocalNetworkUsageDescription` missing from Info.plist while ATS
   local networking is enabled; add the purpose string or drop the ATS
   exception from release builds. (iOS lane change.)
7. Decision — keep or remove the developer-run default server URL; it
   determines the §3 label ("collected, not linked" vs "not collected").
8. Demo server with temporary password and seeded data must be live before
   pressing Submit.
