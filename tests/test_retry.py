from x_scrap.runtime.retry import RetryPolicy


def test_exponential_backoff_is_bounded():
    policy = RetryPolicy(base_delay_seconds=2, max_delay_seconds=10)
    assert [policy.delay_for_attempt(i) for i in range(1, 6)] == [2, 4, 8, 10, 10]
