from datetime import date, datetime, timezone

import pytest

from basis.sources import dukascopy as dk

pytestmark = pytest.mark.live


def test_zero_indexed_month_against_a_known_weekend():
    """
    Dukascopy path segment 07 is August when the month is zero indexed, and
    2026-08-08 is a Saturday with the market closed. If the convention were
    ever one indexed the same path would resolve to Wednesday 2026-07-08 and
    come back full, so an empty result is what pins the mapping down.
    """
    with dk.open_client() as client:
        saturday = dk.fetch_hour(
            client, "EURUSD", datetime(2026, 8, 8, 13, tzinfo=timezone.utc)
        )
        friday = dk.fetch_hour(
            client, "EURUSD", datetime(2026, 8, 7, 13, tzinfo=timezone.utc)
        )

    assert saturday.empty
    assert len(friday) > 1000


def test_a_real_hour_decodes_into_plausible_eurusd():
    with dk.open_client() as client:
        frame = dk.fetch_hour(
            client, "EURUSD", datetime(2026, 8, 7, 13, tzinfo=timezone.utc)
        )

    assert (frame["ask"] >= frame["bid"]).all()
    assert frame["bid"].between(0.9, 1.6).all()
    assert frame["ts"].is_monotonic_increasing
