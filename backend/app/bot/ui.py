"""Reply = text + inline buttons. Buttons carry a callback string.

Most buttons simply run a command as if the owner had typed it: the callback
is ``do:<command>`` (e.g. ``do:/review``). That keeps one code path for typed
commands and button taps. Telegram limits callback data to 64 bytes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

Button = tuple[str, str]  # (label, callback_data)


def do(label: str, command: str) -> Button:
    """A button that runs ``command`` when tapped."""
    return (label, f"do:{command}")


@dataclass
class Reply:
    text: str
    rows: list[list[Button]] = field(default_factory=list)

    def markup(self) -> dict | None:
        if not self.rows:
            return None
        return {
            "inline_keyboard": [
                [{"text": label, "callback_data": data} for label, data in row]
                for row in self.rows
            ]
        }

    def with_next(self, button: Button | None) -> "Reply":
        """Add one closing button unless the reply already has buttons."""
        if not self.rows and button is not None:
            self.rows = [[button]]
        return self
