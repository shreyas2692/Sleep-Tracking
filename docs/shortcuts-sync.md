# JSON Sync With Apple Shortcuts

`POST /api/ingest` accepts sleep nights from Apple Shortcuts and other local
automation. It uses the same `(date, source)` identity as wearable file imports,
so sending a night again updates its existing row instead of creating a
duplicate.

## Before You Start

Set a production password before accepting requests from another device:

```sh
export SLEEP_USERNAME="sleep"
export SLEEP_PASSWORD="replace-with-a-strong-password"
```

Use HTTPS when the request crosses a network. HTTP Basic authentication
protects access, but it does not encrypt credentials or sleep data. The
`/healthz` endpoint remains public.

## Request Format

Send `Content-Type: application/json` with one object or an array of at most
100 objects. The complete body must be no larger than 1 MiB.

```json
{
  "date": "2026-07-30",
  "bedtime": "23:00",
  "wake": "07:00",
  "source": "apple_health",
  "quality": 4,
  "notes": "Synced by Shortcuts",
  "stages": {
    "deep": 60,
    "rem": 90,
    "light": 300,
    "awake": 30
  },
  "efficiency": 92.5
}
```

Fields:

| Field | Required | Rules |
| --- | --- | --- |
| `date` | Yes | Wake date in zero-padded `YYYY-MM-DD`; future dates are rejected. |
| `bedtime` | Yes | Local start time in zero-padded 24-hour `HH:MM`. |
| `wake` | Yes | Local end time in zero-padded 24-hour `HH:MM`. Overnight wraparound is automatic. |
| `source` | No | `apple_health` (default) or `fitbit`. |
| `quality` | No | Integer 1 through 5. When omitted or `null`, it is derived from stages, or defaults to neutral 3 without stages. |
| `notes` | No | String of at most 500 characters. |
| `stages` | No | Either `null` or exactly `deep`, `rem`, `light`, and `awake`, each a nonnegative integer number of minutes. Their total must match the bedtime-to-wake interval within one minute. |
| `efficiency` | No | Finite number from 0 through 100. |

Do not send `source: "manual"` through this endpoint. Manual entries use the
form UI and have different identity semantics.

## Apple Shortcuts Setup

Create a shortcut named **Sync Sleep Night**:

1. Add **Format Date** for the sleep end date. Choose **Custom** and enter
   `yyyy-MM-dd`. Name the result `Wake Date`.
2. Add **Format Date** for the sleep start time. Choose **Custom** and enter
   `HH:mm`. Name the result `Bedtime`.
3. Add **Format Date** for the sleep end time. Choose **Custom** and enter
   `HH:mm`. Name the result `Wake`.
4. Add a **Dictionary** with `date`, `bedtime`, `wake`, `source`, and any
   optional fields from the table above. Set `source` to `apple_health`.
5. If `SLEEP_PASSWORD` is configured, add a **Text** action containing
   `sleep:replace-with-your-password`, then a **Base64 Encode** action. Keep the
   credential in your private shortcut, not in a shared shortcut or screenshot.
6. Add **Get Contents of URL** with your `/api/ingest` URL. Set **Method** to
   `POST`, **Request Body** to `JSON`, and use the Dictionary from step 4.
7. Add the header `Content-Type: application/json`. With authentication
   enabled, also add `Authorization: Basic ` followed by the Base64 result from
   step 5.
8. Read the returned dictionary. Treat `ok` as success and show or log any
   entries in `errors`.

For a batch shortcut, build a **List** of Dictionaries and use that List as the
JSON request body. Split larger histories into batches of 100.

## curl Examples

Send one night to a password-protected instance:

```sh
curl --fail-with-body \
  --user 'sleep:replace-with-your-password' \
  --header 'Content-Type: application/json' \
  --data '{
    "date": "2026-07-30",
    "bedtime": "23:00",
    "wake": "07:00",
    "source": "apple_health",
    "notes": "Synced by curl"
  }' \
  'https://sleep.example.com/api/ingest'
```

Send a batch:

```sh
curl --fail-with-body \
  --user 'sleep:replace-with-your-password' \
  --header 'Content-Type: application/json' \
  --data '[
    {
      "date": "2026-07-29",
      "bedtime": "22:45",
      "wake": "06:45",
      "source": "apple_health"
    },
    {
      "date": "2026-07-30",
      "bedtime": "23:00",
      "wake": "07:00",
      "source": "apple_health"
    }
  ]' \
  'https://sleep.example.com/api/ingest'
```

For a loopback-only instance with no `SLEEP_PASSWORD`, omit `--user` and use
`http://127.0.0.1:5000/api/ingest`.

## Responses

A fully valid request returns HTTP 200:

```json
{
  "ok": true,
  "imported": 1,
  "replaced": 0,
  "skipped": 0,
  "stats": {}
}
```

A mixed array still applies valid records. It returns HTTP 200 with `skipped`
and indexed errors:

```json
{
  "ok": true,
  "imported": 1,
  "replaced": 0,
  "skipped": 1,
  "stats": {},
  "errors": [
    {
      "index": 1,
      "error": "Quality must be an integer from 1 to 5."
    }
  ]
}
```

If every item is invalid, nothing is written and the endpoint returns HTTP 400
with `ok: false`. Malformed JSON also returns 400, a body over 1 MiB returns
413, a non-JSON content type returns 415, and missing or incorrect configured
credentials return 401.
