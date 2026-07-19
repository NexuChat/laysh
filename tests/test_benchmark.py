from scripts.benchmark import percentile


def test_benchmark_percentile_uses_nearest_rank_without_hiding_tail_latency():
    assert percentile([1, 2], 50) == 1
    assert percentile([1, 2], 95) == 2
    assert percentile([4, 1, 3, 2], 95) == 4
