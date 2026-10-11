# Basis

A daily and weekly signal, produced by digesting public information, across a
set of instruments that respond to the same scheduled events. Two users, no
customers.

**Widened on 2026-09-02, agreed by both users.** The project ran until now on
one instrument at one horizon. Both were scoping decisions and both were costing
sample, which is the constraint that broke the Phase 2 gate. EUR/USD stays the
reference instrument, and it stops being the only one.

**Turned on 2026-09-06, and it is a change of subject rather than a change of
scope.** The instrument is no longer a currency pair and the horizon is no
longer a session. Basis is now a tool for deciding whether to hold a share of an
individual company over days and weeks, and it opens on a search field rather
than on a reading.

Everything measured before this stands, and none of it transfers. The FOMC work
below is a true account of what that event universe supports, and this plan
already says in two places why it does not carry to a company: the daily trade
was calibrated on a pair that trades through the night, and a share gaps over
its own invalidation while the market is shut. What survives the turn is the
discipline rather than the findings. Every number still traces to a stored
record, every record still carries the instant it became knowable, and a price
the feed has not confirmed is still labelled as the last one that was.

The sections below are kept as the record of what was measured and why the
answer was no. They are no longer a description of the product.

**Direction set on 2026-08-26: the signal is mandatory and daily.** Every
trading session gets a direction, an entry, an invalidation, a target and an
hour to be flat, published before the New York open. This replaces the earlier
framing, which emitted only when a threshold was cleared and expected silence on
most days.

The cost of that decision is stated rather than hidden. A system obliged to
speak every day will speak on days it has nothing, so its Brier score will be
worse than one allowed to stay quiet. What keeps it honest is that **every
signal carries its own calibrated probability and its own scorecard**. A day
with no edge produces a signal near 0.50 and says so, and the execution record
is separate from the signal, so taking the trade stays a human decision.

Every forecast is still scored against the coin flip. That is the whole point of
scoring: a signal that cannot beat a coin is a signal that should not be traded,
and the platform's job is to say which is which rather than to look confident.

Three sources feed it, and all three must be public and verifiable: the price
record itself, read technically; the scheduled event calendar with its
expectations; and the text of what institutions and the press actually publish.

Not a business. That is a scoping decision, not a disclaimer: no multi-tenancy,
no billing, no roles, no onboarding. Two accounts, one shared canonical record,
two languages and two timezones on top of it.

## Architecture

**Python everywhere on the server.** Collectors, event study and the engine live
in one language because they share the same data structures, and the statistics
we need (isotonic regression, quantile regression, Brier decomposition) already
exist there. FastAPI for the API surface.

**React and Vite on the front**, carrying over the mockup that already exists as
plain HTML and CSS.

**Postgres as the primary lane.** Calendar, expectations, features, signals,
executions and price bars all live there under the bitemporal contract in
db/schema/001_point_in_time.sql. A decade of one minute bars is a few million
rows, which Postgres handles comfortably, and keeping price beside the calendar
makes every as-of join plain SQL.

**Parquet and DuckDB as a narrow second lane**, for Dukascopy ticks inside
event windows. Bars cannot express a spread: a bar carries a bid series and an
ask series, and the only spread recoverable from them is close minus close,
which samples one instant per bar and misses the release entirely. High minus
low is worse, because it mixes the spread with genuine price movement. A tick
carries bid and ask at the same instant, which is the only thing that measures
the cost of trading at the moment it is paid.

The scope is narrow: a couple of hours either side of each event, a few hundred
files rather than the 87,600 a continuous decade would need, which keeps this
well inside what the feed tolerates.

**Bitemporal by default.** Every fact carries effective_time (the instant it
describes) and available_at (the instant it became knowable). Every read goes
through an as-of accessor. This is the most important constraint in the project:
without it the backtest measures information we did not have, and every number
downstream is fiction.

## Data sources

Verified by real calls during Phase 0.

| Source | Status | What it gives | Cost |
|---|---|---|---|
| OANDA v20 | verified | bid/ask bars S5 to D back to 2007, live stream, execution venue | account |
| Dukascopy | verified | tick bid/ask, sub-minute detail inside event windows only | free |
| CFTC Socrata | verified | Commitments of Traders, EURO FX code 099741, full history, no key | free |
| ECB Data Portal | verified | AAA yield curve (YC), euro short-term rate (EST), daily, no key | free |
| Atlanta Fed MPT | wired | daily distribution over the 3 month average rate, quarterly windows, from 2023-03-29 | free |
| NY Fed Survey of Market Expectations | to wire | rate expectation distributions, 8x/year, PDF since 2011 | free |
| ECB Survey of Monetary Analysts | to wire | rate expectation distributions, 8x/year, PDF since 2021 | free |
| FRED and ALFRED | to wire | macro actuals with vintages, ALFRED for anything historical | free, key |
| FOMC statements and minutes | wired | full text, statement at the decision, minutes three weeks later | free |
| Consensus for data releases | unresolved | consensus for CPI, payrolls, PMI | quote pending |
| Intraday euro rates | unresolved | Schatz or Euribor futures, for the rates versus spot divergence | paid, small |

Two gaps carry real consequences and are tracked under Open decisions.

## Instruments and horizons

Widened on 2026-09-02, agreed by both users. The reason given at the time was
sample: the Phase 2 gate did not fail on its thesis, it failed on 26 meetings
carrying 8 target range changes, and no statistical care repairs eight
anecdotes. Reading the same announcement against more instruments was argued to
multiply the sample on the day it was wired.

**That argument is now measured, and it is half wrong.** The measurement is
below, under the cross-instrument gate, and it changes what the widening is for.

The universe is chosen by one rule: an instrument enters when the events already
in the calendar explain it. Rates news reaches currencies, metals, equity
indices and government notes, so those cost a backfill and nothing else. An
individual company needs quarterly results and a commodity needs inventory
releases, so neither is a wider instrument list, they are a new event universe,
and they wait.

Every row was read from the venue rather than typed from memory, through
`/v3/accounts/{id}/instruments` on 2026-09-02, and `basis.instruments.drift`
reads the same endpoint again and refuses to agree that a stale constant is
still true. It reported no disagreement. pip_size is 10 raised to the venue's
own pipLocation, which OANDA publishes for the index and note CFDs exactly as it
does for currency pairs, so the word stays the venue's rather than becoming a
currency one.

| Instrument | Class | pip | Why it is in |
|---|---|---|---|
| EUR_USD | fx | 0.0001 | the reference instrument, everything measured before this date |
| USD_JPY | fx | 0.01 | the most rate-sensitive major, dollar on the other side |
| GBP_USD | fx | 0.0001 | a second dollar leg with its own domestic calendar |
| XAU_USD | metal | 0.01 | the non-yielding asset, where a real rate reads directly |
| SPX500_USD | index | 1 | equity duration, the other side of the same discount rate |
| USB02Y_USD | bond | 0.01 | the front of the curve, where a policy decision is priced |
| USB10Y_USD | bond | 0.01 | the long end, where the path rather than the decision is priced |
| DE10YB_EUR | bond | 0.01 | the euro leg of the differential, absent from every free source |

