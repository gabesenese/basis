import hashlib
import html
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from psycopg.types.json import Jsonb

from basis.config import settings

SOURCE_ID = "sec_edgar"

BASE = "https://data.sec.gov"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data"

"""
EDGAR is the only source in this project that carries the bitemporal contract on
its own. `acceptanceDateTime` is the instant a filing became public, stamped to
the second by the publisher, which is exactly what available_at is defined to be
and is the one field that normally has to be reconstructed by hand.

The XBRL side goes further: every reported fact carries both the period it
describes and the date it was filed, so a balance sheet can be read as it was
reported at the time rather than as later restated. Nothing else here supplies a
vintage without being asked twice.
"""

"""
Acceptance is the only field on a filing that is always an instant which has
already passed, and it is the reason nothing here uses reportDate as a
timestamp. On a proxy statement reportDate is the annual meeting, which is still
weeks away when the proxy is filed: seven of NVIDIA's own filings carry a
reportDate between 43 and 55 days after they were accepted. Treating that field
as an effective_time would write facts dated in the future.
"""

EARNINGS_ITEM = "2.02"

PERIODIC_FORMS = ("10-K", "10-Q")

"""
Companies do not agree on which XBRL concept a number lives under, and the
disagreement is not cosmetic: reading Apple's revenue under `Revenues` returns
eleven observations and misses every recent year, while reading NVIDIA's under
`RevenueFromContractWithCustomerExcludingAssessedTax` returns a five year stub
that stops in 2022 and hides the decade around it.

So a measure is a list of candidates and the one that answers for the longest
is the one taken, rather than the first that answers at all. Order alone would
have handed NVIDIA the stub, since it does answer, and a series that ends in
2022 is worse than no series because it looks like one. The concept that won is
recorded beside every value it produced, so a later reader can see which
definition is being read and can tell two companies apart.
"""
CONCEPTS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
}


def _headers() -> dict:
    return {
        "User-Agent": settings.sec_user_agent,
        "Accept-Encoding": "gzip, deflate",
    }


def open_client() -> httpx.Client:
    return httpx.Client(headers=_headers(), timeout=httpx.Timeout(30.0, read=60.0))


def tickers(client: httpx.Client) -> dict[str, str]:
    """
    The ticker to CIK map, which is the only way in. CIK is zero padded to ten
    digits everywhere in the API and unpadded in the archive paths, so both
    forms are needed and the padding is done at the call site rather than
    stored, to keep one representation in the database.
    """
    response = client.get("https://www.sec.gov/files/company_tickers.json")
    response.raise_for_status()
    return {
        row["ticker"].upper(): str(row["cik_str"])
        for row in response.json().values()
    }


def submissions(client: httpx.Client, cik: str) -> dict:
    response = client.get(f"{BASE}/submissions/CIK{int(cik):010d}.json")
    response.raise_for_status()
    return response.json()


def filings(payload: dict) -> list[dict]:
    """
    The recent block flattened into rows. Every row carries the acceptance
    instant parsed to an aware datetime, because a naive one would be read as
    local time on a machine that is not in New York and would silently move
    every filing by hours.
    """
    recent = payload["filings"]["recent"]
    count = len(recent["accessionNumber"])

    rows = []
    for index in range(count):
        accepted = recent["acceptanceDateTime"][index]
        rows.append(
            {
                "cik": str(payload["cik"]),
                "ticker": (payload.get("tickers") or [None])[0],
                "company": payload.get("name"),
                "accession": recent["accessionNumber"][index],
                "form": recent["form"][index],
                "items": recent["items"][index],
                "filing_date": recent["filingDate"][index],
                "report_date": recent["reportDate"][index] or None,
                "primary_document": recent["primaryDocument"][index],
                "accepted_at": datetime.fromisoformat(
                    accepted.replace("Z", "+00:00")
                ),
            }
        )
    return rows


