# Basis

A daily day-trading signal for EUR/USD, produced by digesting public
information. Two users, one instrument, no customers.

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
| Consensus for data releases | unresolved | consensus for CPI, payrolls, PMI | quote pending |
| Intraday euro rates | unresolved | Schatz or Euribor futures, for the rates versus spot divergence | paid, small |

Two gaps carry real consequences and are tracked under Open decisions.

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

A coin loses about 1.5 pips a session at every level sizing tried, which is the
spread and nothing else. Eight ordinary technical rules were scored against it:
always long, always short, follow London, fade London, follow the prior day,
follow five day momentum, above the pivot, and the Asian range breakout. Every
one of them loses, between 0.60 and 1.74 pips a session, and every confidence
interval covers both zero and the coin. Picking the better side landed between
47.9 and 52.1 percent.

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

The interface has one rule that shapes everything else. Colour encodes epistemic
status and nothing else: one hue for an observed fact, one for a number derived
under a stated assumption, graphite for everything else. There is no red and no
green anywhere in it. Direction is carried by the sign of a numeral and by which
side of the zero rule a mark falls on, because red and green are the grammar of
urgency and this engine's whole claim is that most days the answer is no trade.

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