The backfill added 7,452,498 one minute bid and ask bars from 2023-01-01, which
took about twenty minutes against the venue's rate limit. Bond CFDs return
roughly half the bars of a currency pair over the same span, which is trading
hours rather than a gap.

**Every instrument earns its place, measured rather than assumed.** The
membership test is whether the instrument moves more in the two hours from 14:00
Eastern on a meeting day than on an ordinary session read from the same clock,
in basis points of price, Mann Whitney one sided.

| Instrument | Meetings | Ordinary | Median meeting | Median ordinary | Lift | p |
|---|---|---|---|---|---|---|
| USB02Y_USD | 29 | 839 | 12.09 | 1.46 | 8.30 | 6.9e-11 |
| EUR_USD | 29 | 920 | 31.50 | 4.47 | 7.04 | 5.5e-15 |
| USD_JPY | 29 | 923 | 31.59 | 4.74 | 6.67 | 4.5e-17 |
| XAU_USD | 29 | 888 | 65.56 | 11.14 | 5.88 | 1.2e-11 |
| GBP_USD | 29 | 923 | 28.27 | 4.94 | 5.73 | 3.4e-14 |
| USB10Y_USD | 29 | 862 | 23.75 | 4.27 | 5.57 | 9.7e-13 |
| DE10YB_EUR | 28 | 853 | 14.93 | 3.13 | 4.77 | 1.7e-11 |
| SPX500_USD | 29 | 883 | 36.85 | 15.69 | 2.35 | 3.9e-05 |

All eight pass. The two year note carries the largest lift, which is where
theory puts a policy decision, and the equity index carries the smallest, which
is what an instrument with many other drivers looks like. The EUR/USD figure
here is 7.04 against the 6.8 recorded earlier in this plan, because this reads
basis points of price where the earlier one read pips and the samples differ by
a few sessions.

Responses are not comparable in native units. A pip of EUR/USD, a cent of gold
and a tick of a note are different quantities, so every response is carried
three ways: in the instrument's own pips, where the cost is paid; in basis
points of price, which is unit free; and in multiples of that instrument's own
ordinary two hour move from the same clock, which is what makes a number large
or small for that instrument.

Two horizons, daily and weekly, on top of the intraday event windows. Horizon is
cheap for study and expensive for calibration: the event study already computes
1d and 5d, so the study side costs nothing, while a daily horizon resolves about
250 forecasts a year and a weekly one resolves 50, and the isotonic calibration
in Phase 6 needs resolved forecasts.

**What does not generalise is the trade definition.** The 1.0 ATR invalidation,
the 1.5 ATR target and the 16:00 flat hour were calibrated on a session ATR of
54.9 pips and a 58 percent resolution rate measured on EUR/USD alone. Every
(instrument, horizon) pair needs its own version of that measurement, by the
same method, before it carries a signal. This is mechanical work and it cannot
be assumed.

### Company sources, verified on 2026-09-02

The universe rule above says an individual company is a new event universe
rather than a wider instrument list. This is the survey of what that universe
costs, run as real calls rather than as a reading of documentation.

The reason for running it now is the cross-instrument gate. That gate found the
binding constraint to be event count, and it found instrument count exhausted as
a way to raise it. A hundred companies produce four hundred quarterly results a
year against roughly eight rate decisions, and companies reporting on the same
date surprise in different directions, so those are the independent observations
eight instruments reading one announcement could never be.

| Source | Status | What it gives | Cost |
|---|---|---|---|
| SEC EDGAR submissions | verified | every filing with an acceptance timestamp to the second | free, no key |
| SEC EDGAR XBRL facts | verified | financial statement facts, each carrying the date it was filed | free, no key |
| Yahoo chart, daily | verified | daily OHLCV, deep history, unofficial endpoint | free, no key |
| Yahoo chart, intraday | verified, limited | 1m for 7 days, 5m for 60 days, 1h for 730 days | free, no key |
| Alpaca | to wire | US equity bars including intraday history | free tier, key |
| Analyst consensus per company | unresolved | the expectation an earnings surprise is measured against | quote pending |

**EDGAR carries its own point-in-time discipline, which is the reason to build
on it.** The submissions endpoint returns `acceptanceDateTime` stamped to the
second in UTC, which is the instant a filing became public and therefore exactly
the `available_at` the bitemporal contract asks for, taken from the publisher
rather than inferred by us. The `items` field carries 8-K item codes, so an
earnings release is identifiable as item 2.02 rather than by parsing prose.

The XBRL company concept endpoint goes further and returns, for each reported
fact, both the period it describes and the date it was filed. That is a vintage,
and it means a balance sheet can be read as it was reported at the time rather
than as later restated, without building the vintage machinery ourselves. Every
other financial source in this plan required that work.

One caution on it: companies do not agree on which concept a number lives under.
Apple's revenue sits under `RevenueFromContractWithCustomerExcludingAssessedTax`
in recent years and `Revenues` returns only eleven observations, so any concept
read across companies needs a fallback list rather than one name.

**Equity price is the one real gap, and it is smaller than it looks.** Yahoo
serves daily bars with deep history, verified at 2,933 sessions from 2015 for
three large names, but its intraday history is capped: one minute reaches back
seven days, five minute sixty days, and one hour two years. There is no free
minute history for a study of past earnings.

That matters less than it would for the rate engine, and for a mechanical
reason. A quarterly result is published outside market hours, so the first
tradable response is the gap between one session's close and the next session's
open, and the documented continuation runs over days. The natural horizon for a
company is swing, and a swing horizon is served by daily bars. Intraday equity
data is what a day trade on a company would need, and the daily trade definition
in this plan was calibrated on a currency pair and does not transfer to a stock
that gaps overnight through its own invalidation level.

The remaining caution is that the Yahoo chart endpoint is unofficial. It carries
no service guarantee, can change shape without notice, and is not
redistributable, which the source table already has a column for. For a tool two
people run it is acceptable and it is what the schema's `redistributable` flag
exists to record. It should never become the thing a live signal depends on
without a licensed source behind it.

An earlier reading of the same endpoint reported 169 daily bars over four
decades, which was wrong and worth writing down. Asking for `range=max` silently
returns a coarser series than the interval requested. Explicit `period1` and
`period2` return what was asked for. A collector built on the range parameter
would have quietly studied the wrong bars.

### The equity lane, decided on 2026-09-02

Yahoo for daily bars, chosen over Alpaca because both are free and the axis is
not cost. Yahoo needs no key and serves the granularity the event imposes;
Alpaca is an official documented API and would be the better source under a live
signal. The choice is reversible at no cost, because `price_bar` and
`equity_bar` are both keyed by source, so a second price source sits beside the
first rather than replacing it.

