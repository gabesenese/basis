create schema if not exists basis;

/*
  Bitemporal contract. Every fact carries two instants:

    effective_time  the instant the fact describes
    available_at    the instant the fact first became knowable to us

  A correction or revision is a new row with the same entity key, the same
  effective_time and a later available_at. Rows are never updated in place,
  so any as-of query reconstructs exactly what was knowable at that instant
  by taking the row with the greatest available_at not exceeding the cutoff.
*/

create type basis.source_kind as enum (
  'price', 'calendar', 'expectation', 'outcome', 'positioning', 'text'
);

create table basis.source (
  id            text primary key,
  kind          basis.source_kind not null,
  publisher     text not null,
  redistributable boolean not null,
  notes         text
);

create table basis.instrument (
  id        text primary key,
  base_ccy  char(3) not null,
  quote_ccy char(3) not null,
  pip_size  numeric(12,8) not null
);

create table basis.calendar_event (
  id              bigserial primary key,
  event_key       text not null,
  source_id       text not null references basis.source(id),
  region          text not null,
  event_code      text not null,
  scheduled_time  timestamptz not null,
  available_at    timestamptz not null,
  payload         jsonb not null default '{}'::jsonb,
  unique (event_key, available_at)
);

create index calendar_event_asof on basis.calendar_event (event_key, available_at desc);
create index calendar_event_upcoming on basis.calendar_event (scheduled_time);

create table basis.expectation (
  id             bigserial primary key,
  event_key      text not null,
  source_id      text not null references basis.source(id),
  measure        text not null,
  effective_time timestamptz not null,
  available_at   timestamptz not null,
  point_value    numeric(18,8),
  distribution   jsonb,
  unique (event_key, source_id, measure, effective_time, available_at),
  constraint expectation_has_value check (point_value is not null or distribution is not null),
  constraint expectation_not_precognitive check (available_at >= effective_time)
);

create index expectation_asof on basis.expectation (event_key, measure, available_at desc);

create table basis.macro_observation (
  id             bigserial primary key,
  series_id      text not null,
  source_id      text not null references basis.source(id),
  effective_time timestamptz not null,
  available_at   timestamptz not null,
  value          numeric(18,8) not null,
  unique (series_id, effective_time, available_at),
  constraint macro_not_precognitive check (available_at >= effective_time)
);

create index macro_observation_asof on basis.macro_observation (series_id, effective_time, available_at desc);

create table basis.positioning (
  id             bigserial primary key,
  contract_code  text not null,
  source_id      text not null references basis.source(id),
  effective_time timestamptz not null,
  available_at   timestamptz not null,
  metrics        jsonb not null,
  unique (contract_code, effective_time, available_at),
  constraint positioning_not_precognitive check (available_at >= effective_time)
);

create index positioning_asof on basis.positioning (contract_code, available_at desc);

create table basis.text_document (
  id            bigserial primary key,
  document_key  text not null unique,
  source_id     text not null references basis.source(id),
  event_key     text,
  document_type text not null,
  published_at  timestamptz not null,
  body          text not null,
  body_sha256   char(64) not null
);

create index text_document_event on basis.text_document (event_key, published_at);

/*
  available_at mirrors the document's published_at rather than computed_at.
  The information existed the moment the text was published; computed_at only
  records when this labeller got around to reading it. Backfilled labels must
  therefore be reachable by as-of queries at the publication instant, while a
  change of labeller_version obliges a full reprocessing of history so that
  live and historical labels remain the same measurement.
*/
create table basis.text_feature (
  id                bigserial primary key,
  document_id       bigint not null references basis.text_document(id),
  feature_key       text not null,
  labeller_id       text not null,
  labeller_version  text not null,
  input_sha256      char(64) not null,
  available_at      timestamptz not null,
  computed_at       timestamptz not null default now(),
  value             jsonb not null,
  unique (document_id, feature_key, labeller_id, labeller_version)
);

create index text_feature_asof on basis.text_feature (feature_key, available_at desc);

create table basis.price_bar (
  instrument_id  text not null references basis.instrument(id),
  source_id      text not null references basis.source(id),
  granularity    text not null,
  effective_time timestamptz not null,
  bid_open   numeric(18,8) not null,
  bid_high   numeric(18,8) not null,
  bid_low    numeric(18,8) not null,
  bid_close  numeric(18,8) not null,
  ask_open   numeric(18,8) not null,
  ask_high   numeric(18,8) not null,
  ask_low    numeric(18,8) not null,
  ask_close  numeric(18,8) not null,
  tick_count integer,
  primary key (instrument_id, source_id, granularity, effective_time)
);

