# Product Strategy — synthesized from market research 2026-07-31

Two research passes (competitor audit + user-complaint mining, full reports in
Claude's session) converge on four unserved gaps that this app's architecture
already sits on top of:

## Positioning

**"Import everything. Merge it. Keep it forever. Analyze years, not weeks.
No subscription, no account, no cloud."**

The market: subscription-fatigued (Whoop upgrade-fee backlash, Oura's
crippled-without-membership app, Fitbit's pay-to-see-your-own-history),
fragmenting across devices with no merge layer, paywalling users' own history,
and offering ZERO self-hosted or web-first options. Web dashboards essentially
don't exist (only Whoop has one). Long-horizon (multi-year) analysis: nobody
does it — most apps paywall even 30-day history.

Instant time-to-value beats every phone app: an Apple Health export contains
YEARS of data on day one. A phone app starts from night zero; we start from
2019.

## What we deliberately do NOT compete on

Smart alarms, snore/audio detection, real-time tracking, sensor accuracy —
infeasible from exports, and the free floor (Apple/Samsung) covers them.
Coaching-content libraries — commodity. We read the sensors' output and win on
what happens after.

## Feature roadmap (ranked: complaint-frequency × feasibility)

Wave 1 — the thesis demo:
1. One-click wearable import: upload export.zip / Takeout file in the UI →
   full history appears. Dedup on re-import (by date+source). Schema grows
   additive columns: source, deep/rem/light/awake minutes, efficiency.
2. Multi-year trend explorer: range selector (30d / 90d / 1y / all), year
   heatmap, month-vs-month and season comparisons. Never paywalled, obviously.
3. Sleep debt (rolling 14-day vs personal need) + nap-inclusive accounting.
4. Stage visualization per night (stacked composition) — the data Apple buries.

Wave 2 — trust & calm (differentiators nobody ships):
5. Transparent score: show the arithmetic, decomposable ("why was last night
   a 62"), trivially correctable nights, no red-badge shaming; weekly-average-
   first framing (orthosomnia-aware).
6. Merged multi-source timeline with visible provenance + disagreement view
   (Watch says 6.2h, Fitbit says 7.1h — show both, let the user pick priority).
7. Personal correlations with honest statistics (tags: caffeine/alcohol/
   exercise → within-person effect sizes with sample-size caveats).

Wave 3 — reach:
8. Shift-worker mode (user-defined day boundary; sleep as sessions not nights).
9. Oura (token API) / Garmin / Whoop-CSV importers.
10. Optional local/BYO-key AI insights layer (market is heading to AI coaches;
    ours reads a richer archive and phones nothing home).

## Non-negotiable principles (from complaint data)

- History and trends are NEVER paywalled, time-limited, or cloud-gated.
- Export always: documented schema, CSV + JSON out, SQLite file is yours.
- No account required. Runs on your machine. Data never leaves it.
- Scores explain themselves. One bad night is never presented as failure.
