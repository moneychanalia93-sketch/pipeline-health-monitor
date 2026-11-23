"""The health checks. Every check is one small function with the same shape:

    check(cfg, runs, as_of) -> list of findings   (an empty list means healthy)

`cfg` is one pipeline from pipelines.json. `runs` is that pipeline's run history,
oldest first. `as_of` is the moment we are judging. Nothing here touches the database,
so every check can be tested with a few hand-made runs.
"""

import statistics

HISTORY_RUNS = 14      # how many earlier good runs define "normal"
MIN_HISTORY = 5        # fewer earlier runs than this: we do not guess
FAILURE_WINDOW = 10    # the failure rate looks at this many latest runs
MISSED_GRACE = 1.5     # a run may be this many intervals late before we call it missed
MAD_FACTOR = 6         # the MAD rule: how many "usual wobbles" away counts as odd
MIN_WOBBLE = 0.02      # the usual wobble is never smaller than 2% of the median
CREEP_RUNS = 30        # creep: look at the last 30 good runs. The oldest 7 are the
BASELINE_RUNS = 7      # baseline, the newest 5 are "recent". Fewer than 12 runs
RECENT_RUNS = 5        # in total: we do not guess.
CREEP_WARNING = 1.3    # recent run time is 1.3x the baseline
CREEP_CRITICAL = 1.6
REJECT_FLOOR = 0.02    # never alert on a reject rate below 2%
REJECT_CRITICAL = 0.10


# Build one finding. `check_name` says which check found it, `runbook` is the
# tiny "check this first" line for the person who gets the alert.
def make_finding(cfg, check_name, severity, message, runbook):
    return {"pipeline": cfg["name"], "check_name": check_name, "severity": severity,
            "message": message, "runbook": runbook}


# Only the runs that finished with status "success".
def successes(runs):
    return [run for run in runs if run["status"] == "success"]


# How many hours lie between two datetimes.
def hours_between(later, earlier):
    return (later - earlier).total_seconds() / 3600


# FRESHNESS: is the newest good data too old?
# Looks at the end of the last SUCCESSFUL run. Older than the limit = warning,
# older than twice the limit = critical.
def check_freshness(cfg, runs, as_of):
    done = successes(runs)
    if not done:
        return [make_finding(cfg, "freshness", "warning", "no successful run on record yet",
                             "Check the pipeline is switched on and has run at least once.")]
    age = hours_between(as_of, done[-1]["end"])
    limit = cfg["freshness_hours"]
    if age <= limit:
        return []
    return [make_finding(cfg, "freshness", "critical" if age > 2 * limit else "warning",
                         f"last success was {age:.0f}h ago (limit {limit}h)",
                         "Open the latest run and read its error. If none ran, check the scheduler.")]


# MISSED SCHEDULE: did a run even start when it should have?
# Looks at the start of the last run of ANY status. More than 1.5 intervals
# of silence = warning, more than 2.5 intervals = critical.
def check_missed_schedule(cfg, runs, as_of):
    if not runs:
        return []
    gap = hours_between(as_of, runs[-1]["start"])
    interval = cfg["interval_hours"]
    if gap <= interval * MISSED_GRACE:
        return []
    return [make_finding(cfg, "missed_schedule", "critical" if gap > interval * 2.5 else "warning",
                         f"no run has started for {gap:.0f}h (expected one every {interval}h)",
                         "Check the scheduler: was the trigger disabled, or did it fail to fire?")]


# FAILURES: two ways to see a sick pipeline.
#   - consecutive failures: the newest runs all failed (2 = warning, 3+ = critical)
#   - failure rate: 30% or more of the last 10 runs failed (warning)
# One failed run alone is normal (a retry often fixes it), so it raises nothing.
def check_failures(cfg, runs, as_of):
    streak = 0
    for run in reversed(runs):
        if run["status"] != "failed":
            break
        streak += 1
    recent = runs[-FAILURE_WINDOW:]
    failed = sum(run["status"] == "failed" for run in recent)
    if streak >= 2:
        message = f"{streak} failed runs in a row. Last error: {runs[-1]['error']}"
    elif len(recent) >= MIN_HISTORY and failed / len(recent) >= 0.3:
        message = f"{failed} of the last {len(recent)} runs failed"
    else:
        return []
    return [make_finding(cfg, "failures", "critical" if streak >= 3 else "warning", message,
                         "Read the newest error first. Then check if the source or target was down.")]


