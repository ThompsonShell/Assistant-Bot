"""Write audit entries. Detail is always redacted before persistence."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from ..models.audit import AuditLog
from ..redaction import redact

logger = logging.getLogger("lifeos.audit")


def record_audit(
    db: Session,
    *,
    action: str,
    category: str,
    actor: str = "admin",
    success: bool = True,
    ip: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    """Persist an audit entry and mirror it to the structured log.

    `detail` is run through `redact()` so a secret accidentally included is
    masked rather than stored.
    """
    safe_detail = redact(detail) if detail else None
    entry = AuditLog(
        actor=actor,
        action=action,
        category=category,
        success=success,
        ip=ip,
        detail=safe_detail,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    logger.info(
        "audit",
        extra={
            "extra_fields": {
                "audit_action": action,
                "audit_category": category,
                "audit_actor": actor,
                "audit_success": success,
            }
        },
    )
    return entry
