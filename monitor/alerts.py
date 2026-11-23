"""Open and close alerts, and never repeat an alert that is already open."""

from monitor.db import to_text

# Higher number = more serious.
SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


# Compare this run's findings with the alerts already open, and update the table.
#   - a finding with no open alert yet  -> open a new alert        ("opened")
#   - a finding that already has one    -> only refresh it         ("kept")
#   - an open alert with no finding now -> close it                ("closed")
# The pair (pipeline, check_name) is what makes two alerts "the same".
# Returns the three lists so the report can say what changed.
def sync_alerts(conn, findings, now):
    stamp = to_text(now)
    result = {"opened": [], "kept": [], "closed": []}
    with conn:
        for f in findings:
            row = conn.execute(
                "SELECT alert_id FROM alerts WHERE pipeline = ? AND check_name = ?"
                " AND closed_at IS NULL", (f["pipeline"], f["check_name"])).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO alerts (pipeline, check_name, severity, message, runbook,"
                    " first_seen, last_seen, times_seen) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                    (f["pipeline"], f["check_name"], f["severity"], f["message"],
                     f["runbook"], stamp, stamp))
                result["opened"].append(f)
            else:
                conn.execute(
                    "UPDATE alerts SET severity = ?, message = ?, runbook = ?, last_seen = ?,"
                    " times_seen = times_seen + 1 WHERE alert_id = ?",
                    (f["severity"], f["message"], f["runbook"], stamp, row["alert_id"]))
                result["kept"].append(f)
        current = {(f["pipeline"], f["check_name"]) for f in findings}
        for row in conn.execute(
                "SELECT alert_id, pipeline, check_name FROM alerts WHERE closed_at IS NULL"
        ).fetchall():
            if (row["pipeline"], row["check_name"]) not in current:
                conn.execute("UPDATE alerts SET closed_at = ? WHERE alert_id = ?",
                             (stamp, row["alert_id"]))
                result["closed"].append(
                    {"pipeline": row["pipeline"], "check_name": row["check_name"]})
    return result


# All alerts that are open right now, most serious first.
def open_alerts(conn):
    rows = conn.execute(
        "SELECT * FROM alerts WHERE closed_at IS NULL ORDER BY CASE severity"
        " WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, pipeline, check_name")
    return [dict(row) for row in rows]
