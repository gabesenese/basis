import { useResource, useSession } from "../lib/session";
import type { CalendarEvent } from "../lib/api";
import { Badge, Card, CardHead, Failure, Loading } from "../components/primitives";
import { dateTime, dayOnly, eventName } from "../lib/format";

type Payload = { from: string; to: string; events: CalendarEvent[] };

export function Calendar() {
  const { language, timezone, t } = useSession();
  const { data, error, reload } = useResource<Payload>(
    "/calendar?months_back=18&months_ahead=18",
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

  const now = Date.now();
  const ahead = data.events.filter((e) => new Date(e.scheduled_time).getTime() > now);
  const past = data.events
    .filter((e) => new Date(e.scheduled_time).getTime() <= now)
    .reverse();

  const section = (title: string, events: CalendarEvent[]) => (
    <Card key={title}>
      <CardHead title={title} aside={<Badge>{events.length}</Badge>} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[46rem] text-left">
          <thead>
            <tr className="border-b border-line">
              {[t("event"), t("region"), t("scheduledFor"), t("knownSince"), t("vintages")].map(
                (heading, index) => (
                  <th
                    key={heading}
                    className={`eyebrow px-5 py-2.5 font-medium ${index > 1 ? "text-right" : ""}`}
                  >
                    {heading}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={event.event_key} className="border-b border-line last:border-b-0">
                <td className="px-5 py-3 text-[13px] text-ink">
                  {eventName(language, event.event_code)}
                </td>
                <td className="num px-5 py-3 text-[12px] text-muted">{event.region}</td>
                <td className="num px-5 py-3 text-right text-[13px] text-ink">
                  {dateTime(language, timezone, event.scheduled_time)}
                </td>
                <td className="num px-5 py-3 text-right text-[12px] text-muted">
                  {dayOnly(language, timezone, event.known_since)}
                </td>
                <td className="num px-5 py-3 text-right text-[12px] text-muted">
                  {event.vintages}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="prose-read text-[30px] leading-tight text-ink">{t("calendar")}</h1>
        <p className="mt-1.5 max-w-[64ch] text-[13px] leading-relaxed text-muted">
          {language === "pt"
            ? "Cada linha é a versão mais recente do evento. Conhecido desde é o instante em que a data virou pública, e é o que impede um backtest de usar um calendário que ainda não existia."
            : "Each row is the latest vintage of the event. Known since is the instant the date became public, and it is what stops a backtest from using a calendar that did not exist yet."}
        </p>
      </div>

      {section(t("ahead"), ahead)}
      {section(t("past"), past)}
    </div>
  );
}
