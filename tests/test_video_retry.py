from app.video_generation.retry import exponential_backoff_seconds


def test_exponential_backoff_caps_delay() -> None:
    assert exponential_backoff_seconds(1, base_seconds=2, cap_seconds=10) == 2
    assert exponential_backoff_seconds(3, base_seconds=2, cap_seconds=10) == 8
    assert exponential_backoff_seconds(10, base_seconds=2, cap_seconds=10) == 10