create table basis.input_snapshot (
  sha256      char(64) primary key,
  as_of       timestamptz not null,
  captured_at timestamptz not null default now(),
  payload     jsonb not null
);

create table basis.signal (
  id                   bigserial primary key,
  instrument_id        text not null references basis.instrument(id),
  event_key            text,
  as_of                timestamptz not null,
  horizon              interval not null,
  direction            text not null check (direction in ('long', 'short')),
  raw_probability      numeric(6,5) not null check (raw_probability between 0 and 1),
  calibrated_probability numeric(6,5) not null check (calibrated_probability between 0 and 1),
  threshold            numeric(6,5) not null check (threshold between 0 and 1),
  entry                numeric(18,8) not null,
  invalidation         numeric(18,8) not null,
  target               numeric(18,8) not null,
  flat_by              timestamptz not null,
  gate_results         jsonb not null,
  input_snapshot_sha256 char(64) not null references basis.input_snapshot(sha256),
  engine_version       text not null,
  created_at           timestamptz not null default now()
);

create index signal_as_of on basis.signal (as_of desc);

create function basis.reject_signal_mutation()
returns trigger language plpgsql as $$
begin
  raise exception 'basis.signal is append only: % rejected on signal %',
    tg_op, coalesce(old.id, new.id)
    using errcode = 'restrict_violation';
end;
$$;

create trigger signal_append_only
  before update or delete on basis.signal
  for each row execute function basis.reject_signal_mutation();

create table basis.signal_resolution (
  signal_id     bigint primary key references basis.signal(id),
  resolved_at   timestamptz not null,
  outcome       boolean not null,
  realised_move numeric(18,8) not null,
  price_source_id text not null references basis.source(id)
);

create table basis.execution (
  id            bigserial primary key,
  signal_id     bigint not null references basis.signal(id),
  account_ref   text not null,
  action        text not null check (action in ('taken', 'skipped')),
  skip_reason   text,
  filled_at     timestamptz,
  fill_price    numeric(18,8),
  size          numeric(18,8),
  recorded_at   timestamptz not null default now(),
  constraint execution_skip_has_reason check (action = 'taken' or skip_reason is not null),
  constraint execution_taken_has_fill check (action = 'skipped' or (filled_at is not null and fill_price is not null))
);

create index execution_signal on basis.execution (signal_id);

create function basis.macro_as_of(p_series_id text, p_as_of timestamptz)
returns table (effective_time timestamptz, value numeric)
language sql stable as $$
  select distinct on (o.effective_time) o.effective_time, o.value
  from basis.macro_observation o
  where o.series_id = p_series_id and o.available_at <= p_as_of
  order by o.effective_time, o.available_at desc
$$;

create function basis.expectation_as_of(p_event_key text, p_measure text, p_as_of timestamptz)
returns table (effective_time timestamptz, point_value numeric, distribution jsonb)
language sql stable as $$
  select e.effective_time, e.point_value, e.distribution
  from basis.expectation e
  where e.event_key = p_event_key and e.measure = p_measure and e.available_at <= p_as_of
  order by e.available_at desc, e.effective_time desc
  limit 1
$$;

create function basis.positioning_as_of(p_contract_code text, p_as_of timestamptz)
returns table (effective_time timestamptz, metrics jsonb)
language sql stable as $$
  select p.effective_time, p.metrics
  from basis.positioning p
  where p.contract_code = p_contract_code and p.available_at <= p_as_of
  order by p.available_at desc
  limit 1
$$;

create function basis.calendar_as_of(p_as_of timestamptz, p_from timestamptz, p_to timestamptz)
returns table (event_key text, region text, event_code text, scheduled_time timestamptz, payload jsonb)
language sql stable as $$
  select distinct on (c.event_key) c.event_key, c.region, c.event_code, c.scheduled_time, c.payload
  from basis.calendar_event c
  where c.available_at <= p_as_of and c.scheduled_time >= p_from and c.scheduled_time < p_to
  order by c.event_key, c.available_at desc
$$;
