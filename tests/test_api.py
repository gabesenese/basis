import pytest

from basis import accounts, db

EMAIL = "pytest-fixture@basis.invalid"
PASSWORD = "correct-horse-battery-staple"
PROTECTED = [
    "/api/session",
    "/api/today",
    "/api/calendar",
    "/api/study/fomc",
    "/api/context/positioning",
]


@pytest.fixture(scope="module")
def client():
    """
    The account is real and is removed afterwards. A rolled back fixture would
    be invisible here, because the app opens its own connections rather than
    borrowing the test's.
    """
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from basis.api.app import app

    try:
        with db.connect() as conn:
            conn.execute("delete from basis.account where email = %s", (EMAIL,))
            accounts.create(conn, EMAIL, "Pytest", PASSWORD, "pt", "America/Sao_Paulo")
            conn.commit()
    except psycopg.OperationalError as exc:
        pytest.skip(f"basis database unavailable: {exc}")

    try:
        with TestClient(app) as ready:
            yield ready
    finally:
        with db.connect() as conn:
            conn.execute("delete from basis.account where email = %s", (EMAIL,))
            conn.commit()


@pytest.fixture
def signed_in(client):
    client.cookies.clear()
    response = client.post("/api/session", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200
    return client


@pytest.mark.parametrize("path", PROTECTED)
def test_every_read_requires_a_session(client, path):
    client.cookies.clear()

    assert client.get(path).status_code == 401


def test_a_wrong_password_is_refused(client):
    client.cookies.clear()
    response = client.post("/api/session", json={"email": EMAIL, "password": "wrong"})

    assert response.status_code == 401


def test_an_unknown_address_is_refused_the_same_way(client):
    client.cookies.clear()
    response = client.post(
        "/api/session", json={"email": "nobody@basis.invalid", "password": PASSWORD}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "email or password is wrong"


def test_signing_in_returns_the_account_and_its_preferences(signed_in):
    body = signed_in.get("/api/session").json()

    assert body["email"] == EMAIL
    assert body["language"] == "pt"
    assert body["timezone"] == "America/Sao_Paulo"
    assert "password_hash" not in body


def test_signing_out_ends_the_session(signed_in):
    signed_in.delete("/api/session")

    assert signed_in.get("/api/today").status_code == 401


def test_preferences_persist(signed_in):
    updated = signed_in.patch(
        "/api/preferences", json={"language": "en", "timezone": "Europe/Lisbon"}
    ).json()

    assert updated["language"] == "en"
    assert signed_in.get("/api/session").json()["timezone"] == "Europe/Lisbon"

    signed_in.patch(
        "/api/preferences", json={"language": "pt", "timezone": "America/Sao_Paulo"}
    )


def test_an_unsupported_language_is_refused(signed_in):
    response = signed_in.patch("/api/preferences", json={"language": "fr"})

    assert response.status_code == 422


def test_today_carries_a_next_event_and_a_health_reading(signed_in):
    body = signed_in.get("/api/today").json()

    assert body["instrument"]["id"] == "EUR_USD"
    assert body["instrument"]["quote_ccy"] == "USD"
    assert {f["subject"] for f in body["health"]} == {"recorder", "ticks", "bars"}
    if body["next_event"]:
        assert body["next_event"]["scheduled_time"] > body["as_of"]


def test_every_cost_point_declares_where_it_came_from(signed_in):
    cost = signed_in.get("/api/today").json()["cost"]

    assert all(point["provenance"] for point in cost["points"])
    assert all(point["basis"] for point in cost["points"])
    assert not any(point["provenance"] == "measured" for point in cost["points"])


def test_the_calendar_returns_the_latest_vintage_in_time_order(signed_in):
    events = signed_in.get("/api/calendar?months_back=3&months_ahead=6").json()["events"]
    times = [e["scheduled_time"] for e in events]

    assert times == sorted(times)
    assert len({e["event_key"] for e in events}) == len(events)
    assert all(e["vintages"] >= 1 for e in events)


def test_the_calendar_never_returns_an_event_before_it_was_knowable(signed_in):
    events = signed_in.get("/api/calendar?months_back=12&months_ahead=12").json()["events"]

    assert all(e["known_since"] <= e["scheduled_time"] for e in events)


def test_the_study_reports_intervals_beside_every_slope(signed_in):
    body = signed_in.get("/api/study/fomc").json()
    fit = body["tests"]["repricing"]["by_horizon"][body["gate_horizon"]]

    assert body["coverage"]["meetings"] == len(body["meetings"])
    for slope in fit["slopes"]:
        assert slope["robust_low"] <= slope["estimate"] <= slope["robust_high"]
        assert isinstance(slope["excludes_zero"], bool)


def test_the_constrained_surprise_does_not_clear_zero(signed_in):
    """
    The Phase 2 answer, asserted rather than described. If a later collector
    changes this the test fails and the plan gets revisited on purpose.
    """
    body = signed_in.get("/api/study/fomc").json()
    slope = body["tests"]["constrained"]["by_horizon"]["ret_2h"]["slopes"][1]

    assert slope["name"] == "z_surprise"
    assert not slope["excludes_zero"]


def test_positioning_comes_back_oldest_first_with_its_release_lag(signed_in):
    body = signed_in.get("/api/context/positioning?weeks=12").json()
    series = body["series"]

    assert [s["effective_time"] for s in series] == sorted(
        s["effective_time"] for s in series
    )
    assert all(s["known_since"] > s["effective_time"] for s in series)
