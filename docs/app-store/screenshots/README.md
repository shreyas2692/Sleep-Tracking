# App Store screenshots (6.7")

All files are **1290 × 2796** (iPhone 15 Pro Max).

| # | File | Content |
|---|------|---------|
| 1 | `01-today.png` | Dashboard — stats, sleep debt, stage bars |
| 2 | `02-trends.png` | Trends — range control + chart |
| 3 | `03-nights.png` | Nights list — Watch provenance + stage strips |
| 4 | `04-night-detail.png` | Stage composition + quality math |
| 5 | `05-settings.png` | Optional server + Apple Health + principles |

Copies also live at `ios/screenshots/store-0*.png`.

Re-run the capture script after accepting the Xcode license so shot 04 is from the live app:

```bash
sudo xcodebuild -license accept
./docs/app-store/scripts/capture-store-screenshots.sh
```