def all_filings(client: httpx.Client, payload: dict) -> list[dict]:
    """
    The whole filing history rather than the last thousand rows of it.

    `recent` holds a thousand filings and nothing says how far back that
    reaches, because it depends on how much a company files. Apple's thousand
    go back to 2015 and NVIDIA's stop in 2020, since NVIDIA's insiders file
    more often than Apple's, and a study that took what recent offered would
    have given one company eleven years of results and the other five for a
    reason that has nothing to do with either company.

    The older pages are published beside it and are read in full here, which is
    a handful of extra requests once per company.
    """
    rows = filings(payload)

    for page in payload["filings"].get("files") or []:
        response = client.get(f"{BASE}/submissions/{page['name']}")
        response.raise_for_status()
        rows.extend(
            filings(
                {
                    "cik": payload["cik"],
                    "name": payload.get("name"),
                    "tickers": payload.get("tickers"),
                    "filings": {"recent": response.json()},
                }
            )
        )

    return sorted(rows, key=lambda row: row["accepted_at"])


def earnings_releases(rows: list[dict]) -> list[dict]:
    """
    An 8-K carrying item 2.02 is a results of operations release. Identifying it
    by the item code rather than by reading the prose is the difference between
    a rule and a guess, and the code is published in the same payload.
    """
    return [
        row
        for row in rows
        if row["form"].startswith("8-K")
        and EARNINGS_ITEM in (row["items"] or "").split(",")
    ]


def periodic_reports(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row["form"] in PERIODIC_FORMS]


def _folder(row: dict) -> str:
    return f"{ARCHIVE}/{int(row['cik'])}/{row['accession'].replace('-', '')}"


def document_url(row: dict, filename: str | None = None) -> str:
    return f"{_folder(row)}/{filename or row['primary_document']}"


DOCUMENT_BLOCK = re.compile(
    r"<TYPE>([^\r\n<]+)\s*<SEQUENCE>([^\r\n<]+)\s*<FILENAME>([^\r\n<]+)"
)

RELEASE_TYPES = ("EX-99.1", "EX-99", "EX-99.2")


def documents(client: httpx.Client, row: dict) -> list[dict]:
    """
    The filing's own manifest, which is the only authoritative statement of what
    each attached file is. The header serves it with the SGML tags escaped, so it
    is unescaped before matching rather than matched with a looser pattern.
    """
    response = client.get(
        f"{_folder(row)}/{row['accession']}-index-headers.html"
    )
    response.raise_for_status()

    body = html.unescape(response.text)
    return [
        {"type": kind.strip(), "sequence": int(sequence), "filename": name.strip()}
        for kind, sequence, name in DOCUMENT_BLOCK.findall(body)
    ]


def release_document(documents: list[dict]) -> dict | None:
    """
    An 8-K announcing results is a cover page that incorporates the release by
    reference, so its primary document carries no numbers at all. The press
    release is an exhibit, conventionally EX-99.1, and storing the cover page
    instead would hand the labeller a document with nothing in it to cite.
    """
    for kind in RELEASE_TYPES:
        for document in sorted(documents, key=lambda d: d["sequence"]):
            if document["type"].upper() == kind and document["filename"].lower().endswith(
                (".htm", ".html", ".txt")
            ):
                return document
    return None


TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"[ \t\r\f\v]+")
BLANK = re.compile(r"\n{3,}")


def fetch_document(client: httpx.Client, row: dict, filename: str | None = None) -> str:
    """
    Strips markup and leaves the text. The labeller's rule is that every field
    cites a verbatim quote from the document, so what is stored has to be what
    the model was shown, which means the stripping happens once here rather than
    differently at each read.
    """
    response = client.get(document_url(row, filename))
    response.raise_for_status()

    body = response.text
    body = re.sub(r"(?is)<(script|style).*?</\1>", " ", body)
    body = TAG.sub(" ", body)

    """
    Entities are decoded after the tags are stripped and never before. An escaped
    &lt;b&gt; inside the text would otherwise become a real tag on the way past
    the stripper and be deleted along with the words around it.
    """
    body = html.unescape(body).replace("\xa0", " ")
    body = SPACE.sub(" ", body)
    body = "\n".join(line.strip() for line in body.splitlines())
    return BLANK.sub("\n\n", body).strip()


