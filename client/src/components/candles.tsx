import { useEffect, useLayoutEffect, useRef } from "react";
import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useSession } from "../lib/session";
import type { Bar } from "../lib/api";

/*
  The price chart, on TradingView's Lightweight Charts.

  It draws candles this project already drew, and it brings the three things a
  hand rolled chart does not get for free: dragging back through history,
  zooming into a stretch of it, and a crosshair that reads the series rather
  than the pixel. For a swing horizon those are the interaction, not polish.

  The library carries no data of its own. Every bar here still comes from
  basis.equity_bar, so provenance, the stamp on each reading and the honesty
  about a delayed feed are unchanged. That is the whole reason to take the
  open source library rather than the embeddable widget, which would have
  drawn TradingView's own prices beside our own and left no way to say which
  number the screen was making a claim about.
*/

/*
  The library has no timezone setting and renders every timestamp as UTC, so
  the shift is done to the data before it goes in.

  A daily bar is a session rather than a moment, and it is stamped at the
  instant the session opened, so rendering it in the reader's own zone can move
  it onto the day before. Those go in as a calendar date in the exchange's zone.
  An intraday bar really is a moment, so it goes in shifted to the zone the
  reader is reading in.
*/
const EXCHANGE_ZONE = "America/New_York";

/*
  Worked out once per day rather than once per bar.

  A zone offset is a property of the calendar day, not of the minute, so a
  session of 390 candles asks the same question 390 times and gets the same
  answer. Each ask is two Intl formats, which are among the most expensive
  calls in the browser, and that arithmetic was most of what made changing to
  an intraday window slower than changing to a daily one.

  Keyed on the day so a window spanning a clock change still gets both answers.
*/
const offsets = new Map<string, number>();

function zoneOffsetSeconds(zone: string, at: Date): number {
  const day = `${zone}:${at.toISOString().slice(0, 10)}`;
  const known = offsets.get(day);
  if (known !== undefined) return known;

  const utc = new Date(at.toLocaleString("en-US", { timeZone: "UTC" }));
  const local = new Date(at.toLocaleString("en-US", { timeZone: zone }));
  const offset = Math.round((local.getTime() - utc.getTime()) / 1000);

  offsets.set(day, offset);
  return offset;
}

