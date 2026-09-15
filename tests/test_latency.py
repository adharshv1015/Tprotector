from app.models.latency import LatencyBaseline
from app.models.snapshot import ApiSnapshot
from app.services.latency import check_drift, compute_metrics


def test_latency_metrics_computation():
    snapshots = [
        ApiSnapshot(status_code=200, response_time_ms=100.0),
        ApiSnapshot(status_code=200, response_time_ms=110.0),
        ApiSnapshot(status_code=200, response_time_ms=90.0),
        ApiSnapshot(status_code=500, response_time_ms=500.0),  # Error
    ]

    avg, std_dev, error_rate = compute_metrics(snapshots)
    assert avg == 200.0
    assert error_rate == 25.0  # 1 out of 4 is error
    assert std_dev > 0.0


def test_latency_drift_anomaly_detection():
    baseline = LatencyBaseline(
        avg_response_time_ms=100.0,
        std_dev_ms=10.0,
        error_rate_percent=0.0
    )

    # 1. Normal response (115ms = 1.5 std devs -> not a spike at threshold 3.0)
    is_spike, z_score = check_drift(115.0, baseline, z_threshold=3.0)
    assert is_spike is False
    assert z_score == 1.5

    # 2. Significant anomaly (145ms = 4.5 std devs -> spike!)
    is_spike_high, z_score_high = check_drift(145.0, baseline, z_threshold=3.0)
    assert is_spike_high is True
    assert z_score_high == 4.5
