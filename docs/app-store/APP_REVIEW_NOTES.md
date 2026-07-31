# App Store Connect — App Review Notes

**Paste the block below into App Store Connect → App Review Information → Notes.**  
Update bracketed fields before submit. Keep the temporary demo server up for the whole review window.

---

## Paste this

```text
Sleep Tracker — App Review guide

SUMMARY
Sleep Tracker is a personal sleep history viewer. It reads Sleep Analysis
from Apple Health (HealthKit) with the user’s permission and shows multi-year
trends, sleep debt, and stage breakdown. There is no account, no subscription,
and no third-party analytics. An optional self-hosted server can be configured
in Settings for backup/web charts; it is not required to use the app.

HOW TO REVIEW (HealthKit-only path — preferred)
1. Install the build on a device or simulator that has Health data available.
2. Launch Sleep Tracker. Grant “Sleep” / Sleep Analysis read access when prompted.
3. Open Settings → Apple Health → Sync nights from Health (if shown), or wait
   for the automatic fetch after permission.
4. Today: stats, sleep debt, last-30-nights chart.
5. Trends: switch 30d / 90d / 1y / All — ranges are never paywalled.
6. Nights: open a night to see stage composition when Watch recorded stages.
7. Settings → About: version + privacy policy link.

OPTIONAL SERVER PATH (not required)
If you want to exercise the self-hosted connection:
  URL:  [https://REVIEW-DEMO.example]
  User: sleep
  Pass: [TEMPORARY_PASSWORD]
Settings → Your Server → enter the above → Test connection.
Demo credentials are valid only during this review; password will be rotated
after approval.

WHAT WE DO NOT DO
• No medical diagnosis, treatment claims, or clinical decision support.
• No write access to HealthKit (read sleep analysis only).
• No forced account, IAP, ads, or tracking (ATT not used).
• No central cloud that we operate for user nights by default.

CONTACT
[YOUR NAME] — [YOUR EMAIL] — [PHONE optional]
```

---

## Export compliance (usually)

When ASC asks about encryption:

- Uses HTTPS only (standard TLS) to the optional user-configured server and system networking.
- Typical answer: **Yes, uses encryption** → **exempt** (HTTPS only / standard encryption), unless you ship custom crypto.

Confirm against current ASC questionnaire wording at submit time.

---

## Sign-in required?

| Field | Value |
|-------|--------|
| Sign-in required? | **No** |
| Demo account | Only if you enable the optional review server above |

---

## Contact fields (fill in ASC form)

| Field | Value |
|-------|--------|
| First name | |
| Last name | |
| Phone | |
| Email | |

---

## After approval

1. Rotate or disable `[TEMPORARY_PASSWORD]` / tear down review demo host.  
2. Phased release 7 days recommended for first public build.  
3. Tag `ios-1.0.0` when git is initialized.
