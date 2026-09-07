import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useResource, useSession } from "../lib/session";
import { api } from "../lib/api";
import type { CollectedCompany, CompanyHit, Search as SearchPayload } from "../lib/api";
import { Card, CardHead, Empty, Failure } from "../components/primitives";
import { Change, Money } from "../components/change";
import { dayOnly, number } from "../lib/format";

/*
  Long enough that a fast typist sends one request for a word rather than one
  for each letter, short enough that the list has already moved by the time the
  eye reaches it. The search itself reads a stored index and touches no network
  beyond this process, so this is about request count and not about latency.
*/
const SETTLE_MS = 140;

function useSettled(value: string, delay: number) {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);

  return settled;
}

function Row({
  ticker,
  name,
  last,
  active,
  onOpen,
  onHover,
}: {
  ticker: string;
  name: string;
  last: CompanyHit["last"];
  active: boolean;
  onOpen: () => void;
  onHover: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      onPointerMove={onHover}
      className={`grid w-full grid-cols-[5.5rem_1fr] items-baseline gap-x-4 border-b border-line border-l-2 px-5 py-3 text-left last:border-b-0 sm:grid-cols-[5.5rem_1fr_auto] ${
        active ? "border-l-ink bg-sunken" : "border-l-transparent"
      }`}
    >
      <span className="num text-[14px] text-ink">{ticker}</span>
      <span className="truncate text-[13px] text-muted">{name}</span>
      <span className="col-span-2 flex items-baseline gap-3 sm:col-span-1 sm:justify-end">
        {last ? (
          <>
            <Money value={last.close} />
            <Change amount={last.change} pct={last.change_pct} />
          </>
        ) : (
          <span className="eyebrow">·</span>
        )}
      </span>
    </button>
  );
}

/*
  Square caps and hairline strokes, because nothing else in this interface has
  a rounded corner. Drawn inline rather than pulled from an icon set: it is one
  glyph, and a dependency for one glyph is a dependency to keep current forever.
*/
function TrashMark() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.15"
      strokeLinecap="square"
      aria-hidden
    >
      <path d="M2.5 3.6h9" />
      <path d="M5.4 3.6V2.1h3.2v1.5" />
      <path d="M3.7 3.6l.55 8.3h5.5l.55-8.3" />
      <path d="M6 6.1v3.6M8 6.1v3.6" />
    </svg>
  );
}

function CollectedRow({
  company,
  onOpen,
  onForget,
}: {
  company: CollectedCompany;
  onOpen: () => void;
  onForget: () => Promise<void>;
}) {
  const { language, timezone, t } = useSession();
  const [asking, setAsking] = useState(false);
  const [working, setWorking] = useState(false);

  /*
    Asked in the row rather than in a dialogue, and asked at all because this
    removes a real collection: ten years of sessions and every filing read for
    the company. It is recoverable by opening the company again, which is what
    the note says, so the question is a pause rather than a warning.
  */
  if (asking) {
    return (
      <div className="border-b border-line px-5 py-3 last:border-b-0">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
          <span className="text-[13px] text-ink">
            <span className="num">{company.ticker}</span> · {t("removeAsk")}
          </span>
          <span className="flex items-center gap-2">
            <button
              type="button"
              disabled={working}
              onClick={() => {
                setWorking(true);
                void onForget().finally(() => setWorking(false));
              }}
              className="pressable eyebrow border px-2 py-1 disabled:opacity-45"
              style={{ color: "var(--modelled)", borderColor: "var(--modelled)" }}
            >
              {t("removeConfirm")}
            </button>
            <button
              type="button"
              onClick={() => setAsking(false)}
              className="pressable eyebrow border border-line px-2 py-1 text-muted"
            >
              {t("removeCancel")}
            </button>
          </span>
        </div>
        <p className="mt-2 max-w-[62ch] text-[12px] leading-relaxed text-muted">
          {t("removeNote")}
        </p>
      </div>
    );
  }

  return (
    <div className="group grid grid-cols-[5.5rem_1fr_auto] items-baseline gap-x-4 border-b border-line last:border-b-0 hover:bg-sunken">
      <button
        type="button"
        onClick={onOpen}
        className="col-span-2 grid grid-cols-[5.5rem_1fr] items-baseline gap-x-4 py-3 pl-5 text-left"
      >
        <span className="num text-[14px] text-ink">{company.ticker}</span>
        <span className="truncate text-[13px] text-muted">{company.name}</span>
      </button>

      <span className="flex flex-wrap items-baseline justify-end gap-x-4 py-3 pr-5">
        <span className="num text-[11px] text-faint">
          {number(language, company.sessions, 0)} {t("sessions")} ·{" "}
          {dayOnly(language, timezone, company.oldest)}
        </span>
        {company.last && (
          <>
            <Money value={company.last.close} />
            <Change amount={company.last.change} pct={company.last.change_pct} />
          </>
        )}
        {/*
          Quiet until the row is under the pointer, so a list of companies
          reads as a list of companies rather than as a column of buttons. On a
          device with no pointer there is nothing to hover, so it stays visible
          and the affordance does not disappear entirely.
        */}
        <button
          type="button"
          onClick={() => setAsking(true)}
          aria-label={`${t("remove")} ${company.ticker}`}
          title={t("remove")}
          className="pressable ml-1 self-center text-faint opacity-100 transition-opacity hover:text-ink focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:hover)]:opacity-0"
        >
          <TrashMark />
        </button>
      </span>
    </div>
  );
}

