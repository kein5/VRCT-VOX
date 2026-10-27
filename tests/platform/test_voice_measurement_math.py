import pytest


def samples():
    return [dict(before_ns=1_000_000_000, browser_ms=10., after_ns=1_020_000_000),
            dict(before_ns=1_190_000_000, browser_ms=200., after_ns=1_192_000_000)]


def test_asymmetric_round_trip_uses_bounds_not_assumed_half_rtt():
    from native_voice_measurement import elapsed_bounds
    result = elapsed_bounds(1_100_000_000, 25., samples(), padding_ns=0)
    assert result == {"lower_ms": 83., "upper_ms": 85., "calibration_width_ms": 2.}


@pytest.mark.parametrize("bad", [
    [dict(before_ns=20, browser_ms=1, after_ns=10)],
    [dict(before_ns=10, browser_ms=float("nan"), after_ns=20)],
    [dict(before_ns=1_000_000, browser_ms=1, after_ns=1_000_100),
     dict(before_ns=3_000_000, browser_ms=2, after_ns=3_000_100)],
])
def test_invalid_or_disjoint_clock_samples_are_rejected(bad):
    from native_voice_measurement import clock_offset
    with pytest.raises(ValueError):
        clock_offset(bad, padding_ns=0)


@pytest.mark.parametrize("first,ui", [(1_000_000_000, 25.), (1_100_000_000, 5.)])
def test_negative_latency_or_unbracketed_ui_event_is_rejected(first, ui):
    from native_voice_measurement import elapsed_bounds
    with pytest.raises(ValueError):
        elapsed_bounds(first, ui, samples(), padding_ns=0)


def trial(value=200):
    return dict(lower_ms=value - 2, upper_ms=value, calibration_width_ms=2,
                valid=True, outcome="completed", warm=True)


def test_gate_uses_upper_bound_nearest_rank_percentile_and_sample_count():
    from native_voice_measurement import summarize_trials
    rows = [trial(349)] * 28 + [trial(799), trial(900)]
    result = summarize_trials(rows, real_inference=True)
    assert result["verdict"] == "pass"
    assert result["p50_upper_ms"] == 349 and result["p95_upper_ms"] == 799
    assert summarize_trials(rows[:-1], real_inference=True)["verdict"] == "insufficient_samples"
    assert summarize_trials([trial(349)] * 28 + [trial(800)] * 2, real_inference=True)["verdict"] == "target_not_met"
    assert summarize_trials(rows, real_inference=False)["verdict"] == "fixture_only"


@pytest.mark.parametrize("change", [dict(valid=False), dict(outcome="error"), dict(warm=False),
                                    dict(calibration_width_ms=6), dict(upper_ms=float("nan")),
                                    dict(lower_ms=-1), dict(lower_ms=201)])
def test_invalid_trials_cannot_be_discarded_to_claim_passing_tail(change):
    from native_voice_measurement import summarize_trials
    rows = [trial()] * 30 + [{**trial(), **change}]
    assert summarize_trials(rows, real_inference=True)["verdict"] == "invalid_measurement"
