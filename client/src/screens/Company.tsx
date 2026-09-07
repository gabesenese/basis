import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useResource, useSession } from "../lib/session";
import type { CompanyBars, CompanyHead, CompanyQuote } from "../lib/api";
import {
  Card,
  CardHead,
  Empty,
  Failure,
  Loading,
  Provenance,
  Segmented,
} from "../components/primitives";
import { Candles } from "../components/candles";
import { Change } from "../components/change";
import { age, dateTime, dayOnly, money, number } from "../lib/format";

/*
  A window is a granularity and a bar count together, because they are not
  independent: a year of one minute bars is a quarter of a million rows nobody
  can read, and a day of daily bars is one candle. Naming the window rather
  than either axis is how every chart both readers already use is driven, and
  it leaves one control on the screen instead of two.
*/
const WINDOWS = [
  { key: "1D", granularity: "M1", count: 390 },
  { key: "5D", granularity: "M5", count: 400 },
  { key: "1M", granularity: "H1", count: 160 },
  { key: "6M", granularity: "D", count: 130 },
  { key: "1Y", granularity: "D", count: 260 },
  { key: "5Y", granularity: "D", count: 1200 },
] as const;

type WindowKey = (typeof WINDOWS)[number]["key"];

/*
  The quote goes upstream on every read, because a price is only current if it
  was just asked for, so it polls on the clock a delayed feed deserves. The
  series answers from the store, so reading it more often costs almost nothing
  and what it spends upstream is bounded by the API rather than by this number.
*/
const QUOTE_MS = 30_000;
const BARS_MS = 60_000;

/*
  Filings are read from the SEC behind the first response, so the header comes
  back before they exist. While that is outstanding the header is re-read
  quickly, and once the company is complete it settles to the slow clock.
*/
const COLLECTING_MS = 3_000;
const SETTLED_MS = 120_000;

const CHART_HEIGHT = 380;

function windowLabel(key: WindowKey, language: string): string {
  return language === "pt" ? key.replace("Y", "A") : key;
}

function Quote({ ticker, stored }: { ticker: string; stored: CompanyHead["last_close"] }) {
  const { language, timezone, t } = useSession();

  /*
    Read on its own, so the price is the only thing on this screen waiting for
    the feed. Until it lands, the stored close carries the number, which is a
    real reading rather than a placeholder and is labelled by its own date.
  */
  const { data } = useResource<CompanyQuote>(`/company/${ticker}/quote`, QUOTE_MS);

  const quote = data?.quote ?? null;
  const last = data?.last_close ?? stored;

  const price = quote?.price ?? last?.close ?? null;
  const previous = quote?.previous_close ?? last?.previous_close ?? null;

  const move =
    price !== null && previous !== null && previous !== 0
      ? { amount: price - previous, pct: (price / previous - 1) * 100 }
      : { amount: null, pct: null };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-4">
        <span className="eyebrow">{t("lastPrice")}</span>
        <Provenance kind="measured">{t("measured")}</Provenance>
      </div>

      <div className="num flex items-baseline gap-3 text-[40px] leading-none text-ink">
        {price === null ? "—" : money(language, price)}
        <span className="text-[15px] text-faint">{quote?.currency ?? ""}</span>
      </div>

      <Change amount={move.amount} pct={move.pct} size={16} />

      {data && !data.feed_answered && (
        <p className="border-l-2 border-modelled pl-3 text-[12px] leading-relaxed text-muted">
          <span className="eyebrow block pb-1" style={{ color: "var(--modelled)" }}>
            {t("feedSilent")}
          </span>
          {t("feedSilentBody")}
        </p>
      )}

      {/*
        Always two rows, whichever of them is knowable yet.

        The live quote arrives about half a second after the stored close, and
        when the rows were conditional that arrival added one and changed the
        height of the block, which shifted everything under it. The second row
        answers a different question depending on what is known, and it is
        labelled with which question it answered.
      */}
      <div className="border-t border-line pt-3">
        <div className="flex items-baseline justify-between gap-x-4">
          <span className="text-[12px] text-muted">{t("previousClose")}</span>
          <span className="num text-[12px] text-ink">
            {previous === null ? "—" : money(language, previous)}
          </span>
        </div>
        <div className="flex items-baseline justify-between gap-x-4 pt-1">
          <span className="text-[12px] text-muted">
            {quote?.as_of ? t("takenAt") : t("storedClose")}
          </span>
          <span className="num text-[12px] text-ink">
            {quote?.as_of ? (
              <>
                {dateTime(language, timezone, quote.as_of)}
                <span className="pl-2 text-faint">
                  {age(quote.age_seconds, t("ago"), t("never"))}
                </span>
              </>
            ) : last?.as_of ? (
              dayOnly(language, timezone, last.as_of)
            ) : (
              "—"
            )}
          </span>
        </div>
      </div>
    </div>
  );
}

