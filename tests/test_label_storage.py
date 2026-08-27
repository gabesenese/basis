from datetime import datetime, timedelta, timezone

import pytest

from basis.sources import claude_labeller, fed_text

PUBLISHED = datetime(2024, 9, 18, 18, 0, tzinfo=timezone.utc)
LABEL = {"policy_action": "cut", "action_size_bps": -50, "evidence": []}


@pytest.fixture
def planted():
    """
    A document and a label planted in the real database and rolled back. The
    property under test is bitemporal behaviour, which a fake connection cannot
    demonstrate.
    """
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    from basis import db as db_module
    from basis.config import settings

    try:
        conn = psycopg.connect(
            settings.basis_database_url, row_factory=dict_row, connect_timeout=3
        )
    except psycopg.OperationalError as exc:
        pytest.skip(f"basis database unavailable: {exc}")

    try:
        db_module.upsert_source(conn, fed_text.SOURCE_ID, "text", "Federal Reserve", True)
        document = conn.execute(
            """
            insert into basis.text_document
              (document_key, source_id, event_key, document_type, published_at,
               body, body_sha256)
            values ('TEST_DOC', %s, 'TEST_EVENT', 'statement', %s, %s, %s)
            returning id, published_at, body
            """,
            (fed_text.SOURCE_ID, PUBLISHED, "body " * 200, "0" * 64),
        ).fetchone()
        yield conn, document
    finally:
        conn.rollback()
        conn.close()


def test_a_label_is_credited_to_the_publication_and_not_to_the_run(planted):
    conn, document = planted
    claude_labeller.store(conn, document, LABEL)

    row = conn.execute(
        "select available_at, computed_at from basis.text_feature where document_id = %s",
        (document["id"],),
    ).fetchone()

    assert row["available_at"] == PUBLISHED
    assert row["computed_at"] > PUBLISHED


def test_relabelling_at_the_same_version_writes_nothing(planted):
    conn, document = planted

    first = claude_labeller.store(conn, document, LABEL)
    second = claude_labeller.store(conn, document, LABEL)

    assert (first, second) == (1, 0)


def test_a_label_is_invisible_before_its_document_was_published(planted):
    conn, document = planted
    claude_labeller.store(conn, document, LABEL)

    before = claude_labeller.features_as_of(conn, PUBLISHED - timedelta(seconds=1))

    assert not [row for row in before if row["event_key"] == "TEST_EVENT"]


def test_a_label_computed_today_is_visible_at_the_moment_of_publication(planted):
    """
    The whole point of mirroring available_at onto publication. A backfill run
    now must be readable by a backtest standing at the instant the text became
    public, or the text lane is useless to history.
    """
    conn, document = planted
    claude_labeller.store(conn, document, LABEL)

    at_publication = claude_labeller.features_as_of(conn, PUBLISHED, "TEST_EVENT")

    assert len(at_publication) == 1
    assert at_publication[0]["value"] == LABEL


def test_the_digest_records_what_determined_the_answer(planted):
    conn, document = planted
    claude_labeller.store(conn, document, LABEL)

    row = conn.execute(
        "select input_sha256 from basis.text_feature where document_id = %s",
        (document["id"],),
    ).fetchone()

    assert row["input_sha256"] == claude_labeller.input_digest(document["body"])


def test_a_new_version_coexists_with_the_old_one(planted):
    """
    Two versions of the labeller are two measurements, and both stay on the
    record. A study picks one; it never sees a silently overwritten answer.
    """
    conn, document = planted
    claude_labeller.store(conn, document, LABEL)

    conn.execute(
        """
        insert into basis.text_feature
          (document_id, feature_key, labeller_id, labeller_version,
           input_sha256, available_at, value)
        values (%s, %s, %s, 'policy-language-2', %s, %s, '{}'::jsonb)
        """,
        (
            document["id"], claude_labeller.FEATURE_KEY, claude_labeller.LABELLER_ID,
            "1" * 64, PUBLISHED,
        ),
    )

    versions = conn.execute(
        "select count(distinct labeller_version) as n from basis.text_feature "
        "where document_id = %s",
        (document["id"],),
    ).fetchone()

    assert versions["n"] == 2


def test_an_unlabelled_document_is_offered_and_a_labelled_one_is_not(planted):
    conn, document = planted

    before = claude_labeller.unlabelled(conn, "statement")
    claude_labeller.store(conn, document, LABEL)
    after = claude_labeller.unlabelled(conn, "statement")

    assert document["id"] in [row["id"] for row in before]
    assert document["id"] not in [row["id"] for row in after]