**Equities do not go in price_bar, and the reason is the spread.** That table
carries a bid series and an ask series because the venue quotes both, and the
whole cost discipline here rests on charging a measured spread rather than
assuming one. A daily bar from a chart feed carries open, high, low, close and
volume and no quote at all. Writing the close into both sides would state a
spread of zero, which is not a missing value but a false one, and every backtest
reading it would price execution as free. `basis.equity_bar` is therefore shaped
like the fact actually is, and the cost of an equity trade has to be supplied
explicitly rather than inferred from a bar.

**The series is restated, and that is a change of units rather than a
revision.** NVIDIA's close a week before its ten for one split comes back as
115.00 rather than 1150, so the prices are expressed in units set by the most
recent split. Returns are invariant under that, which is why a study may use
them, and it is a different thing from a macro revision, where the quantity
itself changes.

What it costs is the claim that a stored row never changes. `basis.corporate_action`
records every split and dividend the feed reports, and `yahoo.units_drift` reads
the newest stored close against the same session in a fresh fetch and refuses
the ingest when they disagree. A restatement therefore surfaces as a decision to
rewrite rather than as half a series silently in the wrong units. Verified on
NVIDIA: 2,934 daily sessions from 2015, and both splits collected, 4:1 in July
2021 and 10:1 in June 2024.

available_at on a corporate action is set to its effective date, because this
feed publishes no announcement date. That is deliberately late: the market knows
about a split weeks before it takes effect, so a study reading this is withheld
something it would really have had. Late is the safe direction and early is the
one that manufactures results.

**The earnings event resolves at the daily horizon, measured rather than
assumed.** All six of NVIDIA's collected releases were accepted between 16:20
and 16:31 Eastern, which is after the 16:00 close, so the first tradable
response is the gap to the next session's open. The gaps run from -0.66 to
+6.30 percent. One of the six opened 5.06 percent higher and closed the day 3.15
percent lower than the prior close, which is the case a gap-only reading and a
day-trade framing would each get wrong in opposite directions.

This is why the daily trade definition in this plan does not transfer to a
company. It was calibrated on a currency pair that trades through the night, and
a stock gaps over its own invalidation level while the market is shut.

`basis backfill yahoo --ticker NVDA --name NVIDIA --start ... --end ...` and
`basis collect edgar --ticker NVDA` reproduce all of it.

Still unresolved and now the next thing that matters: the expectation. A gap is
not a surprise until there is a published number it is measured against. The
free route inside EDGAR is the company's own prior guidance against the actual,
both filed, both timestamped, both attributable to a named source.

### The cross-instrument gate

Declared before running: does the repricing of the two year note across the
first minutes of the announcement predict what an instrument does over the rest
of the two hours? That is the tradable form of the Phase 2 result, and it is the
question the widening was bought to answer.

The distinction it turns on is the one Phase 2 named. The repricing Phase 2
measured ran from the eve of the meeting to the close an hour after it, so it
was not knowable until after the move it explained had already happened. A
window that opens at the statement and closes five minutes later is knowable at
14:05, and the response is then measured from 14:05 to 16:00, so the predictor
and the response never share a second of price.

**The transmission replicates, on all eight instruments, and it is
contemporaneous.** Regressing the whole two hour move on the whole window
repricing gives R2 between 0.29 and 0.58, and both the HC3 and the 20,000 draw
bootstrap intervals exclude zero on seven of the eight. Every sign is the one
theory asks for: a note price rising is a yield falling, and it lifts EUR/USD
(+0.331 sigma per basis point), lifts gold (+0.224), lifts the Bund (+0.221) and
the ten year (+0.314), and sells USD/JPY (-0.284). The equity index is the
single exception, R2 0.09, interval covering zero, which is consistent with its
low lift above.

**The tradable form finds nothing, on every instrument, at both windows.** With
the predictor closed at 5 minutes and the response opened there, R2 falls to
between 0.001 and 0.072 and every interval covers zero. Pooled across the seven
instruments other than the predictor's own, with standard errors clustered on
the meeting: +0.037 sigma per basis point, 95 percent interval [-0.039, +0.114],
p 0.34. At a 15 minute window it is +0.052, [-0.018, +0.122], p 0.15.

The reason is not that the move is over. Only 28 to 40 percent of the two hour
move has happened by 14:05, so most of it is still ahead when the predictor
becomes readable. The reason is that the first five minutes of the rate move
does not lead anything, including itself: the rank correlation between the note's
own 0 to 5 minute repricing and its own 5 minute to 2 hour move is 0.144, p 0.46.
Rates and everything else reprice together across the two hours rather than
rates leading and the rest following.

The cross-sectional version fails too. Regressing each instrument's 5 minute to
2 hour move on its own first five minute jump, with instrument fixed effects and
errors clustered on the meeting, gives +0.232, interval [-0.268, +0.731], p 0.36.
Point estimates are positive on all eight, between +0.04 and +0.68, and not one
of them is separable from noise.

**The structural finding is about sample, and it corrects the argument the
widening was agreed on.** Eight instruments read against one announcement are
not eight observations. For any predictor that varies at the event level, which
the rate repricing does, clustering returns the effective sample to the number
of events, which is 29. The widening multiplied rows and did not multiply
events, and the clustered intervals above are what that looks like when it is
written down honestly. Broadening instruments buys cross-sectional questions,
and it does not buy statistical power for event-level ones.

So the tradable tests here are underpowered rather than decisive, and the
distinction matters. The pooled interval still admits effects up to +0.114 sigma
per basis point, and a typical announcement reprices the note by 4.95 basis
points, so an effect worth roughly half an ordinary session's move is not
excluded. What is excluded is the claim that this is measurable now.

**Two consequences for the open decisions.** The intraday rate feed under open
decision 2 was carried in this plan as the highest value purchase in the
project, on the argument that it would turn the Phase 2 diagnostic into a
signal. The venue already serves it free, back to 2023 on one minute bid and ask
bars, so the purchase was never needed to answer the question. The answer, on
that free data, is that it does not become a signal at this horizon. The
purchase is not justified by evidence and comes off the critical path.

And open decision 5, consensus for data releases, is now the only remaining way
to raise the event count, which this section has just shown is the binding
constraint. It was already promoted from a widening to a requirement by the
Phase 2 answer. It is now the critical path.

## The daily trade

Fixed so that a signal, a backtest and a scorecard all describe the same thing.
Every one of these is a default chosen on 2026-08-26 and changeable, but never
silently: changing one invalidates every score measured under the old one.

| | |
|---|---|
| Published | 07:00 New York, before the New York open |
| Entry | the mid at publication, crossed at the real ask to buy and bid to sell |
| Invalidation | 1.0 average true range from entry |
| Target | 1.5 average true range from entry |
| Flat by | 16:00 New York, whatever has happened |
| Session studied | London and New York, where the book is deep enough to pay the spread |

