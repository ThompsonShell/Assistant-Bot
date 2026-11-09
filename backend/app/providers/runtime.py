"""Runtime-adjustable AI settings the owner can change from the Telegram bot
(e.g. reasoning effort), persisted to a small file so they survive restarts.

Shared across the Telegram thread and web requests (same process).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max")

_FILE = Path(os.environ.get("RUNTIME_STATE_FILE", "claude_runtime.json"))
_cache: Optional[dict] = None


def _data() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _cache = {}
    return _cache


def get_effort(default: str = "medium") -> str:
    val = _data().get("effort")
    return val if val in VALID_EFFORTS else default


def set_effort(level: str) -> None:
    if level not in VALID_EFFORTS:
        raise ValueError("invalid effort")
    data = _data()
    data["effort"] = level
    try:
        _FILE.write_text(json.dumps(data), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
