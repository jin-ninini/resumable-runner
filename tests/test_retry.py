import pytest

from resumable import RetryPolicy


def test_delay_grows_exponentially() -> None:
    policy = RetryPolicy(base_delay=1, backoff=2, max_delay=100)
    assert [policy.delay(n) for n in (1, 2, 3, 4)] == [1, 2, 4, 8]


def test_delay_is_capped() -> None:
    policy = RetryPolicy(base_delay=10, backoff=3, max_delay=25)
    assert policy.delay(3) == 25


@pytest.mark.parametrize(
    "kwargs",
    [{"max_attempts": 0}, {"base_delay": -1}, {"max_delay": -1}, {"backoff": 0.5}],
)
def test_rejects_invalid_settings(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        RetryPolicy(**kwargs)  # type: ignore[arg-type]


def test_attempt_is_one_based() -> None:
    with pytest.raises(ValueError):
        RetryPolicy().delay(0)