Outcome is whichever of invalidation and target the price reaches first, read
off one minute bars, and the close at the flat hour when it reaches neither.
Cost is charged at the measured spread, not assumed away, because Phase 1a
already showed the venue quotes 1.5 pips at rest and far more around a release.

A minute that holds both levels is resolved as the loss. A bar cannot say which
of its own extremes came first, and any other convention flatters the backtest
exactly on the violent days a day trader cares about.

The multiples are sized on the session range and not on the daily range. Read
first against the daily average true range of 71 pips, 92.6 percent of sessions
reached neither level inside the nine hours and the definition stopped
describing a day trade. The session average true range is 54.9 pips, which puts
the invalidation near 27 pips and the target near 41.

Measured across the whole sweep, on 933 sessions from 2023-01-19: tighter levels
resolve more often and are worth less. At 1.00 and 1.50 only 16 percent resolve
and perfect foresight is worth 24.5 pips a session; at 0.25 and 0.375, 95
percent resolve and perfect foresight is worth 10.5. At the chosen 0.50 and
0.75, 58 percent resolve and perfect foresight is worth 20.3 pips. That last
figure is the ceiling every later claim of skill is measured against.

### What technical reading alone is worth

Measured before building anything on top of it, because a baseline discovered
afterwards is a baseline chosen to flatter.

Reproduce all of this with `basis study technical`. The figures below are that
command's output over the 897 sessions where every feature is defined, which is
the same sample the models are scored on.

A coin loses 1.53 pips a session, which is the spread and nothing else. Eight
ordinary technical rules were scored against it: always long, always short,
follow London, fade London, follow the prior day, follow five day momentum,
above the pivot, and the Asian range breakout. Every one of them loses, between
0.60 and 2.02 pips a session, and every confidence interval covers the coin.
Picking the better side landed between 48.0 and 52.0 percent.

Then a real model, walk forward with no look ahead, over all sixteen features,
warmed on 250 sessions and scored on the remaining 647. Logistic regression
returns -3.24 pips a session, interval -5.25 to -1.23, side accuracy 48.7
percent, Brier 0.2581. Gradient boosting returns -2.49 pips, interval -4.52 to
-0.46, accuracy 48.2 percent, Brier 0.2712. Both are worse than the coin's
-1.53, and both Brier scores are worse than the 0.2500 a coin scores by
definition.

So the finding is not that technical reading is weak here. It is that fitting
these features to this horizon produces negative skill out of sample, which is
what fitting noise looks like. That is one feature set and two model families on
one instrument at one horizon, and it does not condemn technical analysis in
general. It does say the daily signal cannot rest on it.

The mechanism that did measure, in Phase 2, was information: repricing across a
rate announcement explains 37 percent of the two hour move, with the sign theory
asks for and robust to dropping any meeting. Technical features stay in the
engine as regime and as level geometry, which is what they are good for. The
direction has to come from the information layer.

## Swing on a company

The screen opens on a question, which company are you looking at, and a field.
Search reads the SEC's own ticker index, 10,415 names collected into
`basis.company` by `basis collect edgar-index`, and it answers from Postgres
rather than from the network so it moves on a keystroke. An exact symbol
outranks a name match, because someone typing NVDA means the company that
trades as NVDA and not the twenty whose printed name contains those letters,
and inside a rank the shortest name wins, which is what puts Apple Inc. above
Apple iSports Group.

Opening a company collects it. The daily series comes from Yahoo, ten years of
it, and the filing history from EDGAR, and both land in the tables the equity
lane already defined. A company already collected answers from the store in
tens of milliseconds; a company nobody here has opened blocks once, because
there is nothing to answer with until it does. Removing one deletes its bars,
its corporate actions, its filings and its instrument row, and leaves its line
in the SEC index, so forgetting a company is cheap and reversible.

**The delete refuses anything that is not an equity, and that guard is the
reason it can exist at all.** The same tables hold the reference instruments,
and EUR_USD alone carries every measurement in this document. A mistyped ticker
must not be able to delete a week of collection.

### What the screen is allowed to claim

There is no real time US equity feed in this project. The quote comes from a
chart endpoint that is delayed and unofficial, and it publishes the instant the
price was taken, so that instant is rendered beside the number and its age with
it. Until the feed answers, the header shows the last stored close labelled as a
stored close rather than as a price. When the feed refuses, the series stays on
screen and the screen says the feed did not answer.

The change figure is measured against a session close and never against the
previous bar, whatever window is on screen. Two ways of getting that wrong were
found and fixed. The feed's own previous close is the close before the whole
requested window, so on a ten year pull it compares today against a price from
2016. And the bar before the last one is the previous minute when the reader is
on a minute chart, which turns a day up two percent into a day up one cent.

Bars whose low is not the lowest of their own four prices are dropped at the
loader rather than stored. Measured on Apple iSports Group, one bar in 2,516
returns an open of 0.50 against a low of 3.50, on twenty shares traded. Carrying
it would mean either storing a bar that contradicts itself, which the table's
own constraint refuses, or relaxing that constraint, which would let every later
reader treat a high below an open as a real price.

### The chart, and why it is TradingView's

Lightweight Charts, Apache 2.0, fed from `basis.equity_bar`. It was taken for
dragging back through history, zooming, and a crosshair that reads the series
rather than the pixel, which at a swing horizon are the interaction rather than
polish. The attribution the licence asks for is rendered by the chart itself.

The embeddable widget was considered and refused. It is an iframe carrying
TradingView's own prices, which cannot be read, cannot be stored, cannot take
the earnings marks, and would sit above a header showing a different number with
no way to say which one the screen was claiming. A better chart is worth less
than the ability to say where a number came from.

Earnings are marked at the SEC's acceptance instant, placed on the first bar at
or after it, which is the session the release has yet to move rather than the
one that already closed. A release older than the window is not marked at all.

### Colour, and the second exception

The epistemic palette stands: one hue for an observed fact, one for a number
derived under a stated assumption. Red and green are a scoped exception and they
mark price and price alone, which now means the candle body and the change
figure read off two closes. They may not spread. Every probability, interval,
score and signal stays on measured and modelled, because a number saying how
confident the engine is must never borrow the colour of a number saying whether
the last bar closed up.

### What the interface owes the reader

Three rules, each of which was a defect first.

A reading answers from the store and refreshes behind the response. The quote is
the only thing that must go upstream to be true, so it is the only thing that
waits on the network, and it does so on its own endpoint. The header, the series
and the filings are served from Postgres and refreshed after the answer has been
sent. Freshness is measured as when this process last asked rather than as how
old the newest bar is, because a market that closed on Friday leaves every
series looking permanently stale.

The page is built once and filled in, never swapped from a placeholder into a
layout. Every slot is reserved at its final size before the thing that fills it
arrives, measured at a cumulative layout shift of 0.0002 against a good
threshold of 0.1.

Changing theme is one animation rather than forty. The whole surface cross-fades
as a single snapshot and every element level transition is suppressed
underneath it. That also fixes the order of the switch: the attribute has to
change before React flushes, because anything painting itself from the
stylesheet reads the custom properties during its layout effect, and flushing
first paints it in the theme being left.

