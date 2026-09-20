import argparse
from datetime import date, datetime, timezone

from basis import db, instruments
from basis.lanes import bars as bars_lane
from basis.lanes import reconcile as reconcile_lane
from basis.lanes import calendar as calendar_lane
from basis.sources import (
    atlanta_mpt,
    cftc,
    ecb,
    edgar,
    fomc,
    oanda,
    oanda_stream,
    yahoo,
)


def collect_cftc(since: date | None) -> None:
    payload = cftc.fetch(since=since)
    rows = cftc.to_rows(payload)

    with db.connect() as conn:
        db.upsert_source(
            conn,
            cftc.SOURCE_ID,
            "positioning",
            "CFTC",
            True,
            "Commitments of Traders, released Friday 15:30 ET for Tuesday positions",
        )
        written = cftc.ingest(conn, rows)
        conn.commit()

    print(f"cftc: {len(rows)} fetched, {written} new")


def collect_mpt(path: str | None) -> None:
    content = path if path else atlanta_mpt.fetch()
    rows = atlanta_mpt.to_rows(atlanta_mpt.parse(content))

    with db.connect() as conn:
        db.upsert_source(
            conn,
            atlanta_mpt.SOURCE_ID,
            "expectation",
            "Federal Reserve Bank of Atlanta",
            True,
            "Market Probability Tracker, CME three month SOFR options",
        )
        written = atlanta_mpt.ingest(conn, rows)
        conn.commit()

    print(f"atlanta mpt: {len(rows)} distributions, {written} new")


def collect_fed_text(since: date | None) -> None:
    from basis.sources import fed_text

    with db.connect() as conn:
        rows = conn.execute(
            """
            select distinct on (event_key) event_key, scheduled_time
            from basis.calendar_event
            where event_code = 'FOMC_DECISION' and scheduled_time < now()
              and (%s::date is null or scheduled_time >= %s::date)
            order by event_key, available_at desc
            """,
            (since, since),
        ).fetchall()

    decisions = sorted(row["scheduled_time"].date() for row in rows)
    documents, missing = fed_text.collect(decisions)

    with db.connect() as conn:
        db.upsert_source(
            conn,
            fed_text.SOURCE_ID,
            "text",
            "Federal Reserve",
            True,
            "FOMC statements at the decision, minutes three weeks later",
        )
        written = fed_text.ingest(conn, documents)
        conn.commit()

    print(
        f"fomc text: {len(decisions)} meetings, {len(documents)} documents, "
        f"{written} new, {len(missing)} without a page"
    )


def collect_calendar() -> None:
    fomc_rows = fomc.to_calendar_rows(fomc.parse(fomc.fetch_page()))
    ecb_rows = ecb.to_calendar_rows(ecb.parse(ecb.fetch_page()))

    with db.connect() as conn:
        db.upsert_source(conn, fomc.SOURCE_ID, "calendar", "Federal Reserve", True)
        db.upsert_source(conn, ecb.SOURCE_ID, "calendar", "European Central Bank", True)
        written = calendar_lane.ingest(conn, fomc.SOURCE_ID, fomc_rows)
        written += calendar_lane.ingest(conn, ecb.SOURCE_ID, ecb_rows)
        conn.commit()

    print(f"calendar: {len(fomc_rows)} FOMC, {len(ecb_rows)} ECB, {written} new")


def collect_edgar_index() -> None:
    """
    The whole ticker to company map, which is what search reads. One request
    for every listed name, so it is a minute of work once a quarter rather than
    a lookup on the path of a keystroke.
    """
    with db.connect() as conn, edgar.open_client() as client:
        db.upsert_source(
            conn,
            edgar.SOURCE_ID,
            "text",
            "SEC EDGAR",
            True,
            "filings with acceptance timestamps, item 2.02 marks a results release",
        )
        conn.commit()

        rows = edgar.company_names(client)
        written = edgar.ingest_companies(conn, rows)
        conn.commit()

    print(f"edgar index: {len(rows)} empresas lidas, {written} gravadas")


