# Sleep Tracker Privacy Policy

> **Superseded (2026-08-03):** the canonical, publishable policy — unified
> across iOS, Android, and the web app, and the one to host for both store
> submissions — is [`docs/store/PRIVACY_POLICY.md`](docs/store/PRIVACY_POLICY.md).
> The text below is the earlier Android-focused draft, kept for reference.

Effective date: July 31, 2026

Sleep Tracker is a self-hosted sleep journal. The Android and iOS apps connect
to the Sleep Tracker server URL that you configure. The person or organization
operating that server controls the sleep data stored there.

## Data the app handles

Sleep Tracker handles the records you enter or import, including sleep dates,
times, duration, quality, notes, source, sleep stages, efficiency, goals, and
derived trends. The Android app also stores the configured server URL and HTTP
Basic username. The username and password are encrypted with a key held by the
Android Keystore; Android backup is disabled for the app.

The current Android app does not request Health Connect permissions and does
not read Health Connect data.

## Network use

The mobile app sends requests to the server URL you choose. Release builds
require HTTPS. Debug builds can use cleartext HTTP only for loopback and
private-network development addresses.

Weekly AI summaries are optional and run only when you request one. If the
server operator enables this feature, the server sends aggregate statistics,
such as weekly averages, consistency, streak, and sleep debt, to Anthropic to
generate the summary. Notes and individual record contents are not included in
that request. Anthropic processes that request under its applicable privacy
terms. The Anthropic API credential remains on the server and is never sent to
the mobile app.

Sleep Tracker does not include advertising or sell personal data.

## Retention and deletion

Sleep records remain on the configured server until its operator deletes them.
You can delete individual records or clear all server records from the app.
Server credentials remain on the Android device until you replace them, clear
the app's storage, or uninstall the app. The server may cache an AI summary
until the underlying aggregate statistics or date changes.

## Security

No system can guarantee absolute security. Use HTTPS, choose a strong and
unique server password, keep the server and device updated, and limit access to
the server. Do not put provider credentials in a mobile build or source
control.

## Health disclaimer

Sleep Tracker is not a medical device and does not provide medical advice,
diagnosis, or treatment. Consult a qualified healthcare professional about
medical concerns.

## Changes and contact

Material changes will be published in this document with a new effective date.
Questions and privacy requests can be opened at
<https://github.com/shreyas2692/Sleep-Tracking/issues>.
