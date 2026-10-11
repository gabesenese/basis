import type { Language } from "./i18n";

const LOCALE: Record<Language, string> = { pt: "pt-BR", en: "en-GB" };

export function number(
  language: Language,
  value: number | null | undefined,
  digits = 2,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  /*
    A tick a hair below zero rounds to "-0" on an axis, which reads as a real
    negative quantity at a glance. Collapsing it to zero is not rounding twice,
    it is refusing to print a sign the value does not have.
  */
  const rounded = Number(value.toFixed(digits));
  return (rounded === 0 ? 0 : rounded).toLocaleString(LOCALE[language], {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function signed(
  language: Language,
  value: number | null | undefined,
  digits = 2,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const body = Math.abs(value).toLocaleString(LOCALE[language], {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  if (value > 0) return `+${body}`;
  if (value < 0) return `−${body}`;
  return body;
}

/*
  A quarter's revenue is tens of billions and a quarter's earnings per share is
  about a dollar, and the two sit in the same table. Printing the first in full
  would make the column wider than the screen and would ask the reader to count
  digits to tell forty billion from four hundred, which is a comparison the eye
  should make without arithmetic.
*/
export function compact(language: Language, value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (Math.abs(value) < 1000) return number(language, value, 2);
  return value.toLocaleString(LOCALE[language], {
    notation: "compact",
    maximumFractionDigits: 1,
  });
}

/*
  EUR/USD quotes how many dollars buy one euro, so the symbol on a spot price
  is the quote currency's and never the base's. It comes from the instrument
  row rather than from the pair's name.
*/
const SYMBOLS: Record<string, string> = {
  USD: "$",
  EUR: "€",
  GBP: "£",
  JPY: "¥",
  CHF: "Fr",
  CAD: "$",
  BRL: "R$",
};

export function currencySymbol(code: string | null | undefined): string {
  if (!code) return "";
  return SYMBOLS[code] ?? code;
}

export function price(language: Language, value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString(LOCALE[language], {
    minimumFractionDigits: 5,
    maximumFractionDigits: 5,
  });
}

export function dateTime(
  language: Language,
  timezone: string,
  iso: string | null | undefined,
): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(LOCALE[language], {
    timeZone: timezone,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}

export function dayOnly(
  language: Language,
  timezone: string,
  iso: string | null | undefined,
): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(LOCALE[language], {
    timeZone: timezone,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(iso));
}

export function clock(timezone: string, at: Date): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: timezone,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(at);
}

export function zoneLabel(timezone: string): string {
  const city = timezone.split("/").pop() ?? timezone;
  return city.replace(/_/g, " ");
}

export function age(seconds: number | null | undefined, agoWord: string, neverWord: string): string {
  if (seconds === null || seconds === undefined) return neverWord;
  if (seconds < 120) return `${Math.round(seconds)}s ${agoWord}`;
  if (seconds < 7200) return `${Math.round(seconds / 60)}m ${agoWord}`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)}h ${agoWord}`;
  return `${Math.round(seconds / 86400)}d ${agoWord}`;
}

export type Countdown = { days: number; hours: number; minutes: number; past: boolean };

export function countdown(target: string, from: Date): Countdown {
  const delta = new Date(target).getTime() - from.getTime();
  const past = delta < 0;
  const total = Math.floor(Math.abs(delta) / 1000);
  return {
    days: Math.floor(total / 86400),
    hours: Math.floor((total % 86400) / 3600),
    minutes: Math.floor((total % 3600) / 60),
    past,
  };
}

const EVENT_NAMES: Record<string, Record<Language, string>> = {
  FOMC_DECISION: { pt: "Decisão do FOMC", en: "FOMC decision" },
  ECB_GOVERNING_COUNCIL: {
    pt: "Conselho do BCE",
    en: "ECB Governing Council",
  },
};

export function eventName(language: Language, code: string): string {
  return EVENT_NAMES[code]?.[language] ?? code;
}

const HORIZON_LABELS: Record<string, string> = {
  ret_5m: "5m",
  ret_30m: "30m",
  ret_1h: "1h",
  ret_2h: "2h",
  ret_1d: "1d",
};

export function horizonLabel(key: string): string {
  return HORIZON_LABELS[key] ?? key;
}

/*
  A share price is quoted in cents and a currency pair in pips, so the five
  decimals `price` fixes are wrong for a company. Two is right for almost every
  listed name, and the sub-dollar ones need more, so the count follows the
  magnitude rather than being fixed.
*/
export function money(language: Language, value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const digits = Math.abs(value) >= 1 ? 2 : 4;
  return value.toLocaleString(LOCALE[language], {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function percent(language: Language, value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${signed(language, value, 2)}%`;
}

/*
  A daily bar is stamped at the session's opening instant, so rendering it in
  the reader's own zone can move it onto the day before. The date on a daily
  candle is therefore read in the exchange's zone, and only an intraday bar,
  which is a moment rather than a day, is shown in the reader's own.
*/
const EXCHANGE_ZONE = "America/New_York";

export function barStamp(
  language: Language,
  timezone: string,
  iso: string,
  granularity: string,
  form: "axis" | "full",
): string {
  const daily = granularity === "D";
  const zone = daily ? EXCHANGE_ZONE : timezone;
  const date = new Date(iso);

  if (daily) {
    return new Intl.DateTimeFormat(LOCALE[language], {
      timeZone: zone,
      day: "2-digit",
      month: "2-digit",
      ...(form === "full" ? { year: "numeric" } : {}),
    }).format(date);
  }

  return new Intl.DateTimeFormat(LOCALE[language], {
    timeZone: zone,
    ...(form === "full" ? { day: "2-digit", month: "2-digit" } : {}),
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}
