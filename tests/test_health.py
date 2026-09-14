from core.health import healthcheck


def test_healthcheck_returns_ok() -> None:
    status = healthcheck()
    assert status.status == "ok"
    assert status.component == "core"
    assert status.version