def collect_edgar(ticker: str, limit: int) -> None:
    """
    One company's earnings releases, as calendar events and as the text of the
    exhibit that carries the numbers. The SEC asks callers to stay under ten
    requests a second and to declare a contact, so the pause is deliberate and
    SEC_CONTACT belongs in .env before any sustained run.
    """
    import time

    ticker = ticker.upper()
    events = 0
    documents = 0

    with db.connect() as conn, edgar.open_client() as client:
        db.upsert_source(
            conn,
            edgar.SOURCE_ID,
            "text",
            "SEC EDGAR",
            True,
            "filings with acceptance timestamps, item 2.02 marks a results release",
        )
        conn.commit()

        found = edgar.tickers(client)
        if ticker not in found:
            print(f"edgar: ticker {ticker} desconhecido")
            return

        payload = edgar.submissions(client, found[ticker])
        history = edgar.all_filings(client, payload)
        releases = sorted(
            edgar.earnings_releases(history),
            key=lambda row: row["accepted_at"],
            reverse=True,
        )[:limit]
        print(f"edgar {ticker}: {payload['name']}, {len(releases)} releases")

        events = edgar.ingest_events(conn, releases)
        conn.commit()

        for release in releases:
            body, filename = edgar.fetch_release(client, release)
            written = edgar.ingest_document(conn, release, body)
            documents += written
            conn.commit()
            mark = "novo" if written else "ja tinha"
            print(
                f"  {release['accepted_at']:%Y-%m-%d %H:%M} {filename:28} "
                f"{len(body):>7} chars  {mark}"
            )
            time.sleep(0.15)

    print(f"edgar {ticker}: {events} eventos novos, {documents} documentos novos")


def collect_edgar_facts(ticker: str) -> None:
    """
    What the company reported, as numbers rather than as prose.

    The release text already collected says the quarter out loud and cannot be
    computed with. XBRL says the same quarter in a form that can, and stamps
    every fact with the filing that stated it, which is what lets an
    expectation be built from only the filings that existed at the time.

    One request per measure, which the SEC's rate limit swallows easily for one
    company and would not for the whole index, so this is deliberately per
    ticker rather than a sweep.
    """
    import time

    ticker = ticker.upper()

    with db.connect() as conn, edgar.open_client() as client:
        found = conn.execute(
            "select ticker, cik, name from basis.company where ticker = %s",
            (ticker,),
        ).fetchone()

        if found is None:
            print(f"edgar: {ticker} nao esta no indice, rode collect edgar-index")
            return

        db.upsert_source(
            conn,
            edgar.SOURCE_ID,
            "text",
            "SEC EDGAR",
            True,
            "filings with acceptance timestamps, item 2.02 marks a results release",
        )
        conn.commit()

        payload = edgar.submissions(client, found["cik"])
        history = edgar.all_filings(client, payload)
        acceptance = {row["accession"]: row["accepted_at"] for row in history}

        """
        The releases are written here as well as the facts, because a number
        without the instant it was published at cannot be studied and an
        instant without a number cannot be measured against anything. One
        command leaves a company ready for both.
        """
        releases = edgar.earnings_releases(history)
        events = edgar.ingest_events(conn, releases)
        conn.commit()

        print(
            f"edgar {ticker}: {found['name']}, {len(history)} filings, "
            f"{len(releases)} releases, {events} eventos novos"
        )

        total = 0
        for measure in edgar.CONCEPTS:
            rows = edgar.reported(client, found["cik"], [measure])
            written = edgar.ingest_facts(conn, found["cik"], rows, acceptance)
            conn.commit()
            total += written

            concept = rows[0]["concept"] if rows else "nenhum conceito responde"
            print(f"  {measure:<20} {len(rows):>5} fatos  {written:>5} novos  {concept}")
            time.sleep(0.15)

    print(f"edgar {ticker}: {total} fatos novos")


