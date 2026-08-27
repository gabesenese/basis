import { useId } from "react";

/*
  The interval rail is the one mark this whole interface is built around.

  A bare number claims more than the data supports. The rail refuses to render
  one: it shows the point estimate as a hard tick, the interval around it as a
  band, and zero as a fixed rule that never moves. Whether the band crosses that
  rule is the entire finding, readable without looking at a single digit.

  Two intervals can be drawn at once. The outer band is the wider of the two,
  usually a bootstrap, and it is stroked rather than filled so the pair reads as
  one measurement of two strictnesses instead of two measurements.
*/

export type RailProps = {
  estimate: number;
  low: number;
  high: number;
  outerLow?: number;
  outerHigh?: number;
  domain: [number, number];
  tone?: "measured" | "modelled";
  height?: number;
  label?: string;
};

const PAD = 1;

export function Rail({
  estimate,
  low,
  high,
  outerLow,
  outerHigh,
  domain,
  tone = "measured",
  height = 40,
  label,
}: RailProps) {
  const clipId = useId();
  const [from, to] = domain;
  const span = to - from || 1;
  const at = (value: number) => ((value - from) / span) * 100;

  const color = tone === "modelled" ? "var(--modelled)" : "var(--measured)";
  const wash = tone === "modelled" ? "var(--modelled-wash)" : "var(--measured-wash)";

  const mid = height / 2;
  const bandHeight = 12;
  const outerHeight = 20;
  const crossesZero = low <= 0 && high >= 0;

  const inner = { x: at(Math.min(low, high)), width: Math.abs(at(high) - at(low)) };
  const outer =
    outerLow !== undefined && outerHigh !== undefined
      ? {
          x: at(Math.min(outerLow, outerHigh)),
          width: Math.abs(at(outerHigh) - at(outerLow)),
        }
      : null;

  return (
    <svg
      viewBox={`0 0 100 ${height}`}
      preserveAspectRatio="none"
      className="w-full"
      style={{ height }}
      role="img"
      aria-label={label}
    >
      <defs>
        <clipPath id={clipId}>
          <rect x={PAD} y={0} width={100 - PAD * 2} height={height} />
        </clipPath>
      </defs>

      <g clipPath={`url(#${clipId})`}>
        <line
          x1={PAD}
          y1={mid}
          x2={100 - PAD}
          y2={mid}
          stroke="var(--line)"
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
        />

        {outer && (
          <g stroke={color} strokeWidth={1} vectorEffect="non-scaling-stroke" opacity={0.75}>
            <line x1={outer.x} y1={mid} x2={outer.x + outer.width} y2={mid} />
            <line
              x1={outer.x}
              y1={mid - outerHeight / 2}
              x2={outer.x}
              y2={mid + outerHeight / 2}
            />
            <line
              x1={outer.x + outer.width}
              y1={mid - outerHeight / 2}
              x2={outer.x + outer.width}
              y2={mid + outerHeight / 2}
            />
          </g>
        )}

        <rect
          x={inner.x}
          y={mid - bandHeight / 2}
          width={Math.max(inner.width, 0.3)}
          height={bandHeight}
          fill={wash}
          stroke={color}
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
        />

        <line
          x1={at(0)}
          y1={2}
          x2={at(0)}
          y2={height - 2}
          stroke="var(--rule)"
          strokeWidth={crossesZero ? 1.5 : 1}
          vectorEffect="non-scaling-stroke"
          opacity={crossesZero ? 1 : 0.45}
        />

        <line
          x1={at(estimate)}
          y1={mid - outerHeight / 2 - 2}
          x2={at(estimate)}
          y2={mid + outerHeight / 2 + 2}
          stroke={color}
          strokeWidth={2}
          vectorEffect="non-scaling-stroke"
        />
      </g>
    </svg>
  );
}

export function RailScale({
  domain,
  format,
}: {
  domain: [number, number];
  format: (value: number) => string;
}) {
  const [from, to] = domain;
  const zeroAt = ((0 - from) / (to - from || 1)) * 100;
  const inside = zeroAt > 12 && zeroAt < 88;

  return (
    <div className="num relative h-4 text-[10px] text-faint">
      <span className="absolute left-0">{format(from)}</span>
      {inside && (
        <span
          className="absolute text-muted"
          style={{ left: `${zeroAt}%`, transform: "translateX(-50%)" }}
        >
          0
        </span>
      )}
      <span className="absolute right-0">{format(to)}</span>
    </div>
  );
}
