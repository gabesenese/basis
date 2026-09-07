import { useEffect, useRef, useState, type ReactNode } from "react";

/*
  Charts are measured at their real pixel size rather than scaled from a fixed
  viewBox, so a label is the same size here as it is in a table two rows above.
  A chart whose type grows with the window reads as an image of a chart.
*/
export function useMeasure<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(entry.contentRect.width),
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return { ref, width };
}

function Tip({ x, y, children }: { x: number; y: number; children: ReactNode }) {
  return (
    <div
      className="pointer-events-none absolute z-20 border border-line-strong bg-surface px-2.5 py-1.5 text-[11px] leading-snug text-ink shadow-sm"
      style={{ left: x, top: y, transform: "translate(-50%, -115%)", whiteSpace: "nowrap" }}
    >
      {children}
    </div>
  );
}

function niceTicks(from: number, to: number, count = 5): number[] {
  const span = to - from;
  if (span <= 0) return [from];
  const raw = span / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? magnitude * 10;
  const first = Math.ceil(from / step) * step;
  const ticks: number[] = [];
  for (let value = first; value <= to + step / 1000; value += step) ticks.push(value);
  return ticks;
}

export function CostBars({
  points,
  baseline,
  formatNumber,
}: {
  points: { seconds: number; pips: number; basis: string }[];
  baseline: number | null;
  formatNumber: (value: number, digits?: number) => string;
}) {
  const { ref, width } = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const height = 268;
  const margin = { top: 14, right: 12, bottom: 32, left: 44 };
  const plotWidth = Math.max(width - margin.left - margin.right, 10);
  const plotHeight = height - margin.top - margin.bottom;

  const peak = Math.max(...points.map((p) => p.pips), baseline ?? 0) * 1.12;
  const slot = plotWidth / points.length;
  const barWidth = Math.max(slot - 8, 4);
  const y = (value: number) => plotHeight - (value / peak) * plotHeight;

  const label = (seconds: number) =>
    seconds < 0 ? `−${Math.abs(seconds)}s` : `+${seconds}s`;

  return (
    <div ref={ref} className="relative">
      {width > 0 && (
        <svg width={width} height={height} role="img">
          <g transform={`translate(${margin.left},${margin.top})`}>
            {niceTicks(0, peak, 4).map((tick) => (
              <g key={tick}>
                <line
                  x1={0}
                  y1={y(tick)}
                  x2={plotWidth}
                  y2={y(tick)}
                  stroke="var(--line)"
                  strokeWidth={1}
                />
                <text
                  x={-8}
                  y={y(tick)}
                  textAnchor="end"
                  dominantBaseline="middle"
                  className="num"
                  fontSize={10}
                  fill="var(--ink-faint)"
                >
                  {formatNumber(tick, 1)}
                </text>
              </g>
            ))}

            {baseline !== null && (
              <line
                x1={0}
                y1={y(baseline)}
                x2={plotWidth}
                y2={y(baseline)}
                stroke="var(--rule)"
                strokeWidth={1}
                strokeDasharray="3 3"
              />
            )}

            {points.map((point, index) => {
              const x = index * slot + (slot - barWidth) / 2;
              const top = y(point.pips);
              return (
                <g
                  key={point.seconds}
                  onPointerEnter={() => setHover(index)}
                  onPointerLeave={() => setHover(null)}
                >
                  <rect
                    x={index * slot}
                    y={0}
                    width={slot}
                    height={plotHeight}
                    fill="transparent"
                  />
                  <rect
                    x={x}
                    y={top}
                    width={barWidth}
                    height={plotHeight - top}
                    fill="var(--modelled)"
                    opacity={hover === null || hover === index ? 0.9 : 0.4}
                    rx={2}
                  />
                  <text
                    x={index * slot + slot / 2}
                    y={plotHeight + 16}
                    textAnchor="middle"
                    className="num"
                    fontSize={10}
                    fill="var(--ink-faint)"
                  >
                    {label(point.seconds)}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      )}

      {hover !== null && (
        <Tip
          x={margin.left + hover * slot + slot / 2}
          y={margin.top + y(points[hover].pips)}
        >
          <span className="num">{formatNumber(points[hover].pips, 2)} pips</span>
        </Tip>
      )}
    </div>
  );
}

export function Scatter({
  points,
  intercept,
  slope,
  xLabel,
  yLabel,
  formatNumber,
}: {
  points: { x: number; y: number; label: string }[];
  intercept: number;
  slope: number;
  xLabel: string;
  yLabel: string;
  formatNumber: (value: number, digits?: number) => string;
}) {
  const { ref, width } = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const height = 300;
  const margin = { top: 14, right: 16, bottom: 34, left: 46 };
  const plotWidth = Math.max(width - margin.left - margin.right, 10);
  const plotHeight = height - margin.top - margin.bottom;

  const pad = (values: number[]) => {
    const low = Math.min(...values);
    const high = Math.max(...values);
    const room = (high - low) * 0.1 || 1;
    return [low - room, high + room] as [number, number];
  };

  const [x0, x1] = pad(points.map((p) => p.x));
  const [y0, y1] = pad(points.map((p) => p.y));
  const sx = (value: number) => ((value - x0) / (x1 - x0)) * plotWidth;
  const sy = (value: number) => plotHeight - ((value - y0) / (y1 - y0)) * plotHeight;

  return (
    <div ref={ref} className="relative">
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={`${xLabel} · ${yLabel}`}>
          <g transform={`translate(${margin.left},${margin.top})`}>
            {niceTicks(y0, y1, 4).map((tick) => (
              <g key={`y${tick}`}>
                <line x1={0} y1={sy(tick)} x2={plotWidth} y2={sy(tick)} stroke="var(--line)" />
                <text
                  x={-8}
                  y={sy(tick)}
                  textAnchor="end"
                  dominantBaseline="middle"
                  className="num"
                  fontSize={10}
                  fill="var(--ink-faint)"
                >
                  {formatNumber(tick, 0)}
                </text>
              </g>
            ))}

            {niceTicks(x0, x1, 5).map((tick) => (
              <text
                key={`x${tick}`}
                x={sx(tick)}
                y={plotHeight + 18}
                textAnchor="middle"
                className="num"
                fontSize={10}
                fill="var(--ink-faint)"
              >
                {formatNumber(tick, 1)}
              </text>
            ))}

            <line x1={sx(0)} y1={0} x2={sx(0)} y2={plotHeight} stroke="var(--rule)" opacity={0.5} />
            <line x1={0} y1={sy(0)} x2={plotWidth} y2={sy(0)} stroke="var(--rule)" opacity={0.5} />

            <line
              x1={sx(x0)}
              y1={sy(intercept + slope * x0)}
              x2={sx(x1)}
              y2={sy(intercept + slope * x1)}
              stroke="var(--measured)"
              strokeWidth={2}
            />

            {points.map((point, index) => (
              <circle
                key={point.label}
                cx={sx(point.x)}
                cy={sy(point.y)}
                r={hover === index ? 6 : 4.5}
                fill="var(--surface)"
                stroke="var(--measured)"
                strokeWidth={2}
                onPointerEnter={() => setHover(index)}
                onPointerLeave={() => setHover(null)}
              />
            ))}
          </g>

          <text
            x={margin.left + plotWidth / 2}
            y={height - 2}
            textAnchor="middle"
            fontSize={10}
            fill="var(--ink-faint)"
          >
            {xLabel}
          </text>
          <text
            x={12}
            y={margin.top + plotHeight / 2}
            textAnchor="middle"
            fontSize={10}
            fill="var(--ink-faint)"
            transform={`rotate(-90 12 ${margin.top + plotHeight / 2})`}
          >
            {yLabel}
          </text>
        </svg>
      )}

      {hover !== null && (
        <Tip x={margin.left + sx(points[hover].x)} y={margin.top + sy(points[hover].y)}>
          <div className="num">{points[hover].label}</div>
          <div className="num text-muted">
            {formatNumber(points[hover].x, 2)} · {formatNumber(points[hover].y, 1)} pips
          </div>
        </Tip>
      )}
    </div>
  );
}

export function NetSeries({
  series,
  formatNumber,
  formatDay,
}: {
  series: { t: number; value: number; label: string }[];
  formatNumber: (value: number, digits?: number) => string;
  formatDay: (index: number) => string;
}) {
  const { ref, width } = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const height = 260;
  const margin = { top: 14, right: 16, bottom: 28, left: 62 };
  const plotWidth = Math.max(width - margin.left - margin.right, 10);
  const plotHeight = height - margin.top - margin.bottom;

  if (series.length === 0) return <div ref={ref} />;

  const values = series.map((point) => point.value);
  const low = Math.min(...values, 0);
  const high = Math.max(...values, 0);
  const room = (high - low) * 0.08 || 1;
  const sy = (value: number) =>
    plotHeight - ((value - (low - room)) / (high + room - (low - room))) * plotHeight;
  const sx = (index: number) => (index / Math.max(series.length - 1, 1)) * plotWidth;

  const path = series
    .map((point, index) => `${index === 0 ? "M" : "L"}${sx(index)},${sy(point.value)}`)
    .join(" ");

  const area = `${path} L${sx(series.length - 1)},${sy(0)} L${sx(0)},${sy(0)} Z`;

  const track = (event: React.PointerEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const local = event.clientX - bounds.left - margin.left;
    const index = Math.round((local / plotWidth) * (series.length - 1));
    setHover(Math.min(Math.max(index, 0), series.length - 1));
  };

  return (
    <div ref={ref} className="relative">
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          onPointerMove={track}
          onPointerLeave={() => setHover(null)}
        >
          <g transform={`translate(${margin.left},${margin.top})`}>
            {niceTicks(low - room, high + room, 4).map((tick) => (
              <g key={tick}>
                <line x1={0} y1={sy(tick)} x2={plotWidth} y2={sy(tick)} stroke="var(--line)" />
                <text
                  x={-8}
                  y={sy(tick)}
                  textAnchor="end"
                  dominantBaseline="middle"
                  className="num"
                  fontSize={10}
                  fill="var(--ink-faint)"
                >
                  {formatNumber(tick / 1000, 0)}k
                </text>
              </g>
            ))}

            <path d={area} fill="var(--measured-wash)" />
            <line x1={0} y1={sy(0)} x2={plotWidth} y2={sy(0)} stroke="var(--rule)" strokeWidth={1} />
            <path d={path} fill="none" stroke="var(--measured)" strokeWidth={2} />

            {hover !== null && (
              <>
                <line
                  x1={sx(hover)}
                  y1={0}
                  x2={sx(hover)}
                  y2={plotHeight}
                  stroke="var(--line-strong)"
                />
                <circle
                  cx={sx(hover)}
                  cy={sy(series[hover].value)}
                  r={5}
                  fill="var(--surface)"
                  stroke="var(--measured)"
                  strokeWidth={2}
                />
              </>
            )}

            <text x={0} y={plotHeight + 18} className="num" fontSize={10} fill="var(--ink-faint)">
              {formatDay(0)}
            </text>
            <text
              x={plotWidth}
              y={plotHeight + 18}
              textAnchor="end"
              className="num"
              fontSize={10}
              fill="var(--ink-faint)"
            >
              {formatDay(series.length - 1)}
            </text>
          </g>
        </svg>
      )}

      {hover !== null && (
        <Tip x={margin.left + sx(hover)} y={margin.top + sy(series[hover].value)}>
          <div className="num">{series[hover].label}</div>
          <div className="num text-muted">
            {formatNumber(series[hover].value, 0)}
          </div>
        </Tip>
      )}
    </div>
  );
}

