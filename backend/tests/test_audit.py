from app.audit import record_audit
from app.db import Base, make_engine, make_sessionmaker
from app.models.audit import AuditLog
from app.redaction import REDACTED


def _session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_sessionmaker(engine)()


def test_audit_record_persists_and_redacts():
    db = _session()
    record_audit(
        db,
        action="auth.login.success",
        category="auth",
        ip="127.0.0.1",
        detail={"username": "admin", "password": "should-not-be-stored"},
    )
    rows = db.query(AuditLog).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "auth.login.success"
    assert row.detail["username"] == "admin"
    assert row.detail["password"] == REDACTED
    assert row.success is True


def test_audit_defaults_actor_system_and_failure_flag():
    db = _session()
    record_audit(db, action="system.test", category="system", actor="system", success=False)
    row = db.query(AuditLog).one()
    assert row.actor == "system"
    assert row.success is False
