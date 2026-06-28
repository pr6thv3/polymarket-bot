"""Tests for the risk manager (core/risk.py)."""

import pytest

from core.portfolio import Portfolio, Position
from core.risk import RiskManager, RiskHaltTriggered


class TestRiskManager:
    """Test RiskManager pre-flight checks."""

    def _make_risk_manager(self, mock_portfolio, sample_config):
        """Helper to create a RiskManager with a real portfolio."""
        return RiskManager(mock_portfolio, sample_config)

    def test_taker_fee_lookup(self, sample_config, mock_portfolio):
        rm = self._make_risk_manager(mock_portfolio, sample_config)
        assert rm.get_taker_fee("crypto") == 0.018
        assert rm.get_taker_fee("geopolitics") == 0.0
        assert rm.get_taker_fee("unknown") == 0.01  # Default

    def test_rebate_rate_lookup(self, sample_config, mock_portfolio):
        rm = self._make_risk_manager(mock_portfolio, sample_config)
        assert rm.get_rebate_rate("finance") == 0.50
        assert rm.get_rebate_rate("crypto") == 0.20

    def test_expected_rebate_calculation(self, sample_config, mock_portfolio):
        rm = self._make_risk_manager(mock_portfolio, sample_config)
        # Finance: taker fee 1.0%, rebate 50% → expected rebate = notional * 0.01 * 0.50
        rebate = rm.calculate_expected_rebate(notional=1000.0, category="finance")
        assert rebate == pytest.approx(5.0, abs=0.01)

    def test_calculate_rebate_value_matches_expected_rebate(self, sample_config, mock_portfolio):
        rm = self._make_risk_manager(mock_portfolio, sample_config)

        assert rm.calculate_rebate_value(
            notional=1000.0,
            category="finance",
        ) == pytest.approx(rm.calculate_expected_rebate(1000.0, "finance"))

    def test_expected_rebate_geopolitics(self, sample_config, mock_portfolio):
        rm = self._make_risk_manager(mock_portfolio, sample_config)
        # Geopolitics: taker fee 0%, rebate 20% → expected rebate = 0
        rebate = rm.calculate_expected_rebate(notional=1000.0, category="geopolitics")
        assert rebate == pytest.approx(0.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_allow_small_order(self, sample_config, mock_portfolio):
        rm = self._make_risk_manager(mock_portfolio, sample_config)
        # Portfolio value is 10000, 5% limit = 500. Order of $50 should be fine.
        allowed, reason = await rm.allow_order(
            market_id="m1",
            side="BUY",
            price=0.50,
            size=100.0,  # $50 notional
            category="finance",
        )
        assert allowed is True
        assert reason == "OK"

    @pytest.mark.asyncio
    async def test_reject_order_exceeding_position_limit(self, sample_config, mock_portfolio):
        rm = self._make_risk_manager(mock_portfolio, sample_config)
        # Portfolio value is 10000, 5% limit = 500. Order of $600 should be rejected.
        allowed, reason = await rm.allow_order(
            market_id="m1",
            side="BUY",
            price=0.60,
            size=1000.0,  # $600 notional
            category="finance",
        )
        assert allowed is False
        assert "exceed limit" in reason

    @pytest.mark.asyncio
    async def test_reject_order_when_halted(self, sample_config, mock_portfolio):
        rm = self._make_risk_manager(mock_portfolio, sample_config)
        rm._halt_triggered = True
        rm._halt_reason = "Test halt"

        allowed, reason = await rm.allow_order(
            market_id="m1",
            side="BUY",
            price=0.50,
            size=10.0,
        )
        assert allowed is False
        assert "halt" in reason.lower()

    @pytest.mark.asyncio
    async def test_halt_triggered_on_total_loss(self, sample_config, mock_portfolio):
        rm = self._make_risk_manager(mock_portfolio, sample_config)
        # Simulate a portfolio that has lost 45% (> 40% threshold)
        mock_portfolio._initial_capital = 10000.0
        mock_portfolio._free_usdc = 5000.0  # Lost 50%
        mock_portfolio._locked_usdc = 0.0

        allowed, reason = await rm.allow_order(
            market_id="m1",
            side="BUY",
            price=0.50,
            size=10.0,
        )
        assert allowed is False
        assert rm.is_halted is True

    @pytest.mark.asyncio
    async def test_correlated_exposure_rejection(self, sample_config, mock_portfolio):
        rm = self._make_risk_manager(mock_portfolio, sample_config)

        # Set up correlation groups
        mock_portfolio.set_correlation_groups({
            "us_election": {"m1", "m2", "m3"}
        })

        # Strategy: make m2 consume most of the 15% correlated budget.
        # m1 has a small existing position so the new order stays within 5%.
        #
        # Portfolio value = free_usdc ($10,000) + positions
        #   = 10000 + 1200 (m2) + 200 (m1) = 11,400
        # 5% position limit for m1 = 5% * 11400 = $570
        # 15% correlated limit = 15% * 11400 = $1,710
        #
        # get_correlated_exposure("m1") = m1_notional + m2_notional = 200 + 1200 = $1,400
        # New order for m1: 400 shares @ $0.50 = $200 notional
        #   → new m1 position = 200 + 200 = $400 (3.5% — under 5% limit ✓)
        #   → total_correlated = 1400 + 200 = $1,600
        #   → correlated_pct = 1600 / 11400 = 14.0% — under 15%, not enough
        #
        # Need to push over 15%. Try 500 shares @ $0.50 = $250 notional:
        #   → new m1 = 200 + 250 = $450 (3.9% — under 5% limit ✓)
        #   → total_correlated = 1400 + 250 = $1,650
        #   → correlated_pct = 1650 / 11400 = 14.5% — still under
        #
        # Make m2 bigger. Set m2 = $1,400 notional:
        #   Portfolio value = 10000 + 1400 + 200 = 11,600
        #   5% limit = $580, 15% limit = $1,740
        #   get_correlated_exposure("m1") = 200 + 1400 = $1,600
        #   Order 500 @ $0.50 = $250:
        #   → total_correlated = 1600 + 250 = $1,850
        #   → correlated_pct = 1850 / 11600 = 15.9% > 15% ✓

        mock_portfolio._positions["m2"] = Position(
            market_id="m2",
            size=2800.0,
            avg_entry_price=0.50,
        )  # $1,400 notional
        mock_portfolio._positions["m1"] = Position(
            market_id="m1",
            size=400.0,
            avg_entry_price=0.50,
        )  # $200 notional

        allowed, reason = await rm.allow_order(
            market_id="m1",
            side="BUY",
            price=0.50,
            size=500.0,  # $250 notional → correlated total $1,850 (15.9%)
            category="politics",
        )
        assert allowed is False
        assert "correlated" in reason.lower()

    def test_reset_halt(self, sample_config, mock_portfolio):
        rm = self._make_risk_manager(mock_portfolio, sample_config)
        rm._halt_triggered = True
        rm._halt_reason = "Test halt"

        rm.reset_halt()
        assert rm.is_halted is False
        assert rm.halt_reason == ""

    def test_risk_summary(self, sample_config, mock_portfolio):
        rm = self._make_risk_manager(mock_portfolio, sample_config)
        summary = rm.get_risk_summary()

        assert "halted" in summary
        assert "total_loss_pct" in summary
        assert "portfolio_value" in summary
        assert summary["halted"] is False
