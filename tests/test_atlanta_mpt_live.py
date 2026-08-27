import pytest

from basis.sources import atlanta_mpt

pytestmark = pytest.mark.live


def test_the_workbook_still_carries_the_fields_the_parser_reads():
    """
    The Atlanta Fed republishes this file daily and has changed its layout
    before. Reading the newest copy is what catches a renamed column while it
    is still a parse error rather than a silently empty study.
    """
    frame = atlanta_mpt.parse(atlanta_mpt.fetch())

    assert "Rate: mean" in frame.columns
    assert any(column.startswith("Prob: cut") for column in frame.columns)
    assert frame.index.names == ["date", "reference_start", "target_range"]


def test_a_live_pull_produces_ingestable_rows():
    """
    A handful of windows days from opening collapse into a single bin and
    carry zero dispersion, which is the data telling the truth rather than a
    parse failure. The study skips those rather than dividing by them, so the
    assertion here is that dispersion exists and is never negative.
    """
    rows = atlanta_mpt.to_rows(atlanta_mpt.parse(atlanta_mpt.fetch()))
    dispersions = [row["distribution"]["std_bps"] for row in rows]

    assert len(rows) > 1000
    assert all(row["available_at"] > row["effective_time"] for row in rows)
    assert all(value is not None and value >= 0 for value in dispersions)
    assert sum(value > 0 for value in dispersions) / len(dispersions) > 0.99
