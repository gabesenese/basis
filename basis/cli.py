import argparse
from datetime import date, datetime, timezone

from basis import db
from basis.lanes import bars as bars_lane
from basis.lanes import reconcile as reconcile_lane
from basis.lanes import calendar as calendar_lane
from basis.sources import atlanta_mpt, cftc, ecb, fomc, oanda, oanda_stream


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


def backfill_oanda(instrument: str, granularity: str, start: date, end: date) -> None:
    from datetime import datetime, time, timezone

    begin = datetime.combine(start, time(), tzinfo=timezone.utc)
    finish = datetime.combine(end, time(), tzinfo=timezone.utc)
    total = 0
    pages = 0

    with db.connect() as conn, oanda.open_client() as client:
        db.upsert_source(conn, oanda.SOURCE_ID, "price", "OANDA", False, "v20 practice")
        conn.execute(
            """
            insert into basis.instrument values ('EUR_USD', 'EUR', 'USD', 0.0001)
            on conflict (id) do nothing
            """
        )
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
        ).run()
    except Exception:
        crash = Path(settings.basis_var_root) / "recorder-crash.log"
        crash.parent.mkdir(parents=True, exist_ok=True)
        with crash.open("a", encoding="utf-8") as handle:
            handle.write(f"\n{datetime.now(timezone.utc).isoformat()}\n")
            handle.write(traceback.format_exc())
        raise


def manage_account(action: str, email: str | None, name: str | None,
                   language: str, timezone_name: str) -> None:
    from basis import accounts

    with db.connect() as conn:
        if action == "list":
            for account in accounts.listing(conn):
                print(
                    f"  {account.id}  {account.email:<32} {account.display_name:<20} "
                    f"{account.language}  {account.timezone}"
                )
            return

        password = accounts.generate_password()

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


def run_study() -> None:
    from basis.study import report

    with db.connect() as conn:
        report.render(conn)


def main() -> None:
    parser = argparse.ArgumentParser(prog="basis")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect")
    collect.add_argument("source", choices=["cftc", "calendar", "mpt"])
    collect.add_argument("--since", type=date.fromisoformat, default=None)
    collect.add_argument("--path", default=None)

    study = sub.add_parser("study")
    study.add_argument("subject", choices=["fomc"])

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
    account.add_argument("action", choices=["add", "passwd", "list"])
    account.add_argument("--email", default=None)
    account.add_argument("--name", default=None)
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
    fill.add_argument("source", choices=["oanda"])
    fill.add_argument("--instrument", default="EUR_USD")
    fill.add_argument("--granularity", default="M1")
    fill.add_argument("--start", type=date.fromisoformat, required=True)
    fill.add_argument("--end", type=date.fromisoformat, required=True)

    args = parser.parse_args()
    if args.command == "collect":
        if args.source == "cftc":
            collect_cftc(args.since)
        elif args.source == "calendar":
            collect_calendar()
        elif args.source == "mpt":
            collect_mpt(args.path)
    elif args.command == "study" and args.subject == "fomc":
        run_study()
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
        manage_account(args.action, args.email, args.name, args.language, args.timezone)
    elif args.command == "serve":
        import uvicorn

        uvicorn.run(
            "basis.api.app:app", host=args.host, port=args.port, reload=args.reload
        )
    elif args.command == "compact":
        run_compaction(args.instrument)
    elif args.command == "reconcile":
        run_reconcile(args.day, args.hours)
    elif args.command == "backfill" and args.source == "oanda":
        backfill_oanda(args.instrument, args.granularity, args.start, args.end)


if __name__ == "__main__":
    main()
