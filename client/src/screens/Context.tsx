import { useResource, useSession } from "../lib/session";
import type { Positioning } from "../lib/api";
import {
  Card,
  CardHead,
  Failure,
  Loading,
  Provenance,
  Stat,
} from "../components/primitives";
import { NetSeries } from "../components/charts";
import { dayOnly, number, signed } from "../lib/format";

export function Context() {
  const { language, timezone, t } = useSession();
  const { data, error, reload } = useResource<Positioning>(
    "/context/positioning?weeks=260",
  );

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

  const series = data.series
    .filter((point) => point.noncomm_net !== null)
    .map((point) => ({
      t: new Date(point.effective_time).getTime(),
      value: point.noncomm_net as number,
      label: dayOnly(language, timezone, point.effective_time),
    }));

  const newest = data.series[data.series.length - 1];
  const lag = newest
    ? Math.round(
        (new Date(newest.known_since).getTime() -
          new Date(newest.effective_time).getTime()) /
          86_400_000,
      )
    : null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="prose-read text-[30px] leading-tight text-ink">{t("positioning")}</h1>
        <p className="mt-1.5 max-w-[64ch] text-[13px] leading-relaxed text-muted">
          {t("positioningLead")}
        </p>
      </div>

      <Card>
        <CardHead
          title={data.contract}
          aside={<Provenance kind="measured">{t("measured")}</Provenance>}
        />

        <div className="grid gap-6 border-b border-line px-5 py-4 sm:grid-cols-3">
          <Stat
            label={t("netPosition")}
            value={signed(language, newest?.noncomm_net ?? null, 0)}
            unit={t("contracts")}
            tone="measured"
          />
          <Stat
            label={t("openInterest")}
            value={number(language, newest?.open_interest ?? null, 0)}
            unit={t("contracts")}
          />
          <div>
            <div className="eyebrow pb-1">{t("knownSince")}</div>
            <div className="num text-[22px] leading-none text-ink">
              {dayOnly(language, timezone, newest?.known_since)}
            </div>
            {lag !== null && (
              <div className="num pt-1 text-[11px] text-faint">
                +{lag} {t("days")}
              </div>
            )}
          </div>
        </div>

        <div className="px-4 py-4">
          <NetSeries
            series={series}
            formatNumber={(value, digits) => number(language, value, digits ?? 0)}
            formatDay={(index) => series[index]?.label ?? ""}
          />
        </div>

        <p className="num border-t border-line px-5 py-3 text-[11px] text-faint">
          {series.length} {language === "pt" ? "semanas" : "weeks"}
        </p>
      </Card>
    </div>
  );
}
