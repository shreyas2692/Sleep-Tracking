# Sleep Tracker — Apple App Store Plan

**Owner doc (Grok, 2026-07-31)**  
**Status:** planning + visual mockups  
**Product north star:** *Import everything. Merge it. Keep it forever. Analyze years, not weeks. No subscription, no account, no cloud.*  
**Companion mockups:** [`mockups/`](./mockups/) · existing live capture: [`../../ios/screenshots/dashboard-light.png`](../../ios/screenshots/dashboard-light.png)

---

## 1. What we ship (positioning for the store)

| | |
|--|--|
| **Name** | Sleep Tracker |
| **Subtitle** (30 chars) | Years of sleep, no paywall |
| **Category** | Health & Fitness |
| **Secondary** | Lifestyle (optional) |
| **Price** | Free (no IAP, no subscription) |
| **Age** | 4+ (no medical claims) |
| **Devices** | iPhone only for v1.0 (`TARGETED_DEVICE_FAMILY: 1`) |
| **Min OS** | iOS 17.0 (matches `project.yml`) |

**One-line App Store pitch**

> See every night from Apple Health in one calm app — multi-year trends, sleep debt, and stage breakdown. Your data stays on your devices. Optional self-hosted server for backup and web charts.

**What we are *not*** (review-safe framing)

- Not a medical device, not a diagnostic tool, not a sleep coach that shames.
- Not a real-time tracker / smart alarm / snore detector.
- Not a cloud SaaS: no account required; HealthKit data is not sold; optional server is *user-controlled*.

---

## 2. Architecture for App Store (two modes)

Ship **one binary** with two honest data paths:

```
┌─────────────────────────────────────────────┐
│  iOS App (SwiftUI)                          │
│  Today · Trends · Nights · Settings         │
└───────────────┬───────────────┬─────────────┘
                │               │
        HealthKit read    optional HTTPS
        (on-device)       (user's server)
                │               │
                ▼               ▼
        NightClustering    GET/POST API
        local cache        (Basic Auth)
```

| Mode | When | Review story |
|------|------|----------------|
| **A — HealthKit first** | Default. Read `HKCategoryTypeIdentifierSleepAnalysis`, cluster into nights, show trends offline. | Standard HealthKit consumer app. |
| **B — Self-hosted sync** | User pastes server URL + Basic Auth in Settings; optional push via Shortcuts / `/api/ingest`. | “Connects only to a server you run.” Document ATS local networking. |

v1.0 **must work without a server** (Mode A). Server features are power-user optional so App Review does not reject on “requires private server.”

---

## 3. Screen map (SwiftUI today → store screenshots)

| Tab | Swift file | Screenshot role |
|-----|------------|-----------------|
| **Today** | `DashboardView.swift` | Hero: greeting, stats, sleep debt, 30-day bars |
| **Trends** | `TrendsView.swift` | Differentiator: 30d / 90d / 1y / all |
| **Nights** | `NightsView` + detail/form | Stage stack, edit, provenance |
| **Settings** | `SettingsView.swift` | HealthKit grant + optional server |
| *(sheet)* | `NightDetailView` | Deep / REM / light / awake |

**Mockups for review decks / early ASCs:**

| File | Purpose |
|------|---------|
| [`mockups/01-today.html`](./mockups/01-today.html) | Matches live dashboard language |
| [`mockups/02-trends.html`](./mockups/02-trends.html) | Multi-year range story |
| [`mockups/03-nights.html`](./mockups/03-nights.html) | List + stages |
| [`mockups/04-night-detail.html`](./mockups/04-night-detail.html) | Composition breakdown |
| [`mockups/05-settings.html`](./mockups/05-settings.html) | Health + server honesty |
| [`mockups/index.html`](./mockups/index.html) | Gallery of all five |

Open any file in Safari/Chrome → export as 1290×2796 (or device screenshot) for ASC.

---

## 4. App Store Connect checklist

### 4.1 Account & identity

- [ ] Apple Developer Program membership ($99/yr)
- [ ] App ID: reverse-DNS **not** `local.sleeptracker.app` — e.g. `app.yourname.sleeptracker`
- [ ] Capabilities: **HealthKit** only for v1 (no HealthKit Clinical Records)
- [ ] Certificates: Apple Distribution + App Store provisioning profile
- [ ] App Store Connect record: name, bundle ID, SKU, primary language **English (U.S.)**

### 4.2 Binary build

```text
Current blockers in project.yml:
  CODE_SIGNING_ALLOWED: "NO"
  DEVELOPMENT_TEAM: ""
  PRODUCT_BUNDLE_IDENTIFIER: local.sleeptracker.app
```

Ship checklist:

- [ ] Set `DEVELOPMENT_TEAM` and real `PRODUCT_BUNDLE_IDENTIFIER`
- [ ] Enable automatic signing for Release or export archive via Xcode Organizer
- [ ] `MARKETING_VERSION` 1.0.0, `CURRENT_PROJECT_VERSION` build number bump every upload
- [ ] Archive → Validate App → Distribute to App Store Connect
- [ ] Optional: TestFlight internal group first (see §7)