def concept(client: httpx.Client, cik: str, name: str) -> dict | None:
    """
    One concept for one company. A 404 here is an ordinary result rather than a
    failure: it means this company does not report under that tag.
    """
    response = client.get(
        f"{BASE}/api/xbrl/companyconcept/CIK{int(cik):010d}/us-gaap/{name}.json"
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def periods(payload: dict) -> int:
    """
    How many distinct periods a concept covers, which is the measure of whether
    it is this company's definition or a tag it used for two years.
    """
    return len({fact["period_end"] for fact in facts(payload)})


def widest_concept(
    client: httpx.Client, cik: str, names: list[str]
) -> tuple[str, dict] | None:
    found = []
    for name in names:
        payload = concept(client, cik, name)
        if payload is None:
            continue
        found.append((periods(payload), name, payload))

    if not found:
        return None

    """
    Ties break on the order the candidates were listed, which is the order they
    are preferred in, so a company reporting the same span under two tags gets
    the one this project considers the more specific definition.
    """
    best = max(found, key=lambda item: (item[0], -names.index(item[1])))
    return best[1], best[2]


def facts(payload: dict, unit: str | None = None) -> list[dict]:
    """
    Flattens one concept into rows. `filed` is kept and becomes available_at,
    because a fact for the quarter ending in March that was filed in May was not
    knowable in April, and a restatement filed a year later is a second row
    rather than a correction of the first.
    """
    units = payload.get("units", {})
    chosen = unit or next(iter(units), None)
    if chosen is None:
        return []

    rows = []
    for item in units[chosen]:
        rows.append(
            {
                "unit": chosen,
                "period_start": item.get("start"),
                "period_end": item["end"],
                "value": item["val"],
                "fiscal_year": item.get("fy"),
                "fiscal_period": item.get("fp"),
                "form": item.get("form"),
                "filed": item["filed"],
                "accession": item.get("accn"),
                "frame": item.get("frame"),
            }
        )
    return rows


"""
A fact's vintage is the day it was filed, and a day is not an instant. Writing
it as midnight would claim the number was readable eight hours before anyone
could have read it, which is the one direction this schema refuses.

Two ways out, and both are used. The submission history carries the acceptance
instant for every filing, so an accession found there is stamped to the second
by the publisher. An accession that is not there, which happens once a company
has filed past the thousand rows the recent block holds, falls back to the end
of the filing day in New York. That is late rather than early, so a backtest is
denied something the market already had and is never handed something it did
not.
"""
FILING_ZONE = ZoneInfo("America/New_York")


def acceptance_instants(payload: dict) -> dict[str, datetime]:
    return {row["accession"]: row["accepted_at"] for row in filings(payload)}


def available_from(filed: str, accepted: datetime | None) -> tuple[datetime, str]:
    if accepted is not None:
        return accepted, "acceptance"

    day = date.fromisoformat(filed) + timedelta(days=1)
    return datetime.combine(day, time.min, FILING_ZONE), "filing_day_end"


def reported(client: httpx.Client, cik: str, measures: list[str] | None = None) -> list[dict]:
    """
    Every measure this project knows how to read, for one company, as flat
    rows carrying the concept that answered.

    Every candidate concept is asked, and the one covering the most periods is
    kept whole. Asking all of them is what makes the choice a measurement
    rather than a guess, and keeping only one is what stops a company reporting
    the same quarter twice under two definitions from becoming two series
    stitched into one.
    """
    rows = []
    for measure in measures or list(CONCEPTS):
        found = widest_concept(client, cik, CONCEPTS[measure])
        if found is None:
            continue
        name, payload = found
        for fact in facts(payload):
            rows.append({**fact, "measure": measure, "concept": name})
    return rows


def ingest_facts(
    conn, cik: str, rows: list[dict], acceptance: dict[str, datetime]
) -> int:
    written = 0
    for row in rows:
        moment, stamp = available_from(
            row["filed"], acceptance.get(row["accession"])
        )
        result = conn.execute(
            """
            insert into basis.company_fact
              (cik, measure, concept, unit, period_start, period_end,
               fiscal_year, fiscal_period, form, accession, value, filed,
               available_at, stamp)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict do nothing
            """,
            (
                str(int(cik)),
                row["measure"],
                row["concept"],
                row["unit"],
                row["period_start"],
                row["period_end"],
                row["fiscal_year"],
                row["fiscal_period"],
                row["form"],
                row["accession"],
                row["value"],
                row["filed"],
                moment,
                stamp,
            ),
        )
        written += result.rowcount
    return written


def event_key(row: dict) -> str:
    return f"EARN:{row['ticker'] or row['cik']}:{row['report_date'] or row['filing_date']}"


def ingest_events(conn, rows: list[dict]) -> int:
    """
    An earnings release is written as a calendar event whose scheduled_time and
    available_at are both the acceptance instant. That is honest rather than
    lazy: the release was not scheduled to the second in advance, and the moment
    it became public is the only instant about it that is a fact.
    """
    written = 0
    for row in rows:
        result = conn.execute(
            """
            insert into basis.calendar_event
              (event_key, source_id, region, event_code, scheduled_time,
               available_at, payload)
            values (%s, %s, 'US', 'EARNINGS_RELEASE', %s, %s, %s)
            on conflict (event_key, available_at) do nothing
            """,
            (
                event_key(row),
                SOURCE_ID,
                row["accepted_at"],
                row["accepted_at"],
                Jsonb(
                    {
                        "cik": row["cik"],
                        "ticker": row["ticker"],
                        "company": row["company"],
                        "form": row["form"],
                        "items": row["items"],
                        "accession": row["accession"],
                        "report_date": row["report_date"],
                    }
                ),
            ),
        )
        written += result.rowcount
    return written


def ingest_document(conn, row: dict, body: str) -> int:
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    result = conn.execute(
        """
        insert into basis.text_document
          (document_key, source_id, event_key, document_type, published_at,
           body, body_sha256)
        values (%s, %s, %s, %s, %s, %s, %s)
        on conflict (document_key) do nothing
        """,
        (
            row["accession"],
            SOURCE_ID,
            event_key(row),
            "earnings_release" if row["form"].startswith("8-K") else row["form"],
            row["accepted_at"],
            body,
            digest,
        ),
    )
    return result.rowcount


def fetch_release(client: httpx.Client, row: dict) -> tuple[str, str]:
    """
    Returns the text and the filename it came from, so what was read is
    recoverable later. Falling back to the primary document is deliberate and
    visible in the returned name rather than silent.
    """
    chosen = release_document(documents(client, row))
    filename = chosen["filename"] if chosen else row["primary_document"]
    return fetch_document(client, row, filename), filename


def company_names(client: httpx.Client) -> list[dict]:
    """
    The same file `tickers` reads, kept whole rather than reduced to a mapping.

    Search needs the printed name as well as the symbol, because a reader who
    remembers a company remembers what it is called far more often than what it
    trades as. The file is one request and about ten thousand rows, so it is
    stored rather than fetched per keystroke.
    """
    response = client.get("https://www.sec.gov/files/company_tickers.json")
    response.raise_for_status()
    return [
        {
            "ticker": row["ticker"].upper(),
            "cik": str(row["cik_str"]),
            "name": row["title"],
        }
        for row in response.json().values()
    ]


def ingest_companies(conn, rows: list[dict]) -> int:
    """
    A company that changes its name keeps its ticker and its CIK, and the new
    name is the one to search by, so this updates rather than skips. Nothing
    measured hangs off these rows, which is what makes overwriting them safe
    here and unsafe in every other table in this schema.
    """
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            insert into basis.company (ticker, cik, name, source_id)
            values (%s, %s, %s, %s)
            on conflict (ticker) do update
              set cik = excluded.cik,
                  name = excluded.name,
                  collected_at = now()
            """,
            [(row["ticker"], row["cik"], row["name"], SOURCE_ID) for row in rows],
        )
        return cursor.rowcount


def find(conn, query: str, limit: int = 20) -> list[dict]:
    """
    Ranked so an exact symbol wins outright. Someone typing NVDA means the
    company that trades as NVDA, not the twenty whose printed name happens to
    contain those letters, and a search that buries the obvious answer under
    near misses is a search nobody uses twice.

    Inside a rank the shortest name wins, which is the tiebreak that puts Apple
    Inc. above Apple iSports Group. A name that is almost exactly the term is a
    closer match than one that merely starts with it, and length is what
    measures that without a similarity index.
    """
    term = query.strip().upper()
    if not term:
        return []

    rows = conn.execute(
        """
        select ticker, cik, name,
               case
                 when ticker = %(exact)s then 0
                 when ticker like %(prefix)s then 1
                 when upper(name) like %(prefix)s then 2
                 else 3
               end as rank
        from basis.company
        where ticker like %(prefix)s or upper(name) like %(anywhere)s
        order by rank, length(name), length(ticker), ticker
        limit %(limit)s
        """,
        {
            "exact": term,
            "prefix": f"{term}%",
            "anywhere": f"%{term}%",
            "limit": limit,
        },
    ).fetchall()

    return [
        {"ticker": row["ticker"], "cik": row["cik"], "name": row["name"]}
        for row in rows
    ]
