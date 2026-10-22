from scripts.backhaul_guard import advance


def test_healthy_listener_resets_failure_count() -> None:
    state, restart = advance({"rathole": "UP", "frp": "UP"}, {"failures": 2}, 2000, True)
    assert state["failures"] == 0 and not restart


def test_only_three_failures_with_healthy_alternate_allow_restart() -> None:
    state, restart = advance({"rathole": "DOWN", "frp": "UP"}, {}, 2000, True)
    assert not restart
    state, restart = advance({"rathole": "DOWN", "frp": "UP"}, state, 2060, True)
    assert not restart
    state, restart = advance({"rathole": "DOWN", "frp": "UP"}, state, 2120, True)
    assert restart and state["last_restart"] == 2120 and state["failures"] == 0
    _, restart = advance({"rathole": "DOWN", "frp": "UP"}, {**state, "failures": 3}, 2200, True)
    assert not restart


def test_never_restarts_during_total_outage_or_admin_closure() -> None:
    for permitted, alternate in [(False, "UP"), (True, "DOWN")]:
        _, restart = advance(
            {"rathole": "DOWN", "frp": alternate}, {"failures": 3}, 2000, permitted
        )
        assert not restart
