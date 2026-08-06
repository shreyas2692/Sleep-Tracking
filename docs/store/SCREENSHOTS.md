# Screenshot Plan — both stores

Status updated 2026-08-06. **iOS is done:** all five shots were re-captured
2026-08-04 from the live app (preview fixtures, iPhone 16 Pro Max class) at
**1320×2868** — the exact 6.9" ASC slot size — including a real capture for
shot 04, which was previously a prohibited design mock. The upload set lives
in `docs/app-store/screenshots/` (mirrored as `ios/screenshots/store-*.png`).

**Android still has a gap:** the 1024×500 feature graphic exists
(`android/screenshots/feature-graphic.png`), but the five phone screenshots
in that folder are **empty placeholder files** — the emulator captures never
ran. That is the remaining asset work (§3–4).

<details>
<summary>Original audit (2026-08-03) — kept for history</summary>

Verdict at the time: every existing store capture was stale (pre-dating the
first-run sign-in screen and the Trends Insights/AI-summary section), shot
04 was a design mock that Apple prohibits, and zero Play assets existed.
</details>

---

## 1. Inventory — what exists today

### `docs/app-store/screenshots/` (the intended ASC upload set)

All 1290×2796 PNG (6.7-inch class), verified valid and distinct by
`reports/ios-release-review.md` §Screenshot Check.

All five re-captured 2026-08-04 at 1320×2868 (6.9" slot) from the live app
with preview fixtures — coherent numbers across shots, clean 9:41 status
bar, light mode.

| File | Content | Verdict |
|---|---|---|
| `01-today.png` | Dashboard: stats, sleep debt, 30-day bars | **Ready** |
| `02-trends.png` | Trends: range control + chart + Insights/AI-summary section | **Ready** |
| `03-nights.png` | Nights list, provenance + stage strips | **Ready** |
| `04-night-detail.png` | Night detail sheet: stage composition over Nights list | **Ready** — real capture (was a design mock before 2026-08-04) |
| `05-settings.png` | Server + Apple Health + principles | **Ready** |

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

### Android (`android/screenshots/`)

- `feature-graphic.png` — **Ready:** 1024×500 (wordmark + crescent motif,
  brand palette).
- `01-today.png` … `05-log-night.png` — **empty placeholder files (0 bytes);
  the real emulator captures are still TODO.**
- No 512×512 icon export yet (downscale `AppIcon-1024.png` when needed).

---

## 2. Apple requirements mapping

Recommendation: **iPhone-only** (project already sets
`TARGETED_DEVICE_FAMILY: 1`). Do not opt into iPad — it would demand a 13"
iPad set for an untested layout.

| ASC slot | Size | Need | Have |
|---|---|---|---|
| 6.9" (required) | 1320×2868 — ASC also accepts 1290×2796 in this slot | 3–5 shots (up to 10) | **5 current captures at exactly 1320×2868 — ready to upload** |
| 6.5"/6.7" (optional; auto-scaled from 6.9" if omitted) | 1284×2778 / 1290×2796 | 0 (let ASC scale) | n/a |
| iPad 13" | — | 0 (iPhone-only) | n/a |
| App icon | 1024×1024, no alpha | 1 | **Ready:** `docs/app-store/assets/AppIcon-1024.png` (verified valid, no alpha) |

Verify the 1290×2796 acceptance in ASC's uploader at submit time; if it
insists on 1320×2868, capture on an iPhone 16 Pro Max simulator instead
(the capture script takes a device argument).

## 3. Play requirements mapping

| Asset | Spec | Have |
|---|---|---|
| Phone screenshots | 2–8, PNG/JPG, each side 320–3840 px; for store-promotion eligibility ≥4 at ≥1080 px in 9:16 | **None yet** (placeholders in `android/screenshots/` are empty) — must show the Android app's actual Material UI, not iOS |
| Feature graphic | 1024×500 PNG/JPG, required for listing promotion | **Ready:** `android/screenshots/feature-graphic.png` |
| App icon | 512×512 PNG ≤1 MB | Downscale `AppIcon-1024.png` |
| Tablet shots | only if targeting tablets | Skip for v1 |

Capture Android shots on a Pixel emulator (e.g. Pixel 8, 1080×2400 —
within Play limits) via Android Studio or `adb exec-out screencap`.

## 4. Re-capture shot list

**iOS: done 2026-08-04** with
`./docs/app-store/scripts/capture-store-screenshots.sh` (uses
`-previewFixtures`, `-initialTab`, `-initialRange 1y`, `-showNightDetail`
launch args). Re-run only if the UI changes before submit:

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
