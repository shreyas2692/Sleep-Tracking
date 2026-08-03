#!/usr/bin/env bash
# Archive Sleep Tracker for App Store upload.
#
# One-time setup (see RELEASE.md):
#   cp Signing.xcconfig.example Signing.xcconfig   # fill in DEVELOPMENT_TEAM
#
# The script prefers Signing.xcconfig; without it, Xcode must already show a
# green Team under Signing & Capabilities.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v xcodegen >/dev/null && xcodegen generate

SIGNING_ARGS=()
if [[ -f Signing.xcconfig ]]; then
  SIGNING_ARGS=(-xcconfig Signing.xcconfig)
  echo "Using Signing.xcconfig"
else
  echo "No Signing.xcconfig found — relying on the team selected in Xcode."
  echo "(cp Signing.xcconfig.example Signing.xcconfig to make this repeatable.)"
fi

ARCHIVE=/tmp/SleepTracker.xcarchive
rm -rf "$ARCHIVE"
echo "Archiving Sleep Tracker for App Store..."
xcodebuild -project "Sleep Tracker.xcodeproj" \
  -scheme "Sleep Tracker" \
  -destination 'generic/platform=iOS' \
  -archivePath "$ARCHIVE" \
  -allowProvisioningUpdates \
  "${SIGNING_ARGS[@]+"${SIGNING_ARGS[@]}"}" \
  archive
echo ""
echo "Archive OK: $ARCHIVE"
echo "Opening Organizer — click Distribute App → App Store Connect → Upload"
open -a Xcode
osascript -e 'tell application "Xcode" to activate' 2>/dev/null || true
open "$ARCHIVE"
