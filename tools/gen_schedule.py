#!/usr/bin/env python3
"""Generate bus_display/schedule.h from SF Muni GTFS.

The 511 StopMonitoring feed only lists actively tracked vehicles, so
untracked (usually "on time") buses are invisible to it. The firmware
merges these baked-in scheduled departures with live predictions,
matching trips by ID so a tracked bus never shows twice.

Usage:
    python3 tools/gen_schedule.py [--gtfs DIR]

Without --gtfs, downloads the current Muni GTFS from 511 (needs the API
key, read from bus_display/bus_display.ino). Re-run + reflash whenever
Muni changes schedules (the feed covers ~5 weeks; the firmware logs a
warning and runs predictions-only once the table is stale).
"""

import argparse
import csv
import datetime
import io
import json
import os
import re
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "bus_display" / "secrets.h"
OUT = ROOT / "bus_display" / "schedule.h"
OUT_JSON = ROOT / "schedule.json"  # fetched by the device at runtime

STOP_ID = "14189"
ROUTE_ID = "23"


def sketch_api_key():
    if os.environ.get("API_KEY_511"):  # CI: GitHub Actions secret
        return os.environ["API_KEY_511"]
    m = re.search(r'SECRET_API_KEY_511\s+"([^"]+)"', SECRETS.read_text())
    if not m:
        sys.exit("set API_KEY_511 env var or fill bus_display/secrets.h")
    return m.group(1)


def download_gtfs():
    url = f"https://api.511.org/transit/datafeeds?api_key={sketch_api_key()}&operator_id=SF"
    print(f"downloading Muni GTFS from 511...")
    data = urllib.request.urlopen(url, timeout=120).read()
    d = Path(tempfile.mkdtemp(prefix="sf_gtfs_"))
    zipfile.ZipFile(io.BytesIO(data)).extractall(d)
    print(f"extracted to {d} ({len(data)//1024} kB)")
    return d


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        yield from csv.DictReader(f)


def hms_to_minutes(hms):
    h, m, s = (int(x) for x in hms.split(":"))
    return h * 60 + m + (1 if s >= 30 else 0)


def days_from_civil(y, m, d):
    """Same algorithm as parseIso8601Utc in the firmware."""
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gtfs", type=Path, help="path to extracted GTFS directory")
    args = ap.parse_args()
    gtfs = args.gtfs or download_gtfs()

    # route trips -> service
    trip_service = {r["trip_id"]: r["service_id"]
                    for r in read_csv(gtfs / "trips.txt") if r["route_id"] == ROUTE_ID}

    # departures at our stop, keyed by service id
    svc_deps = {}
    for r in read_csv(gtfs / "stop_times.txt"):
        if r["stop_id"] != STOP_ID or r["trip_id"] not in trip_service:
            continue
        trip32 = int(re.match(r"\d+", r["trip_id"]).group(0))
        svc_deps.setdefault(trip_service[r["trip_id"]], []).append(
            (hms_to_minutes(r["departure_time"]), trip32))
    for v in svc_deps.values():
        v.sort()

    # per-date active services: calendar.txt (weekly) + calendar_dates.txt (exceptions)
    weekly = list(read_csv(gtfs / "calendar.txt"))
    exceptions = list(read_csv(gtfs / "calendar_dates.txt"))
    dates = set()
    for r in weekly:
        d0 = datetime.datetime.strptime(r["start_date"], "%Y%m%d").date()
        d1 = datetime.datetime.strptime(r["end_date"], "%Y%m%d").date()
        dates.update(d0 + datetime.timedelta(n) for n in range((d1 - d0).days + 1))
    for r in exceptions:
        dates.add(datetime.datetime.strptime(r["date"], "%Y%m%d").date())
    first, last = min(dates), max(dates)

    dows = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_services = {}
    d = first
    while d <= last:
        active = set()
        for r in weekly:
            if (r[dows[d.weekday()]] == "1"
                    and r["start_date"] <= d.strftime("%Y%m%d") <= r["end_date"]):
                active.add(r["service_id"])
        for r in exceptions:
            if r["date"] == d.strftime("%Y%m%d"):
                (active.add if r["exception_type"] == "1" else active.discard)(r["service_id"])
        day_services[d] = frozenset(active)
        d += datetime.timedelta(1)

    # dedupe identical daily departure lists into patterns
    patterns, day_pattern = [], []
    d = first
    while d <= last:
        deps = sorted(set(dep for s in day_services[d] for dep in svc_deps.get(s, [])))
        if deps in patterns:
            idx = patterns.index(deps)
        elif deps:
            patterns.append(deps)
            idx = len(patterns) - 1
        else:
            idx = -1  # no service data for this date
        day_pattern.append(idx)
        d += datetime.timedelta(1)

    total = sum(len(p) for p in patterns)
    lines = [
        "// AUTO-GENERATED by tools/gen_schedule.py — do not edit by hand.",
        f"// Muni route {ROUTE_ID} scheduled departures at stop {STOP_ID}.",
        f"// GTFS validity: {first} .. {last} ({len(patterns)} day patterns, {total} entries).",
        "#ifndef SCHEDULE_H",
        "#define SCHEDULE_H",
        "#include <stdint.h>",
        "",
        "struct SchedDep {",
        "  uint16_t minutes;  // departure, minutes after local midnight",
        "  uint32_t trip;     // numeric prefix of the GTFS/511 trip id",
        "};",
        "",
    ]
    for i, p in enumerate(patterns):
        rows = ", ".join(f"{{{m}, {t}UL}}" for m, t in p)
        lines.append(f"static const SchedDep SCHED_P{i}[] = {{ {rows} }};")
    lines += [
        "",
        "static const SchedDep* const SCHED_PATTERNS[] = { "
        + ", ".join(f"SCHED_P{i}" for i in range(len(patterns))) + " };",
        "static const uint16_t SCHED_PATTERN_LEN[] = { "
        + ", ".join(str(len(p)) for p in patterns) + " };",
        "",
        f"// day serial (days-from-civil, as in parseIso8601Utc) of {first}",
        f"static const long SCHED_FIRST_DAY = {days_from_civil(first.year, first.month, first.day)}L;",
        "static const int8_t SCHED_DAY_PATTERN[] = { "
        + ", ".join(str(i) for i in day_pattern) + " };",
        f"static const int SCHED_DAY_COUNT = {len(day_pattern)};",
        "",
        "#endif",
        "",
    ]
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT}: {len(patterns)} patterns, {len(day_pattern)} days "
          f"({first}..{last}), {total} entries")

    # firmware caps (RS_MAX_* in bus_display.ino)
    if len(patterns) > 8 or len(day_pattern) > 70 or max(len(p) for p in patterns) > 64:
        print("WARNING: exceeds firmware RS_MAX_* caps; device will truncate", file=sys.stderr)

    OUT_JSON.write_text(json.dumps({
        "v": 1,
        "generated": datetime.date.today().isoformat(),
        "stop": STOP_ID,
        "line": ROUTE_ID,
        "valid": f"{first}..{last}",
        "first_day": days_from_civil(first.year, first.month, first.day),
        "day_pattern": day_pattern,
        "patterns": [{"m": [m for m, _ in p], "t": [t for _, t in p]} for p in patterns],
    }, separators=(",", ":")) + "\n")
    print(f"wrote {OUT_JSON} ({OUT_JSON.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