### 4.3 Privacy (mandatory)

| Item | Content |
|------|---------|
| **Privacy Nutrition Label** | Health & Fitness → Sleep Analysis: *used for App Functionality*; **not** linked to identity; **not** used for tracking |
| **Data Not Collected** (if true) | No analytics SDK, no ads, no crash cloud — claim only what binary does |
| **Privacy Policy URL** | Required if HealthKit is used. Host a static page (GitHub Pages / self-host). Draft outline in §8 |
| **NSHealthShareUsageDescription** | Already in `Info.plist` — keep human, non-marketing |
| **Tracking** | ATT not required if no tracking; set “No” on tracking questionnaire |

### 4.4 HealthKit review expectations

- Purpose string must match UI (we already describe read + optional sync).
- Do **not** claim to diagnose sleep apnea / insomnia / medical conditions.
- Prefer calm copy: “Rested +5.8h vs your need” over red failure badges (aligns with PRODUCT.md orthosomnia-aware principle).
- If writing to HealthKit is never done, do **not** request write types.

### 4.5 App Review notes (paste into ASC)

```text
Sleep Tracker is a personal sleep history viewer.

1. On first launch, grant Sleep read access when prompted (HealthKit).
2. The Today tab shows stats from HealthKit-clustered nights and/or
   an optional self-hosted server configured in Settings.
3. No account, no subscription, no third-party analytics.
4. Server URL is optional. For review without a server: use HealthKit only
   with the sample sleep data already on the review device, or install
   any sleep samples via the Health app.
5. Demo server (if needed): <URL>  user: sleep  pass: <temporary>
   (enable only during review window; set SLEEP_PASSWORD).
```

### 4.6 Metadata copy bank

**Promotional text** (170 chars, updatable without review)

> Your Apple Watch nights, years deep — sleep debt, stages, and trends without a subscription. Data stays yours.

**Description** (draft)

```text
Sleep Tracker turns your Apple Health sleep history into a calm, long-horizon
dashboard — the kind of multi-year view most wearable apps bury behind a paywall.

WHAT YOU GET
• Today: nights logged, average hours & quality, streak, rolling sleep debt
• Trends: 30 days, 90 days, 1 year, or all history — never paywalled
• Nights: per-night stages (deep, REM, light, awake) when your Watch recorded them
• Optional: connect a self-hosted Sleep Tracker server for web charts & backup

WHAT WE BELIEVE
• No account. No cloud we control. No subscription.
• One bad night is not a failure — weekly and multi-year context first
• Export and own your data (CSV / JSON on the server side)

NOT A MEDICAL DEVICE
Sleep Tracker does not diagnose conditions or replace professional advice.
It visualizes data your devices already collected.
```

**Keywords** (100 chars, comma-separated, no spaces after commas carefully)

```text
sleep,healthkit,apple watch,sleep debt,stages,REM,trends,self hosted,history
```

**What’s New (1.0)**

```text
First release: HealthKit nights, multi-year trends, sleep debt, stage view,
optional self-hosted server sync.
```

### 4.7 Screenshots (required sizes)

Priority device sets for 2026:

| Slot | Device | Size (px) |
|------|--------|-----------|
| 6.7" | iPhone 15/16 Pro Max class | 1290 × 2796 |
| 6.5" | older max (if still required in ASC) | 1284 × 2778 |

**Ready set (upload these):** [`screenshots/`](./screenshots/)

| File | Source | Size |
|------|--------|------|
| `01-today.png` | Simulator + `-previewFixtures` | 1290×2796 |
| `02-trends.png` | Simulator + fixtures | 1290×2796 |
| `03-nights.png` | Simulator + fixtures | 1290×2796 |
| `04-night-detail.png` | Design mock (re-capture from app after license) | 1290×2796 |
| `05-settings.png` | Simulator + fixtures | 1290×2796 |

**Shot order (story):** Today → Trends → Nights → Night detail → Settings.

**Re-capture after Xcode license:**

```bash
sudo xcodebuild -license accept   # once
./docs/app-store/scripts/capture-store-screenshots.sh
# optional: ./docs/app-store/scripts/capture-store-screenshots.sh "iPhone 16 Pro Max"
```

Launch args used by the script: `-previewFixtures`, `-initialTab`, `-initialRange 1y`, `-showNightDetail`.

### 4.8 Icon & brand

- 1024×1024 App Store icon, no alpha, no rounded mask (Apple applies mask)
- Wordmark already in-app (“Sleep Tracker” serif + system)
- Palette (from `Theme.swift`): page `#FAF9F5`, accent terracotta `#D97757`, ink `#141413`

---

## 5. Engineering milestones → store

### Wave A — Store-ready core (blockers)

| # | Task | Owner | Done when |
|---|------|-------|-----------|
| A1 | HealthKit path works **offline** (no server required for first paint) | iOS | Launch with only HK shows nights |
| A2 | Real bundle ID + signing + archive | iOS / owner | IPA validates in Organizer |
| A3 | Privacy policy URL live | docs | HTTPS link in ASC |
| A4 | Crash-free TestFlight week on owner’s Watch data | owner | 7 days, no P0 |
| A5 | App Review notes + demo path | docs | ASC form complete |
| A6 | Screenshot set (5) + 1024 icon | design | uploaded to ASC |

