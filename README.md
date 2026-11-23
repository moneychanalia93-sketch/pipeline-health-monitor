# pipeline-health-monitor

A small command-line tool that watches a set of data pipelines and tells you which ones are unhealthy and why.

It reads a run log (one row per pipeline run) and a settings file (`pipelines.json`), runs eight checks, and prints a health table. It can also write a single self-contained HTML health page. The pipelines and their runs are **fake**: a seed command generates 30 days of runs with eight problems put in on purpose, so you can see each check catch its problem.

It uses only the Python standard library (`sqlite3`, `json`, `statistics`, `argparse`, `html`, `unittest`). There is nothing to install. Python 3.13 was used; any recent Python 3 should work.

> Built with AI assistance (Kiro). I designed the rules, reviewed the code, and ran the tests.
> This is a learning project with fake data. It has not been used in production.

## What it does

- Reads a **run log** (a SQLite table): run id, pipeline, start, end, status, rows in, rows out, rows rejected, columns seen, error message.
- Reads **pipelines.json**: for each pipeline, its owner, how often it should run, how fresh its data must be, how far its row count may move, and which columns it must have.
- Runs eight **checks** (table below). Each finding has a severity (`info`, `warning`, `critical`), a plain-English message, and a tiny "check this first" runbook line.
- Keeps an **alerts table**. An alert that is already open is not raised again on the next check. It closes by itself when the problem goes away.
- Prints a **health table** in the terminal and can write an **HTML page** with a green / amber / red status per pipeline, a small row-count sparkline, and the list of open alerts.
- **Replays** the checks as of earlier times, so you can watch the problems appear and disappear.

## Run it (3 commands)

Run these from the project folder. If `python` is not on your PATH, use `py` or the full path to `python.exe`.

```powershell
python -m monitor seed                      # creates runs.db with 30 fake days of runs
python -m monitor check --html health.html  # prints the health table, writes health.html
python -m unittest discover -s tests -t .   # runs the tests
```

Real output of the first command:

```
Wrote 331 runs for 8 pipelines to runs.db
Problems put in on purpose:
  2026-11-02  inventory_snapshot late run
  2026-11-03  inventory_snapshot slow creep in run time
  2026-11-05  shipments_feed     failed twice, then succeeded
  2026-11-09  customs_docs       missed run
  2026-11-13  returns_daily      sudden row-count drop
  2026-11-16  billing_export     duplicated load
  2026-11-18  route_plans        dropped column (schema drift)
  2026-11-21  shipments_feed     rejects spike
```

Real output of the second command (the check is judged "as of" the end of the log, 2026-11-22):

```
Pipeline health as of 2026-11-22 18:06:03
8 pipelines: 5 green, 2 amber, 1 red

PIPELINE            STATUS  OWNER           LAST OK    ROWS OUT  ALERTS
orders_daily        GREEN   orders-team     16h ago      11,973  0
carrier_events      GREEN   events-team     0h ago        3,954  0
inventory_snapshot  AMBER   inventory-team  15h ago      25,156  1
shipments_feed      AMBER   shipping-team   15h ago       7,349  1
customs_docs        GREEN   trade-team      14h ago       1,477  0
returns_daily       GREEN   returns-team    16h ago       2,184  0
billing_export      GREEN   finance-team    13h ago       4,875  0
route_plans         RED     routing-team    17h ago         909  1

This check: 3 new, 0 still open, 0 closed

Open alerts (3):
  [CRITICAL] route_plans / schema_drift  (open since 2026-11-22 18:06:03, seen 1x)
      required column(s) missing: carrier_code
      Check first: Ask the source owner what changed. Compare with the last good extract.
  [WARNING] inventory_snapshot / runtime_creep  (open since 2026-11-22 18:06:03, seen 1x)
      recent runs take 28 min, 1.4x the baseline of 20 min
      Check first: Compare data volume and the slowest step of an old run with a new one.
  [WARNING] shipments_feed / rejects_spike  (open since 2026-11-22 18:06:03, seen 1x)
      6.0% of incoming rows were rejected (normal is 0.5%)
      Check first: Look at a sample of rejected rows: is a format or value new?

Wrote health.html
```

Run `python -m monitor check` a second time and the same three alerts are not raised again. The line reads `This check: 0 new, 3 still open, 0 closed`, and each alert shows `seen 2x`.

