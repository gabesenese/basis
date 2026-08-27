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

  const height = 208;
  const margin = { top: 12, right: 12, bottom: 30, left: 40 };
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
