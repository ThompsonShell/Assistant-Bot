"""Spaced repetition (SM-2) scheduling for vocabulary cards.

After you see a card's answer you grade yourself:

    again -> forgot it, see it again today
    hard  -> remembered with effort, small step
    good  -> remembered, normal step
    easy  -> instant, bigger step

Remembered cards come back after 1 day, then 6 days, then the previous gap
multiplied by the card's "ease" (2.5 by default, adjusted by how hard it felt).
Forgotten cards restart from today. This is the classic SM-2 algorithm used
by Anki-style apps.
"""
from __future__ import annotations

import datetime as dt

from ..models.study import VocabCard

GRADES = {"again": 1, "hard": 3, "good": 4, "easy": 5}
MIN_EASE = 1.3


def schedule(card: VocabCard, grade: str, today: dt.date) -> None:
    """Update the card's interval, ease and due date in place for a grade."""
    q = GRADES[grade]
    if q < 3:
        card.reps = 0
        card.interval_days = 0
        card.lapses = (card.lapses or 0) + 1
        card.due_date = today
    else:
        card.reps = (card.reps or 0) + 1
        if card.reps == 1:
            card.interval_days = 1
        elif card.reps == 2:
            card.interval_days = 6
        else:
            card.interval_days = max(1, round((card.interval_days or 1) * card.ease))
        card.due_date = today + dt.timedelta(days=card.interval_days)
    card.ease = max(MIN_EASE, card.ease + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    card.last_reviewed = today