Options: `--db other.db` and `--config other.json` go before the command. `check --as-of "2026-11-10 12:00"` pretends it is another time. Running `seed` again wipes the run log and the alerts and starts over. `python -m monitor --help` lists everything.

## The eight checks

Every check is one small function in `monitor/checks.py`. Each reads one pipeline's run history and returns a list of findings (empty means healthy).

| Check | Question it asks | Rule | Severity |
|---|---|---|---|
| `freshness` | Is the newest good data too old? | Hours since the last **successful** run ended, against `freshness_hours`. No good run at all counts as a warning. | warning past the limit, critical past 2x the limit |
| `missed_schedule` | Did a run even start on time? | Hours since the last run **started** (any status) against `interval_hours`. A run may be up to 1.5 intervals late. | warning past 1.5 intervals, critical past 2.5 |
| `failures` | Is the pipeline failing? | Newest runs all failed: 2 in a row, or 3 or more. Or 30% or more of the last 10 runs failed. One failed run alone raises nothing, because a retry often fixes it. | warning at 2 in a row or a 30% rate, critical at 3 in a row |
| `row_count` | Is the newest run a normal size? | Compare `rows_out` with the median of the 14 good runs before it (rules explained below). | critical outside the percent band, warning for the MAD rule alone |
| `reconciliation` | Do the numbers add up? | `rows_in` must equal `rows_out + rows_rejected` on the newest good run. | critical |
| `schema_drift` | Are the expected columns there? | Columns seen against `required_columns`. | critical if one is missing, info if a new one appears |
| `runtime_creep` | Is it slowly getting slower? | Average minutes of the newest 5 good runs against the average of the oldest 7 of the last 30. Needs 12 runs. | warning at 1.3x, critical at 1.6x |
| `rejects_spike` | Are many more rows thrown away than usual? | Newest reject rate against the median reject rate of the 14 runs before it. Alerts above 3x normal and above 2%. | warning, critical at 10% or more |

All checks that compare with "normal" need at least 5 earlier good runs. With less history they say nothing instead of guessing.

### The two row-count rules in plain words

Both rules start from the **median** of the last 14 good runs. The median is the middle value when you sort the numbers. One freak run barely moves it, which an average would not survive.

1. **Percent band.** Take the median and allow `band_percent` either way. If the median is 2,185 rows and the band is 30%, anything below 1,530 or above 2,840 is outside. Outside the band is `critical`. This catches big jumps: a half-empty extract, a load run twice.
2. **MAD rule** (median absolute deviation). First ask how far each past run was from the median, and take the median of those distances. That is the pipeline's *usual wobble*. If the newest run is more than 6 usual wobbles away, it is odd for **this** pipeline even when it is inside the band. The wobble is never counted as less than 2% of the median, so a very quiet pipeline does not alert on tiny moves. This rule alone gives a `warning`.

Example from the tests: a pipeline that normally has 980 to 1,020 rows, median 1,000. A run of 1,150 is only +15%, inside a 30% band. But its usual wobble is tiny (10 rows, raised to 20 by the 2% floor), and 150 is more than 6 x 20 = 120, so the MAD rule raises a warning.

### Alerts do not repeat

Each check produces findings. `monitor/alerts.py` compares them with the alerts already open, using the pair (pipeline, check) as the identity:

- a finding with no open alert yet: **open** a new alert
- a finding that already has one: only refresh it (`last_seen`, `times_seen`, severity and message if they changed)
- an open alert whose finding is gone: **close** it, and keep the row as history

The database also refuses a second open alert for the same pair (a unique index), so a bug in the code could not create duplicates.

## Replay: watch the problems appear

`replay` runs the checks hour by hour over a range of times and prints every alert the moment it opens or closes. It reads the same run log, looking only at runs that had finished by each step. Alerts are kept in memory, so your real alert table is untouched.

```powershell
python -m monitor replay --from 2026-10-25 --to "2026-11-22 18:30"
```

Real output (the whole 30 days):