def build_expectations(ticker: str | None, quiet: bool = False) -> None:
    """
    One expectation per earnings release, for every release whose company has
    enough filed history behind it to form one. Without a ticker it runs over
    every company collected, which is what the study reads.
    """
    from basis.lanes import expectation as lane
    from basis.study import earnings

    ticker = ticker.upper() if ticker else None

    with db.connect() as conn:
        db.upsert_source(
            conn,
            lane.SOURCE_ID,
            "expectation",
            "Basis",
            False,
            "same quarter a year ago carried forward by the drift of the four since",
        )
        conn.commit()

        built = earnings.build(conn, ticker)
        conn.commit()

    if not quiet:
        for row in built["rows"]:
            print(
                f"  {row['ticker']:<6} {row['accepted_at']:%Y-%m-%d}  {row['period_end']}  "
                f"{row['measure']:<12} esperado {row['expected']:>16,.2f}  "
                f"realizado {row['actual']:>16,.2f}  z {row['surprise']:>6.2f}  "
                f"{row['rule']}"
            )

    print(
        f"{ticker or 'todas'}: {built['written']} expectativas novas, "
        f"{len(built['rows'])} eventos com surpresa, "
        f"{built['skipped']} sem historico suficiente"
    )


def backfill_oanda(instrument: str, granularity: str, start: date, end: date) -> None:
    from datetime import datetime, time, timezone

    begin = datetime.combine(start, time(), tzinfo=timezone.utc)
    finish = datetime.combine(end, time(), tzinfo=timezone.utc)
    total = 0
    pages = 0

    with db.connect() as conn, oanda.open_client() as client:
        db.upsert_source(conn, oanda.SOURCE_ID, "price", "OANDA", False, "v20 practice")
        instruments.ensure(conn)
        conn.commit()

        for page in oanda.backfill(client, instrument, granularity, begin, finish):
            with db.connect() as page_conn:
                total += bars_lane.ingest(
                    page_conn, instrument, oanda.SOURCE_ID, granularity, page
                )
                page_conn.commit()
            pages += 1
            if pages % 20 == 0:
                print(f"  {pages} paginas, {total} barras, ate {page['ts'].max()}")

    print(f"oanda {instrument} {granularity}: {pages} paginas, {total} barras novas")


def backfill_yahoo(ticker: str, name: str, start: date, end: date) -> None:
    """
    Bars and corporate actions in one pass, because the actions are what say
    which units the bars are in. Fetching them separately would leave a window
    where the series is stored and nothing records how it was scaled.
    """
    ticker = ticker.upper()

    with db.connect() as conn, yahoo.open_client() as client:
        db.upsert_source(
            conn,
            yahoo.SOURCE_ID,
            "price",
            "Yahoo Finance",
            False,
            "unofficial chart endpoint, split-restated series, no service guarantee",
        )
        instruments.register_equity(conn, ticker, name or ticker)
        conn.commit()

        result = yahoo.fetch(client, ticker, start, end)

        drift = yahoo.units_drift(conn, ticker, result)
        if drift:
            print(f"  aviso: {drift}")
            print("  as barras armazenadas estao noutra escala, reescrita e decisao sua")
            return

        frame = yahoo.bars(result)
        events = yahoo.actions(result)

        written = yahoo.ingest_bars(conn, ticker, "D", frame)
        recorded = yahoo.ingest_actions(conn, ticker, events)
        conn.commit()

    splits = [e for e in events if e["action_type"] == "split"]
    span = f"{frame['ts'].min():%Y-%m-%d} a {frame['ts'].max():%Y-%m-%d}" if len(frame) else "vazio"
    print(f"yahoo {ticker}: {len(frame)} barras ({span}), {written} novas")
    print(f"  acoes corporativas: {recorded} novas de {len(events)}, {len(splits)} desdobramentos")
    for event in splits:
        ratio = event["numerator"] / event["denominator"]
        print(f"    {event['effective_date']} desdobramento {ratio:g}:1")


def run_reconcile(day: date, hours: list[int]) -> None:
    from datetime import datetime, time, timezone

    moments = [
        datetime.combine(day, time(hour), tzinfo=timezone.utc) for hour in hours
    ]
    frame = reconcile_lane.report(moments)

    if frame.empty:
        print("reconcile: no overlapping data")
        return

    pandas_options = {"index": False, "float_format": lambda v: f"{v:.3f}"}
    print(frame.to_string(**pandas_options))
    print()
    print(f"mid agreement, worst case across hours: {frame['mid_worst_pips'].max():.3f} pips")
    print(f"spread ratio, oanda over dukascopy:     {frame['spread_ratio'].mean():.1f}x")


