"""Build the text table and the HTML page from the results of one check."""

from html import escape

from monitor.alerts import SEVERITY_RANK
from monitor.db import to_text

COLORS = ["green", "amber", "red"]   # position = rank of the worst open alert
SPARK_RUNS = 30                      # the sparkline shows the last 30 good runs

# Plain inline CSS. No external fonts, files or scripts.
STYLE = """
body { font-family: Arial, sans-serif; margin: 2em; color: #222; }
th, td { border-bottom: 1px solid #ddd; padding: 6px 12px; text-align: left; }
.dot { display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 6px; }
.green { background: #2e9e4f; } .amber { background: #f0a30a; } .red { background: #d62f2f; }
ul { list-style: none; padding: 0; } small, .meta { color: #666; }
li { border-left: 6px solid #999; padding: 6px 12px; margin-bottom: 8px; background: #f6f6f6; }
li.critical { border-color: #d62f2f; } li.warning { border-color: #f0a30a; }
li.info { border-color: #2e9e4f; }
"""


# Green, amber or red for one pipeline, from its open alerts.
# The worst alert decides. Info alerts do not change the color.
def pipeline_status(alerts):
    worst = max((SEVERITY_RANK[a["severity"]] for a in alerts), default=0)
    return COLORS[worst]


# One summary row per pipeline: the facts that both reports show.
def summarize(cfg, runs, as_of, open_alerts):
    mine = [a for a in open_alerts if a["pipeline"] == cfg["name"]]
    done = [run for run in runs if run["status"] == "success"]
    last = done[-1] if done else None
    return {
        "name": cfg["name"],
        "owner": cfg["owner"],
        "status": pipeline_status(mine),
        "hours_since_ok": (as_of - last["end"]).total_seconds() / 3600 if last else None,
        "rows_out": last["rows_out"] if last else None,
        "spark": [run["rows_out"] for run in done[-SPARK_RUNS:]],
        "alerts": len(mine),
    }


# A line like "8 pipelines: 5 green, 2 amber, 1 red".
def count_line(summary):
    counts = [sum(1 for row in summary if row["status"] == color) for color in COLORS]
    parts = ", ".join(f"{n} {color}" for n, color in zip(counts, COLORS))
    return f"{len(summary)} pipelines: {parts}"


# "16h ago", or "never" when the pipeline has no good run yet.
def ago(hours):
    return "never" if hours is None else f"{hours:.0f}h ago"


# The report for the terminal: a header, one row per pipeline, then the open alerts.
# `changes` is what sync_alerts returned, so we can say what is new this time.
def text_report(summary, alerts, changes, as_of):
    lines = [f"Pipeline health as of {to_text(as_of)}", count_line(summary), "",
             f"{'PIPELINE':<20}{'STATUS':<8}{'OWNER':<16}{'LAST OK':<10}{'ROWS OUT':>9}  ALERTS"]
    for row in summary:
        rows = "-" if row["rows_out"] is None else f"{row['rows_out']:,}"
        lines.append(f"{row['name']:<20}{row['status'].upper():<8}{row['owner']:<16}"
                     f"{ago(row['hours_since_ok']):<10}{rows:>9}  {row['alerts']}")
    lines += ["", f"This check: {len(changes['opened'])} new, {len(changes['kept'])} still open, "
                  f"{len(changes['closed'])} closed", "", f"Open alerts ({len(alerts)}):"]
    for a in alerts:
        lines += [f"  [{a['severity'].upper()}] {a['pipeline']} / {a['check_name']}"
                  f"  (open since {a['first_seen']}, seen {a['times_seen']}x)",
                  f"      {a['message']}", f"      Check first: {a['runbook']}"]
    return "\n".join(lines)


# A tiny line chart as inline SVG. Needs at least 2 values, else we show "n/a".
# Every value is scaled so the lowest sits at the bottom and the highest at the top.
def sparkline(values, width=120, height=24):
    if len(values) < 2:
        return "n/a"
    low, high = min(values), max(values)
    span = (high - low) or 1
    step = width / (len(values) - 1)
    points = " ".join(f"{i * step:.1f},{height - 2 - (v - low) / span * (height - 4):.1f}"
                      for i, v in enumerate(values))
    label = f"rows out, last {len(values)} runs, from {low:,} to {high:,}"
    return (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'role="img" aria-label="{label}"><polyline points="{points}" fill="none" '
            f'stroke="#456" stroke-width="1.5"/></svg>')


# One table row of the HTML page. Every piece of text goes through escape().
def html_row(row):
    rows = "-" if row["rows_out"] is None else f"{row['rows_out']:,}"
    return (f'<tr><td><span class="dot {row["status"]}"></span>{row["status"]}</td>'
            f'<td>{escape(row["name"])}</td><td>{escape(row["owner"])}</td>'
            f'<td>{ago(row["hours_since_ok"])}</td><td>{rows}</td>'
            f'<td>{sparkline(row["spark"])}</td><td>{row["alerts"]}</td></tr>')


# One list item of the open-alerts section. The message can contain text from the
# run log (an error message), so it is escaped: it must never become HTML.
def html_alert(a):
    return (f'<li class="{escape(a["severity"])}"><strong>{escape(a["severity"].upper())}</strong> '
            f'{escape(a["pipeline"])} / {escape(a["check_name"])}: {escape(a["message"])}<br>'
            f'<em>Check first:</em> {escape(a["runbook"])}<br>'
            f'<small>open since {escape(a["first_seen"])}</small></li>')


# The whole self-contained HTML page: a heading, the pipeline table, the open alerts.
def html_report(summary, alerts, as_of):
    head = ("<th>Status</th><th>Pipeline</th><th>Owner</th><th>Last OK</th>"
            "<th>Rows out</th><th>Last 30 runs</th><th>Open alerts</th>")
    items = "".join(html_alert(a) for a in alerts) or "<li class=\"info\">No open alerts.</li>"
    return (f'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<title>Pipeline health</title>\n<style>{STYLE}</style>\n</head>\n<body>\n'
            f'<h1>Pipeline health</h1>\n'
            f'<p class="meta">As of {to_text(as_of)}. {count_line(summary)}.</p>\n'
            f'<table>\n<tr>{head}</tr>\n' + "\n".join(html_row(row) for row in summary) +
            f'\n</table>\n<h2>Open alerts ({len(alerts)})</h2>\n<ul>{items}</ul>\n'
            f'</body>\n</html>\n')