### The expectation, and what a naive one is worth

A gap is not a surprise until there is a number the release can be read
against, and until 2026-09-13 there was none. The earnings marks on the chart
sat at the SEC's acceptance instant over a price series and said only that
something had been published. Six NVIDIA results had produced next session gaps
from -0.66 to +6.30 percent and nothing in the store could say which of them was
news.

Consensus is sold rather than given. What is free is the company's own filings,
so the expectation built here is the same quarter a year ago carried forward by
the drift of the four quarters since, taken from XBRL and formed only from
filings accepted strictly before the release. It is a weak forecast on purpose.
Analysts know about a launch, a guidance cut and a currency move; this rule
knows four numbers. Every result measured against it is therefore a floor, and
what a bought consensus is worth is the difference between it and this.

Three measurement problems had to be solved before the number meant anything,
and each was a defect first.

**XBRL publishes periods rather than quarters.** A 10-Q states its own quarter
and the year to date, and a 10-K states the year and never the fourth quarter,
because no quarterly report covers it. Reading only the ninety day durations
drops one release in four, and the one it drops is the annual, which is the
release a company says the most at. The fourth quarter is therefore derived as
the year minus the nine months inside it, matched on the period start rather
than on a calendar quarter, and marked as derived. Dropping all 214 derived
quarters leaves the result stronger rather than weaker, so the subtraction is
not carrying it.

**The first concept that answers is not the company's concept.** Apple reports
revenue under `RevenueFromContractWithCustomerExcludingAssessedTax` and NVIDIA
under `Revenues`. Trying the candidates in order and stopping at the first that
answers handed NVIDIA a five year stub ending in 2022, which is worse than no
series because it looks like one. Every candidate is now asked and the one
covering the most periods is taken whole, which moved NVIDIA's revenue from 12
quarters to 73.

**A split changes the share count and nothing else.** Prices already survive
this, because the feed restates the whole series and a return is invariant under
it. Earnings per share does not, because XBRL states each fact in the units in
force when it was filed. NVIDIA's quarter to April 2024 is 5.98 a share as
filed and 0.60 after the ten for one split in June, and both rows are in the
store. Read raw, the rule expected 14.32 a share against an actual of 0.76 and
called it a surprise of -7.5 standard deviations. A fact's units are set by its
filing date, so expressing it at a later instant divides by every split between
the two, and a row already filed after the split is divided by nothing and
agrees with the restated one. The same event then reads -0.77, which is what the
revenue line said all along.

The `recent` block of a submission history holds a thousand filings and how far
back that reaches depends on how much a company files. Apple's thousand go back
to 2015 and NVIDIA's stopped in 2020, because NVIDIA's insiders file more often,
which would have given one company eleven years of results and the other five
for a reason that has nothing to do with either company. The older pages are
published beside it and are now read in full: NVIDIA goes from 26 releases to 94.

### The earnings gate, answered on 2026-09-13

Thirty companies, 163,000 daily sessions, 36,833 XBRL facts, 2,635 releases and
2,448 expectations. The panel is 1,515 releases over 28 companies from
2010-10-28 to 2026-09-10, and none of the 2,460 rows had its actual on file
before the release it is measured at.

**The event is real.** The median absolute move on a result session is 2.94
percent against 0.86 percent across 148,014 ordinary sessions, a factor of 3.44.
That is the equity analogue of the 6.8 measured on FOMC afternoons, and it says
the same thing: something happens here, whatever predicts it.

**Revenue surprise predicts nothing.** Every interval straddles zero at every
horizon, R2 rounds to zero, and the direction test is 52.6 percent with a 95
percent interval of [49.6, 55.6]. Dropping the derived quarters leaves -0.010.

**Earnings per share surprise does something small and it survives every check.**
The opening gap moves +0.273 percent per standard deviation of surprise, HC3
[+0.108, +0.438] and bootstrap [+0.109, +0.440]. Clustered on the company, which
is the only honest reading when 24 names contribute 1,357 correlated rows, it is
+0.273 with [+0.070, +0.476] and p 0.008. The full session is +0.208 [+0.017,
+0.399] and five sessions is +0.259 [+0.016, +0.503]. Holding out each company
in turn leaves the session slope between +0.153 and +0.237, always the same
sign, with the lowest reading obtained without Amazon. Dropping every derived
fourth quarter leaves +0.263 [+0.106, +0.420]. The direction is right in 730 of
1,356 sessions, 53.8 percent [51.1, 56.5], p 0.005.

**And it is nowhere near enough to trade.** R2 is 0.009 at the gap and 0.004 at
the session. A one standard deviation surprise shifts the expected move by about
a quarter of a percent inside a session whose typical move is 2.94 percent, so
the sign is real and the variance around it is the entire trade. Magnitude does
not track either: the rank correlation between the size of the surprise and the
size of the move is +0.034, p 0.213.

What that combination measures is precisely the thing this lane was built to
measure. The move is large, it is directionally related to the numbers, and the
company's own history explains almost none of it. The missing quantity is the
expectation, not the event. This is now a floor with a number on it, and any
consensus feed has to beat +0.273 percent per sigma and an R2 of 0.009 to have
been worth buying.

Standing caveats. The thirty names were chosen today as large companies that
exist today, so the panel is survivorship selected and every result should be
read as applying to large surviving caps rather than to listed companies. The
actual is read from XBRL, which arrives with the 10-Q weeks after the release,
so this measures ex post what a live signal would have to read out of the press
release itself, and reading it out of the release is what the text labeller is
for. And a naive expectation is a floor in one direction only: it can understate
what consensus is worth and cannot overstate it.

## Phases

Each phase ends on a checkable condition. A phase is not done because the code
runs, it is done because the condition holds.

### Phase 0. Foundation of record (done)

Sources verified with real calls. Bitemporal schema written and proven against
Postgres 18 across nine scenarios, including COT release lag, macro revision
vintages, calendar reschedule and signal immutability.

Done when: as-of queries provably refuse to return information that was not
knowable at the cutoff. Holds.

### Phase 1a. Price and calendar spine

Dukascopy tick backfill into Parquet. OANDA v20 live stream and recent candles.
UTC normalisation at ingest with the source recorded per row. Event calendar
populated. Feed reconciliation across the Dukascopy and OANDA overlap. Gap and
staleness detection.

Done when: a single as-of call returns spot, spread and the next scheduled event
for any instant in the backfill, and the Dukascopy against OANDA mid difference
over the overlap window is measured and written down.

Measured, and it reversed the design. OANDA serves bid and ask bars from S5
upward back to 2007, 5000 candles per request, five consecutive requests in 1.5
seconds with no throttling. A decade of one minute bars is roughly 662 requests
and about a minute of work. Dukascopy needs 87,600 hourly files, throttles after
a handful, and refuses non-browser user agents by timing out rather than
answering. OANDA is therefore the spine and Dukascopy is optional.

