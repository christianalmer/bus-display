#!/usr/bin/env python3
"""Generate bus_display/schedule.h (and schedule.json) from SF Muni GTFS.

The 511 StopMonitoring feed only lists actively tracked vehicles, so
untracked (usually "on time") buses are invisible to it. The firmware
merges these baked-in scheduled departures with live predictions,
matching trips by ID so a tracked bus never shows twice.

Supports multiple routes (one per display row). Stop/line/direction come
from gitignored bus_display/secrets.h (SECRET_STOP_CODE / _2, etc.) or
from env vars STOP_ID/ROUTE_ID/GTFS_DIR, STOP_ID_2/... in CI.

Usage:
    python3 tools/gen_schedule.py [--gtfs DIR]

Without --gtfs, downloads the current Muni GTFS from 511. Re-run +
reflash whenever Muni changes schedules (the feed covers ~5 weeks; the
firmware logs a warning and runs predictions-only once the table is
stale).
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
OUT_JSON = ROOT / "schedule.json"  # optional runtime download (SECRET_SCHEDULE_URL)


def _secret(name, env, required=True):
    if os.environ.get(env):
        return os.environ[env]
    m = re.search(rf'{name}\s+"([^"]*)"', SECRETS.read_text())
    if not m:
        if required:
            sys.exit(f"set {env} env var or add {name} to bus_display/secrets.h")
        return ""
    return m.group(1)


def routes_from_config():
    routes = [{
        "stop": _secret("SECRET_STOP_CODE", "STOP_ID"),
        "line": _secret("SECRET_LINE_REF", "ROUTE_ID"),
        "gtfs_dir": _secret("SECRET_GTFS_DIR", "GTFS_DIR", required=False),
    }]
    stop2 = _secret("SECRET_STOP_CODE_2", "STOP_ID_2", required=False)
    if stop2:
        routes.append({
            "stop": stop2,
            "line": _secret("SECRET_LINE_REF_2", "ROUTE_ID_2"),
            "gtfs_dir": _secret("SECRET_GTFS_DIR_2", "GTFS_DIR_2", required=False),
        })
    return routes


def api_key():
    if os.environ.get("API_KEY_511"):
        return os.environ["API_KEY_511"]
    m = re.search(r'SECRET_API_KEY_511\s+"([^"]+)"', SECRETS.read_text())
    if not m:
        sys.exit("set API_KEY_511 env var or fill bus_display/secrets.h")
    return m.group(1)


def download_gtfs():
    url = f"https://api.511.org/transit/datafeeds?api_key={api_key()}&operator_id=SF"
    print("downloading Muni GTFS from 511...")
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


def build_route_tables(gtfs, route, day_services, first, last):
    """Return (patterns, day_pattern) for one stop/line/direction."""
    trip_service = {}
    for r in read_csv(gtfs / "trips.txt"):
        if r["route_id"] != route["line"]:
            continue
        if route["gtfs_dir"] and r["direction_id"] != route["gtfs_dir"]:
            continue
        trip_service[r["trip_id"]] = r["service_id"]

    svc_deps = {}
    for r in read_csv(gtfs / "stop_times.txt"):
        if r["stop_id"] != route["stop"] or r["trip_id"] not in trip_service:
            continue
        trip32 = int(re.match(r"\d+", r["trip_id"]).group(0))
        svc_deps.setdefault(trip_service[r["trip_id"]], []).append(
            (hms_to_minutes(r["departure_time"]), trip32))
    for v in svc_deps.values():
        v.sort()

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
            idx = -1
        day_pattern.append(idx)
        d += datetime.timedelta(1)
    return patterns, day_pattern


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gtfs", type=Path, help="path to extracted GTFS directory")
    args = ap.parse_args()
    gtfs = args.gtfs or download_gtfs()
    routes = routes_from_config()

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

    # Trim history: GTFS validity can span months, but the firmware caps the
    # day table (RS_MAX_DAYS). Days before yesterday are useless on-device.
    yesterday = datetime.date.today() - datetime.timedelta(1)
    if first < yesterday:
        first = yesterday
    if (last - first).days + 1 > 70:
        print(f"NOTE: table spans {(last - first).days + 1} days; firmware keeps the first 70",
              file=sys.stderr)

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

    first_day_serial = days_from_civil(first.year, first.month, first.day)
    tables = [build_route_tables(gtfs, rt, day_services, first, last) for rt in routes]

    lines = [
        "// AUTO-GENERATED by tools/gen_schedule.py — do not edit by hand.",
        f"// {len(routes)} route(s); GTFS validity: {first} .. {last}.",
        "#ifndef SCHEDULE_H",
        "#define SCHEDULE_H",
        "#include <stdint.h>",
        "",
        "struct SchedDep {",
        "  uint16_t minutes;  // departure, minutes after local midnight",
        "  uint32_t trip;     // numeric prefix of the GTFS/511 trip id",
        "};",
        "",
        "struct SchedTable {",
        "  const SchedDep* const* patterns;",
        "  const uint16_t* patLen;",
        "  uint8_t patternCount;",
        "  long firstDay;      // day serial (days-from-civil) of dayPattern[0]",
        "  const int8_t* dayPattern;",
        "  int dayCount;",
        "};",
        "",
    ]
    for ri, (patterns, day_pattern) in enumerate(tables):
        total = sum(len(p) for p in patterns)
        print(f"route {routes[ri]['line']} @ {routes[ri]['stop']}: "
              f"{len(patterns)} patterns, {total} entries")
        if total == 0:
            sys.exit(f"ERROR: no departures found for route {routes[ri]['line']} "
                     f"at stop {routes[ri]['stop']} (wrong stop/direction?)")
        if len(patterns) > 8 or len(day_pattern) > 70 or max(len(p) for p in patterns) > 64:
            print("WARNING: exceeds firmware RS_MAX_* caps; device will truncate",
                  file=sys.stderr)
        for i, p in enumerate(patterns):
            rows = ", ".join(f"{{{m}, {t}UL}}" for m, t in p)
            lines.append(f"static const SchedDep SCHED_R{ri}_P{i}[] = {{ {rows} }};")
        lines += [
            f"static const SchedDep* const SCHED_R{ri}_PATTERNS[] = {{ "
            + ", ".join(f"SCHED_R{ri}_P{i}" for i in range(len(patterns))) + " };",
            f"static const uint16_t SCHED_R{ri}_PATTERN_LEN[] = {{ "
            + ", ".join(str(len(p)) for p in patterns) + " };",
            f"static const int8_t SCHED_R{ri}_DAY_PATTERN[] = {{ "
            + ", ".join(str(i) for i in day_pattern) + " };",
            "",
        ]
    lines += [
        f"static const int SCHED_NUM_ROUTES = {len(tables)};",
        "static const SchedTable SCHED_TABLES[] = {",
    ]
    for ri, (patterns, day_pattern) in enumerate(tables):
        lines.append(
            f"  {{ SCHED_R{ri}_PATTERNS, SCHED_R{ri}_PATTERN_LEN, {len(patterns)}, "
            f"{first_day_serial}L, SCHED_R{ri}_DAY_PATTERN, {len(day_pattern)} }},")
    lines += ["};", "", "#endif", ""]
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT} ({first}..{last})")

    # v2 JSON for the (optional) runtime download path
    OUT_JSON.write_text(json.dumps({
        "v": 2,
        # no "generated" timestamp: byte-identical output when unchanged
        "valid": f"{first}..{last}",
        "routes": [{
            "stop": routes[ri]["stop"],
            "line": routes[ri]["line"],
            "first_day": first_day_serial,
            "day_pattern": day_pattern,
            "patterns": [{"m": [m for m, _ in p], "t": [t for _, t in p]} for p in patterns],
        } for ri, (patterns, day_pattern) in enumerate(tables)],
    }, separators=(",", ":")) + "\n")
    print(f"wrote {OUT_JSON} ({OUT_JSON.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
