/*
  What a company actually reported, which is the half of a surprise that free
  data can supply.

  An earnings release is already in basis.calendar_event, stamped to the second
  by the SEC, and its text is in basis.text_document. Neither of them carries a
  number a later reader can compute with: the event is a timestamp and the text
  is prose. This table is the numbers, taken from XBRL, where every fact arrives
  with the period it describes and the filing that reported it.

  It is not basis.macro_observation. That table is keyed by series, one value
  per instant, which is the right shape for a published statistic and the wrong
  one for an accounting fact: the same quarter is reported many times, under
  concepts that differ by company, in units that differ by measure, and each of
  those distinctions changes what the number means.
*/

create table basis.company_fact (
  id             bigserial primary key,
  cik            text not null,
  measure        text not null,
  concept        text not null,
  unit           text not null,
  period_start   date,
  period_end     date not null,
  span_days      int generated always as (period_end - period_start) stored,
  fiscal_year    int,
  fiscal_period  text,
  form           text,
  accession      text,
  value          numeric(28,6) not null,
  filed          date not null,
  available_at   timestamptz not null,
  stamp          text not null check (stamp in ('acceptance', 'filing_day_end')),

  /*
    The same quarter reported twice is two rows, not a correction of one. A
    10-Q states the quarter, the next year's filing states it again as a
    comparative, and a restatement states it a third time with a different
    value. Which of the three was knowable on a given day is the only question
    a backtest is allowed to ask, and it is answerable only if all three are
    kept. The accession is what separates them, since it names the filing.

    Nulls are not distinct here because period_start is absent on every
    balance sheet fact, and the default treatment would let the same instant
    be written without limit.
  */
  unique nulls not distinct
    (cik, measure, concept, period_start, period_end, form, accession),

  /*
    A quarter cannot be reported before it has ended. This is the same refusal
    the other tables carry, written against filed rather than against
    available_at so that it compares two dates and stays immutable.
  */
  constraint company_fact_not_precognitive check (filed >= period_end)
);

create index company_fact_asof
  on basis.company_fact (cik, measure, period_end desc, available_at desc);

create index company_fact_available
  on basis.company_fact (cik, available_at);