### Wave B — Sync polish (can ship 1.0.1)

| # | Task | Notes |
|---|------|-------|
| B1 | Fix `POST /api/ingest` shape (`wake` + nested stages) | server; red-team C1 |
| B2 | Shortcuts recipe + Health Auto Export | `docs/shortcuts-sync.md` |
| B3 | Dedup / unique identity policy | red-team H1 |
| B4 | CSRF / password defaults for public deploy | red-team C2 |

### Wave C — Differentiation (post 1.0)

Aligned with PRODUCT.md Waves 2–3: transparent score, multi-source disagreement, tags/correlations, shift-worker mode — **not** required for first approval.

---

## 6. Compliance & rejection risk matrix

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| “Requires private server” | Med | HealthKit-only path default; server optional |
| Medical claims in copy | Med | Scrub description; no diagnose language |
| Incomplete Health purpose string | Low | Already present; keep accurate |
| Missing privacy policy | High if omitted | Ship static policy before submit |
| Placeholder bundle ID / unsigned | High until A2 | Replace `local.*` before archive |
| Broken ingest during review demo | Med | Don’t depend on ingest for review; use HK |
| Guideline 2.1 incomplete info | Med | Detailed Review Notes + demo account |

---

## 7. TestFlight path (recommended before full release)

1. Internal testing (owner + 1 device) — 1–2 days  
2. External TestFlight (optional, needs Beta App Review) — 1 week  
3. Production submit when:
   - No crashes on real export-scale history (years of Watch data)
   - Trends `all` remains usable (server already handles 50k; iOS should paginate/window)
   - Settings copy makes optional server obvious

---

## 8. Privacy policy outline (host this)

```text
# Privacy Policy — Sleep Tracker

Last updated: YYYY-MM-DD

Sleep Tracker (“the App”) is a personal sleep history tool.

## Data we access
• Apple Health sleep analysis (with your permission), on device.
• Optional: connection details you enter for a self-hosted server (URL,
  username, password) stored in the iOS Keychain / app preferences.

## Data we do not collect
• We do not operate a central account system.
• We do not sell personal data.
• We do not use third-party advertising or tracking SDKs in v1.

## Optional self-hosted server
If you configure a server URL, the App sends and receives sleep records
only to that address, using the credentials you provide. You control that
server’s privacy and retention.

## Contact
<your email>
```

---

## 9. Submission day runbook

1. Bump build number → Archive → Upload.  
2. Select build in ASC → fill IAP “None” → export compliance (likely **No** encryption beyond HTTPS exemption).  
3. Attach screenshots + icon + description.  
4. Paste Review Notes (§4.5).  
5. Submit for Review.  
6. Monitor Resolution Center; typical Health apps: 24–48h if clean.  
7. On approval: phased release 7 days or manual release.  
8. Tag git `ios-1.0.0` (when git exists).

---

## 10. Success metrics (post-launch, privacy-respecting)

No analytics SDK required. Owner-side:

- TestFlight / ASC crash reports only  
- Personal: “Does this beat Apple Health for *my* multi-year view?”  
- Optional: GitHub stars / self-host Docker pulls as proxy interest  

---

## 11. Open decisions for the owner

1. **Public App Store vs TestFlight-only?** Public needs polished marketing; TestFlight can ship sooner.  
2. **Bundle ID / team** — confirm reverse-DNS and Apple team.  
3. **Privacy policy host** — domain choice.  
4. **Include optional server in 1.0 marketing** or bury under Settings until ingest is fixed?  
   *Recommendation:* mention optional; screenshot Settings honestly; default UX is HealthKit.  
5. **App name collision** — “Sleep Tracker” is generic; may need “Sleep Tracker Local” / distinctive name if taken.

---

## 12. Deliverables in this folder

| Path | What |
|------|------|
| `APP_STORE_PLAN.md` | This plan |
| `APP_REVIEW_NOTES.md` | **Paste-ready** App Review Notes for ASC |
| `PRIVACY_POLICY_DRAFT.md` | Host before submit (HealthKit) |
| `mockups/*.html` | Five phone frames + gallery, design tokens from iOS `Theme.swift` |
| `assets/AppIcon-1024.png` | **1024×1024 RGB, no alpha** — ASC + Xcode |
| `../../ios/Support/Assets.xcassets/AppIcon.appiconset/` | Wired App Icon asset |
| `../../ios/Sources/Preview/PreviewFixtures.swift` | SwiftUI `#Preview` fixtures (DEBUG) |
| `../../ios/screenshots/dashboard-light.png` | Real SwiftUI capture (Today) |

**Next concrete actions (suggested order):** A1 offline HealthKit → A2 signing → canvas previews / real screenshots → host privacy page → TestFlight → submit (paste `APP_REVIEW_NOTES.md`).

---

*Document owned for fleet coordination; does not change `app.py` / web lanes. iOS source remains the build agent’s lane unless the owner assigns UI polish here.*