def run_stream(instrument: str, seconds: int | None) -> None:
    import time as _time

    from basis.config import settings
    from basis.lanes.tick_writer import TickWriter

    started = _time.monotonic()
    stop = (lambda: _time.monotonic() - started >= seconds) if seconds else None
    received = 0

    with TickWriter(settings.basis_parquet_root, oanda_stream.SOURCE_ID, instrument) as writer:
        try:
            for tick in oanda_stream.stream([instrument], stop=stop):
                writer.add(tick)
                received += 1
                if received % 500 == 0:
                    print(f"  {received} ticks, {writer.written} gravados")
        except KeyboardInterrupt:
            print("interrompido")

    print(f"stream {instrument}: {received} ticks recebidos, {writer.written} gravados")


def run_recorder(instrument: str) -> None:
    """
    Under pythonw there is no console to print a traceback to, so a failure
    before the logger exists would leave nothing behind at all. The crash file
    is the only trace a scheduled task gets of an import that went wrong.
    """
    import traceback
    from pathlib import Path

    from basis.config import settings

    try:
        from basis.lanes.recorder import Recorder

        Recorder(
            settings.basis_parquet_root,
            instrument,
            settings.recorder_heartbeat_path,
            settings.recorder_log_path,
            settings.recorder_quote_path,
        ).run()
    except Exception:
        crash = Path(settings.basis_var_root) / "recorder-crash.log"
        crash.parent.mkdir(parents=True, exist_ok=True)
        with crash.open("a", encoding="utf-8") as handle:
            handle.write(f"\n{datetime.now(timezone.utc).isoformat()}\n")
            handle.write(traceback.format_exc())
        raise


def _dry_run(pending: list[dict]) -> None:
    """
    Everything a paid run would do except the call. The character count is a
    crude token proxy, deliberately: an exact count needs the API, and the
    point of this command is to say what a run costs before anyone has a key.
    """
    import json

    from basis.sources import claude_labeller

    characters = sum(len(claude_labeller.PROMPT.format(body=d["body"])) for d in pending)
    tokens = characters / 4

    print(f"  model          {claude_labeller.MODEL} at effort {claude_labeller.EFFORT}")
    print(f"  version        {claude_labeller.LABELLER_VERSION}")
    print(f"  documents      {len(pending)}")
    print(f"  input          about {tokens/1000:.0f}k tokens, roughly ${tokens/1e6*5:.2f}")
    print()
    print("  first request, verbatim except the document body:")
    sample = claude_labeller.request_params("<document body>")
    sample["messages"][0]["content"] = sample["messages"][0]["content"][:0] or "<prompt>"
    print("   ", json.dumps(sample, indent=2).replace("\n", "\n    "))
    print()
    print("  set ANTHROPIC_API_KEY and drop --dry-run to run it")


def run_labeller(document_type: str | None, limit: int | None, dry_run: bool) -> None:
    import anthropic

    from basis.sources import claude_labeller

    with db.connect() as conn:
        pending = claude_labeller.unlabelled(conn, document_type)

    if limit:
        pending = pending[:limit]

    if not pending:
        print(f"labeller {claude_labeller.LABELLER_VERSION}: nothing to label")
        return

    if dry_run:
        print("dry run, nothing sent")
        _dry_run(pending)
        return

    print(
        f"labeller {claude_labeller.LABELLER_VERSION}: {len(pending)} documents "
        f"with model {claude_labeller.MODEL}"
    )

    client = anthropic.Anthropic()
    written = 0
    failed = []

    for document in pending:
        try:
            value = claude_labeller.label(document["body"], client)
        except Exception as exc:
            failed.append(f"{document['document_key']}: {type(exc).__name__}: {exc}")
            continue

        with db.connect() as conn:
            written += claude_labeller.store(conn, document, value)
            conn.commit()

        print(f"  {document['document_key']} {value['policy_action']}")

    print(f"labelled {written} of {len(pending)}")
    for failure in failed:
        print(f"  FAILED {failure}")