The reconciliation over a common hour: mid prices agree to a median of 0.000
pips, 5th to 95th percentile inside 0.15 pips, worst case 0.2 pips. The two
feeds measure the same market.

Spreads do not agree, and the gap is structural rather than noise. Dukascopy
runs a 0.30 pip median where OANDA runs 1.50, a five to one ratio that is the
difference between raw ECN pricing and a market maker quote. **The cost hurdle
must be calibrated on OANDA, because OANDA is where the order actually fills.**
Calibrating it on Dukascopy would make every signal look 1.2 pips cheaper than
it is, and near the hurdle that bias points one way only, toward trading.

Measured at one real FOMC release, on ticks: a 0.30 pip quiet baseline, widening
to 0.50 a minute out and 0.90 in the final five seconds, peaking at 8.00 pips in
the five seconds after the statement, twenty seven times baseline. It holds
under 1.0 pip from T+40s and under 0.6 from T+200s. The mockup guessed a 90
second dead window; the measurement says that is conservative but the right
order of magnitude, and it is now evidence rather than a guess.

The same window read from one minute bars shows the spread peaking at T-1 and
looking normal at T+0, which is an artefact of close to close sampling and not
what happened. Anything calibrating the dead window has to come from ticks.

Staleness detection was the last piece of this phase and was left out on the
argument that it protected a production path that did not exist. Standing the
recorder up as a service created that path, so it is now written. `basis health`
reports three things against the clock: whether the recorder's own heartbeat is
turning, whether ticks are arriving, and how far behind the newest bar is. It
exits non zero when any of them fails, so it can be scheduled later without
being rewritten.

The heartbeat is deliberately independent of the ticks. A closed weekend and a
dead process produce the same silence on the tick side, and only a clock the
process keeps turning separates them. The check knows the spot week runs Sunday
17:00 to Friday 17:00 Eastern and does not cry about a quiet Saturday.

### Phase 2. Event study database

Historical events with expectation, outcome, standardised surprise, and EUR/USD
response at 5m, 30m, 1h, 2h, 1d and 5d, plus peak spread and maximum adverse
excursion in each window. Statement text labelled by Claude for surprise type,
versioned, backfilled across history.

Measured constraint: the ECB meeting calendar page carries only forward dates,
starting at the next meeting, and no archive URL pattern responds. Historical
ECB decision dates therefore need a different route, most likely the policy rate
series or the press release index. The Fed page carries 2021 onward, and earlier
years live on separate historical pages that also used a 14:15 release rather
than 14:00. Both gaps bite in this phase, not before.

The event universe must be wider than central bank decisions. Rate decisions
alone give roughly 8 events per year per bank, which cannot estimate anything.
CPI, payrolls, flash PMI and retail sales are what make the sample usable.

### The text lane

Collected: 29 statements and 29 sets of minutes covering every FOMC meeting
from 2023-02-01, straight from the Fed. The statement is public at the decision,
14:00 Eastern; the minutes follow three weeks later at the same hour, pushed to
the next business day rather than credited early when that date falls on a
holiday. Nothing in the corpus claims to have been published before its own
meeting.

This is the answer to what broke the Phase 2 gate. The decision itself took four
values across 26 meetings and moved eight times; the language of the same 26
meetings varies enormously, and it costs nothing.

Two rules make the labeller usable rather than merely clever. **Every field must
cite a verbatim quote from the document.** A label that cannot point at the text
came from somewhere else, and for statements published between 2023 and 2026
that somewhere else is very likely the model's own training data, which knows
what the market did next. And **the labeller extracts, it does not judge**:
there is no hawkish or dovish field, deliberately. That reading is exactly where
hindsight would enter. What the statement said about inflation is checkable;
whether it was a surprise is for price to answer.

The version pins model, prompt and schema together, and `input_sha256` records
what actually determined each answer. Changing any of the three is a change of
measurement, so it takes a new version and obliges relabelling the whole history
before the new version is used in a study. `available_at` mirrors publication
and never the instant the labeller ran.

**Not yet run, by decision.** The labeller waits on an API key, so the whole
path around it is proven without one. A stub of the Messages API stands in front
of the real SDK, which establishes that the parameters are accepted, that the
schema and model reach the wire intact, that a refusal and a truncated answer
each raise instead of storing half a label, and that the same document produces
byte-identical requests. Storage is proven against the real database: a label
computed today is readable at the instant its document was published and
invisible a second earlier, relabelling at the same version writes nothing, and
two versions coexist rather than overwriting. What is unproven is the model's
answer, which is the only part a key can settle.

`basis label fomc --dry-run` prints the request a paid run would send, verbatim,
and what it would cost. The whole corpus is 376k input tokens, about $1.88.

Done when: the study answers, in writing, whether standardised surprise predicts
the T+2h move at all, with a confidence interval. This is the gate for
everything after it. If surprise does not predict, the thesis changes here
rather than six phases later.

Answered on 26 FOMC meetings between 2023-05-03 and 2026-07-29, the whole span
where the Atlanta Fed tracker, the calendar and the OANDA bars overlap. The gate
does not pass on the measure this plan names, and the reason is worth more than
the verdict.

Standardised surprise, taken as the actual target range change minus the
expectation the tracker carried on the eve of the meeting, moves the T+2h
response by -7.5 pips per standard deviation, 95 percent interval [-25.7,
+10.7]. The interval is wide and it straddles zero. Entering the decision and
the priced path as separate terms, rather than forcing their difference, does
not rescue it: the decision slope is +1.2 pips per standard deviation, 95
percent interval [-55.2, +57.6].

Two measurement facts explain that, and neither of them is about the thesis.
Only 8 of the 26 meetings changed the target range at all, so the actual has
almost no variation to regress on. And the nearest forward-looking window the
tracker publishes sits a median of 49 days past the meeting, minimum 7 and
maximum 98, because it prices quarterly SOFR contracts and drops a window once
that quarter opens. The pre-meeting expectation is a price of the quarter's
path, not of this decision. Both facts push the estimate toward zero.

What is not weak is the transmission. Repricing the curve from the eve of the
meeting to the close an hour after it explains 37 percent of the T+2h move, at
-96.9 pips per standard deviation, 95 percent interval [-162.3, -31.6] on HC3
and [-161.9, -48.6] on a 20,000 draw bootstrap. Dropping any single meeting
leaves the slope between -120.9 and -85.9, so no one afternoon is carrying it.
The sign is the one theory asks for: a hawkish repricing sells EUR/USD.

The horizon in this plan is the right one. That same regression finds nothing at
5 minutes, is marginal at 30 minutes, and is fully expressed by one hour, R2
0.39, and two hours, R2 0.37. The move takes about an hour to finish, which sits
directly on top of the spread decay measured in Phase 1a.

