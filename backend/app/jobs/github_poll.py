"""Background GitHub poll job.

Runnable as a one-shot CLI:  python -m app.jobs.github_poll
Also invoked periodically by the scheduler wired in app.main.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import sessionmaker

from ..config import settings
from ..integrations.github import make_github_client, poll_all
from ..notifications import build_notifier

logger = logging.getLogger("lifeos.jobs.github")


def run_poll_once(session_local: sessionmaker, *, http=None) -> dict[str, int]:
    if not settings.github_token:
        logger.info("github poll skipped: GITHUB_TOKEN not configured")
        return {}
    client = make_github_client()
    notifier = build_notifier(http=http)
    with session_local() as db:
        results = poll_all(db, client, notifier)
        db.commit()
    return results


def _main() -> None:
    from ..db import make_engine, make_sessionmaker
    from ..logging_config import configure_logging

    configure_logging(settings.log_level)
    engine = make_engine(settings.database_url)
    session_local = make_sessionmaker(engine)
    results = run_poll_once(session_local)
    logger.info("github poll complete", extra={"extra_fields": {"results": results}})


if __name__ == "__main__":
    _main()