function Collected({ onOpen }: { onOpen: (ticker: string) => void }) {
  const { t } = useSession();
  const { data, reload } = useResource<{ companies: CollectedCompany[] }>(
    "/companies/collected",
  );

  if (!data || data.companies.length === 0) return null;

  return (
    <Card>
      <CardHead title={t("collected")} lead={t("collectedBody")} />
      {data.companies.map((company) => (
        <CollectedRow
          key={company.ticker}
          company={company}
          onOpen={() => onOpen(company.ticker)}
          onForget={async () => {
            await api.remove(`/company/${company.ticker}/collected`);
            reload();
          }}
        />
      ))}
    </Card>
  );
}

export function Search() {
  const { language, t } = useSession();
  const navigate = useNavigate();
  const field = useRef<HTMLInputElement>(null);
  const [typed, setTyped] = useState("");
  const [cursor, setCursor] = useState(0);

  const query = useSettled(typed.trim(), SETTLE_MS);
  const { data, error, reload } = useResource<SearchPayload>(
    query ? `/companies?q=${encodeURIComponent(query)}` : "/companies?q=",
  );

  /*
    The last answer stays on screen while the next one is read. Blanking the
    list on every keystroke made a search that answers in forty milliseconds
    feel like one that does not, because what the reader saw between two
    answers was an empty card rather than the row they were aiming at.
  */
  const [held, setHeld] = useState<CompanyHit[]>([]);
  useEffect(() => {
    if (data?.results) setHeld(data.results);
  }, [data]);

  const results = useMemo(
    () => (query ? (data?.results ?? held) : []),
    [query, data, held],
  );

  useEffect(() => setCursor(0), [query]);
  useEffect(() => field.current?.focus(), []);

  const open = (ticker: string) => navigate(`/empresa/${ticker}`);

  const walk = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (results.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((at) => (at + 1) % results.length);
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((at) => (at - 1 + results.length) % results.length);
    }
    if (event.key === "Enter") {
      event.preventDefault();
      open(results[cursor].ticker);
    }
  };

  return (
    <div className="mx-auto w-full max-w-[880px] space-y-6 pt-[4vh]">
      <div>
        <h1 className="prose-read text-[34px] leading-[1.1] tracking-[-0.015em] text-ink">
          {t("searchPrompt")}
        </h1>

        <div className="mt-5 border border-line-strong bg-surface">
          <input
            ref={field}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            onKeyDown={walk}
            placeholder={t("searchPlaceholder")}
            autoComplete="off"
            spellCheck={false}
            aria-label={t("search")}
            className="num h-14 w-full bg-transparent px-5 text-[17px] text-ink placeholder:text-faint focus:outline-none"
          />
        </div>

        {data && (
          <p className="num mt-2 text-[11px] text-faint">
            {number(language, data.universe, 0)} {t("searchUniverse")}
          </p>
        )}
      </div>

      {error && (
        <Card>
          <Failure
            label={t("failed")}
            detail={error.message}
            onRetry={reload}
            retryLabel={t("retry")}
          />
        </Card>
      )}

      {query && data && results.length === 0 && (
        <Card>
          <Empty title={t("searchNothing")} body={t("searchNothingBody")} />
        </Card>
      )}

      {results.length > 0 && (
        <Card>
          {results.map((hit, index) => (
            <Row
              key={hit.ticker}
              ticker={hit.ticker}
              name={hit.name}
              last={hit.last}
              active={index === cursor}
              onOpen={() => open(hit.ticker)}
              onHover={() => setCursor(index)}
            />
          ))}
        </Card>
      )}

      {!query && <Collected onOpen={open} />}
    </div>
  );
}
