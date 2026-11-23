"""Shared test helpers: tiny hand-made runs and pipeline settings."""

from datetime import datetime, timedelta

NOON = datetime(2026, 3, 10, 12, 0)   # the moment most tests judge ("as of")
COLUMNS = ["order_id", "amount"]


# Pipeline settings that pass validation. Pass keyword arguments to change fields.
def make_cfg(**changes):
    cfg = {"name": "p1", "owner": "team-a", "interval_hours": 24, "freshness_hours": 30,
           "band_percent": 30, "required_columns": list(COLUMNS)}
    cfg.update(changes)
    return cfg


# One hand-made run. By default it is a good run of 10 minutes whose numbers add up.
def make_run(start, status="success", rows_out=1000, rejected=0, rows_in=None,
             minutes=10, columns=None, error=None):
    failed = status == "failed"
    return {"pipeline": "p1", "start": start, "end": start + timedelta(minutes=minutes),
            "status": status,
            "rows_in": rows_in if rows_in is not None else (0 if failed else rows_out + rejected),
            "rows_out": 0 if failed else rows_out, "rows_rejected": rejected,
            "columns": [] if failed else (columns if columns is not None else list(COLUMNS)),
            "error": error or ("boom" if failed else None)}


# A daily history, oldest first, one run per value in `rows_out_list`.
# The newest run starts 2 hours before NOON, the one before it 24 hours earlier, and so on.
def daily_runs(rows_out_list, **changes):
    count = len(rows_out_list)
    return [make_run(NOON - timedelta(hours=2 + 24 * (count - 1 - i)), rows_out=rows, **changes)
            for i, rows in enumerate(rows_out_list)]


# A daily history of `count` good runs, all with the same row count.
def steady_runs(count, rows_out=1000, **changes):
    return daily_runs([rows_out] * count, **changes)


# The check names found in a list of findings.
def names(findings):
    return [f["check_name"] for f in findings]
