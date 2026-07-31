#!/usr/bin/env bash
# Capture App Store screenshots from the iOS Simulator with fixture data.
#
# Prerequisites:
#   - Xcode license accepted:  sudo xcodebuild -license accept
#   - iPhone 15/16 Pro Max simulator available
#
# Usage (from repo root):
#   ./docs/app-store/scripts/capture-store-screenshots.sh
#   ./docs/app-store/scripts/capture-store-screenshots.sh "iPhone 16 Pro Max"

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
IOS="$ROOT/ios"
OUT="$ROOT/docs/app-store/screenshots"
DERIVED="${DERIVED_DATA:-/tmp/SleepTrackerDerived}"
DEVICE_NAME="${1:-iPhone 15 Pro Max}"
BUNDLE_ID="local.sleeptracker.app"

mkdir -p "$OUT"

if ! xcodebuild -version >/dev/null 2>&1; then
  echo "error: xcodebuild not usable. Run: sudo xcodebuild -license accept" >&2
  exit 1
fi

UDID="$(xcrun simctl list devices available | awk -v n="$DEVICE_NAME" '
  $0 ~ n && $0 ~ /\([A-F0-9-]{36}\)/ {
    if (match($0, /\([A-F0-9-]{36}\)/)) {
      id=substr($0, RSTART+1, RLENGTH-2)
      print id
      exit
    }
  }')"

if [[ -z "${UDID:-}" ]]; then
  echo "error: no available simulator matching '$DEVICE_NAME'" >&2
  xcrun simctl list devices available | grep -i iphone || true
  exit 1
fi

echo "Using $DEVICE_NAME ($UDID)"
xcrun simctl boot "$UDID" 2>/dev/null || true
open -a Simulator --args -CurrentDeviceUDID "$UDID" 2>/dev/null || true

echo "Building…"
cd "$IOS"
xcodebuild -scheme "Sleep Tracker" \
  -destination "platform=iOS Simulator,id=$UDID" \
  -configuration Debug \
  -derivedDataPath "$DERIVED" \
  CODE_SIGNING_ALLOWED=NO \
  build

APP="$DERIVED/Build/Products/Debug-iphonesimulator/Sleep Tracker.app"
test -d "$APP"

xcrun simctl uninstall "$UDID" "$BUNDLE_ID" 2>/dev/null || true
xcrun simctl install "$UDID" "$APP"

shot() {
  local name="$1"; shift
  echo "→ $name  ($*)"
  xcrun simctl terminate "$UDID" "$BUNDLE_ID" 2>/dev/null || true
  xcrun simctl launch "$UDID" "$BUNDLE_ID" "$@"
  sleep 2.8
  xcrun simctl io "$UDID" screenshot "$OUT/${name}.png"
  sips -g pixelWidth -g pixelHeight "$OUT/${name}.png" | paste - - || true
}

shot 01-today -previewFixtures -initialTab today
shot 02-trends -previewFixtures -initialTab trends -initialRange 1y
shot 03-nights -previewFixtures -initialTab nights
shot 04-night-detail -previewFixtures -initialTab nights -showNightDetail
shot 05-settings -previewFixtures -initialTab settings

# Mirror into ios/screenshots for the iOS agent
mkdir -p "$IOS/screenshots"
for f in 01-today 02-trends 03-nights 04-night-detail 05-settings; do
  cp "$OUT/${f}.png" "$IOS/screenshots/store-${f}.png"
done

echo
echo "Done. Store set:"
ls -la "$OUT"/*.png
echo
echo "Upload 01–05 to App Store Connect (6.7\" slot). Prefer re-running this"
echo "script after accepting the Xcode license so 04 is a real app capture."