def manage_account(action: str, email: str | None, name: str | None,
                   language: str, timezone_name: str, password: str | None) -> None:
    """
    A supplied password lands in shell history, so the default is a generated
    one printed once. Both are stored the same way, as a scrypt hash with its
    own salt, and neither can be read back out.
    """
    from basis import accounts

    with db.connect() as conn:
        if action == "list":
            for account in accounts.listing(conn):
                print(
                    f"  {account.id}  {account.email:<40} {account.display_name:<20} "
                    f"{account.language}  {account.timezone}"
                )
            return

        if action == "remove":
            removed = conn.execute(
                "delete from basis.account where email = %s", (email.strip().lower(),)
            ).rowcount
            conn.commit()
            if not removed:
                raise SystemExit(f"no account for {email}")
            print(f"removed {email}")
            return

        generated = password is None
        password = password or accounts.generate_password()

        if action == "add":
            account = accounts.create(
                conn, email, name or email, password, language, timezone_name
            )
            conn.commit()
            print(f"created account {account.id} for {account.email}")
        else:
            if not accounts.set_password(conn, email, password):
                raise SystemExit(f"no account for {email}")
            conn.commit()
            print(f"password reset for {email}")

    print()
    print(f"  password: {password}")
    if generated:
        print()
        print("  Shown once. It is stored only as a scrypt hash and cannot be read back.")


def run_refresh(instrument: str) -> None:
    """
    The slow lanes catch up from wherever they stopped rather than from a fixed
    window, so a machine that was off for a week fills the week. Each lane is
    isolated: a calendar page that changed shape must not stop the bars, since
    a gap in price is the expensive one to notice late.
    """
    import traceback
    from datetime import timedelta
    from pathlib import Path

    from basis.config import settings

    log = Path(settings.basis_var_root) / "refresh.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc)
    lines = [f"\n{stamp.isoformat()} refresh {instrument}"]

    with db.connect() as conn:
        row = conn.execute(
            "select max(effective_time) as newest from basis.price_bar where instrument_id = %s",
            (instrument,),
        ).fetchone()

    newest = row["newest"] if row and row["newest"] else stamp - timedelta(days=7)
    start = (newest - timedelta(days=1)).date()
    finish = (stamp + timedelta(days=1)).date()

    for name, task in (
        ("bars", lambda: backfill_oanda(instrument, "M1", start, finish)),
        ("calendar", collect_calendar),
        ("cftc", lambda: collect_cftc(None)),
        ("mpt", lambda: collect_mpt(None)),
    ):
        try:
            task()
            lines.append(f"  {name}: ok")
        except Exception as exc:
            lines.append(f"  {name}: FAILED {type(exc).__name__}: {exc}")
            lines.append(traceback.format_exc())

    with log.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print("\n".join(lines))


def show_health() -> None:
    from basis.config import settings
    from basis.lanes import health

    with db.connect() as conn:
        report = health.inspect(conn, settings.recorder_heartbeat_path)

    session = "open" if report.open_market else "closed"
    print(f"{report.moment:%Y-%m-%d %H:%M:%S} UTC, spot market {session}")
    for finding in report.findings:
        mark = "ok  " if finding.healthy else "FAIL"
        print(f"  {mark} {finding.subject:<9} {finding.detail}")

    raise SystemExit(0 if report.healthy else 1)


def run_compaction(instrument: str) -> None:
    from datetime import datetime, timezone

    from basis.config import settings
    from basis.lanes import ticks as tick_lane
    from basis.sources import oanda_stream

    root = settings.basis_parquet_root
    today = datetime.now(timezone.utc).date()
    total = 0

    for day in tick_lane.recorded_days(root, oanda_stream.SOURCE_ID, instrument):
        if day >= today:
            continue
        chunks = tick_lane.chunk_paths(root, oanda_stream.SOURCE_ID, instrument, day)
        if not chunks:
            continue

        rows = tick_lane.compact_day(root, oanda_stream.SOURCE_ID, instrument, day)
        total += 1
        print(f"  {day} {len(chunks)} chunks into {rows} ticks")

    print(f"compact {instrument}: {total} days folded")


