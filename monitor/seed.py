"""Make fake run logs: 30 days of runs for 8 pipelines, with 8 problems put in on purpose."""

import random
from datetime import datetime, timedelta

START = datetime(2026, 10, 24)   # day 0. Day 29 is 2026-11-22.
DAYS = 30
RETRY_HOURS = 4                  # a failed run is tried again 4 hours later

# What "normal" looks like for each fake pipeline: the hour of its first run,
# the usual rows read per run, the usual minutes per run, the usual share rejected.
PROFILES = {
    "orders_daily":       {"hour": 2, "rows": 12000, "minutes": 18, "reject": 0.004},
    "carrier_events":     {"hour": 0, "rows": 4000,  "minutes": 6,  "reject": 0.010},
    "inventory_snapshot": {"hour": 3, "rows": 25000, "minutes": 20, "reject": 0.002},
    "shipments_feed":     {"hour": 3, "rows": 8000,  "minutes": 12, "reject": 0.005},
    "customs_docs":       {"hour": 4, "rows": 1500,  "minutes": 5,  "reject": 0.020},
    "returns_daily":      {"hour": 2, "rows": 2200,  "minutes": 7,  "reject": 0.008},
    "billing_export":     {"hour": 5, "rows": 5000,  "minutes": 9,  "reject": 0.001},
    "route_plans":        {"hour": 1, "rows": 900,   "minutes": 4,  "reject": 0.003},
}

# The answer key: every problem we put in, the day it starts, and which checks
# (pipeline, check_name) should notice it. The tests use this list.
PROBLEMS = [
    {"name": "late run", "pipeline": "inventory_snapshot", "day": 9, "expect": ["freshness"]},
    {"name": "slow creep in run time", "pipeline": "inventory_snapshot", "day": 10,
     "expect": ["runtime_creep"]},
    {"name": "failed twice, then succeeded", "pipeline": "shipments_feed", "day": 12,
     "expect": ["failures", "freshness"]},
    {"name": "missed run", "pipeline": "customs_docs", "day": 16,
     "expect": ["missed_schedule", "freshness"]},
    {"name": "sudden row-count drop", "pipeline": "returns_daily", "day": 20,
     "expect": ["row_count"]},
    {"name": "duplicated load", "pipeline": "billing_export", "day": 23,
     "expect": ["reconciliation", "row_count"]},
    {"name": "dropped column (schema drift)", "pipeline": "route_plans", "day": 25,
     "expect": ["schema_drift"]},
    {"name": "rejects spike", "pipeline": "shipments_feed", "day": 28, "expect": ["rejects_spike"]},
]


# Set the row numbers of a run so they always add up: out = in - rejected.
def set_rows(run, rows_in, rejected):
    run.update(rows_in=rows_in, rows_rejected=rejected, rows_out=rows_in - rejected)


# One healthy run starting at `start`, with a little random wobble in every number.
def good_run(cfg, profile, start, rng):
    rows_in = round(profile["rows"] * rng.uniform(0.96, 1.04))
    rejected = round(rows_in * profile["reject"] * rng.uniform(0.7, 1.3))
    seconds = round(profile["minutes"] * 60 * rng.uniform(0.9, 1.1))
    run = {"pipeline": cfg["name"], "start": start, "end": start + timedelta(seconds=seconds),
           "status": "success", "columns": list(cfg["required_columns"]), "error": None}
    set_rows(run, rows_in, rejected)
    return run


# A run that failed after 3 minutes without moving any rows.
def failed_run(cfg, start):
    return {"pipeline": cfg["name"], "start": start, "end": start + timedelta(minutes=3),
            "status": "failed", "rows_in": 0, "rows_out": 0, "rows_rejected": 0, "columns": [],
            "error": "Connection timed out while reading the source"}


# Put one problem into an otherwise healthy run, if today is a problem day.
def inject(run, day):
    name = run["pipeline"]
    if name == "inventory_snapshot" and day >= 10:        # slow creep: +3% per day
        seconds = (run["end"] - run["start"]).total_seconds() * (1 + 0.03 * (day - 10))
        run["end"] = run["start"] + timedelta(seconds=round(seconds))
    if name == "returns_daily" and day == 20:             # the source sent 45% of the rows
        set_rows(run, round(run["rows_in"] * 0.45), round(run["rows_rejected"] * 0.45))
    if name == "billing_export" and day == 23:            # loaded twice: out is double in
        run["rows_out"] *= 2
    if name == "route_plans" and day >= 25:               # a column disappeared
        run["columns"] = [c for c in run["columns"] if c != "carrier_code"]
    if name == "shipments_feed" and day >= 28:            # 6% of rows rejected
        set_rows(run, run["rows_in"], round(run["rows_in"] * 0.06))


# The run(s) for one scheduled time. Usually one. A problem day can change that:
# no run at all (missed), a late start, or two failures before a good run.
def runs_for_slot(cfg, profile, start, rng):
    day = (start - START).days
    if (cfg["name"], day) == ("customs_docs", 16):
        return []
    if (cfg["name"], day) == ("inventory_snapshot", 9):
        start += timedelta(hours=10)
    if (cfg["name"], day) == ("shipments_feed", 12):
        retry = timedelta(hours=RETRY_HOURS)
        return [failed_run(cfg, start), failed_run(cfg, start + retry),
                good_run(cfg, profile, start + 2 * retry, rng)]
    run = good_run(cfg, profile, start, rng)
    inject(run, day)
    return [run]


# Build the whole fake run log for the pipelines in the config.
# The same seed number always gives the same data.
def build_runs(configs, seed=42):
    rng = random.Random(seed)
    runs = []
    for cfg in configs:
        profile = PROFILES[cfg["name"]]
        for slot in range(round(DAYS * 24 / cfg["interval_hours"])):
            start = START + timedelta(hours=profile["hour"] + slot * cfg["interval_hours"])
            runs.extend(runs_for_slot(cfg, profile, start, rng))
    return runs
