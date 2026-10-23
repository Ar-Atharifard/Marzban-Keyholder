"""Non-secret operational overrides shared by standalone Python 3.10 helpers."""

from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


@lru_cache(maxsize=8)
def document(filename: str) -> dict[str, Any]:
    path = Path(filename)
    try:
        info = path.stat()
    except FileNotFoundError:
        return {}
    if path.is_symlink() or info.st_mode & 0o022 or (os.geteuid() == 0 and info.st_uid != 0):
        raise ValueError("Component settings must be owner-controlled and not a symlink")
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("Component settings must be a JSON object")
    return data


def settings(section: str, defaults: dict[str, Any]) -> dict[str, Any]:
    """Missing files preserve defaults; invalid or unknown section fields fail closed."""
    filename = os.getenv(
        "KEYHOLDER_COMPONENT_CONFIG", str(Path(__file__).with_name("components.json"))
    )
    return merge(section, defaults, document(filename).get(section, {}))


def merge(section: str, defaults: dict[str, Any], supplied: Any) -> dict[str, Any]:
    if not isinstance(supplied, dict) or supplied.keys() - defaults.keys():
        raise ValueError("Unknown component settings: " + section)
    for key, value in supplied.items():
        default = defaults[key]
        if isinstance(default, (int, float)) and not isinstance(default, bool):
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or (type(default) is int and type(value) is not int)
                or (default > 0 and value <= 0)
            ):
                raise ValueError("Invalid positive numeric setting: " + key)
        elif not isinstance(value, type(default)):
            raise ValueError("Invalid component setting type: " + key)
        if isinstance(value, str) and (not value or any(ord(c) < 32 for c in value)):
            raise ValueError("Invalid component string: " + key)
        if key.endswith("api_base"):
            endpoint = urlsplit(value)
            local = endpoint.hostname in {"127.0.0.1", "::1", "localhost"}
            if (
                endpoint.scheme not in {"http", "https"}
                or not endpoint.hostname
                or (endpoint.scheme != "https" and not local)
                or endpoint.username
                or endpoint.password
                or endpoint.query
                or endpoint.fragment
            ):
                raise ValueError("Credential API endpoints require HTTPS or loopback HTTP")
        if isinstance(value, list) and (
            not value or any(type(item) is not type(default[0]) for item in value)
        ):
            raise ValueError("Invalid nonempty component list: " + key)
    return {**defaults, **supplied}


def validate_file(filename: str) -> None:
    """Check overrides against installed helpers without importing or running them."""
    import ast

    supplied = document(filename)
    for source in Path(__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "component_settings"
                and len(node.args) > 1
            ):
                section = ast.literal_eval(node.args[0])
                defaults = ast.literal_eval(node.args[1])
                merge(section, defaults, supplied.get(section, {}))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate non-secret component overrides")
    parser.add_argument("--check", type=str, required=True)
    validate_file(parser.parse_args().check)
    print("Component settings valid for installed helpers; no services were started.")