function Chart({
  ticker,
  marks,
}: {
  ticker: string;
  marks: { t: string; label: string }[];
}) {
  const { language, timezone, t } = useSession();
  const [window_, setWindow] = useState<WindowKey>("6M");

  const chosen = WINDOWS.find((entry) => entry.key === window_) ?? WINDOWS[3];
  const { data, stale } = useResource<CompanyBars>(
    `/company/${ticker}/bars?granularity=${chosen.granularity}&count=${chosen.count}`,
    BARS_MS,
  );

  /*
    The series already on screen stays there while the next one loads, so the
    shape the reader was comparing against does not blink out between two
    windows.
  */
  const [held, setHeld] = useState<CompanyBars | null>(null);
  useEffect(() => {
    if (data) setHeld(data);
  }, [data]);

  const shown = data ?? (held?.ticker === ticker ? held : null);

  return (
    <Card>
      <CardHead
        title={t("priceHistory")}
        aside={
          <div className="flex items-center gap-3">
            {stale && <span className="eyebrow text-modelled">{t("refreshFailed")}</span>}
            <Segmented
              label={t("horizon")}
              value={window_}
              onChange={setWindow}
              options={WINDOWS.map((entry) => ({
                value: entry.key,
                label: windowLabel(entry.key, language),
              }))}
            />
          </div>
        }
      />

      {/*
        The chart's height is reserved whether or not there is a chart yet, so
        arriving data fills a space that was already there. Letting the card
        grow from a loading line to a 380 pixel canvas threw everything below
        it down the page, which is the jump that reads as the screen breaking.
      */}
      <div className="px-4 py-4" style={{ minHeight: CHART_HEIGHT + 32 }}>
        {!shown ? (
          <div
            className="flex items-center justify-center"
            style={{ height: CHART_HEIGHT }}
          >
            <span className="eyebrow">{t("reading")}</span>
          </div>
        ) : shown.bars.length === 0 ? (
          <Empty title={t("noBars")} body={t("noBarsBody")} />
        ) : (
          <Candles
            bars={shown.bars}
            marks={shown.bars.length <= 300 ? marks : []}
            granularity={shown.granularity}
            height={CHART_HEIGHT}
          />
        )}
      </div>
      <p className="num border-t border-line px-5 py-3 text-[11px] text-faint">
        {shown && shown.bars.length > 0
          ? `${number(language, shown.bars.length, 0)} ${shown.granularity} · ${shown.source} · ${dateTime(language, timezone, shown.as_of)}`
          : " "}
      </p>
    </Card>
  );
}

export function Company() {
  const { ticker = "" } = useParams();
  const symbol = ticker.toUpperCase();
  const { language, timezone, t } = useSession();

  const [collecting, setCollecting] = useState(true);
  const {
    data: head,
    error,
    reload,
  } = useResource<CompanyHead>(
    `/company/${symbol}`,
    collecting ? COLLECTING_MS : SETTLED_MS,
  );

  useEffect(() => {
    if (head) setCollecting(head.collecting);
  }, [head]);

  if (error)
    return (
      <Card>
        <Failure
          label={t("failed")}
          detail={error.message}
          onRetry={reload}
          retryLabel={t("retry")}
        />
      </Card>
    );

  /*
    The page is built once and filled in, rather than swapped from a loading
    card into a layout. Every piece of it arrives at a different moment: the
    header from the store almost at once, the series a moment later, the live
    quote after a round trip to the feed. Rendering a placeholder card first
    and the real page second meant the reader watched the whole screen be
    replaced, and then watched it move again under each arrival.

    The ticker is known from the address before anything is read, so the frame
    can carry it immediately and the rest can land inside a shape that is
    already the right one.
  */
  const marks = (head?.earnings ?? []).map((release) => ({
    t: release.accepted_at,
    label: t("earningsMark").toUpperCase(),
  }));

  return (
    <div className="space-y-6">
      <Card ruled>
        <div className="grid gap-8 px-6 py-7 lg:grid-cols-[1.4fr_1fr]">
          <div>
            <div className="num eyebrow pb-3">
              {symbol}
              {head ? ` · CIK ${head.cik}` : ""}
            </div>
            <h1
              className="prose-read text-[38px] leading-[1.05] tracking-[-0.015em] text-ink"
              style={{ minHeight: "1.05em" }}
            >
              {head?.name ?? " "}
            </h1>
            <p className="mt-4 max-w-[54ch] border-l-2 border-line pl-4 text-[12px] leading-relaxed text-muted">
              <span className="eyebrow block pb-1">{t("delayedQuote")}</span>
              {t("delayedQuoteBody")}
            </p>
          </div>

          <div className="border-line lg:border-l lg:pl-8">
            <Quote ticker={symbol} stored={head?.last_close ?? null} />
          </div>
        </div>
      </Card>

      <Chart ticker={symbol} marks={marks} />

      <Card>
        <CardHead
          title={t("earningsReleases")}
          lead={t("earningsLead")}
          aside={<Provenance kind="measured">{t("measured")}</Provenance>}
        />

        {(head?.earnings ?? []).length === 0 ? (
          !head || head.collecting ? (
            <Loading label={t("collectingFilings")} />
          ) : (
            <Empty title={t("noEarnings")} body={t("noEarningsBody")} />
          )
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-left">
              <thead>
                <tr className="border-b border-line">
                  {[t("acceptedAt"), t("form"), t("items")].map((heading, index) => (
                    <th
                      key={heading}
                      className={`eyebrow px-5 py-2.5 font-medium ${index > 0 ? "text-right" : ""}`}
                    >
                      {heading}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...(head?.earnings ?? [])].reverse().map((release) => (
                  <tr key={release.event_key} className="border-b border-line last:border-b-0">
                    <td className="num px-5 py-3 text-[13px] text-ink">
                      {dateTime(language, timezone, release.accepted_at)}
                    </td>
                    <td className="num px-5 py-3 text-right text-[12px] text-muted">
                      {release.form}
                    </td>
                    <td className="num px-5 py-3 text-right text-[12px] text-muted">
                      {release.items}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
