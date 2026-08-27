from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from basis.sources import claude_labeller, fed_text

EASTERN = ZoneInfo("America/New_York")

STATEMENT_PAGE = """
<html><body>
<div class="col-xs-12 col-sm-8 col-md-8">
  <p>Recent indicators suggest that economic activity has continued to expand at
  a moderate pace. The Committee decided to lower the target range for the
  federal funds rate by 1/4 percentage point. Inflation has eased over the past
  year but remains somewhat elevated. Job gains have slowed and the unemployment
  rate has moved up but remains low. The Committee judges that the risks to
  achieving its employment and inflation goals are roughly in balance. Voting
  against this action was one member who preferred no change at this meeting.
  The Committee will continue reducing its holdings of Treasury securities and
  agency mortgage backed securities.</p>
</div>
<div class="row">footer</div>
</body></html>
"""

MINUTES_PAGE = """
<html><body>
<div id="article" class="col-xs-12 col-sm-8 col-md-9">
  <p>A joint meeting of the Federal Open Market Committee was held. Participants
  observed that inflation had eased but remained above the Committee's longer
  run objective, and that labor market conditions had cooled. Several
  participants noted that the risks to the employment side of the mandate had
  increased over recent months, while others judged that inflation risks
  remained material. In their discussion of monetary policy, members agreed
  that it would be appropriate to continue reducing the size of the balance
  sheet, and that future decisions would depend on incoming data, the evolving
  outlook, and the balance of risks rather than on any preset course.</p>
</div>
<div class="col-xs-12 col-sm-4">footer</div>
</body></html>
"""


def test_the_statement_is_public_at_the_decision():
    assert fed_text.published_at(date(2026, 7, 29), fed_text.STATEMENT) == datetime.combine(
        date(2026, 7, 29), time(14, 0), tzinfo=EASTERN
    )


def test_the_minutes_follow_three_weeks_later():
    released = fed_text.published_at(date(2024, 9, 18), fed_text.MINUTES)

    assert released.date() == date(2024, 10, 9)
    assert released.timetz() == time(14, 0, tzinfo=EASTERN)


def test_a_release_landing_on_a_holiday_is_pushed_later_never_earlier():
    released = fed_text.published_at(date(2025, 12, 4), fed_text.MINUTES)

    assert released.date() >= date(2025, 12, 25)
    assert released.date().weekday() < 5


def test_the_minutes_never_claim_to_precede_their_meeting():
    decision = date(2026, 3, 18)

    assert fed_text.published_at(decision, fed_text.MINUTES) > fed_text.published_at(
        decision, fed_text.STATEMENT
    )


def test_both_page_layouts_parse():
    assert "lower the target range" in fed_text.parse(STATEMENT_PAGE)
    assert "joint meeting" in fed_text.parse(MINUTES_PAGE)


def test_a_layout_change_raises_rather_than_capturing_the_navigation():
    with pytest.raises(ValueError):
        fed_text.parse("<html><body><nav>Home About Contact</nav></body></html>")


def test_a_body_too_short_to_be_a_statement_raises():
    short = '<div class="col-xs-12 col-sm-8 col-md-8">too short</div><div class="row">'

    with pytest.raises(ValueError):
        fed_text.parse(short)


def test_the_document_key_carries_the_meeting_and_the_kind():
    document = fed_text.to_document(date(2025, 9, 17), fed_text.STATEMENT, "x" * 500)

    assert document["document_key"] == "FOMC_STATEMENT_2025-09-17"
    assert document["event_key"] == "FOMC_2025-09-17"


def test_the_body_hash_changes_with_the_body():
    first = fed_text.to_document(date(2025, 9, 17), fed_text.STATEMENT, "a" * 500)
    second = fed_text.to_document(date(2025, 9, 17), fed_text.STATEMENT, "b" * 500)

    assert first["body_sha256"] != second["body_sha256"]


def test_a_document_revised_after_publication_fails_loudly(db_conn):
    """
    A changed hash under an existing key means the Fed edited something after
    publishing it. Overwriting quietly would rewrite history the backtest has
    already read.
    """
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    from basis import db as db_module
    from basis.config import settings

    conn = psycopg.connect(settings.basis_database_url, row_factory=dict_row)
    try:
        db_module.upsert_source(conn, fed_text.SOURCE_ID, "text", "Federal Reserve", True)
        original = fed_text.to_document(date(1999, 1, 1), fed_text.STATEMENT, "o" * 500)
        fed_text.ingest(conn, [original])

        revised = fed_text.to_document(date(1999, 1, 1), fed_text.STATEMENT, "r" * 500)
        with pytest.raises(ValueError, match="changed after publication"):
            fed_text.ingest(conn, [revised])
    finally:
        conn.rollback()
        conn.close()


def test_the_labeller_digest_covers_prompt_schema_and_body():
    first = claude_labeller.input_digest("body one")
    second = claude_labeller.input_digest("body two")

    assert first != second
    assert claude_labeller.input_digest("body one") == first


def test_the_schema_refuses_fields_it_did_not_ask_for():
    assert claude_labeller.SCHEMA["additionalProperties"] is False
    assert set(claude_labeller.SCHEMA["required"]) == set(
        claude_labeller.SCHEMA["properties"]
    )


def test_the_schema_has_no_hawkish_or_dovish_judgement():
    """
    The one reading that hindsight would contaminate is deliberately absent.
    Whether a statement was a surprise is for price to answer, not for a model
    that already knows what price did.
    """
    fields = " ".join(claude_labeller.SCHEMA["properties"]).lower()

    assert "hawkish" not in fields
    assert "dovish" not in fields
    assert "surprise" not in fields


def test_every_answer_option_includes_a_way_to_say_the_text_did_not_say_it():
    properties = claude_labeller.SCHEMA["properties"]

    for field in ("inflation_language", "labor_language", "growth_language"):
        assert "not_characterised" in properties[field]["enum"]
    assert "not_stated" in properties["policy_action"]["enum"]
    assert "not_stated" in properties["risk_balance"]["enum"]
