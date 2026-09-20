export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!response.ok) {
    const detail = await response
      .json()
      .then((body) => body.detail)
      .catch(() => response.statusText);
    throw new ApiError(response.status, String(detail));
  }

  return response.json() as Promise<T>;
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  patch: <T,>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  remove: <T,>(path: string) => request<T>(path, { method: "DELETE" }),
};

export type Account = {
  id: number;
  email: string;
  display_name: string;
  language: "pt" | "en";
  timezone: string;
};

export type Finding = {
  subject: string;
  healthy: boolean;
  detail: string;
  facts: {
    age_seconds?: number | null;
    ticks_written?: number;
    started_at?: string;
    reconnects?: number;
    market_closed?: boolean;
    newest?: string | null;
    never_run?: boolean;
  };
};

export type CostPoint = {
  seconds: number;
  pips: number;
  provenance: string;
  basis: string;
};

export type Instrument = {
  id: string;
  base_ccy: string | null;
  quote_ccy: string | null;
  pip_size: number | null;
};

export type Today = {
  as_of: string;
  market_open: boolean;
  instrument: Instrument;
  spot: {
    bid: number;
    ask: number;
    mid: number;
    spread_pips: number | null;
    as_of: string;
    source: string;
    measured: boolean;
  } | null;
  next_event: {
    event_key: string;
    region: string;
    event_code: string;
    scheduled_time: string;
    known_since: string;
    payload: Record<string, unknown>;
  } | null;
  cost: {
    baseline_pips: number | null;
    events_measured: number;
    shape_source?: string;
    applied_to?: string;
    points: CostPoint[];
  };
  health: Finding[];
};

export type CalendarEvent = {
  event_key: string;
  region: string;
  event_code: string;
  scheduled_time: string;
  known_since: string;
  vintages: number;
  payload: Record<string, unknown>;
};

export type Slope = {
  name: string;
  estimate: number;
  robust_low: number;
  robust_high: number;
  boot_low: number;
  boot_high: number;
  p_value: number;
  excludes_zero: boolean;
};

export type Fit = {
  response: string;
  n: number;
  r_squared: number;
  slopes: Slope[];
};

export type Meeting = {
  event_key: string;
  statement_time: string;
  window_lead_days: number;
  actual_bps: number;
  expected_bps: number;
  surprise_bps: number;
  std_bps: number;
  z_surprise: number;
  z_actual: number;
  z_expected: number;
  z_reprice: number | null;
  reprice_bps: number | null;
  ret_5m: number | null;
  ret_30m: number | null;
  ret_1h: number | null;
  ret_2h: number | null;
  ret_1d: number | null;
};

export type Study = {
  horizons: string[];
  gate_horizon: string;
  coverage: {
    meetings: number;
    first: string;
    last: string;
    decisions_that_moved: number;
    window_lead_days: { min: number; median: number; max: number };
  };
  tests: Record<
    string,
    {
      regressors: string[];
      tradable: boolean;
      by_horizon: Record<string, Fit>;
    }
  >;
  leave_one_out: { low: number; high: number };
  magnitude: { n: number; spearman: number; p_value: number };
  event_versus_ordinary: {
    event_n: number;
    event_median_pips: number;
    ordinary_n: number;
    ordinary_median_pips: number;
    ratio: number | null;
  };
  response_median_pips: Record<string, number>;
  meetings: Meeting[];
};

export type Positioning = {
  contract: string;
  weeks: number;
  series: {
    effective_time: string;
    known_since: string;
    noncomm_net: number | null;
    noncomm_long: number | null;
    noncomm_short: number | null;
    open_interest: number | null;
  }[];
};

export type LastClose = {
  close: number;
  previous_close?: number;
  change?: number;
  change_pct?: number;
  as_of: string;
};

export type CompanyHit = {
  ticker: string;
  cik: string;
  name: string;
  last: LastClose | null;
};

export type Search = {
  query: string;
  universe: number;
  results: CompanyHit[];
};

export type CollectedCompany = {
  ticker: string;
  name: string;
  sessions: number;
  oldest: string;
  newest: string;
  last: LastClose | null;
};

export type Bar = {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number | null;
};

export type Quote = {
  price: number;
  previous_close: number | null;
  currency: string | null;
  exchange: string | null;
  as_of: string | null;
  age_seconds: number | null;
  market_state: string | null;
  delayed: boolean;
  source: string;
};

/*
  What the company's own history implied for the quarter it was about to
  report, beside what it reported. The expectation is a rule over its filings
  and not a consensus, so it is modelled where the release instant is measured,
  and the interface has to keep the two apart.
*/
export type Reading = {
  expected: number;
  actual: number;
  surprise: number;
  period_end: string;
  rule: string;
  origin: string;
};

export type EarningsRelease = {
  event_key: string;
  accepted_at: string;
  known_since: string;
  form: string | null;
  items: string | null;
  accession: string | null;
  against: Record<string, Reading> | null;
};

/*
  Two payloads rather than one, because the two move at different speeds. The
  header carries what has to be current and is fetched upstream to be so. The
  series carries what the reader changes often and is answered from the store.
*/
export type CompanyHead = {
  ticker: string;
  cik: string;
  name: string;
  as_of: string;
  last_close: LastClose | null;
  earnings: EarningsRelease[];
  collecting: boolean;
  source: string;
};

export type CompanyQuote = {
  ticker: string;
  as_of: string;
  quote: Quote | null;
  last_close: LastClose | null;
  feed_answered: boolean;
};

export type CompanyBars = {
  ticker: string;
  as_of: string;
  granularity: string;
  bars: Bar[];
  collected: boolean;
  refreshing: boolean;
  source: string;
};
