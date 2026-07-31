# Sleep Tracker — iOS

Native SwiftUI client for the **same** self-hosted Sleep Tracker server that
powers the web app. The phone is not a separate product: history still lives
on your server (Render or Docker). HealthKit is the on-device bridge from
Apple Watch.

```
iPhone app  ──HTTPS──►  https://sleep-tracker-n4cs.onrender.com  (or local Docker)
   │                              │
   └── HealthKit (Watch sleep) ──┘  POST /api/ingest
```

## Requirements

- macOS with **Xcode 15+** (project targets **iOS 17**)
- [XcodeGen](https://github.com/yonaskolb/XcodeGen) (`brew install xcodegen`)
- Your server password (`SLEEP_PASSWORD` from Render or Docker)

## Open & run

```bash
cd ios
xcodegen generate
open "Sleep Tracker.xcodeproj"
```

In Xcode:

1. Select an **iPhone simulator** (or your device).
2. You may need to set your **Team** under Signing (bundle id is
   `local.sleeptracker.app` — change it for a real device/App Store).
3. Press **Run** (⌘R).

### First launch

A **Connect** sheet opens:

| Field | Value |
|--------|--------|
| URL | `https://sleep-tracker-n4cs.onrender.com` (pre-filled) |
| Username | `sleep` |
| Password | your Render `SLEEP_PASSWORD` |

Tap **Connect & save**. Free-tier Render can take up to ~60s if the service
was sleeping.

Or in **Settings → Fill cloud server (Render)** then **Test connection**.

### Local server instead

1. Run Docker on your Mac (`docs/DEPLOY.md`).
2. In the Connect sheet, tap **Use local Docker** (`http://127.0.0.1:8080`).
3. Simulator can reach the Mac host on that URL; a physical phone needs your
   Mac’s LAN IP.

## What each tab does

| Tab | Role |
|-----|------|
| **Today** | Stats, sleep debt, last 30 nights chart |
| **Trends** | 30d / 90d / 1y / all series from the server |
| **Nights** | List, detail, manual add/edit/delete |
| **Settings** | Server credentials + Apple Health sync |

## Apple Health

On a **real iPhone** with Watch sleep data:

1. Settings → **Sync from Apple Health** → allow Sleep read.
2. **Send N new nights to server** → `POST /api/ingest` as `apple_health`.

Simulator usually has no Health sleep samples; server data still works.

## Screenshots & App Store

See [`../docs/app-store/`](../docs/app-store/) for plan, mockups, and store
screenshot set. Capture script:

```bash
../docs/app-store/scripts/capture-store-screenshots.sh
```

## Tests

```bash
# From ios/ after xcodegen
xcodebuild -scheme "Sleep Tracker" \
  -destination 'platform=iOS Simulator,name=iPhone 15' \
  test
```

Unit coverage today: API decoding + night clustering (mirrors the Python
Apple Health importer).

## Architecture (short)

| File | Role |
|------|------|
| `Sources/Networking/APIClient.swift` | REST client + Basic Auth |
| `Sources/Store/SleepStore.swift` | App state + disk cache |
| `Sources/Health/*` | HealthKit + night clustering |
| `Sources/Views/*` | SwiftUI tabs |
| `project.yml` | XcodeGen project definition |

Web remains source of truth. This app is the native shell.