# ROW COUNT: is the newest run's size normal for this pipeline?
# "Normal" = the median rows_out of the 14 good runs before it. Two rules:
#   percent band: more than band_percent away from the median       -> critical
#   MAD rule:     more than 6 "usual wobbles" away from the median  -> warning
# The usual wobble (MAD) is the median of how far each past run was from the median.
# shortcut: a median of 0 is skipped (nothing normal to compare); handle it if a
# pipeline is ever expected to be empty.
def check_row_count(cfg, runs, as_of):
    done = successes(runs)
    if len(done) <= MIN_HISTORY:
        return []
    latest = done[-1]["rows_out"]
    history = [run["rows_out"] for run in done[-1 - HISTORY_RUNS:-1]]
    middle = statistics.median(history)
    if middle == 0:
        return []
    wobble = statistics.median([abs(x - middle) for x in history])
    gap = abs(latest - middle)
    outside_band = gap > middle * cfg["band_percent"] / 100
    if not (outside_band or gap > MAD_FACTOR * max(wobble, middle * MIN_WOBBLE)):
        return []
    reason = (f"outside the {cfg['band_percent']:g}% band" if outside_band
              else "far outside this pipeline's usual wobble (MAD rule)")
    runbook = ("Look for a duplicated load: the same file or batch loaded twice." if latest > middle
               else "Did the source send fewer rows? Compare rows_in with earlier runs.")
    return [make_finding(cfg, "row_count", "critical" if outside_band else "warning",
                         f"rows_out is {latest:,}, the recent median is {middle:,.0f} "
                         f"({(latest - middle) / middle * 100:+.0f}%): {reason}", runbook)]


# RECONCILIATION: do the numbers add up? Rows in must equal rows out plus rows rejected.
# Checked on the newest good run. A difference means rows appeared or vanished.
def check_reconciliation(cfg, runs, as_of):
    done = successes(runs)
    if not done:
        return []
    last = done[-1]
    total = last["rows_out"] + last["rows_rejected"]
    difference = total - last["rows_in"]
    if difference == 0:
        return []
    runbook = ("Rows were added: look for a duplicated load or a join that multiplies rows."
               if difference > 0 else "Rows went missing: check filters and the load step.")
    return [make_finding(cfg, "reconciliation", "critical",
                         f"rows_in is {last['rows_in']:,} but rows_out + rejected is {total:,} "
                         f"(difference {difference:+,})", runbook)]


# SCHEMA DRIFT: do the columns seen match the columns we require?
# A required column that is missing = critical. A new unexpected column = info only.
def check_schema_drift(cfg, runs, as_of):
    done = successes(runs)
    if not done:
        return []
    seen = done[-1]["columns"]
    missing = [c for c in cfg["required_columns"] if c not in seen]
    extra = [c for c in seen if c not in cfg["required_columns"]]
    if missing:
        return [make_finding(cfg, "schema_drift", "critical",
                             f"required column(s) missing: {', '.join(missing)}",
                             "Ask the source owner what changed. Compare with the last good extract.")]
    if extra:
        return [make_finding(cfg, "schema_drift", "info",
                             f"new column(s) appeared: {', '.join(extra)}",
                             "Decide: add it to required_columns, or ignore it.")]
    return []


# RUN-TIME CREEP: is the pipeline slowly getting slower?
# Baseline = average minutes of the oldest 7 of the last 30 good runs.
# Recent = average minutes of the newest 5. Recent 1.3x baseline = warning, 1.6x = critical.
def check_runtime_creep(cfg, runs, as_of):
    done = successes(runs)[-CREEP_RUNS:]
    if len(done) < BASELINE_RUNS + RECENT_RUNS:
        return []
    minutes = [hours_between(run["end"], run["start"]) * 60 for run in done]
    baseline = statistics.mean(minutes[:BASELINE_RUNS])
    recent = statistics.mean(minutes[-RECENT_RUNS:])
    if baseline <= 0 or recent < baseline * CREEP_WARNING:
        return []
    severity = "critical" if recent >= baseline * CREEP_CRITICAL else "warning"
    return [make_finding(cfg, "runtime_creep", severity,
                         f"recent runs take {recent:.0f} min, {recent / baseline:.1f}x the baseline "
                         f"of {baseline:.0f} min",
                         "Compare data volume and the slowest step of an old run with a new one.")]


# The share of incoming rows that were rejected, for one run (0 if nothing came in).
def reject_rate(run):
    return run["rows_rejected"] / run["rows_in"] if run["rows_in"] else 0.0


# REJECTS SPIKE: are many more rows being thrown away than usual?
# Normal = median reject rate of the 14 good runs before the newest. Alert when
# the newest rate is more than 3x normal and above 2%. At 10% or more it is critical.
def check_rejects_spike(cfg, runs, as_of):
    done = successes(runs)
    if len(done) <= MIN_HISTORY:
        return []
    normal = statistics.median([reject_rate(r) for r in done[-1 - HISTORY_RUNS:-1]])
    latest = reject_rate(done[-1])
    if latest <= max(3 * normal, REJECT_FLOOR):
        return []
    severity = "critical" if latest >= REJECT_CRITICAL else "warning"
    return [make_finding(cfg, "rejects_spike", severity,
                         f"{latest:.1%} of incoming rows were rejected (normal is {normal:.1%})",
                         "Look at a sample of rejected rows: is a format or value new?")]


CHECKS = [check_freshness, check_missed_schedule, check_failures, check_row_count,
          check_reconciliation, check_schema_drift, check_runtime_creep, check_rejects_spike]


# Run every check on one pipeline and collect all findings.
def run_checks(cfg, runs, as_of):
    findings = []
    for check in CHECKS:
        findings.extend(check(cfg, runs, as_of))
    return findings
