"""Serve the built-in single-page dashboard."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["web"])

_INDEX = Path(__file__).resolve().parent.parent / "web" / "index.html"


@router.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    return HTMLResponse(_INDEX.read_text(encoding="utf-8"))
