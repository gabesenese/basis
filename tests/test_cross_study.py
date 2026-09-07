from datetime import timedelta

import pytest

from basis import db, instruments
from basis.study import cross, fomc


@pytest.fixture(scope="module")
def panel():
    """
    Reads the collected history rather than a fixture, for the same reason the
    Phase 2 study tests do: the property under test is whether the windows hold
    against real bars, and a synthetic meeting would prove only that the
    arithmetic compiles.
    """
    psycopg = pytest.importorskip("psycopg")

    try:
        with db.connect() as conn:
            frame = cross.panel(conn)
    except psycopg.OperationalError as exc:
        pytest.skip(f"basis database unavailable: {exc}")

    if frame.empty:
        pytest.skip("no cross-instrument panel yet, backfill the universe first")
    return frame


def test_every_instrument_in_the_panel_is_registered(panel):
    unknown = set(panel["instrument"]) - set(instruments.ids())
    assert not unknown, unknown


def test_the_registry_agrees_with_the_stored_rows():
    psycopg = pytest.importorskip("psycopg")

    try:
        with db.connect() as conn:
            rows = conn.execute(
                "select id, pip_size, asset_class from basis.instrument"
            ).fetchall()
    except psycopg.OperationalError as exc:
        pytest.skip(f"basis database unavailable: {exc}")

    stored = {row["id"]: row for row in rows}
    for entry in instruments.REGISTRY:
        row = stored.get(entry["id"])
        assert row is not None, f"{entry['id']} is registered but not stored"
        assert row["pip_size"] == entry["pip_size"], entry["id"]
        assert row["asset_class"] == entry["asset_class"], entry["id"]


def test_the_response_opens_exactly_where_the_predictor_closes(panel):
    """
    The property the whole gate rests on. The predictor is knowable at the end
    of its window and the response is measured from that same instant, so a
    response that quietly started at the statement would be reading the very
    minutes the predictor was built from and would manufacture the result.
    """
    with db.connect() as conn:
        sample = panel.dropna(subset=["after_5m_bps"]).head(20)
        assert len(sample) > 0

        for _, row in sample.iterrows():
            at = row["statement_time"]
            opens = cross._mid_at(conn, row["instrument"], at + timedelta(minutes=5))
            closes = cross._mid_at(conn, row["instrument"], at + cross.RESPONSE_END)
            assert opens is not None and closes is not None

            expected = (closes / opens - 1.0) * 1e4
            assert row["after_5m_bps"] == pytest.approx(expected, rel=1e-9)


def test_the_full_window_response_starts_at_the_statement(panel):
    with db.connect() as conn:
        sample = panel.dropna(subset=["full_2h_bps"]).head(20)

        for _, row in sample.iterrows():
            at = row["statement_time"]
            entry = cross._mid_at(conn, row["instrument"], at)
            closes = cross._mid_at(conn, row["instrument"], at + cross.RESPONSE_END)
            assert entry is not None and closes is not None

            expected = (closes / entry - 1.0) * 1e4
            assert row["full_2h_bps"] == pytest.approx(expected, rel=1e-9)


def test_the_yardstick_excludes_meeting_days():
    """
    The ordinary move is what a response is judged large or small against, so a
    yardstick that folded the meeting afternoons back in would be inflated by
    exactly the events it is meant to measure.
    """
    psycopg = pytest.importorskip("psycopg")

    try:
        with db.connect() as conn:
            schedule = fomc.meetings(conn)
            if not schedule:
                pytest.skip("no FOMC meetings collected yet")
            start, finish, meeting_days = cross._span(schedule)

            everything = cross.ordinary_sigma(
                conn, instruments.REFERENCE, start, finish, set()
            )
            quiet = cross.ordinary_sigma(
                conn, instruments.REFERENCE, start, finish, meeting_days
            )
    except psycopg.OperationalError as exc:
        pytest.skip(f"basis database unavailable: {exc}")

    assert quiet["n"] < everything["n"]
    assert quiet["sigma_bps"] < everything["sigma_bps"]


def test_the_pooled_fit_drops_the_instrument_that_supplies_the_predictor(panel):
    """
    The two year note is both the predictor and a tradable instrument. Leaving
    it on the response side would regress a series on a window of itself and
    return a slope that describes arithmetic rather than transmission.
    """
    result = cross.pooled(panel)
    if result is None:
        pytest.skip("not enough rows to pool")

    assert result["instruments"] == panel["instrument"].nunique() - 1
    assert result["events"] <= panel["event_key"].nunique()


def test_pooled_clusters_on_the_event_rather_than_the_row(panel):
    """
    Eight correlated readings of one afternoon are not eight observations. The
    clustered interval must therefore be wider than the naive one, and this is
    the guard against quietly reporting the narrow version.
    """
    import statsmodels.api as sm

    usable = panel[panel["instrument"] != cross.RATE_LEADER]
    usable = usable[["after_5m_sigma", "reprice_5m_bps", "event_key"]].dropna()
    if len(usable) < 20:
        pytest.skip("not enough rows to pool")

    design = sm.add_constant(
        usable[["reprice_5m_bps"]].to_numpy(float), has_constant="add"
    )
    naive = sm.OLS(usable["after_5m_sigma"].to_numpy(float), design).fit()
    naive_width = naive.conf_int()[1][1] - naive.conf_int()[1][0]

    clustered = cross.pooled(panel)
    clustered_width = clustered["cluster_high"] - clustered["cluster_low"]

    assert clustered_width > naive_width
