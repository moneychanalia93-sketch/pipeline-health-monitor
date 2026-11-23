"""The command line: python -m monitor seed | check | replay"""

import argparse
import os
import sys
from datetime import datetime, timedelta

from monitor import alerts, checks, db, report, seed
from monitor.config import ConfigError, load_config


# Read a time typed on the command line: 2026-11-10 (midnight) or "2026-11-10 12:00".
def parse_when(text):
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date or time: {text!r}") from None


# Run every check for every pipeline, as of one moment.
# Returns all findings and the run history of each pipeline (the report needs both).
def collect(conn, configs, as_of):
    findings, histories = [], {}
    for cfg in configs:
        histories[cfg["name"]] = db.load_runs(conn, cfg["name"], as_of)
        findings.extend(checks.run_checks(cfg, histories[cfg["name"]], as_of))
    return findings, histories


# The seed command: wipe the log, write 30 fake days, say what was put in.
def seed_command(args, configs):
    conn = db.connect(args.db)
    db.clear_all(conn)
    runs = seed.build_runs(configs)
    db.add_runs(conn, runs)
    conn.close()
    print(f"Wrote {len(runs)} runs for {len(configs)} pipelines to {args.db}")
    print("Problems put in on purpose:")
    for p in seed.PROBLEMS:
        day = (seed.START + timedelta(days=p["day"])).date()
        print(f"  {day}  {p['pipeline']:<19}{p['name']}")


# The check command: judge every pipeline now, update the alert table,
# print the table, and optionally write the HTML page.
def check_command(args, configs):
    conn = db.connect(args.db)
    as_of = args.as_of or db.latest_end(conn)
    if as_of is None:
        print("the run log is empty: run the seed command first", file=sys.stderr)
        return 2
    findings, histories = collect(conn, configs, as_of)
    changes = alerts.sync_alerts(conn, findings, as_of)
    open_now = alerts.open_alerts(conn)
    summary = [report.summarize(c, histories[c["name"]], as_of, open_now) for c in configs]
    print(report.text_report(summary, open_now, changes, as_of))
    if args.html:
        with open(args.html, "w", encoding="utf-8") as handle:
            handle.write(report.html_report(summary, open_now, as_of))
        print(f"\nWrote {args.html}")
    conn.close()
    return 0


# The replay command: run the checks again and again, as of earlier times, and
# print every alert the moment it opens or closes. Alerts are kept in memory
# only, so the real alert table is not touched.
def replay_command(args, configs):
    conn = db.connect(args.db)
    memory = db.connect(":memory:")
    moment = args.start
    while moment <= args.end:
        findings, histories = collect(conn, configs, moment)
        changes = alerts.sync_alerts(memory, findings, moment)
        stamp = db.to_text(moment)[:16]
        for f in changes["opened"]:
            print(f"{stamp}  OPENED  {f['severity']:<9}{f['pipeline']} / {f['check_name']}: "
                  f"{f['message']}")
        for a in changes["closed"]:
            print(f"{stamp}  CLOSED  {a['pipeline']} / {a['check_name']}")
        last = moment
        moment += timedelta(hours=args.step_hours)
    open_now = alerts.open_alerts(memory)
    summary = [report.summarize(c, histories[c["name"]], last, open_now) for c in configs]
    print(f"\nState at the last step: {report.count_line(summary)}")
    conn.close()
    return 0


# Describe the three commands and their options.
def build_parser():
    parser = argparse.ArgumentParser(prog="python -m monitor",
                                     description="Watch fake data pipelines.")
    parser.add_argument("--db", default="runs.db", help="run log database (default runs.db)")
    parser.add_argument("--config", default="pipelines.json", help="pipeline settings file")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed", help="write 30 fake days of runs")
    check = commands.add_parser("check", help="judge every pipeline now")
    check.add_argument("--as-of", type=parse_when, help="pretend it is this time")
    check.add_argument("--html", help="also write the HTML health page to this file")
    replay = commands.add_parser("replay", help="show how alerts opened and closed over time")
    replay.add_argument("--from", dest="start", type=parse_when, required=True)
    replay.add_argument("--to", dest="end", type=parse_when, required=True)
    replay.add_argument("--step-hours", type=int, default=1, help="hours between checks")
    return parser


# Entry point. Returns the exit code: 0 fine, 2 for a problem with the input.
def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command != "seed" and not os.path.exists(args.db):
        print(f"no run log at {args.db}: run the seed command first", file=sys.stderr)
        return 2
    try:
        configs = load_config(args.config)
    except ConfigError as error:
        print(f"config error: {error}", file=sys.stderr)
        return 2
    if args.command == "replay" and (args.step_hours < 1 or args.end < args.start):
        print("replay needs --to on or after --from, and --step-hours 1 or more", file=sys.stderr)
        return 2
    commands = {"seed": seed_command, "check": check_command, "replay": replay_command}
    return commands[args.command](args, configs) or 0