```
2026-11-02 08:00  OPENED  warning  inventory_snapshot / freshness: last success was 29h ago (limit 28h)
2026-11-02 14:00  CLOSED  inventory_snapshot / freshness
2026-11-05 08:00  OPENED  warning  shipments_feed / freshness: last success was 29h ago (limit 28h)
2026-11-05 08:00  OPENED  warning  shipments_feed / failures: 2 failed runs in a row. Last error: Connection timed out while reading the source
2026-11-05 12:00  CLOSED  shipments_feed / failures
2026-11-05 12:00  CLOSED  shipments_feed / freshness
2026-11-09 09:00  OPENED  warning  customs_docs / freshness: last success was 29h ago (limit 28h)
2026-11-09 17:00  OPENED  warning  customs_docs / missed_schedule: no run has started for 37h (expected one every 24h)
2026-11-10 05:00  CLOSED  customs_docs / freshness
2026-11-10 05:00  CLOSED  customs_docs / missed_schedule
2026-11-13 03:00  OPENED  critical returns_daily / row_count: rows_out is 1,015, the recent median is 2,185 (-54%): outside the 30% band
2026-11-14 03:00  CLOSED  returns_daily / row_count
2026-11-16 04:00  OPENED  warning  inventory_snapshot / runtime_creep: recent runs take 26 min, 1.3x the baseline of 20 min
2026-11-16 06:00  OPENED  critical billing_export / row_count: rows_out is 9,780, the recent median is 4,947 (+98%): outside the 25% band
2026-11-16 06:00  OPENED  critical billing_export / reconciliation: rows_in is 4,896 but rows_out + rejected is 9,786 (difference +4,890)
2026-11-17 06:00  CLOSED  billing_export / reconciliation
2026-11-17 06:00  CLOSED  billing_export / row_count
2026-11-18 02:00  OPENED  critical route_plans / schema_drift: required column(s) missing: carrier_code
2026-11-21 04:00  OPENED  warning  shipments_feed / rejects_spike: 6.0% of incoming rows were rejected (normal is 0.5%)

State at the last step: 8 pipelines: 5 green, 2 amber, 1 red
```

A date alone means midnight at the start of that day. `--step-hours` sets the gap between checks (default 1). Note that the slow creep began on 2026-11-03 and was first noticed on 2026-11-16: by design it needs the newest five runs to average 1.3x the baseline.

## The HTML page

`python -m monitor check --html health.html` writes one file. It has inline CSS and an inline SVG sparkline per pipeline. It loads nothing from the internet, uses no fonts, and has no JavaScript. Every piece of text from the data (pipeline names, owners, alert messages, error messages) is escaped, so an error message such as `<script>` cannot become markup.

The page structure (real file, shortened):

```
<h1>Pipeline health</h1>
<p class="meta">As of 2026-11-22 18:06:03. 8 pipelines: 5 green, 2 amber, 1 red.</p>

<table>
  <tr>  Status | Pipeline | Owner | Last OK | Rows out | Last 30 runs | Open alerts  </tr>
  <tr>  <span class="dot green"></span>green | orders_daily | orders-team | 16h ago | 11,973 | <svg><polyline .../></svg> | 0  </tr>
  ... one row per pipeline ...
  <tr>  <span class="dot red"></span>red | route_plans | routing-team | 17h ago | 909 | <svg>...</svg> | 1  </tr>
</table>

<h2>Open alerts (3)</h2>
<ul>
  <li class="critical"><strong>CRITICAL</strong> route_plans / schema_drift: required column(s) missing: carrier_code
      <em>Check first:</em> Ask the source owner what changed. ...
      <small>open since 2026-11-22 18:06:03</small></li>
  ...
</ul>
```

What you see: a heading and one summary line, then a table with one row per pipeline. The first column is a coloured dot plus the word (green, amber or red), so the status does not depend on colour alone. The sparkline shows the rows out of the last 30 good runs, scaled from that pipeline's lowest to its highest value (so a normal wobble can look big, and a real drop such as `returns_daily` stands out). Below the table is the list of open alerts, most serious first, each with a coloured left border, the message, and the "check first" line.

## Real detection numbers

The test `tests/test_seeded_data.py` seeds the fake 30 days, replays the checks **every hour from 2026-10-25 to 2026-11-22 (691 checks)**, and compares with the answer key in `monitor/seed.py`. Real output:

