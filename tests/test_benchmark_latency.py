import pytest

from scripts.benchmark_latency import format_summary, percentile


def test_percentile_p50_of_odd_count_is_middle_value() -> None:
    assert percentile([100.0, 200.0, 300.0], 50) == 200.0


def test_percentile_p95_interpolates_between_values() -> None:
    values = [float(v) for v in range(1, 21)]  # 1..20

    assert percentile(values, 95) == pytest.approx(19.05)


def test_percentile_single_value_returns_that_value() -> None:
    assert percentile([42.0], 50) == 42.0
    assert percentile([42.0], 95) == 42.0


def test_percentile_empty_raises() -> None:
    with pytest.raises(ValueError):
        percentile([], 50)


def test_format_summary_includes_n_and_percentiles() -> None:
    summary = format_summary([100.0, 200.0, 300.0, 400.0, 500.0])

    assert "n=5" in summary
    assert "min=100ms" in summary
    assert "max=500ms" in summary
    assert "p50=" in summary
    assert "p95=" in summary
