"""Alert generation: evaluates the newest hour of data with the bottleneck rules and records what is active."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alert
from app.services.analytics.bottlenecks import CONDITIONS, describe, flagged_history


def scan_alerts(db: Session) -> dict:
    """
    Create an alert for every active condition at the newest data hour. A condition that already has an open
    (unacknowledged) alert for the same department is updated instead of duplicated; a higher severity escalates it.
    """
    df, th = flagged_history(db)
    if df.empty:
        return {"created": 0, "updated": 0, "as_of": None}
    last = df[df["timestamp"] == df["timestamp"].max()]
    open_alerts = {(a.department_id, a.type): a for a in db.scalars(select(Alert).where(Alert.acknowledged.is_(False))).all()}
    created = updated = 0
    for _, r in last.iterrows():
        for c in CONDITIONS:
            sev = int(r[f"sev_{c}"])
            if not sev:
                continue
            msg, value, thr = describe(c, r, th)
            severity = "critical" if sev == 2 else "warning"
            key = (int(r["department_id"]), c)
            existing = open_alerts.get(key)
            if existing:
                existing.severity, existing.message, existing.metric_value, existing.threshold = severity, msg, value, thr
                existing.as_of = r["timestamp"].to_pydatetime()
                updated += 1
            else:
                db.add(Alert(department_id=key[0], type=c, severity=severity, message=msg, metric_value=value,
                             threshold=thr, as_of=r["timestamp"].to_pydatetime()))
                created += 1
    db.commit()
    return {"created": created, "updated": updated, "as_of": df["timestamp"].max().strftime("%Y-%m-%dT%H:00")}