The event itself is real. The median absolute two hour move from 14:00 Eastern
is 33.1 pips on FOMC days against 4.9 pips across the 814 ordinary sessions in
the same span, a factor of 6.8, Mann Whitney p below 0.0001. Size tracks size
too: the rank correlation between the magnitude of the repricing and the
magnitude of the move is 0.62, p 0.001.

So the finding is not that surprise fails to predict. It is that rate news
reaches EUR/USD at exactly the horizon the engine targets, and that nothing
knowable at 14:00 from free data measures how much of the decision was news.
The gate stays open, and it closes on data rather than on code. Phase 3 must not
start on FOMC target range decisions.

### Phase 4a. Signal gate

Six rules as real code. Four are implementable from Phase 1a and 2 alone: dead
window, cost hurdle, daily cap, time stop. Two depend on the engine and the
critic: probability above threshold, critic did not refute. Those two sit behind
an interface that fails closed, so an unavailable check blocks the signal and
never waves it through.

Done when: the gate rejects a deliberately bad signal for each of the six
reasons, proven by test, and an unavailable dependency produces a block rather
than a pass.

### Phase 1b. Context features

FRED and ALFRED macro with vintages. CFTC positioning. Both as slow context,
not as triggers.

Done when: an as-of call at any historical instant returns the COT and macro
picture that was actually published by then, not the revised one.

### Phase 3. Projection engine, simplified

A numeric model producing a conditional distribution of the T+2h return given
standardised surprise and volatility regime. Pooled across event types with an
event-type effect rather than sliced into matched buckets, because slicing
throws away the sample we do not have. No adversarial critic yet. No isotonic
calibration yet, which needs resolved forecasts that do not exist.

The probability is produced by statistics. Claude produces features from text
and writes the prose. That split is what makes the Brier score mean anything.

Done when: walk-forward Brier skill score against the 50 percent baseline is
positive out of sample. The threshold is set before the run, not after. If it
is negative the engine does not ship.

### Phase 5. Pre-event scenario engine

Branch enumeration from policy stance and recent communication, weighted by
market-implied pricing. Press conference reading against the statement reading.

### Phase 6. Critic and calibration

Adversarial critic as a veto with reasoning. Isotonic calibration once enough
forecasts have resolved, which realistically means many months given the daily
cap. Reliability diagram from live resolutions.

The critic discount and the isotonic correction are separate quantities and must
not share a number. Order of application is a decision to make before either is
built.

### Phase 7. Delivery

Real login for two accounts. Notification reaching both of us. Execution record
already lands separately from the signal, since that was pulled forward into the
schema.

Pulled forward, because the engine is waiting on data that has to be bought and
the interface is the one thing that could move meanwhile. Login is real, scrypt
hashed, two accounts, no roles and no tenant column. The read surface is
FastAPI, the client is React and Vite, and one process serves both once the
client is built.

Four screens exist, chosen by what the data can actually fill: Today, Calendar,
Study and Context. The signal screens are not built and are not stubbed, because
`basis.signal` is empty and filling it with an example would put a number on a
screen that traces to nothing.

The price on Today is live. The recorder publishes each tick to `var/quote.json`
as it arrives, overwritten in place, and the read surface serves whichever of
that file and the newest flushed parquet tick carries the later instant, so a
restart that empties the quote falls back rather than blanks. Before it, the
screen showed the newest flushed tick and nothing faster existed: measured at
117 seconds old while the tick heartbeat on the same page read one second.

That file is a display surface and nothing else. It keeps no history, carries no
available_at and enters no study, because a file that keeps no history cannot
answer what was knowable at a past instant. Quotes arriving inside a 50
millisecond floor are dropped rather than queued, since a superseded quote held
back for later would be published as current after it stopped being so, and a
write the operating system refuses while a reader holds the file costs that one
quote rather than the recorder.

The screen refreshes every 20 seconds, pauses while the tab is hidden and reads
once on the way back. A refresh that fails does not become the screen's error:
the last good reading stays on screen and the status line says the refresh
failed and when the reading stopped moving. Replacing a working reading with a
failure card would throw away the last thing we knew, which is the opposite of
what someone watching a price wants. `client/qa/refresh.mjs` drives all of it in
a real browser, including the failure and the recovery.

Measured while wiring this: the machine's clock runs 0.85 seconds behind NTP,
matching the 0.77 seconds by which the venue's tick stamps lead our own. Every
spread and response measurement in this plan is stamped by the venue or the
publisher on both sides, so the offset does not reach them. What it does reach
is available_at on anything stamped here, which is written 0.85 seconds early
against real time.

The interface has one rule that shapes everything else. Colour encodes epistemic
status and nothing else: one hue for an observed fact, one for a number derived
under a stated assumption, graphite for everything else. There is no red and no
green anywhere in it. Direction is carried by the sign of a numeral and by which
side of the zero rule a mark falls on, because red and green are the grammar of
urgency and this engine's whole claim is that most days the answer is no trade.

**Scoped exception, decided on 2026-09-02: the price chart uses red and green
candles.** Reading a candle chart technically is a skill both users already
have, and it is built on that convention, so refusing it would cost fluency to
buy consistency. The exception is the candle body and wick on the price chart
and nothing else. Every signal surface, every probability, every interval and
every scorecard keeps the epistemic palette, because the original reason holds
there: red and green are the grammar of urgency, and most days the answer is no
trade. A number that says how confident the engine is must never borrow the
colour of a number that says whether the last bar closed up.

Every uncertain quantity renders through one mark, the interval rail: the
estimate as a hard tick, the confidence interval as a band, the bootstrap as a
whisker, and zero as a rule that never moves. Whether the band crosses that rule
is the finding, readable without reading a digit. It is why the Phase 2 answer
above is legible on the Study screen in about a second.

## Open decisions

**1. Fed or ECB as the anchor for v1.** The euro side has no free intraday rate
curve and no free OIS forward dated by meeting, and its survey history starts in
2021. The US side has daily implied distributions from 2023 and survey PDFs from
2011. Anchoring on the Fed costs nothing in instrument terms, since EUR/USD
moves on both, but it contradicts the mockup, whose hero screen is an ECB
Governing Council. This decides which collector Phase 1a wires first.

The Phase 2 gate leans on the Fed. The US side produced a measurable answer from
free data, and the euro side could not have produced one: the ECB calendar page
carries no history, so there is no event list to study against. Recommendation
for v1 is the Fed, with the mockup's hero screen restated as an FOMC decision
rather than a Governing Council. That is a change to the mockup, not to the
instrument, since EUR/USD moves on both.

**2. Intraday euro rates, buy or drop.** The rates versus spot divergence is the
most distinctive part of the thesis and is not measurable with free data. A
Schatz futures feed through a broker resolves it cheaply. Dropping it restricts
the first engine to what price alone measures.

The gate raised the price of dropping it. Curve repricing across the
announcement explains 37 percent of the T+2h move, so rates against spot is not
a flourish on the thesis, it is where the measured signal actually lives. What
free data cannot supply is the repricing inside the announcement window itself,
which is the only version of that number knowable in time to trade on. Buying an
intraday rate feed turns the strongest result in the study from a diagnostic
into a signal. On the evidence this is now the highest value purchase in the
project, and it should be scoped on the US curve first, where the study ran,
rather than on the euro leg.

