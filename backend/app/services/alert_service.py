from sqlalchemy.orm import Session

from app.models.control import Alert


def raise_alert(
    db: Session,
    *,
    severity: str,
    code: str,
    message: str,
    subject_type: str | None = None,
    subject_id: str | None = None,
    details: dict | None = None,
) -> Alert:
    alert = Alert(
        severity=severity,
        code=code,
        message=message,
        subject_type=subject_type,
        subject_id=subject_id,
        details=details,
    )
    db.add(alert)
    db.flush()
    return alert
