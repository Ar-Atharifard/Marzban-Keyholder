"""Shared selection syntax for operator commands."""

import re
from typing import Any


def select_tags(entries: list[dict[str, Any]], selection: str, defaults: list[str]) -> list[str]:
    selection = selection.strip().lower()
    if selection == "all":
        chosen = [row["tag"] for row in entries]
    elif selection == "default":
        chosen = list(defaults)
    else:
        if not re.fullmatch(r"\d+(?:\s*,\s*\d+)*", selection):
            raise ValueError("Use comma-separated inbound numbers, all, or default.")
        numbers = [int(n) for n in selection.split(",")]
        if len(set(numbers)) != len(numbers) or any(n < 1 or n > len(entries) for n in numbers):
            raise ValueError("Choose unique numbers from the current inbound list.")
        chosen = [entries[n - 1]["tag"] for n in numbers]
    available = {row["tag"] for row in entries}
    if not chosen or len(set(chosen)) != len(chosen) or not set(chosen) <= available:
        raise ValueError(
            "The selection is empty or contains unavailable inbounds; review defaults."
        )
    return chosen
