import pytest

from tools.voice_latency import summarize


def test_nearest_rank_percentiles_keep_measurement_boundaries_separate():
    rows = [{"metric": "event_to_write", "environment": "FAKE", "warm": "yes",
             "start_ns": "1000000000", "end_ns": str(1000000000 + i * 1000000)} for i in range(1, 101)]
    rows.append({**rows[0], "metric": "physical_loopback", "warm": "no"})
    result = summarize(rows)
    assert result[0] == {"metric": "event_to_write", "environment": "FAKE", "warm": "yes",
                         "count": 100, "p50_ms": 50, "p95_ms": 95, "p99_ms": 99}
    assert result[1]["count"] == 1
    assert summarize([]) == []


def test_latency_rejects_negative_elapsed_time():
    with pytest.raises(ValueError):
        summarize([{"metric": "x", "environment": "fake", "warm": "yes", "start_ns": "2", "end_ns": "1"}])
