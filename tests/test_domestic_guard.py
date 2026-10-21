import json

import pytest

from scripts.domestic_guard import heartbeat_age


def event(stamp: float, message: str = 'INFO:  foreign:1234 - "POST /ping HTTP/1.1" 200 OK') -> str:
    return json.dumps({"__MONOTONIC_TIMESTAMP": str(stamp * 1_000_000), "MESSAGE": message})


def test_latest_authenticated_ping_is_used() -> None:
    records = "\n".join([event(100), event(150), event(120)])
    assert heartbeat_age(records, 200) == 50


@pytest.mark.parametrize(
    "message",
    [
        '"POST /ping HTTP/1.1" 403 Forbidden',
        '"POST / HTTP/1.1" 200 OK',
        '"POST /connect HTTP/1.1" 200 OK',
        '"POST /start HTTP/1.1" 200 OK',
    ],
)
def test_other_requests_do_not_renew_lease(message: str) -> None:
    assert heartbeat_age(event(100, message), 200) is None


def test_future_and_invalid_entries_do_not_renew_lease() -> None:
    assert heartbeat_age(event(1000) + "\ninvalid\n{}", 200) is None


def test_stale_heartbeat_is_not_hidden_by_other_activity() -> None:
    records = event(100) + "\n" + event(450, '"POST / HTTP/1.1" 200 OK')
    assert heartbeat_age(records, 500) == 400
