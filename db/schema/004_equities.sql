/*
  Equities do not fit price_bar, and forcing them in would corrupt the one
  number the engine is least allowed to guess.

  price_bar carries a bid series and an ask series because the venue quotes
  both, and the whole cost discipline in this project rests on charging the
  measured spread rather than assuming it away. A daily equity bar from a chart
  feed carries open, high, low, close and volume, and no quote at all. Writing
  the close into both bid and ask would state a spread of zero, which is not a
  missing value, it is a false one, and every backtest downstream would read it
  as free execution.

  So equities get their own table, shaped like the fact actually is. Cost for an
  equity is commission plus half a spread that this source cannot measure, and
  it has to be supplied explicitly rather than inferred from a bar.
*/

alter table basis.instrument
  drop constraint instrument_asset_class;

alter table basis.instrument
  add constraint instrument_asset_class
    check (asset_class in ('fx', 'metal', 'index', 'bond', 'equity'));

create table basis.equity_bar (
  instrument_id  text not null references basis.instrument(id),
  source_id      text not null references basis.source(id),
  granularity    text not null,
  effective_time timestamptz not null,
  open   numeric(18,6) not null,
  high   numeric(18,6) not null,
  low    numeric(18,6) not null,
  close  numeric(18,6) not null,
  volume bigint,
  primary key (instrument_id, source_id, granularity, effective_time),
  constraint equity_bar_high_is_highest check (high >= greatest(open, close, low)),
  constraint equity_bar_low_is_lowest check (low <= least(open, close, high))
);

create index equity_bar_asof
  on basis.equity_bar (instrument_id, granularity, effective_time desc);

/*
  A split restates every historical price for a name, so the series a feed
  returns today is expressed in units set by the most recent split rather than
  in the units a person saw on the screen at the time. Returns survive that
  unchanged, which is why it is a change of units and not a revision of
  information, and why the study can use the restated series without cheating.

  What does not survive is the claim that a stored row never changes. Recording
  the actions themselves is what makes a units change detectable: a fresh fetch
  whose cumulative split factor disagrees with the stored one is a rewrite that
  has to be deliberate and visible, rather than a silent overwrite of history.

  available_at is the instant the action became knowable, which for a split is
  its announcement and not its effective date. Only the effective date is
  published by this feed, so available_at is set to it and is therefore late
  rather than early. Late is the safe direction: it withholds from a backtest
  something the market already knew, and never the reverse.
*/
create table basis.corporate_action (
  id             bigserial primary key,
  instrument_id  text not null references basis.instrument(id),
  source_id      text not null references basis.source(id),
  action_type    text not null check (action_type in ('split', 'dividend')),
  effective_date date not null,
  numerator      numeric(18,8),
  denominator    numeric(18,8),
  cash_amount    numeric(18,8),
  available_at   timestamptz not null,
  unique (instrument_id, source_id, action_type, effective_date),
  constraint corporate_action_split_has_ratio
    check (action_type <> 'split' or (numerator is not null and denominator is not null)),
  constraint corporate_action_dividend_has_amount
    check (action_type <> 'dividend' or cash_amount is not null)
);

create index corporate_action_asof
  on basis.corporate_action (instrument_id, effective_date desc);
