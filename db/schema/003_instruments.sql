/*
  The instrument table was written when there was one instrument and it was a
  currency pair, so it required a base currency and a quote currency. An equity
  index has neither, and a note future has neither, and both of them respond to
  the same rate announcement the engine already studies.

  What survives is pip_size, because it is the venue's own vocabulary rather
  than a currency one: OANDA publishes pipLocation for every instrument it
  serves, including the index and bond CFDs, and it is the unit the spread is
  quoted in and therefore the unit the cost is paid in.

  What does not survive is base_ccy. The quote currency stays required, since
  every instrument is settled in something and that is the currency the cost
  lands in.
*/

alter table basis.instrument
  add column asset_class  text,
  add column display_name text;

update basis.instrument
   set asset_class  = 'fx',
       display_name = base_ccy || '/' || quote_ccy
 where asset_class is null;

alter table basis.instrument
  alter column asset_class  set not null,
  alter column display_name set not null,
  alter column base_ccy     drop not null;

alter table basis.instrument
  add constraint instrument_asset_class
    check (asset_class in ('fx', 'metal', 'index', 'bond')),
  add constraint instrument_fx_has_base
    check (asset_class <> 'fx' or base_ccy is not null);
