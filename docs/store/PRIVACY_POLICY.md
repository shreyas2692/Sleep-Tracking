# Sleep Tracker Privacy Policy

**Effective date: August 3, 2026**

Sleep Tracker is a personal sleep journal for iPhone, Android, and the web. It
is built around one idea: your sleep history belongs to you. There is no
account with us, no advertising, and no analytics or tracking of any kind.

The apps connect to a Sleep Tracker server. That server is either one you run
yourself (Docker, Render, or your own machine) or one run by someone you
trust. Whoever operates that server controls the sleep data stored on it — in
the normal case, that is you.

## The short version

- Your sleep records live on your device and on the server you configure —
  nowhere else.
- We do not run a mandatory cloud, sell data, show ads, or use tracking or
  analytics SDKs.
- Apple Health access is read-only, sleep only, and always asks permission
  first.
- The optional AI weekly summary sends derived statistics — never your notes
  or raw records — to Anthropic, and only when the server operator has turned
  the feature on.
- You can delete any record, wipe everything, or walk away with a full export
  at any time.

## Data the apps handle

Sleep Tracker handles the sleep records you enter or import: dates, bedtimes,
wake times, duration, quality ratings, notes, data source (manual, Apple
Health, or Fitbit), sleep stages (deep, REM, light, awake), efficiency, sleep
goals, and the trends and statistics derived from them.

The apps also store your connection details:

- **iOS:** the server URL and username are kept in app preferences; the
  password is stored in the iOS Keychain.
- **Android:** the server URL and username are kept in app storage; the
  username and password are encrypted with a key held by the Android
  Keystore. Android backup is disabled for the app, so credentials are not
  copied into device backups.

## Apple Health (HealthKit) — iOS

With your permission, the iOS app reads **sleep analysis** samples from Apple
Health (for example, nights recorded by Apple Watch). It requests read access
only, for sleep-related data only — no other Health categories, and no
writing back to Health.

Health data is used solely to show your nights, stages, trends, and sleep
debt, and — if you choose — to sync those nights to the server you
configured. Health data is never sold, never shared with third parties, never
used for advertising or marketing, and never used to track you. You can
revoke access at any time in iOS Settings → Privacy & Security → Health.

## Health Connect — Android

The current Android app does **not** request Health Connect permissions and
does not read Health Connect data. If a future version adds Health Connect,
this policy and the Play Store data declarations will be updated before that
version ships.

## Network use

The apps send requests only to the server URL you configure, using the
credentials you provide. Release builds require HTTPS; debug builds may use
cleartext HTTP only for loopback and private-network development addresses.
The server supports optional password protection (HTTP Basic authentication),
and you choose that password.

## Optional AI weekly summary

The weekly summary is optional twice over: it exists only if the server
operator has configured an Anthropic API key, and the text is generated
server-side at most once per day per unchanged data.

When a summary is generated, the server sends **derived statistics** to
Anthropic — not your sleep journal. Specifically, the request contains: the
number of nights logged, weekly averages and computed insight sentences, the
overall duration trend, a bedtime-consistency score and social-jetlag figure,
your statistically best sleep duration ("sweet spot"), sleep-debt figures
(current debt, recent average, nightly need, and recovery estimate), and up
to five recent statistical outliers, each listing a date and that night's
duration or sleep-midpoint time.

**Your notes and individual raw records are never included.** No name, email,
account identifier, or device identifier is sent. Anthropic processes the
request under its own privacy terms. The Anthropic API key stays on the
server and is never sent to, or stored on, your phone. The generated summary
is cached in the server's database until your statistics change.

## What we do not do

- No advertising, and no advertising SDKs.
- No analytics or tracking SDKs, and no cross-app or cross-site tracking.
- No sale of personal data, ever.
- No account system operated by us, and no central cloud that your nights
  must pass through.

## Retention and deletion

- Sleep records remain on your configured server until deleted. You can
  delete individual records in the apps or on the web, or clear **all**
  records at once from the web app's settings.
- If you run the server yourself, deleting its database file (`sleep.db`)
  removes everything it stored.
- Server credentials remain on your device until you replace them, clear the
  app's storage, or uninstall the app. Uninstalling the app removes its local
  configuration.
- The server may cache one AI summary until the underlying statistics or the
  date change; clearing records clears the basis for it.
- Export is always available: CSV and JSON downloads, and the SQLite database
  itself if you self-host.

## Security

Use HTTPS, choose a strong and unique server password, keep your server and
devices updated, and limit who can reach the server. No system can guarantee
absolute security; self-hosting means the server's security posture is in the
operator's hands. Never place API keys or passwords in a mobile build or in
source control.

## Children's privacy

Sleep Tracker is not directed at children under 13, and we do not knowingly
collect personal information from children.

## Health disclaimer

Sleep Tracker is not a medical device. It does not provide medical advice,
diagnosis, or treatment, and it visualizes data your devices already
collected. Consult a qualified healthcare professional about medical
concerns.

## Changes and contact

Material changes will be published in this document with a new effective
date. Questions and privacy requests: open an issue at
<https://github.com/shreyas2692/Sleep-Tracking/issues>.

---

<!--
HOSTING NOTE (not part of the published policy — remove or keep as an HTML
comment; it will not render on GitHub Pages):

Both stores require a public HTTPS privacy-policy URL. Easiest path with this
repo: enable GitHub Pages (repo Settings → Pages → Deploy from branch →
main, /docs folder). This file then serves at
https://<username>.github.io/<repo>/store/PRIVACY_POLICY —
or copy it to docs/index.md for a cleaner root URL. Google Play requires the
URL to be public, non-geofenced, and not a PDF; a GitHub Pages markdown page
satisfies both stores. Put the same URL in App Store Connect (App Privacy →
Privacy Policy URL), in Play Console (App content → Privacy policy), and link
it from the iOS Settings screen (an in-app link is required by Apple
guideline 5.1.1).
-->
