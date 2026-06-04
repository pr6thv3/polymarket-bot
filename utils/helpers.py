"""Utility helpers: config loading, retry logic, price conversion."""

import asyncio
import functools
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

import yaml

T = TypeVar("T")

# Default config path relative to project root
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config(path: str = "") -> dict:
    """Load configuration from a YAML file.

    Args:
        path: Path to config.yaml. Defaults to project root config.yaml.

    Returns:
        Parsed config as a dict.

    Raises:
        FileNotFoundError: If config file doesn't exist.
    """
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return config or {}


def save_config(config: dict, path: str = "") -> None:
    """Save configuration dict to a YAML file.

    Args:
        config: Config dict to save.
        path: Path to write. Defaults to project root config.yaml.
    """
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def bps_to_price(bps: float) -> float:
    """Convert basis points to a dollar price on a $1 scale.

    Example: 200 bps = $0.02

    Args:
        bps: Basis points (1 bp = 0.01%).

    Returns:
        Dollar price equivalent.
    """
    return bps / 10_000


def price_to_bps(price: float) -> float:
    """Convert a dollar price to basis points on a $1 scale.

    Example: $0.02 = 200 bps

    Args:
        price: Dollar price (0.0 to 1.0).

    Returns:
        Basis points equivalent.
    """
    return price * 10_000


def retry_async(
    max_attempts: int = 3,
    backoff_base: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
) -> Callable:
    """Decorator for async functions with exponential backoff retry.

    Args:
        max_attempts: Maximum number of attempts.
        backoff_base: Base for exponential backoff (seconds).
        retryable_exceptions: Tuple of exception types to retry on.

    Returns:
        Decorated async function.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_exception = exc
                    if attempt < max_attempts:
                        delay = backoff_base ** attempt
                        await asyncio.sleep(delay)
                    else:
                        raise last_exception from last_exception
            # Should not reach here, but just in case
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator


def rate_limit(max_calls: int, period: float = 60.0) -> Callable:
    """Decorator factory for simple rate limiting using a token bucket.

    Args:
        max_calls: Maximum calls allowed in the period.
        period: Time period in seconds.

    Returns:
        Decorator that enforces rate limiting.
    """
    min_interval = period / max_calls
    last_called: dict = {"time": 0.0}

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            elapsed = time.monotonic() - last_called["time"]
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
            last_called["time"] = time.monotonic()
            return await func(*args, **kwargs)

        return wrapper

    return decorator


class TokenBucketRateLimiter:
    """Token bucket rate limiter for controlling API call frequency.

    Thread-safe via asyncio Lock. Allows burst up to bucket capacity,
    then replenishes tokens at a steady rate.
    """

    def __init__(self, rate: float, capacity: int = 10) -> None:
        """Initialize the rate limiter.

        Args:
            rate: Tokens added per second (e.g., 55/60 for 55 requests/min).
            capacity: Maximum burst size.
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available, then consume it."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(
                self.capacity, self.tokens + elapsed * self.rate
            )
            self.last_refill = now

            if self.tokens < 1.0:
                wait_time = (1.0 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0.0
                self.last_refill = time.monotonic()
            else:
                self.tokens -= 1.0
