#!/usr/bin/env python3
"""Extract dep-calendar records from Electron localStorage leveldb."""
import json
import os
import re
import sys

LOG_PATH = os.path.join(
    os.environ.get("APPDATA", ""),
    "dep-calendar",
    "Local Storage",
    "leveldb",
    "000020.log",
)
OUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "admin_dep_calendar_seed.json",
)


def extract_records(raw: bytes) -> dict:
    idx = raw.rfind(b"dep-calendar-finance-v1")
    if idx < 0:
        raise RuntimeError("dep-calendar-finance-v1 key not found in leveldb log")
    chunk = raw[idx:]
    for start in (m.start() for m in re.finditer(rb"\{", chunk)):
        frag = chunk[start : start + 500_000]
        depth = 0
        end = 0
        for i, c in enumerate(frag):
            if c == 123:
                depth += 1
            elif c == 125:
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if not end:
            continue
        try:
            obj = json.loads(frag[:end].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(obj, dict) and any(re.match(r"20\d{2}-\d{2}-\d{2}", k) for k in obj):
            return obj
    raise RuntimeError("Could not parse records JSON from leveldb log")


def main() -> int:
    if not os.path.isfile(LOG_PATH):
        print(f"Missing: {LOG_PATH}", file=sys.stderr)
        return 1
    raw = open(LOG_PATH, "rb").read()
    records = extract_records(raw)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    payload = {"version": 1, "records": records}
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"Saved {len(records)} days -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
