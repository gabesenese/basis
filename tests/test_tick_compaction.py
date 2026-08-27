from datetime import date, datetime, timezone

import pandas as pd

from basis.lanes import ticks as tick_lane

SOURCE = "oanda_stream"
SYMBOL = "EUR_USD"
DAY = date(2026, 8, 19)


def chunk(root, stamp: str, ticks: list[tuple[int, float]]):
    target = tick_lane.partition_path(root, SOURCE, SYMBOL, DAY)
    target.parent.mkdir(parents=True, exist_ok=True)

    frame = pd.DataFrame(
        [
            {
                "ts": datetime(2026, 8, 19, 12, 0, second, tzinfo=timezone.utc),
                "bid": price,
                "ask": price + 0.00015,
                "instrument": SYMBOL,
            }
            for second, price in ticks
        ]
    )
    path = target.with_name(f"{DAY.isoformat()}T{stamp}.parquet")
    frame.to_parquet(path, index=False)
    return path


def test_chunks_fold_into_the_file_the_partition_is_named_for(tmp_path):
    chunk(tmp_path, "120000000", [(1, 1.1000), (2, 1.1001)])
    chunk(tmp_path, "120100000", [(3, 1.1002)])

    rows = tick_lane.compact_day(tmp_path, SOURCE, SYMBOL, DAY)
    canonical = tick_lane.partition_path(tmp_path, SOURCE, SYMBOL, DAY)

    assert rows == 3
    assert canonical.exists()
    assert len(pd.read_parquet(canonical)) == 3


def test_the_chunks_are_removed_only_after_the_merge_lands(tmp_path):
    chunk(tmp_path, "120000000", [(1, 1.1000)])
    chunk(tmp_path, "120100000", [(2, 1.1001)])

    tick_lane.compact_day(tmp_path, SOURCE, SYMBOL, DAY)

    assert tick_lane.chunk_paths(tmp_path, SOURCE, SYMBOL, DAY) == []


def test_compacting_twice_merges_rather_than_truncating(tmp_path):
    chunk(tmp_path, "120000000", [(1, 1.1000), (2, 1.1001)])
    tick_lane.compact_day(tmp_path, SOURCE, SYMBOL, DAY)

    chunk(tmp_path, "130000000", [(3, 1.1002)])
    rows = tick_lane.compact_day(tmp_path, SOURCE, SYMBOL, DAY)

    assert rows == 3


def test_a_tick_written_into_two_chunks_survives_once(tmp_path):
    chunk(tmp_path, "120000000", [(1, 1.1000), (2, 1.1001)])
    chunk(tmp_path, "120100000", [(2, 1.1001), (3, 1.1002)])

    rows = tick_lane.compact_day(tmp_path, SOURCE, SYMBOL, DAY)

    assert rows == 3


def test_the_merged_file_is_ordered_by_time(tmp_path):
    chunk(tmp_path, "130000000", [(9, 1.1009)])
    chunk(tmp_path, "120000000", [(1, 1.1000)])

    tick_lane.compact_day(tmp_path, SOURCE, SYMBOL, DAY)
    merged = pd.read_parquet(tick_lane.partition_path(tmp_path, SOURCE, SYMBOL, DAY))

    assert merged["ts"].is_monotonic_increasing


def test_a_day_with_nothing_to_fold_is_left_alone(tmp_path):
    assert tick_lane.compact_day(tmp_path, SOURCE, SYMBOL, DAY) == 0


def test_recorded_days_finds_both_chunks_and_compacted_files(tmp_path):
    chunk(tmp_path, "120000000", [(1, 1.1000)])
    tick_lane.compact_day(tmp_path, SOURCE, SYMBOL, DAY)
    chunk(tmp_path, "130000000", [(2, 1.1001)])

    assert tick_lane.recorded_days(tmp_path, SOURCE, SYMBOL) == [DAY]


def test_the_lane_reads_a_compacted_day_the_same_as_chunks(tmp_path):
    chunk(tmp_path, "120000000", [(1, 1.1000), (2, 1.1001)])
    chunk(tmp_path, "120100000", [(3, 1.1002)])

    con = tick_lane.connect(tmp_path)
    before = con.execute("select count(*) from ticks").fetchone()[0]
    con.close()

    tick_lane.compact_day(tmp_path, SOURCE, SYMBOL, DAY)

    con = tick_lane.connect(tmp_path)
    after = con.execute("select count(*) from ticks").fetchone()[0]
    con.close()

    assert before == after == 3
