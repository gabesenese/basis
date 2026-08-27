import { useResource, useSession } from "../lib/session";
import type { Slope, Study as StudyPayload } from "../lib/api";
import { Badge, Card, CardHead, Failure, Loading, Stat } from "../components/primitives";
import { Rail, RailScale } from "../components/Rail";
import { Scatter } from "../components/charts";
import { dayOnly, horizonLabel, number, signed } from "../lib/format";
import type { Key } from "../lib/i18n";

const TEST_ORDER = ["constrained", "decomposed", "repricing"] as const;
const NOTE_KEY: Record<string, Key> = {
  constrained: "constrainedNote",
  decomposed: "decomposedNote",
  repricing: "repricingNote",
};

function bodySlope(fit: { slopes: Slope[] }, regressor: string): Slope | undefined {
  return fit.slopes.find((slope) => slope.name === regressor);
}

function domainFor(values: number[]): [number, number] {
  const reach = Math.max(...values.map(Math.abs)) * 1.08 || 1;
  return [-reach, reach];
}

export function Study() {
  const { language, timezone, t } = useSession();
  const { data, error, reload } = useResource<StudyPayload>("/study/fomc");

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

  const { coverage, tests, gate_horizon: gate } = data;
  const gateFit = tests.repricing.by_horizon[gate];
  const gateSlope = bodySlope(gateFit, "z_reprice");
  const verdict = bodySlope(tests.constrained.by_horizon[gate], "z_surprise");

  const scatterPoints = data.meetings
    .filter((m) => m.z_reprice !== null && m.ret_2h !== null)
    .map((m) => ({
      x: m.z_reprice as number,
      y: m.ret_2h as number,
      label: m.event_key.replace("FOMC_", ""),
    }));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="prose-read text-[30px] leading-tight text-ink">{t("gateTitle")}</h1>
        <p className="prose-read mt-2 max-w-[60ch] text-[17px] leading-relaxed text-muted">
          {t("gateQuestion")}
        </p>
      </div>

      <Card ruled>
        <div className="grid gap-6 px-6 py-6 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label={t("meetings")} value={coverage.meetings} />
          <Stat label={t("movedTheRange")} value={coverage.decisions_that_moved} />
          <Stat
            label={t("windowLead")}
            value={number(language, coverage.window_lead_days.median, 0)}
            unit={t("days")}
          />
          <div>
            <div className="eyebrow pb-1">{t("horizon")}</div>
            <div className="num text-[22px] leading-none text-ink">
              {horizonLabel(gate)}
            </div>
          </div>
        </div>

        {verdict && (
          <div className="border-t border-line px-6 py-5">
            <p className="prose-read max-w-[72ch] text-[16px] leading-relaxed text-ink">
              {language === "pt"
                ? `A surpresa padronizada move a resposta de duas horas em ${signed(language, verdict.estimate, 1)} pips por desvio padrão, com intervalo de 95% de ${signed(language, verdict.robust_low, 1)} a ${signed(language, verdict.robust_high, 1)}. A banda cruza o zero, então o portão não passa nessa medida.`
                : `Standardised surprise moves the two hour response by ${signed(language, verdict.estimate, 1)} pips per standard deviation, with a 95 percent interval from ${signed(language, verdict.robust_low, 1)} to ${signed(language, verdict.robust_high, 1)}. The band crosses zero, so the gate does not pass on that measure.`}
            </p>
          </div>
        )}
      </Card>

      {TEST_ORDER.map((key) => {
        const test = tests[key];
        const regressor = test.regressors[0];
        const bounds = data.horizons.flatMap((horizon) => {
          const slope = bodySlope(test.by_horizon[horizon], regressor);
          return slope ? [slope.boot_low, slope.boot_high, slope.robust_low, slope.robust_high] : [];
        });
        const domain = domainFor(bounds);

        return (
          <Card key={key}>
            <CardHead
              title={t(key as Key)}
              lead={t(NOTE_KEY[key])}
              aside={<Badge>{test.tradable ? t("tradable") : t("diagnostic")}</Badge>}
            />

            <div className="divide-y divide-line">
              {data.horizons.map((horizon) => {
                const fit = test.by_horizon[horizon];
                const slope = bodySlope(fit, regressor);
                if (!slope) return null;

                return (
                  <div
                    key={horizon}
                    className="grid items-center gap-4 px-5 py-4 md:grid-cols-[3.5rem_1fr_11rem]"
                  >
                    <div className="num text-[13px] text-ink">{horizonLabel(horizon)}</div>

                    <div>
                      <Rail
                        estimate={slope.estimate}
                        low={slope.robust_low}
                        high={slope.robust_high}
                        outerLow={slope.boot_low}
                        outerHigh={slope.boot_high}
                        domain={domain}
                        label={`${horizonLabel(horizon)} ${signed(language, slope.estimate, 1)}`}
                      />
                      {horizon === data.horizons[data.horizons.length - 1] && (
                        <RailScale
                          domain={domain}
                          format={(value) => signed(language, value, 0)}
                        />
                      )}
                    </div>

                    <div className="text-right">
                      <div className="num text-[15px] text-ink">
                        {signed(language, slope.estimate, 1)}
                      </div>
                      <div className="num text-[11px] text-faint">
                        R² {number(language, fit.r_squared, 2)}
                      </div>
                      {/*
                        Whether a slope clears zero is a judgement about the
                        data, not a statement about where the number came from,
                        so it is marked in ink and never in one of the two
                        colours that mean observed and derived.
                      */}
                      <div className="mt-1 flex justify-end">
                        {slope.excludes_zero ? (
                          <span className="eyebrow flex items-center gap-1.5 text-ink">
                            <span
                              aria-hidden
                              className="inline-block size-1.5"
                              style={{ background: "var(--rule)" }}
                            />
                            {t("evidence")}
                          </span>
                        ) : (
                          <span className="eyebrow">{t("noEvidence")}</span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            <p className="num border-t border-line px-5 py-3 text-[11px] text-faint">
              {t("perStdDev")} · {t("robustInterval")} HC3 · {t("bootstrapInterval")} 20 000
            </p>
          </Card>
        );
      })}

      <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <Card>
          <CardHead title={t("surpriseVsResponse")} />
          <div className="px-4 py-4">
            {gateSlope && (
              <Scatter
                points={scatterPoints}
                intercept={gateFit.slopes[0].estimate}
                slope={gateSlope.estimate}
                xLabel={language === "pt" ? "Reprecificação, desvios padrão" : "Repricing, standard deviations"}
                yLabel={language === "pt" ? "Resposta 2h, pips" : "2h response, pips"}
                formatNumber={(value, digits) => number(language, value, digits ?? 1)}
              />
            )}
          </div>
          <p className="num border-t border-line px-5 py-3 text-[11px] text-faint">
            {t("leaveOneOut")} {signed(language, data.leave_one_out.low, 1)} ·{" "}
            {signed(language, data.leave_one_out.high, 1)}
          </p>
        </Card>

        <Card>
          <CardHead title={t("eventAfternoon")} />
          <div className="space-y-5 px-5 py-5">
            <Stat
              label={t("eventAfternoon")}
              value={number(language, data.event_versus_ordinary.event_median_pips, 1)}
              unit="pips"
              tone="measured"
            />
            <Stat
              label={`${t("ordinaryAfternoon")} · n=${data.event_versus_ordinary.ordinary_n}`}
              value={number(language, data.event_versus_ordinary.ordinary_median_pips, 1)}
              unit="pips"
            />
            <p className="prose-read max-w-[36ch] text-[14px] leading-relaxed text-muted">
              {language === "pt"
                ? `${t("medianMove")}. A tarde de FOMC é ${number(language, data.event_versus_ordinary.ratio ?? 0, 1)} vezes uma tarde comum.`
                : `${t("medianMove")}. The FOMC afternoon is ${number(language, data.event_versus_ordinary.ratio ?? 0, 1)} times an ordinary one.`}
            </p>
          </div>
          <p className="num border-t border-line px-5 py-3 text-[11px] text-faint">
            {dayOnly(language, timezone, coverage.first)} ·{" "}
            {dayOnly(language, timezone, coverage.last)}
          </p>
        </Card>
      </div>
    </div>
  );
}