```
Detection (hourly checks, 2026-10-25 to 2026-11-22):
  late run                       inventory_snapshot freshness       injected 11-02  first alert 11-02 08:00
  slow creep in run time         inventory_snapshot runtime_creep   injected 11-03  first alert 11-16 04:00
  failed twice, then succeeded   shipments_feed     failures        injected 11-05  first alert 11-05 08:00
  failed twice, then succeeded   shipments_feed     freshness       injected 11-05  first alert 11-05 08:00
  missed run                     customs_docs       missed_schedule injected 11-09  first alert 11-09 17:00
  missed run                     customs_docs       freshness       injected 11-09  first alert 11-09 09:00
  sudden row-count drop          returns_daily      row_count       injected 11-13  first alert 11-13 03:00
  duplicated load                billing_export     reconciliation  injected 11-16  first alert 11-16 06:00
  duplicated load                billing_export     row_count       injected 11-16  first alert 11-16 06:00
  dropped column (schema drift)  route_plans        schema_drift    injected 11-18  first alert 11-18 02:00
  rejects spike                  shipments_feed     rejects_spike   injected 11-21  first alert 11-21 04:00
Detected 11 of 11 expected alerts for 8 of 8 injected problems

False alarms: 0. Alerts on the 2 healthy pipelines: 0 in 691 hourly checks each.

De-duplication: 429 findings across 691 hourly checks became 11 alerts (8 closed, 3 still open at the end).
```

Read this honestly: the data is fake and **I wrote both the problems and the thresholds**, so finding all eight is expected. The useful parts are that the healthy pipelines stayed quiet, that nothing fired that I had not expected, and that 429 repeated findings became 11 alerts. An early version of the row-count MAD rule did raise one false alarm on a healthy pipeline (a +6% move when its usual wobble happened to look tiny). Adding the 2% floor on the wobble fixed that.

## How this would map to cloud monitoring (how this would map; this does not run on AWS)

Nothing here runs on AWS or any cloud service. This is only my reading of how the same ideas appear in a managed monitoring service such as CloudWatch.

| This project | The same idea in cloud monitoring |
|---|---|
| The `runs` table | The run history and metrics a job service reports (status, duration, rows processed) |
| A check function | A metric plus an alarm rule on it |
| `freshness`, `failures` | Alarms on "time since last success" and "failed run count" |
| `row_count` percent band and MAD rule | A fixed threshold alarm and an anomaly-detection alarm on a row-count metric |
| Severity | Different alarm actions: page someone for critical, open a ticket for warning |
| The alerts table with open and closed | Alarm state (OK or ALARM): you are notified when the state changes, not on every evaluation |
| Runbook line | A runbook link in the alarm description |
| HTML health page | A dashboard |

## What it does not do

- The data is fake and the problems are the ones I put in. Real pipelines fail in messier ways, and the thresholds would need tuning on real history.
- The statistics are simple on purpose: a median, a median absolute deviation and fixed percentages. There is no seasonality (a weekend that is always quieter would look like a drop) and no trend model.
- It is not a replacement for real monitoring such as CloudWatch or a proper scheduler's alerting. It does not run on a schedule by itself, send email or pages, or authenticate anyone.
- The run log is a SQLite table that the seed command fills. It does not read CSV files or connect to a real scheduler.
- A run is written to the log when it ends, so a run that hangs and never ends is not seen at all, except through `missed_schedule` and `freshness`.
- The checks judge each pipeline alone. They do not know that one pipeline feeds another, so one root cause can raise alerts on several pipelines.
- A median of zero (a pipeline that is normally empty) is skipped by the row-count check.
- `check --as-of` saves its alerts in the real alert table. Use `replay` to look at the past.
- Times are plain local-style text with no time zones.
- Tested with Python 3.13 on Windows only.

## Run the tests

```powershell
python -m unittest discover -s tests -t .
```

Real result: `Ran 60 tests ... OK` (about 3 seconds). The tests cover: each check on tiny hand-made run logs (healthy, each failing case, empty history, the first run, exact limits), the severity rules, alert opening, de-duplication and closing, the unique index, HTML escaping, the report text and page structure, the sparkline, config validation, the command line (including bad input), and the seeded 30 days end to end.

## Files

```
pipelines.json         the settings for the 8 fake pipelines
monitor/config.py      reads and validates pipelines.json
monitor/db.py          the run log and alerts tables, and all the SQL
monitor/checks.py      the eight checks, one small function each
monitor/alerts.py      opens, refreshes and closes alerts (no repeats)
monitor/report.py      the terminal table, the HTML page, the sparkline
monitor/seed.py        makes the fake 30 days, with the 8 problems
monitor/cli.py         the seed, check and replay commands
tests/                 unittest tests
```

## License

MIT. See `LICENSE`.