**Closed on 2026-09-02, and not by buying it.** The venue already serves the US
curve intraday, as one minute bid and ask bars on two, five, ten and thirty year
note CFDs back to 2023, and the Bund with them, which also answers the euro leg
this entry called impossible on free data. The question was therefore answerable
without the purchase. Measured under the cross-instrument gate above, the answer
is that the repricing does not become a signal at this horizon: it moves
contemporaneously with everything else rather than leading it. The purchase
comes off the critical path, and what took it off is evidence rather than
budget.

**3. OANDA has no historical ticks.** Decided: record the stream now and model
the gap meanwhile, with the modelled number labelled as such.

The recorder writes top of book plus book depth to Parquet. It runs as a Windows
scheduled task named "Basis Tick Recorder", started at logon, restarted every
minute on failure up to 999 times, logging to `var/recorder.log` and reporting
into `var/recorder.json`. Its one real limit is that it starts at logon rather
than at boot, because registering a task that runs with nobody signed in needs
administrator rights this account does not have. A machine sitting at the login
screen records nothing, and `basis health` is what says so.

It also folds each closed day's flush chunks into the single file the partition
is named for. A recorder flushing every two minutes writes hundreds of files a
day, and the lane reads the whole tree through a glob, so without that step the
read cost would grow with uptime rather than with data.

The model takes the blowout shape measured on Dukascopy ticks, normalised to
each event's own quiet baseline so it carries across venues, and scales it onto
OANDA's real baseline. Every number it returns carries its provenance, so a
modelled spread cannot be mistaken downstream for an observed one.

Measured across 29 FOMC releases, as a multiple of each event's quiet baseline.
Median and 95th percentile: 1.2 and 2.0 at half an hour out, 1.7 and 3.0 a
minute out, 3.0 and 4.8 in the final five seconds, 6.0 and 9.9 in the two
seconds after the statement, 1.7 and 3.0 by T+40s, and still 1.2 and 2.0 at
T+5m.

It does not return to baseline inside fifteen minutes. That matters: the dead
window is not a wall with calm on the far side, it is the steepest part of a
decay that keeps costing something for the rest of the session.

Scaled onto OANDA's 1.50 pip baseline at the 95th percentile: 14.8 pips at T+1s,
10.1 at T+5s, 8.0 at T+15s, 4.5 at T+40s, 3.8 at T+90s and 3.0 at T+5m. Set
against the mockup's own illustrative trade, which risked 33 pips to make 46, a
T+1s entry hands roughly a third of the target to the spread, and even the
mockup's T+90s dead window still pays 3.8 pips, about eight percent of the move.
The dead window is not a stylistic flourish, it is the difference between the
trade and no trade at all.

An earlier reading of a single event put T+1s at 38 pips. That event was an
outlier by a factor of about two and a half, which is the reason a shape gets
measured across events rather than sampled from one.

The mockup's cost check reads "46 pips vs 0.4 spread". The real quiet spread at
the venue we trade is 1.50, so that line understates the calm cost by about four
times and the release cost by around ninety. It needs to move to real numbers.

Standing caveat: 29 events is enough for a usable shape and not enough to slice
it by surprise size or volatility regime, which is where it will eventually need
to go. All 29 are FOMC, because the ECB calendar page carries no history. And
the transfer still assumes both venues widen in the same proportion, which is
exactly what the recorder will confirm or refute.

**4. OANDA's historical spread, record it forward or model it.** S5 is the
finest granularity it serves, so Dukascopy's true spread is measurable back
through history but OANDA's is not, and OANDA is the venue that sets our actual
cost. Three ways out: record
the OANDA price stream from now on and build the real series going forward;
apply the Dukascopy blowout shape to the OANDA baseline as a stated modelling
assumption; or take OANDA S5 high minus low as a deliberately pessimistic upper
bound. The first is honest but starts empty, the second is usable immediately
but is an assumption that has to be labelled as one. Decision 3 already took the
first two together, so this entry is answered rather than open.

**5. Consensus for data releases.** Needed to widen the event universe, which is
the only real fix for the sample size problem. Trading Economics is the main
candidate and prices by quote.

The gate turned this from a widening to a requirement. Twenty six meetings
produced eight target range changes, which is not a sample, it is eight
anecdotes, and no amount of care in the statistics repairs that. CPI, payrolls
and flash PMI carry a published consensus and a published actual, so the
surprise is a real number against a real expectation at the instant of release,
which is exactly the object the FOMC target range could not provide. It also
takes the event count from roughly eight a year to roughly fifty.

**Promoted again on 2026-09-02, to the critical path.** The cross-instrument
gate showed that reading one announcement against eight instruments multiplies
rows and not events, so every event-level test stays pinned to an effective
sample of 29 however wide the universe gets. Instrument count is exhausted as a
source of statistical power. Event count is the only one left.

**6. Real time equity price, stream free or buy.** The quote on the company
screen is delayed and says so. Making it live is a feed decision rather than a
code one, and the recorder that already streams EUR/USD is the shape it would
land in.

No free source carries the consolidated tape. Free real time means one venue's
prints: Finnhub serves real time US trades over a WebSocket on its free tier,
and Alpaca's free tier is IEX with the REST side delayed fifteen minutes and the
socket capped at thirty symbols. All US exchanges, unlimited symbols and no
delay is 99 dollars a month at Alpaca. On a liquid name a single venue tracks
the consolidated price closely; on a thin one the last print can be minutes old
and disagree with a broker, which is exactly the kind of gap this project
refuses to hide.

Blocked on a key rather than on a decision. Recommended is Finnhub for the first
pass, because it costs nothing and proves the plumbing, with the paid tape
reconsidered once there is a signal worth paying to execute.

**7. Equity consensus, and what it now has to beat.** The expectation on the
company screen is the company's own history, and on 2026-09-13 that floor was
measured: +0.273 percent of opening gap per standard deviation of earnings per
share surprise, R2 0.009, direction right 53.8 percent of the time. Revenue
adds nothing.

So the question is no longer whether an expectation is needed, it is what a real
one is worth over that floor, and the answer decides whether this becomes a
signal or stays a reading. Two free routes remain before anything is bought.
The company's own prior guidance is filed inside EDGAR in the same 8-K exhibits
already collected, which makes it an expectation that is published, archived and
carried with an acceptance instant, and reading it out of the prose is what the
text labeller was written for and what the Anthropic key blocks. And the
analyst estimate itself is quoted by several feeds under terms that permit
personal use, which is a licence question rather than a price.

Nothing here should be bought until the guidance route has been tried, because
it costs one key that is already needed for the FOMC lane, and because a
guidance number and an analyst number answer different questions: one is what
the company promised and the other is what the market believed.
