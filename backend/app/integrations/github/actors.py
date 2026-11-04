"""Classify who performed a GitHub action.

Honesty rules (per project requirements):
  * We distinguish human / bot / GitHub Action / app / unknown.
  * We NEVER claim an action was "AI-generated" — that cannot be reliably
    detected from GitHub metadata, so AI-assisted work is indistinguishable
    from ordinary human activity here and is simply classified as human.
"""
from __future__ import annotations

HUMAN = "human"
BOT = "bot"
GITHUB_ACTION = "github_action"
APP = "app"
UNKNOWN = "unknown"


def classify_actor(login: str | None, type_hint: str | None = None) -> str:
    if not login:
        return UNKNOWN
    low = login.lower()
    if low == "github-actions[bot]":
        return GITHUB_ACTION
    if low.endswith("[bot]"):
        return BOT
    if type_hint:
        t = type_hint.lower()
        if t == "bot":
            return BOT
        if t in ("organization", "app"):
            return APP
    return HUMAN
