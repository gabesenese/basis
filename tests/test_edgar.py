from datetime import timezone

import pytest

from basis.sources import edgar

PAYLOAD = {
    "cik": "1045810",
    "name": "NVIDIA CORP",
    "tickers": ["NVDA"],
    "filings": {
        "recent": {
            "accessionNumber": ["0001045810-26-000073", "0001045810-26-000060", "x-3"],
            "form": ["8-K", "10-Q", "8-K"],
            "items": ["2.02,9.01", "", "5.02"],
            "filingDate": ["2026-08-26", "2026-08-26", "2026-07-01"],
            "reportDate": ["2026-08-26", "2026-07-27", ""],
            "primaryDocument": ["nvda-20260826.htm", "nvda-10q.htm", "cover.htm"],
            "acceptanceDateTime": [
                "2026-08-26T20:21:19.000Z",
                "2026-08-26T20:30:00.000Z",
                "2026-07-01T12:00:00.000Z",
            ],
        }
    },
}


def test_the_acceptance_instant_is_parsed_as_utc_not_as_local_time():
    """
    A naive datetime here would be read as the machine's own timezone, which is
    not New York, and would move every filing by hours in a database whose whole
    contract is when a thing became knowable.
    """
    rows = edgar.filings(PAYLOAD)

    assert rows[0]["accepted_at"].tzinfo is not None
    assert rows[0]["accepted_at"].utcoffset() == timezone.utc.utcoffset(None)
    assert rows[0]["accepted_at"].hour == 20


def test_an_earnings_release_is_identified_by_its_item_code():
    rows = edgar.filings(PAYLOAD)
    found = edgar.earnings_releases(rows)

    assert [row["accession"] for row in found] == ["0001045810-26-000073"]


def test_an_eight_k_without_item_two_oh_two_is_not_an_earnings_release():
    rows = edgar.filings(PAYLOAD)
    other = [row for row in rows if row["items"] == "5.02"]

    assert other and not edgar.earnings_releases(other)


def test_an_item_code_is_matched_whole_rather_than_as_a_substring():
    """
    Item 2.02 and a hypothetical 12.02 share four characters. Splitting on the
    comma rather than searching the string is what keeps them apart.
    """
    row = dict(edgar.filings(PAYLOAD)[0])
    row["items"] = "12.021,9.01"

    assert not edgar.earnings_releases([row])


def test_periodic_reports_are_the_ten_q_and_ten_k():
    rows = edgar.filings(PAYLOAD)

    assert [row["form"] for row in edgar.periodic_reports(rows)] == ["10-Q"]


def test_a_missing_report_date_becomes_none_rather_than_an_empty_string():
    rows = edgar.filings(PAYLOAD)

    assert rows[2]["report_date"] is None


def test_the_event_key_falls_back_to_the_filing_date():
    rows = edgar.filings(PAYLOAD)

    assert edgar.event_key(rows[0]) == "EARN:NVDA:2026-08-26"
    assert edgar.event_key(rows[2]) == "EARN:NVDA:2026-07-01"


def test_the_press_release_exhibit_is_preferred_over_the_cover_page():
    """
    The 8-K body incorporates the release by reference and carries no numbers.
    Choosing the cover page would hand the labeller a document with nothing in
    it to cite, which its rules would then correctly refuse to label.
    """
    manifest = [
        {"type": "8-K", "sequence": 1, "filename": "nvda-20260826.htm"},
        {"type": "EX-99.1", "sequence": 2, "filename": "q2fy27pr.htm"},
        {"type": "EX-99.2", "sequence": 3, "filename": "q2fy27cfo.htm"},
        {"type": "GRAPHIC", "sequence": 7, "filename": "logo.jpg"},
    ]

    assert edgar.release_document(manifest)["filename"] == "q2fy27pr.htm"


def test_a_filing_with_no_exhibit_returns_nothing_rather_than_a_graphic():
    manifest = [
        {"type": "8-K", "sequence": 1, "filename": "cover.htm"},
        {"type": "GRAPHIC", "sequence": 2, "filename": "logo.jpg"},
    ]

    assert edgar.release_document(manifest) is None


def test_the_document_manifest_pattern_reads_the_unescaped_header():
    header = (
        "<DOCUMENT>\n<TYPE>EX-99.1\n<SEQUENCE>2\n<FILENAME>q2fy27pr.htm\n"
        "<DESCRIPTION>EX-99.1\n<TEXT>\n"
    )
    found = edgar.DOCUMENT_BLOCK.findall(header)

    assert found == [("EX-99.1", "2", "q2fy27pr.htm")]


def test_facts_keep_the_filed_date_that_makes_them_a_vintage():
    """
    The same period is reported again as a comparative in the following year's
    filing. Both rows are kept, and the filed date is the only thing that says
    which of them was knowable when.
    """
    payload = {
        "units": {
            "USD": [
                {"end": "2021-01-31", "val": 1, "fy": 2021, "fp": "FY",
                 "form": "10-K", "filed": "2021-02-26"},
                {"end": "2021-01-31", "val": 1, "fy": 2022, "fp": "FY",
                 "form": "10-K", "filed": "2022-03-18"},
            ]
        }
    }
    rows = edgar.facts(payload, "USD")

    assert len(rows) == 2
    assert [row["filed"] for row in rows] == ["2021-02-26", "2022-03-18"]


def test_facts_on_an_absent_unit_return_nothing_rather_than_raising():
    assert edgar.facts({"units": {}}) == []


@pytest.mark.live
def test_the_release_actually_carries_numbers():
    with edgar.open_client() as client:
        found = edgar.tickers(client)
        payload = edgar.submissions(client, found["NVDA"])
        releases = edgar.earnings_releases(edgar.filings(payload))
        assert releases

        body, filename = edgar.fetch_release(client, releases[0])

    assert filename.endswith((".htm", ".html", ".txt"))
    assert len(body) > 5000
    assert "Revenue" in body
    assert "&#" not in body and "&amp;" not in body


@pytest.mark.live
def test_no_studied_filing_is_accepted_before_the_period_it_reports():
    """
    For the forms this project studies, reportDate is the end of a period that
    has already closed, so acceptance after it is a hard property and a
    violation would mean available_at could precede the fact it describes.
    """
    with edgar.open_client() as client:
        found = edgar.tickers(client)
        rows = edgar.filings(edgar.submissions(client, found["NVDA"]))

    studied = edgar.earnings_releases(rows) + edgar.periodic_reports(rows)
    dated = [row for row in studied if row["report_date"]]
    assert dated

    early = [
        row for row in dated
        if row["accepted_at"].date().isoformat() < row["report_date"]
    ]

    assert not early, [row["accession"] for row in early[:5]]


@pytest.mark.live
def test_a_proxy_reports_a_future_date_and_is_why_report_date_is_not_a_timestamp():
    """
    A proxy statement's reportDate is the annual meeting, which has not happened
    yet when the proxy is filed. It is the counterexample to treating reportDate
    as an effective_time: doing that would write a fact dated in the future.
    Acceptance is the only field on a filing that is always an instant that has
    already passed.
    """
    with edgar.open_client() as client:
        found = edgar.tickers(client)
        rows = edgar.filings(edgar.submissions(client, found["NVDA"]))

    proxies = [
        row for row in rows
        if row["form"].endswith("14A")
        and row["report_date"]
        and row["accepted_at"].date().isoformat() < row["report_date"]
    ]

    assert proxies, "expected at least one proxy dated ahead of its acceptance"
