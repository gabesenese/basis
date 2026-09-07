import { useSession } from "../lib/session";
import { money, percent, signed } from "../lib/format";

/*
  The one mark in the interface that carries red and green, and it carries them
  for the same reason the candles do: a close read against the close before it
  is a price, and price is where the convention already lives. The rule and its
  limits are written beside the tokens in index.css.

  Zero is neither colour. A day that ended where it started is not a small win
  and not a small loss, and painting it green because the last cent rounded up
  would be the interface making a claim the number does not.
*/
export function tone(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "var(--ink)";
  return value > 0 ? "var(--up)" : "var(--down)";
}

export function Change({
  amount,
  pct,
  size = 13,
}: {
  amount: number | null | undefined;
  pct: number | null | undefined;
  size?: number;
}) {
  const { language } = useSession();

  if (pct === null || pct === undefined) return null;

  return (
    <span
      className="num inline-flex items-baseline gap-2"
      style={{ color: tone(pct), fontSize: size }}
    >
      {amount !== null && amount !== undefined && (
        <span>{signed(language, amount, 2)}</span>
      )}
      <span>{percent(language, pct)}</span>
    </span>
  );
}

export function Money({ value, size = 13 }: { value: number | null | undefined; size?: number }) {
  const { language } = useSession();
  return (
    <span className="num text-ink" style={{ fontSize: size }}>
      {money(language, value)}
    </span>
  );
}
