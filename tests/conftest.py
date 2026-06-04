"""Shared test fixtures and configuration."""

import asyncio
import sys
from pathlib import Path
from typing import Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def sample_config() -> Dict:
    """Provide a minimal config dict for testing."""
    return {
        "risk": {
            "max_position_pct": 0.05,
            "daily_loss_cap_pct": 0.10,
            "halt_total_loss_pct": 0.40,
            "min_profit_threshold_usd": 0.30,
            "max_correlated_exposure_pct": 0.15,
            "time_of_day": {
                "enabled": False,
                "active_start_hour_utc": 8,
                "active_end_hour_utc": 22,
                "reduced_size_pct": 0.5,
            },
        },
        "taker_fees": {
            "crypto": 0.018,
            "sports": 0.0075,
            "finance": 0.01,
            "politics": 0.01,
            "economics": 0.015,
            "geopolitics": 0.0,
        },
        "execution": {
            "rate_limit_per_min": 55,
            "post_only_default": True,
            "retry_max_attempts": 2,
            "retry_backoff_base_sec": 0.1,
            "pending_timeout_sec": 2.0,
            "error_circuit_breaker": {
                "threshold": 5,
                "window_sec": 60,
                "pause_sec": 30,
            },
        },
        "strategies": {
            "market_making": {
                "min_size": 5,
                "max_spread_bps": 500,
                "requote_threshold_bps": 5,
                "holding_rewards": {
                    "enabled": True,
                    "target_apy": 0.04,
                    "min_days_to_resolution": 14,
                },
                "adverse_selection": {
                    "volatility_pause_threshold": 0.05,
                    "fill_rate_window_sec": 60,
                    "fill_rate_pause_threshold": 0.8,
                },
            },
        },
        "alerting": {
            "telegram": {
                "enabled": False,
                "min_interval_sec": 30,
                "alerts": ["halt_triggered", "connection_lost"],
            },
        },
        "logging": {
            "level": "DEBUG",
            "file": "logs/test.log",
            "max_size_mb": 5,
            "format": "json",
        },
        "monitoring": {
            "metrics_port": 9091,
            "health_check_sec": 10,
        },
    }


@pytest.fixture
def mock_config(sample_config):
    """Alias for sample_config."""
    return sample_config


@pytest.fixture
def mock_portfolio(sample_config):
    """Create a Portfolio instance with test config."""
    from core.portfolio import Portfolio
    portfolio = Portfolio(sample_config)
    portfolio._free_usdc = 10000.0
    portfolio._initial_capital = 10000.0
    return portfolio


@pytest.fixture
def mock_order_store():
    """Create an OrderStore instance with short timeout for tests."""
    from core.order_state import OrderStore
    return OrderStore(pending_timeout_sec=1.0)


@pytest.fixture
def mock_client(sample_config):
    """Create a mock ClobClient."""
    from core.client import ClobClient
    client = ClobClient(sample_config)
    return client