/*
  Built once. Constructing an Intl formatter is the expensive half of using
  one, and a thousand daily bars would otherwise construct a thousand of them.
*/
const sessionDay = new Intl.DateTimeFormat("en-CA", {
  timeZone: EXCHANGE_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function sessionDate(iso: string): string {
  return sessionDay.format(new Date(iso));
}

function stamp(iso: string, daily: boolean, zone: string): Time {
  if (daily) return sessionDate(iso) as Time;
  const at = new Date(iso);
  return ((at.getTime() / 1000 + zoneOffsetSeconds(zone, at)) as UTCTimestamp);
}

/*
  Colour is read from the stylesheet rather than repeated here, so the palette
  and its one scoped exception stay defined in exactly one place. Reading it
  again is also how the chart follows a theme change.
*/
function palette() {
  const style = getComputedStyle(document.documentElement);
  const read = (name: string) => style.getPropertyValue(name).trim();

  return {
    up: read("--up"),
    down: read("--down"),
    ink: read("--ink"),
    faint: read("--ink-faint"),
    line: read("--line"),
    lineStrong: read("--line-strong"),
    surface: read("--surface"),
    measured: read("--measured"),
    modelled: read("--modelled"),
  };
}

export function Candles({
  bars,
  marks = [],
  granularity,
  height = 380,
}: {
  bars: Bar[];
  marks?: { t: string; label: string; note?: string | null }[];
  granularity: string;
  height?: number;
}) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const pins = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  const { theme, timezone, language } = useSession();
  const daily = granularity === "D";

  useEffect(() => {
    const node = box.current;
    if (!node) return;

    const colours = palette();
    const drawn = createChart(node, {
      height,
      layout: {
        background: { color: "transparent" },
        textColor: colours.faint,
        fontFamily: '"IBM Plex Mono", ui-monospace, monospace',
        fontSize: 10,
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: colours.line },
        horzLines: { color: colours.line },
      },
      rightPriceScale: { borderColor: colours.line },
      timeScale: {
        borderColor: colours.line,
        timeVisible: !daily,
        secondsVisible: false,
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: colours.lineStrong,
          labelBackgroundColor: colours.ink,
        },
        horzLine: {
          color: colours.lineStrong,
          labelBackgroundColor: colours.ink,
        },
      },
    });

    const line = drawn.addSeries(CandlestickSeries, {
      upColor: colours.up,
      downColor: colours.down,
      wickUpColor: colours.up,
      wickDownColor: colours.down,
      borderVisible: false,
    });

    chart.current = drawn;
    series.current = line;
    pins.current = createSeriesMarkers(line, []);

    const resize = new ResizeObserver(([entry]) =>
      drawn.applyOptions({ width: entry.contentRect.width }),
    );
    resize.observe(node);

    return () => {
      resize.disconnect();
      drawn.remove();
      chart.current = null;
      series.current = null;
      pins.current = null;
    };
  }, [height]);

  /*
    Built once and then reconfigured, rather than rebuilt.

    Moving between an intraday window and a daily one changes only whether the
    axis prints a clock, and tearing the chart down to answer that cost a few
    hundred milliseconds on exactly the switches a reader makes most. The
    locale is the same kind of thing: a setting on a chart that already exists.
  */
  useEffect(() => {
    chart.current?.applyOptions({
      timeScale: { timeVisible: !daily, secondsVisible: false },
      localization: { locale: language === "pt" ? "pt-BR" : "en-GB" },
    });
  }, [daily, language]);

  useEffect(() => {
    const line = series.current;
    if (!line || bars.length === 0) return;

    line.setData(
      bars.map((bar) => ({
        time: stamp(bar.t, daily, timezone),
        open: bar.o,
        high: bar.h,
        low: bar.l,
        close: bar.c,
      })),
    );

    /*
      A release accepted after the close belongs to the session it will move,
      which is the next bar, so the mark is placed on the first bar at or after
      the acceptance rather than on the nearest one.

      A release older than the window is not placed at all. Without that test
      every earlier one answers with the first bar and they stack up against
      the left edge, which reads as four results on one session rather than as
      four results the window does not reach.
    */
    /*
      Two marks on one session rather than one carrying both claims. The
      acceptance instant is published and the surprise beside it is a number
      derived under a stated rule, and this palette says which is which with
      colour. A single marker would have to pick one of the two colours and
      would then be telling the reader something false about half of itself.
    */
    const times = bars.map((bar) => bar.t);
    const tone = palette();

    pins.current?.setMarkers(
      marks
        .flatMap((mark) => {
          const index = mark.t < times[0] ? -1 : times.findIndex((time) => time >= mark.t);
          if (index < 0) return [];

          const time = stamp(times[index], daily, timezone);
          const placed: SeriesMarker<Time>[] = [
            {
              time,
              position: "aboveBar",
              shape: "arrowDown",
              color: tone.measured,
              text: mark.label,
            },
          ];

          if (mark.note) {
            placed.push({
              time,
              position: "belowBar",
              shape: "circle",
              color: tone.modelled,
              text: mark.note,
            });
          }

          return placed;
        }),
    );

    chart.current?.timeScale().fitContent();
  }, [bars, marks, daily, timezone]);

  /*
    Laid out rather than deferred, so the repaint lands inside the same frame
    the theme flips in. A passive effect would repaint a frame later, and the
    chart would be the one element arriving after the cross-fade rather than
    inside it.
  */
  useLayoutEffect(() => {
    const drawn = chart.current;
    const line = series.current;
    if (!drawn || !line) return;

    const colours = palette();

    /*
      The colour actually applied is recorded on the container, so that the
      chart being painted in the current theme is a fact something can check
      rather than an assumption. It is how the gridlines-from-the-other-mode
      bug is kept fixed: a canvas cannot be read from the outside, and without
      this the only witness is a person noticing.
    */
    box.current?.setAttribute("data-painted-line", colours.line);

    drawn.applyOptions({
      layout: { textColor: colours.faint },
      grid: {
        vertLines: { color: colours.line },
        horzLines: { color: colours.line },
      },
      rightPriceScale: { borderColor: colours.line },
      timeScale: { borderColor: colours.line },
      crosshair: {
        vertLine: { color: colours.lineStrong, labelBackgroundColor: colours.ink },
        horzLine: { color: colours.lineStrong, labelBackgroundColor: colours.ink },
      },
    });
    line.applyOptions({
      upColor: colours.up,
      downColor: colours.down,
      wickUpColor: colours.up,
      wickDownColor: colours.down,
    });
  }, [theme]);

  return <div ref={box} className="w-full" style={{ height }} />;
}
