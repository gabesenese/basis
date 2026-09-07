from decimal import Decimal

import httpx

from basis.config import settings

"""
The universe, and the rule that decides membership.

An instrument enters when the events already in the calendar explain it. A rate
announcement reaches currencies, metals, equity indices and government notes, so
each of those costs a backfill and nothing else. An individual company needs
quarterly results and a commodity needs inventory releases, so neither of those
is a wider instrument list, they are a new event universe, and they wait.

Every field here was read from the venue rather than typed from memory, on
2026-09-02, through /v3/accounts/{id}/instruments. pip_size is 10 raised to the
pipLocation the venue publishes, which it publishes for the index and note CFDs
exactly as it does for currency pairs. `verify` reads the same endpoint again
and refuses to agree that a stale constant is still true.
"""
REGISTRY = [
    {
        "id": "EUR_USD",
        "asset_class": "fx",
        "base_ccy": "EUR",
        "quote_ccy": "USD",
        "pip_size": Decimal("0.0001"),
        "display_name": "EUR/USD",
        "venue_type": "CURRENCY",
        "reason": "the reference instrument, everything measured before 2026-09-02",
    },
    {
        "id": "USD_JPY",
        "asset_class": "fx",
        "base_ccy": "USD",
        "quote_ccy": "JPY",
        "pip_size": Decimal("0.01"),
        "display_name": "USD/JPY",
        "venue_type": "CURRENCY",
        "reason": "the most rate-sensitive major, and the dollar on the other side",
    },
    {
        "id": "GBP_USD",
        "asset_class": "fx",
        "base_ccy": "GBP",
        "quote_ccy": "USD",
        "pip_size": Decimal("0.0001"),
        "display_name": "GBP/USD",
        "venue_type": "CURRENCY",
        "reason": "a second dollar leg carrying its own domestic calendar",
    },
    {
        "id": "XAU_USD",
        "asset_class": "metal",
        "base_ccy": None,
        "quote_ccy": "USD",
        "pip_size": Decimal("0.01"),
        "display_name": "Gold",
        "venue_type": "METAL",
        "reason": "the non-yielding asset, where a real rate reads directly",
    },
    {
        "id": "SPX500_USD",
        "asset_class": "index",
        "base_ccy": None,
        "quote_ccy": "USD",
        "pip_size": Decimal("1"),
        "display_name": "US SPX 500",
        "venue_type": "CFD",
        "reason": "equity duration, the other side of the same discount rate",
    },
    {
        "id": "USB02Y_USD",
        "asset_class": "bond",
        "base_ccy": None,
        "quote_ccy": "USD",
        "pip_size": Decimal("0.01"),
        "display_name": "US 2Y T-Note",
        "venue_type": "CFD",
        "reason": "the front of the curve, where a policy decision is priced",
    },
    {
        "id": "USB10Y_USD",
        "asset_class": "bond",
        "base_ccy": None,
        "quote_ccy": "USD",
        "pip_size": Decimal("0.01"),
        "display_name": "US 10Y T-Note",
        "venue_type": "CFD",
        "reason": "the long end, where the path rather than the decision is priced",
    },
    {
        "id": "DE10YB_EUR",
        "asset_class": "bond",
        "base_ccy": None,
        "quote_ccy": "EUR",
        "pip_size": Decimal("0.01"),
        "display_name": "Bund",
        "venue_type": "CFD",
        "reason": "the euro leg of the rate differential, absent from every free source",
    },
]

BY_ID = {row["id"]: row for row in REGISTRY}

REFERENCE = "EUR_USD"


def ids(asset_class: str | None = None) -> list[str]:
    return [
        row["id"]
        for row in REGISTRY
        if asset_class is None or row["asset_class"] == asset_class
    ]


def ensure(conn) -> int:
    """
    Idempotent, and deliberately not an update. Changing the pip size of an
    instrument changes the unit every measurement already stored against it was
    expressed in, so it is a migration with a relabelling attached rather than
    an upsert, and `verify` is what catches it.
    """
    written = 0
    for row in REGISTRY:
        result = conn.execute(
            """
            insert into basis.instrument
              (id, base_ccy, quote_ccy, pip_size, asset_class, display_name)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (id) do nothing
            """,
            (
                row["id"],
                row["base_ccy"],
                row["quote_ccy"],
                row["pip_size"],
                row["asset_class"],
                row["display_name"],
            ),
        )
        written += result.rowcount
    return written


def drift(client: httpx.Client) -> list[str]:
    """
    Reads the venue's own instrument list and returns one line per disagreement
    with the registry. An empty list is the only acceptable answer, because a
    pip size that moved without anyone noticing silently rescales every spread,
    every hurdle and every response already measured.
    """
    response = client.get(f"/v3/accounts/{settings.oanda_account_id}/instruments")
    response.raise_for_status()
    served = {item["name"]: item for item in response.json()["instruments"]}

    problems = []
    for row in REGISTRY:
        item = served.get(row["id"])
        if item is None:
            problems.append(f"{row['id']}: nao e servido pela conta")
            continue
        venue_pip = Decimal(10) ** int(item["pipLocation"])
        if venue_pip != row["pip_size"]:
            problems.append(
                f"{row['id']}: pip_size {row['pip_size']} no registro, "
                f"{venue_pip} na OANDA"
            )
        if item["type"] != row["venue_type"]:
            problems.append(
                f"{row['id']}: tipo {row['venue_type']} no registro, "
                f"{item['type']} na OANDA"
            )
    return problems


EQUITY_PIP = Decimal("0.01")


def register_equity(conn, ticker: str, name: str, quote_ccy: str = "USD") -> int:
    """
    Equities are registered on demand rather than listed above, because the
    universe is whichever companies the two of us are looking at this month,
    and a hardcoded list would be stale by the time it was read. The registry
    above stays a fixed set because it is what the FOMC study is measured on,
    and changing it would change what a stored measurement means.
    """
    result = conn.execute(
        """
        insert into basis.instrument
          (id, base_ccy, quote_ccy, pip_size, asset_class, display_name)
        values (%s, null, %s, %s, 'equity', %s)
        on conflict (id) do nothing
        """,
        (ticker.upper(), quote_ccy, EQUITY_PIP, name),
    )
    return result.rowcount


def equities(conn) -> list[str]:
    rows = conn.execute(
        "select id from basis.instrument where asset_class = 'equity' order by id"
    ).fetchall()
    return [row["id"] for row in rows]
