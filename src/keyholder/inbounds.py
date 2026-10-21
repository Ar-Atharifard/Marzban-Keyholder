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


def profile_summary(entries: list[dict[str, Any]]) -> str:
    previews = [row.get("generated_names") for row in entries]
    if any(p is None for p in previews):
        return "Profile total unavailable: one or more host templates cannot be previewed."
    total = sum(len(p) for p in previews if p is not None)
    return (
        f"{len(entries)} inbounds → {total} connection profiles (usage-information row excluded)."
    )


def profile_label(row: dict[str, Any]) -> str:
    names = row.get("generated_names")
    if names is None:
        return "; ".join(row["names"]) + " [preview unavailable]"
    return "; ".join(names) if names else "No compatible profiles (filtered by delivery rules)"
