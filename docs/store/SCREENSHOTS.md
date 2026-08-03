# Screenshot Plan — both stores

Status audited 2026-08-03. Verdict up front: **every existing store capture
is stale** (all pre-date the first-run sign-in screen and the Trends
Insights/AI-summary section, both added later on Jul 31), shot 04 is a
design mock that Apple prohibits, and **zero Play assets exist**. The
capture pipeline already exists
(`docs/app-store/scripts/capture-store-screenshots.sh`), so this is hours,
not days.

---

## 1. Inventory — what exists today

### `docs/app-store/screenshots/` (the intended ASC upload set)

All 1290×2796 PNG (6.7-inch class), verified valid and distinct by
`reports/ios-release-review.md` §Screenshot Check.

| File | Content | Verdict |
|---|---|---|
| `01-today.png` | Dashboard: stats, sleep debt, stage bars | Stale — recheck vs current UI |
| `02-trends.png` | Trends: range control + chart | **Stale — must re-capture**: Trends now renders `InsightsSection` with the AI summary card (`ios/Sources/Views/Trends/InsightsSection.swift`); the capture pre-dates it |
| `03-nights.png` | Nights list, provenance + stage strips | Stale — recheck vs current UI |
| `04-night-detail.png` | Stage composition + quality math | **Must re-capture — it is a design mock** (`APP_STORE_PLAN.md` §4.7 admits this); App Store guideline 2.3.3 requires screenshots to show the actual app |
| `05-settings.png` | Server + Apple Health + principles | **Stale — must re-capture**: Settings/first-run flow changed with `SetupView` (sign-in sheet) |

### `ios/screenshots/` (dev captures + copies)

- `store-01-today.png` … `store-05-settings.png` — byte-identical copies of
  the set above; same verdicts.
- `dashboard-light/dark.png`, `nights-light/dark.png`,
  `settings-light/dark.png`, `trends-light/dark.png` — eight 1179×2556 dev
  captures (iPhone 15 Pro class). Wrong size for ASC slots; useful for
  README/docs only.
- `launch-setup.png` (1179×2556, captured *after* the store set) — the new
  first-run sign-in sheet. Proof the store set pre-dates the login screen;
  itself not store-sized.

### `docs/app-store/mockups/` (HTML design frames)

`01-today` … `05-settings`, `04-night-detail-store`, `index.html`,
`mockup.css`. Design references only — never upload HTML-mockup exports as
store screenshots.

### Android

**Nothing.** No Android screenshots, no feature graphic, no 512×512 icon
export.

---

## 2. Apple requirements mapping

Recommendation: **iPhone-only** (project already sets
`TARGETED_DEVICE_FAMILY: 1`). Do not opt into iPad — it would demand a 13"
iPad set for an untested layout.

| ASC slot | Size | Need | Have |
|---|---|---|---|
| 6.9" (required) | 1320×2868 — ASC also accepts 1290×2796 in this slot | 3–5 shots (up to 10) | 5 stale captures at 1290×2796; size OK, content stale |
| 6.5"/6.7" (optional; auto-scaled from 6.9" if omitted) | 1284×2778 / 1290×2796 | 0 (let ASC scale) | n/a |
| iPad 13" | — | 0 (iPhone-only) | n/a |
| App icon | 1024×1024, no alpha | 1 | **Ready:** `docs/app-store/assets/AppIcon-1024.png` (verified valid, no alpha) |

Verify the 1290×2796 acceptance in ASC's uploader at submit time; if it
insists on 1320×2868, capture on an iPhone 16 Pro Max simulator instead
(the capture script takes a device argument).

## 3. Play requirements mapping

| Asset | Spec | Have |
|---|---|---|
| Phone screenshots | 2–8, PNG/JPG, each side 320–3840 px; for store-promotion eligibility ≥4 at ≥1080 px in 9:16 | **None** — and they must show the Android app's actual Material UI, not iOS |
| Feature graphic | 1024×500 PNG/JPG, required for listing promotion | **None** — design one from the mockup palette (page `#FAF9F5`, terracotta `#D97757`, ink `#141413`): wordmark + one calm chart motif, no screenshots-in-frame clutter |
| App icon | 512×512 PNG ≤1 MB | Downscale `AppIcon-1024.png` |
| Tablet shots | only if targeting tablets | Skip for v1 |

Capture Android shots on a Pixel emulator (e.g. Pixel 8, 1080×2400 —
within Play limits) via Android Studio or `adb exec-out screencap`.

## 4. Re-capture shot list (the work)

iOS — re-run `./docs/app-store/scripts/capture-store-screenshots.sh` after
UI is final (uses `-previewFixtures`, `-initialTab`, `-initialRange 1y`,
`-showNightDetail` launch args):

1. `01-today` — Dashboard (fixtures with realistic multi-month data)
2. `02-trends` — Trends scrolled to show range selector **and the new
   Insights section with the AI summary card** (the differentiator; make
   sure fixtures produce a summary/insights state)
3. `03-nights` — Nights list with stage strips + provenance badges
4. `04-night-detail` — from the **live app** this time (`-showNightDetail`)
5. `05-settings` — current Settings incl. Apple Health block
6. Optional 6th: the first-run sign-in sheet is honest but weak marketing —
   prefer keeping it out of the top 5; reviewers see it anyway and the
   review notes explain it.

Android — mirror shots 1–5 in the Material UI, plus the feature graphic.

Story order for both stores: Today → Trends+Insights → Nights → Night
detail → Settings.

## 5. Consistency rules

- Same fixture dataset for every shot (coherent numbers across screens).
- Light mode for the store set (matches the `#FAF9F5` brand surface); dark
  variants optional extras.
- Status bar: clean simulator status bar (9:41, full battery) — the capture
  script's simulator does this by default.
- No device frames or marketing text overlays for v1 — Apple accepts raw
  captures, and raw honesty matches the product voice. Revisit framed
  panels post-launch if conversion matters.