/*
  Candles, and the one place in this interface where red and green are allowed.
  The rule and its scope are written where the tokens are defined.

  Drawn against an index rather than against the clock. A market is shut more
  hours than it is open, so a time axis spends most of its width on nothing and
  leaves the candles too thin to read. Every trading chart both readers already
  use makes the same choice, and the axis labels carry the real timestamps.
*/
export function Candles({
  bars,
  marks = [],
  labels,
  formatPrice,
  formatStamp,
  height = 380,
}: {
  bars: { t: string; o: number; h: number; l: number; c: number; v: number | null }[];
  marks?: { t: string; label: string }[];
  labels: { open: string; high: string; low: string; close: string };
  formatPrice: (value: number) => string;
  formatStamp: (iso: string, form: "axis" | "full") => string;
  height?: number;
}) {
  const { ref, width } = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  /*
    The top margin carries the event labels, so it is deeper than the others.
    Sharing that band with the highest price tick would print one over the
    other, and a price a reader cannot finish reading is worse than a chart one
    row shorter.
  */
  const margin = { top: 24, right: 60, bottom: 26, left: 12 };
  const plotWidth = Math.max(width - margin.left - margin.right, 10);
  const plotHeight = height - margin.top - margin.bottom;

  if (bars.length === 0) return <div ref={ref} />;

  const low = Math.min(...bars.map((bar) => bar.l));
  const high = Math.max(...bars.map((bar) => bar.h));
  const room = (high - low) * 0.06 || 1;
  const floor = low - room;
  const ceiling = high + room;

  const y = (value: number) =>
    plotHeight - ((value - floor) / (ceiling - floor)) * plotHeight;

  const slot = plotWidth / bars.length;
  const body = Math.max(Math.min(slot - 2, 14), 1);

  const last = bars[bars.length - 1];
  const stamps = bars.map((bar) => bar.t);

  /*
    A mark lands on the candle whose period contains it rather than on the
    nearest one. An earnings release accepted after the close belongs to the
    session it will move, which is the next bar, and the first index at or
    after the release is exactly that bar.
  */
  const placed = marks
    .map((mark) => ({
      mark,
      index: stamps.findIndex((stamp) => stamp >= mark.t),
    }))
    .filter((entry) => entry.index >= 0);

  const track = (event: React.PointerEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const local = event.clientX - bounds.left - margin.left;
    const index = Math.floor(local / slot);
    setHover(Math.min(Math.max(index, 0), bars.length - 1));
  };

  const axisEvery = Math.max(Math.ceil(bars.length / 7), 1);

  return (
    <div ref={ref} className="relative">
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          onPointerMove={track}
          onPointerLeave={() => setHover(null)}
        >
          <g transform={`translate(${margin.left},${margin.top})`}>
            {niceTicks(floor, ceiling, 5).map((tick) => (
              <g key={tick}>
                <line x1={0} y1={y(tick)} x2={plotWidth} y2={y(tick)} stroke="var(--line)" />
                <text
                  x={plotWidth + 8}
                  y={y(tick)}
                  dominantBaseline="middle"
                  className="num"
                  fontSize={10}
                  fill="var(--ink-faint)"
                >
                  {formatPrice(tick)}
                </text>
              </g>
            ))}

            {placed.map(({ mark, index }) => {
              const centre = index * slot + slot / 2;
              /*
                A label near the right edge is written back towards the middle.
                Anchoring every one the same way is what clips the last event
                of the window, which is the one most worth reading.
              */
              const tail = centre > plotWidth * 0.8;

              return (
                <g key={mark.t}>
                  <line
                    x1={centre}
                    y1={-8}
                    x2={centre}
                    y2={plotHeight}
                    stroke="var(--measured)"
                    strokeWidth={1}
                    strokeDasharray="2 4"
                    opacity={0.6}
                  />
                  <text
                    x={tail ? centre - 5 : centre + 5}
                    y={-12}
                    textAnchor={tail ? "end" : "start"}
                    className="eyebrow"
                    fontSize={9}
                    letterSpacing="0.11em"
                    fill="var(--measured)"
                  >
                    {mark.label}
                  </text>
                </g>
              );
            })}

            {bars.map((bar, index) => {
              const rising = bar.c >= bar.o;
              const tone = rising ? "var(--up)" : "var(--down)";
              const centre = index * slot + slot / 2;
              const top = y(Math.max(bar.o, bar.c));
              const bottom = y(Math.min(bar.o, bar.c));

              return (
                <g
                  key={bar.t}
                  opacity={hover === null || hover === index ? 1 : 0.55}
                >
                  <line
                    x1={centre}
                    y1={y(bar.h)}
                    x2={centre}
                    y2={y(bar.l)}
                    stroke={tone}
                    strokeWidth={1}
                  />
                  <rect
                    x={centre - body / 2}
                    y={top}
                    width={body}
                    height={Math.max(bottom - top, 1)}
                    fill={tone}
                  />
                </g>
              );
            })}

            <line
              x1={0}
              y1={y(last.c)}
              x2={plotWidth}
              y2={y(last.c)}
              stroke="var(--rule)"
              strokeWidth={1}
              strokeDasharray="3 3"
              opacity={0.45}
            />
            <rect
              x={plotWidth + 4}
              y={y(last.c) - 8}
              width={margin.right - 6}
              height={16}
              fill="var(--rule)"
            />
            <text
              x={plotWidth + 8}
              y={y(last.c)}
              dominantBaseline="middle"
              className="num"
              fontSize={10}
              fill="var(--surface)"
            >
              {formatPrice(last.c)}
            </text>

            {hover !== null && (
              <line
                x1={hover * slot + slot / 2}
                y1={0}
                x2={hover * slot + slot / 2}
                y2={plotHeight}
                stroke="var(--line-strong)"
              />
            )}

            {bars.map((bar, index) =>
              index % axisEvery === 0 ? (
                <text
                  key={`axis${bar.t}`}
                  x={index * slot + slot / 2}
                  y={plotHeight + 16}
                  textAnchor="middle"
                  className="num"
                  fontSize={10}
                  fill="var(--ink-faint)"
                >
                  {formatStamp(bar.t, "axis")}
                </text>
              ) : null,
            )}
          </g>
        </svg>
      )}

      {hover !== null && (
        <Tip
          x={Math.min(
            Math.max(margin.left + hover * slot + slot / 2, 90),
            width - 90,
          )}
          y={margin.top + y(Math.max(bars[hover].o, bars[hover].c))}
        >
          <div className="num text-muted">{formatStamp(bars[hover].t, "full")}</div>
          <div className="num mt-0.5 flex gap-2">
            {(
              [
                [labels.open, bars[hover].o],
                [labels.high, bars[hover].h],
                [labels.low, bars[hover].l],
                [labels.close, bars[hover].c],
              ] as const
            ).map(([mark, value]) => (
              <span key={mark}>
                <span className="text-faint">{mark}</span> {formatPrice(value)}
              </span>
            ))}
          </div>
        </Tip>
      )}
    </div>
  );
}
