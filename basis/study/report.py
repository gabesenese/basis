from basis.study import answer, technical_gate

TITLES = {
    "constrained": "Constrained surprise, actual minus expected, standardised.",
    "decomposed": "Decision and priced path entered separately, both known before"
    " the statement clears.",
    "repricing": "Repricing of the curve from the eve of the meeting to the hour"
    " after it. Not knowable at the statement.",
}


def _slope_line(slope: dict) -> str:
    mark = "*" if slope["excludes_zero"] else " "
    return (
        f"   {mark}{slope['name']:<12} {slope['estimate']:8.2f}   "
        f"HC3 [{slope['robust_low']:8.2f}, {slope['robust_high']:8.2f}]   "
        f"boot [{slope['boot_low']:8.2f}, {slope['boot_high']:8.2f}]   "
        f"p={slope['p_value']:.3f}"
    )


def render(conn) -> None:
    """
    Prints what the API serves, from the same call, so the terminal and the
    screen can never disagree about a number.
    """
    result = answer.assemble(conn)
    coverage = result["coverage"]
    lead = coverage["window_lead_days"]

    print("Phase 2 gate. Does standardised surprise predict the EUR/USD move")
    print("after an FOMC decision, and over what horizon.")
    print()
    print(f"Meetings with expectation, decision and price: {coverage['meetings']}")
    print(f"Coverage: {coverage['first'][:10]} to {coverage['last'][:10]}")
    print(f"Meetings that changed the target range: {coverage['decisions_that_moved']}")
    print(
        "Reference window lead, days: "
        f"min {lead['min']}, median {lead['median']:.0f}, max {lead['max']}"
    )
    print()

    print("Response, pips, absolute median by horizon")
    for horizon, value in result["response_median_pips"].items():
        print(f"  {horizon:<8} {value:7.1f}")
    print()

    for key, test in result["tests"].items():
        print(TITLES[key])
        if not test["tradable"]:
            print("Diagnostic only, it cannot be traded on.")
        for horizon, fit in test["by_horizon"].items():
            print(f"  {horizon}  n={fit['n']}  R2={fit['r_squared']:.3f}")
            for slope in fit["slopes"]:
                print(_slope_line(slope))
        print()

    loo = result["leave_one_out"]
    print(
        f"Leave one out on the repricing slope at {result['gate_horizon']}: "
        f"stays in [{loo['low']:.2f}, {loo['high']:.2f}]"
    )

    magnitude = result["magnitude"]
    print(
        f"Magnitude, rank correlation between repricing size and move size: "
        f"rho={magnitude['spearman']:.3f} p={magnitude['p_value']:.3f} "
        f"n={magnitude['n']}"
    )

    versus = result["event_versus_ordinary"]
    print(
        f"FOMC afternoon {versus['event_median_pips']:.1f} pips against "
        f"{versus['ordinary_median_pips']:.1f} on {versus['ordinary_n']} ordinary "
        f"sessions, a factor of {versus['ratio']:.2f}"
    )
    print()
    print("* marks a slope whose robust and bootstrap intervals both exclude zero.")


def render_technical(conn) -> None:
    """
    What technical reading alone is worth, measured before anything is built on
    top of it. A baseline discovered afterwards is a baseline chosen to flatter.
    """
    result = technical_gate.assemble(conn)
    trade = result["trade"]

    print("Technical gate. Does reading the price alone beat the coin, out of")
    print("sample, after the spread.")
    print()
    print(
        f"Sessions {result['sessions']}, invalidation {trade['stop_atr']} and target "
        f"{trade['target_atr']} of the session range, warmed on {trade['warmup']}"
    )
    print(
        f"Perfect foresight {result['perfect_foresight_pips']:6.2f} pips a session, "
        f"worst choice {result['worst_choice_pips']:6.2f}"
    )
    print()

    coin = result["coin"]
    print(f"{'coin':<22} {coin['mean_pips']:6.2f} pips  "
          f"[{coin['low']:6.2f}, {coin['high']:6.2f}]   Brier {coin['brier']:.4f}")
    print()

    print("Ordinary rules, scored on every session")
    for name, rule in result["naive_rules"].items():
        print(f"  {name:<20} {rule['mean_pips']:6.2f} pips  "
              f"[{rule['low']:6.2f}, {rule['high']:6.2f}]   "
              f"side {100 * rule['side_accuracy']:4.1f}%")
    print()

    print(f"Walk forward over {len(result['features'])} features, no look ahead")
    for name, fit in result["fits"].items():
        beat = "beats the coin" if fit["mean_pips"] > coin["mean_pips"] else "loses to the coin"
        print(f"  {name:<20} {fit['mean_pips']:6.2f} pips  "
              f"[{fit['low']:6.2f}, {fit['high']:6.2f}]   "
              f"side {100 * fit['side_accuracy']:4.1f}%   "
              f"Brier {fit['brier']:.4f}   {beat}")