def show_spread_profile(baseline: float) -> None:
    from basis.config import settings
    from basis.lanes import spread_model, ticks as tick_lane

    with db.connect() as conn:
        rows = conn.execute(
            "select scheduled_time from basis.calendar_event "
            "where event_code in ('FOMC_DECISION', 'ECB_GOVERNING_COUNCIL') "
            "and scheduled_time < now() order by scheduled_time"
        ).fetchall()

    con = tick_lane.connect(settings.basis_parquet_root)
    profile = spread_model.measure_profile(
        con, [r["scheduled_time"] for r in rows], "dukascopy", "EURUSD"
    )

    if profile.empty:
        print("no tick windows measured yet")
        return

    print(f"blowout shape, multiple of each event's quiet baseline "
          f"({int(profile['events'].max())} events)")
    print("  window (s)      median     p95     max")
    for _, r in profile.iterrows():
        print(f"  [{int(r['bucket_from']):>5},{int(r['bucket_to']):>5})    "
              f"{r['median_ratio']:6.2f}  {r['p95_ratio']:6.2f}  {r['max_ratio']:6.2f}")

    print()
    print(f"scaled onto a {baseline:.2f} pip baseline")
    for seconds in (-30, 1, 5, 15, 40, 90, 300):
        estimate = spread_model.estimate(profile, baseline, seconds)
        print(f"  T{seconds:>+5}s   {estimate.pips:6.2f} pips   {estimate.provenance}")


def run_study(subject: str) -> None:
    from basis.study import report

    with db.connect() as conn:
        if subject == "fomc":
            report.render(conn)
        elif subject == "cross":
            report.render_cross(conn)
        elif subject == "earnings":
            report.render_earnings(conn)
        else:
            report.render_technical(conn)


def serve_once(host: str, port: int) -> None:
    import uvicorn

    uvicorn.run("basis.api.app:app", host=host, port=port)


def watch_and_serve(host: str, port: int) -> None:
    """
    Reload by replacing the whole process rather than by uvicorn's own watcher.

    Measured on 2026-09-13, on this machine, uvicorn 0.52.4 detects the change
    and announces it and then never replaces its worker. The old one keeps the
    connection and keeps answering, so the server returns 200 with the code from
    before the edit and nothing in the log says so. It reproduces on a six line
    ASGI app, so it is not something about this one, and both StatReload and
    WatchFiles do it.

    That failure is the worst shape a failure can take here: it does not crash,
    it disagrees with the file on disk while looking healthy. A whole process
    restart has no worker to fail to replace, so the class of bug is gone rather
    than worked around.
    """
    from pathlib import Path

    try:
        from watchfiles import run_process
    except ImportError:
        raise SystemExit(
            "serve --reload precisa de watchfiles: pip install -e \".[dev]\""
        )

    run_process(Path(__file__).parent, target=serve_once, args=(host, port))


