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
