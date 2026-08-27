import { useEffect, useState } from "react";
import { useResource, useSession } from "../lib/session";
import type { Today as TodayPayload } from "../lib/api";
import {
  Card,
  CardHead,
  Empty,
  Failure,
  Loading,
  Provenance,
  Stat,
} from "../components/primitives";
import { CostBars } from "../components/charts";
import { age, countdown, dateTime, eventName, number, price } from "../lib/format";

function Countdown({ target }: { target: string }) {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const tick = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(tick);
  }, []);

  const left = countdown(target, now);

  return (
    <div className="num flex items-baseline gap-3 text-[38px] leading-none text-ink">
      {(
        [
          [left.days, "d"],
          [left.hours, "h"],
          [left.minutes, "m"],
        ] as const
      ).map(([value, unit]) => (
        <span key={unit} className="flex items-baseline">
          {String(value).padStart(2, "0")}
          <span className="ml-0.5 text-[13px] text-faint">{unit}</span>
        </span>
      ))}
    </div>
  );
}

function Health({ findings }: { findings: TodayPayload["health"] }) {
  const { language, t } = useSession();
  const names: Record<string, string> = {
    recorder: t("recorder"),
    ticks: t("ticks"),
    bars: t("bars"),
  };

  const spell = (finding: TodayPayload["health"][number]) => {
    const { facts } = finding;
    if (facts.never_run) return t("recorderNeverRan");

    const since = age(facts.age_seconds, t("ago"), t("never"));

    if (finding.subject === "recorder") {
      return `${t("heartbeat")} ${since} · ${number(language, facts.ticks_written ?? 0, 0)} ${t("ticksWritten")}`;
    }
    if (finding.subject === "ticks") {
      return `${t("lastTick")} ${since}${facts.market_closed ? ` · ${t("marketClosed").toLowerCase()}` : ""}`;
    }
    return `${t("newestBar")} ${since}`;
  };

  return (
    <div>
      {findings.map((finding) => (
        <div
          key={finding.subject}
          className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line px-5 py-3 last:border-b-0"
        >
          <span className="flex items-center gap-2 text-[13px] text-ink">
            <span
              aria-hidden
              className="inline-block size-1.5"
              style={{
                background: finding.healthy ? "var(--measured)" : "var(--modelled)",
                borderRadius: finding.healthy ? "50%" : 0,
              }}
            />
            {names[finding.subject] ?? finding.subject}
          </span>
          <span className="num text-[12px] text-muted">{spell(finding)}</span>
        </div>
      ))}
    </div>
  );
}

export function Today() {
  const { language, timezone, t } = useSession();
  const { data, error, reload } = useResource<TodayPayload>("/today");

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

  if (!data)
    return (
      <Card>
        <Loading label={t("loading")} />
      </Card>
    );

  const { spot, next_event: next, cost } = data;

  return (
    <div className="space-y-6">
      <Card ruled>
        <div className="grid gap-8 px-6 py-7 lg:grid-cols-[1.3fr_1fr]">
          <div>
            <div className="eyebrow pb-3">
              {data.market_open ? t("marketOpen") : t("marketClosed")}
            </div>

            {next ? (
              <>
                <h1 className="prose-read text-[38px] leading-[1.05] tracking-[-0.015em] text-ink">
                  {eventName(language, next.event_code)}
                </h1>
                <p className="num mt-3 text-[13px] text-muted">
                  {dateTime(language, timezone, next.scheduled_time)}
                </p>
                <p className="mt-1 text-[12px] text-faint">
                  {t("knownSince")}{" "}
                  <span className="num">
                    {dateTime(language, timezone, next.known_since)}
                  </span>
                </p>
              </>
            ) : (
              <>
                <h1 className="prose-read text-[38px] leading-[1.05] text-ink">
                  {t("noNextEvent")}
                </h1>
                <p className="mt-3 max-w-[46ch] text-[13px] leading-relaxed text-muted">
                  {t("noNextEventBody")}
                </p>
              </>
            )}
          </div>

          <div className="flex flex-col justify-between gap-7 border-line lg:border-l lg:pl-8">
            {next && (
              <div>
                <div className="eyebrow pb-2">{t("nextEvent")}</div>
                <Countdown target={next.scheduled_time} />
              </div>
            )}

            {spot && (
              <div>
                <div className="flex items-center justify-between pb-2">
                  <span className="eyebrow">{t("spot")} · EUR/USD</span>
                  <Provenance kind="measured">{t("measured")}</Provenance>
                </div>
                <div className="num text-[30px] leading-none text-ink">
                  {price(language, spot.mid)}
                </div>
                <div className="num mt-2 flex gap-4 text-[12px] text-muted">
                  <span>
                    {t("bid")} {price(language, spot.bid)}
                  </span>
                  <span>
                    {t("ask")} {price(language, spot.ask)}
                  </span>
                  {spot.spread_pips !== null && (
                    <span>
                      {t("spread")} {number(language, spot.spread_pips, 2)}
                    </span>
                  )}
                </div>
                <div className="num mt-1.5 text-[11px] text-faint">
                  {spot.source} · {dateTime(language, timezone, spot.as_of)}
                </div>
              </div>
            )}
          </div>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[1.45fr_1fr]">
        <Card>
          <CardHead
            title={t("costOfTrading")}
            lead={t("costLead")}
            aside={<Provenance kind="modelled">{t("modelled")}</Provenance>}
          />

          {cost.points.length === 0 ? (
            <Empty
              title={t("noNextEvent")}
              body={t("costLead")}
            />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-6 border-b border-line px-5 py-4">
                <Stat
                  label={t("quietBaseline")}
                  value={number(language, cost.baseline_pips, 2)}
                  unit="pips"
                />
                <Stat
                  label={t("eventsMeasured")}
                  value={cost.events_measured}
                  unit="FOMC"
                />
              </div>
              <div className="px-4 py-4">
                <CostBars
                  points={cost.points}
                  baseline={cost.baseline_pips}
                  formatNumber={(value, digits) => number(language, value, digits ?? 2)}
                />
              </div>
              <p className="num border-t border-line px-5 py-3 text-[11px] leading-relaxed text-faint">
                {cost.shape_source} → {cost.applied_to}
              </p>
            </>
          )}
        </Card>

        <Card>
          <CardHead title={t("dataHealth")} />
          <Health findings={data.health} />
          <p className="num border-t border-line px-5 py-3 text-[11px] text-faint">
            {dateTime(language, timezone, data.as_of)}
          </p>
        </Card>
      </div>
    </div>
  );
}