def main() -> None:
    parser = argparse.ArgumentParser(prog="basis")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect")
    collect.add_argument(
        "source",
        choices=[
            "cftc", "calendar", "mpt", "fed-text", "edgar",
            "edgar-index", "edgar-facts",
        ],
    )
    collect.add_argument("--ticker", default=None)
    collect.add_argument("--limit", type=int, default=40)
    collect.add_argument("--since", type=date.fromisoformat, default=None)
    collect.add_argument("--path", default=None)

    study = sub.add_parser("study")
    study.add_argument("subject", choices=["fomc", "technical", "cross", "earnings"])

    expect = sub.add_parser("expect")
    expect.add_argument("--ticker", default=None)
    expect.add_argument("--quiet", action="store_true")

    labels = sub.add_parser("label")
    labels.add_argument("subject", choices=["fomc"])
    labels.add_argument("--type", dest="document_type", default=None,
                        choices=["statement", "minutes"])
    labels.add_argument("--limit", type=int, default=None)
    labels.add_argument("--dry-run", action="store_true")

    spread = sub.add_parser("spread-profile")
    spread.add_argument("--baseline", type=float, default=1.5)

    live = sub.add_parser("stream")
    live.add_argument("source", choices=["oanda"])
    live.add_argument("--instrument", default="EUR_USD")
    live.add_argument("--seconds", type=int, default=None)

    service = sub.add_parser("record")
    service.add_argument("--instrument", default="EUR_USD")

    sub.add_parser("health")

    daily = sub.add_parser("refresh")
    daily.add_argument("--instrument", default="EUR_USD")

    account = sub.add_parser("account")
    account.add_argument("action", choices=["add", "passwd", "remove", "list"])
    account.add_argument("--email", default=None)
    account.add_argument("--name", default=None)
    account.add_argument("--password", default=None)
    account.add_argument("--language", default="pt", choices=["pt", "en"])
    account.add_argument("--timezone", default="America/Sao_Paulo")

    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    fold = sub.add_parser("compact")
    fold.add_argument("--instrument", default="EUR_USD")

    check = sub.add_parser("reconcile")
    check.add_argument("--day", type=date.fromisoformat, required=True)
    check.add_argument("--hours", type=int, nargs="+", default=[9, 13, 16])

    fill = sub.add_parser("backfill")
    fill.add_argument("source", choices=["oanda", "yahoo"])
    fill.add_argument("--ticker", default=None)
    fill.add_argument("--name", default=None)
    fill.add_argument(
        "--instrument",
        default="EUR_USD",
        help="um id do registro, ou 'all' para a universo inteiro",
    )
    fill.add_argument("--granularity", default="M1")
    fill.add_argument("--start", type=date.fromisoformat, required=True)
    fill.add_argument("--end", type=date.fromisoformat, required=True)

    args = parser.parse_args()
    if args.command == "collect":
        if args.source == "cftc":
            collect_cftc(args.since)
        elif args.source == "calendar":
            collect_calendar()
        elif args.source == "edgar":
            if not args.ticker:
                raise SystemExit("collect edgar exige --ticker")
            collect_edgar(args.ticker, args.limit)
        elif args.source == "edgar-index":
            collect_edgar_index()
        elif args.source == "edgar-facts":
            if not args.ticker:
                raise SystemExit("collect edgar-facts exige --ticker")
            collect_edgar_facts(args.ticker)
        elif args.source == "mpt":
            collect_mpt(args.path)
        elif args.source == "fed-text":
            collect_fed_text(args.since)
    elif args.command == "study":
        run_study(args.subject)
    elif args.command == "expect":
        build_expectations(args.ticker, args.quiet)
    elif args.command == "label" and args.subject == "fomc":
        run_labeller(args.document_type, args.limit, args.dry_run)
    elif args.command == "spread-profile":
        show_spread_profile(args.baseline)
    elif args.command == "stream" and args.source == "oanda":
        run_stream(args.instrument, args.seconds)
    elif args.command == "record":
        run_recorder(args.instrument)
    elif args.command == "health":
        show_health()
    elif args.command == "refresh":
        run_refresh(args.instrument)
    elif args.command == "account":
        if args.action != "list" and not args.email:
            raise SystemExit("--email is required")
        manage_account(
            args.action, args.email, args.name, args.language, args.timezone,
            args.password,
        )
    elif args.command == "serve":
        if args.reload:
            watch_and_serve(args.host, args.port)
        else:
            serve_once(args.host, args.port)
    elif args.command == "compact":
        run_compaction(args.instrument)
    elif args.command == "reconcile":
        run_reconcile(args.day, args.hours)
    elif args.command == "backfill":
        if args.source == "yahoo":
            if not args.ticker:
                raise SystemExit("backfill yahoo exige --ticker")
            backfill_yahoo(args.ticker, args.name, args.start, args.end)
        else:
            targets = (
                instruments.ids() if args.instrument == "all" else [args.instrument]
            )
            for target in targets:
                backfill_oanda(target, args.granularity, args.start, args.end)


if __name__ == "__main__":
    main()
