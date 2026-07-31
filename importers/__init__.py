"""File-based importers for wearable sleep exports (parsing only, no DB/Flask).

Each parser turns a vendor export file into a list of normalized night
records, one dict per calendar night, sorted ascending by date:

    {
        "date": "YYYY-MM-DD",      # the wake-up date
        "bedtime": "HH:MM",        # local time as recorded
        "wake": "HH:MM",           # local time as recorded
        "source": "apple_health" | "fitbit",
        "stages": {                # int minutes, or None if no stage data
            "deep": int,
            "rem": int,
            "light": int,
            "awake": int,
        },
        "efficiency": float | None,
        "notes": str,              # short human summary, e.g.
                                   # "Imported from Apple Health (3h12m deep, 1h45m REM)"
    }

Parsers:

- ``parse_apple_health(file_or_path)`` -- Apple Health ``export.xml`` or the
  ``export.zip`` that contains it.
- ``parse_fitbit_takeout(file_or_path)`` -- Fitbit Google Takeout
  ``sleep-YYYY-MM-DD.json`` file, a zip of such files, or an already-decoded
  list of sleep-log dicts.

Both raise ``ValueError`` when the input contains no usable sleep data;
individually malformed records/logs are skipped silently.
"""

from importers.apple_health import parse_apple_health
from importers.fitbit import parse_fitbit_takeout

__all__ = ["parse_apple_health", "parse_fitbit_takeout"]
