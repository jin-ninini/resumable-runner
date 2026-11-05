"""How many times to try an item and how long to wait between tries."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff: base_delay, base_delay * backoff, ... capped at max_delay.

    max_attempts counts the first try, so max_attempts=1 means "never retry".
    """

    max_attempts: int = 3
    base_delay: float = 1.0
    backoff: float = 2.0
    max_delay: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("delays must not be negative")
        if self.backoff < 1:
            raise ValueError("backoff must be at least 1")

    def delay(self, attempt: int) -> float:
        """Seconds to wait after the given failed attempt (1-based) before the next one."""
        if attempt < 1:
            raise ValueError("attempt is 1-based")
        return float(min(self.max_delay, self.base_delay * self.backoff ** (attempt - 1)))
