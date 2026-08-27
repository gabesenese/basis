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
