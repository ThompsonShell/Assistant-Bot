"""Which bot process is answering: its id and when it started.

Shown in the Jira messages so an OLD copy that is still running (with an old
.env and old code) can be recognised by its start time.
"""
from __future__ import annotations

import datetime as dt
import os

STARTED = dt.datetime.now()
PID = os.getpid()


def footer() -> str:
    return f"🤖 Jarayon {PID}, ishga tushgan {STARTED.strftime('%d-%b %H:%M')}"