def render_cross(conn, window: str = "5m") -> None:
    """
    The cross-instrument gate, printed in the order the question was asked:
    which instruments respond to the event at all, then whether the response is
    predictable from a number knowable while there is still time to act.
    """
    from scipy import stats as scipy_stats

    from basis.study import cross

    print("Cross-instrument gate. Does the two year note's repricing over the")
    print(f"first {window} of an FOMC statement predict what an instrument does")
    print("over the rest of the two hours.")
    print()

    print("Membership. Two hour move from 14:00 Eastern, basis points of price,")
    print("meeting days against ordinary sessions, Mann Whitney one sided.")
    print()
    print(
        f"   {'instrument':<12}{'meetings':>9}{'ordinary':>9}"
        f"{'meeting':>9}{'ordinary':>9}{'lift':>7}{'p':>10}"
    )
    for row in cross.event_day_lift(conn):
        print(
            f"   {row['instrument']:<12}{row['meetings']:>9}{row['ordinary']:>9}"
            f"{row['median_meeting_bps']:>9.2f}{row['median_ordinary_bps']:>9.2f}"
            f"{row['lift']:>7.2f}{row['p_value']:>10.1e}"
        )

    frame = cross.panel(conn)
    if frame.empty:
        print()
        print("No panel. Backfill the universe first.")
        return

    print()
    print("Transmission. A starred line is one where the HC3 and the bootstrap")
    print("intervals agree on excluding zero. Responses are in multiples of the")
    print("instrument's own ordinary two hour move.")
    print()
    for tradable in (True, False):
        label = (
            f"knowable at +{window}, response measured from +{window} to +2h"
            if tradable
            else "whole window against whole move, not knowable in time"
        )
        print(f"  {'tradable' if tradable else 'diagnostic'}: {label}")
        for row in cross.rate_transmission(frame, window):
            if row["tradable"] is not tradable:
                continue
            mark = "*" if row["excludes_zero"] else " "
            print(
                f"   {mark}{row['instrument']:<12}n={row['n']:<4}"
                f"R2={row['r_squared']:5.3f}  {row['estimate']:+7.3f}   "
                f"HC3 [{row['robust_low']:+7.3f}, {row['robust_high']:+7.3f}]   "
                f"boot [{row['boot_low']:+7.3f}, {row['boot_high']:+7.3f}]"
            )
        print()

    result = cross.pooled(frame, window)
    if result:
        mark = "*" if result["excludes_zero"] else " "
        print(
            f"  pooled, errors clustered on the meeting: {result['n']} rows over "
            f"{result['events']} events and {result['instruments']} instruments"
        )
        print(
            f"   {mark}{result['estimate']:+7.3f}   "
            f"cluster [{result['cluster_low']:+7.3f}, {result['cluster_high']:+7.3f}]"
            f"   p={result['p_value']:.3f}   R2={result['r_squared']:5.3f}"
        )
        print()

    frame = frame.copy()
    frame["first_bps"] = frame["full_2h_bps"] - frame[f"after_{window}_bps"]
    print(f"  How much of the two hour move is already spent at +{window}:")
    for instrument, block in frame.groupby("instrument", sort=False):
        early = block["first_bps"].abs().median()
        late = block[f"after_{window}_bps"].abs().median()
        if not early or not late:
            continue
        print(
            f"   {instrument:<12}{early:7.2f} before, {late:7.2f} after, "
            f"{100 * early / (early + late):3.0f} percent done"
        )

    leader = frame[frame["instrument"] == cross.RATE_LEADER]
    usable = leader[[f"reprice_{window}_bps", f"after_{window}_bps"]].dropna()
    if len(usable) > 10:
        test = scipy_stats.spearmanr(usable.iloc[:, 0], usable.iloc[:, 1])
        print()
        print(
            "  Does the rate move lead itself? Spearman between the note's own "
            f"0 to {window} repricing"
        )
        print(
            f"  and its own {window} to 2h move: rho={float(test.statistic):+.3f}, "
            f"p={float(test.pvalue):.3f}"
        )
