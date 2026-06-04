"""Telegram alerting for the Polymarket trading bot."""

import asyncio
import time
from typing import Optional

import httpx
import structlog

from utils.helpers import load_config

logger = structlog.get_logger(__name__)

# Alert type formatting
ALERT_EMOJI = {
    "halt_triggered": "🚨",
    "daily_loss_cap_hit": "⚠️",
    "large_fill": "💰",
    "connection_lost": "🔌",
    "rebate_earned": "🏦",
}


class Alerter:
    """Send alerts via Telegram Bot API with rate limiting.

    Graceful degradation: if Telegram is unavailable, logs the error
    but never crashes the bot.
    """

    def __init__(self, config: dict) -> None:
        """Initialize the alerter from config.

        Args:
            config: Full config dict (reads alerting.telegram section).
        """
        import os

        telegram_cfg = config.get("alerting", {}).get("telegram", {})
        self.enabled = telegram_cfg.get("enabled", False)
        self.bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.min_interval = telegram_cfg.get("min_interval_sec", 30)
        self.allowed_alerts = set(telegram_cfg.get("alerts", []))
        self._last_sent_time: float = 0.0
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    async def send_alert(self, alert_type: str, message: str) -> bool:
        """Send an alert via Telegram.

        Respects rate limiting (1 per min_interval_sec) and only sends
        alert types that are configured.

        Args:
            alert_type: Type of alert (must be in allowed_alerts).
            message: Alert message body.

        Returns:
            True if alert was sent successfully, False otherwise.
        """
        if not self.enabled:
            logger.debug("Alerting disabled, skipping", alert_type=alert_type)
            return False

        if alert_type not in self.allowed_alerts:
            logger.debug(
                "Alert type not in allowed list, skipping",
                alert_type=alert_type,
            )
            return False

        if not self.bot_token or not self.chat_id:
            logger.warning(
                "Telegram credentials not configured, cannot send alert",
                alert_type=alert_type,
            )
            return False

        # Rate limit: skip if sent too recently
        now = time.monotonic()
        if now - self._last_sent_time < self.min_interval:
            logger.debug(
                "Alert rate limited, skipping",
                alert_type=alert_type,
                cooldown_remaining=self.min_interval - (now - self._last_sent_time),
            )
            return False

        emoji = ALERT_EMOJI.get(alert_type, "📢")
        formatted = f"{emoji} *{alert_type.replace('_', ' ').title()}*\n\n{message}"

        try:
            client = await self._get_client()
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            response = await client.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": formatted,
                    "parse_mode": "Markdown",
                },
            )
            response.raise_for_status()
            self._last_sent_time = time.monotonic()
            logger.info(
                "Alert sent",
                alert_type=alert_type,
            )
            return True
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Telegram API returned error",
                alert_type=alert_type,
                status_code=exc.response.status_code,
                error=str(exc),
            )
            return False
        except httpx.RequestError as exc:
            logger.error(
                "Telegram request failed",
                alert_type=alert_type,
                error=str(exc),
            )
            return False
        except Exception as exc:
            logger.error(
                "Unexpected error sending alert",
                alert_type=alert_type,
                error=str(exc),
            )
            return False

    async def send_daily_summary(
        self,
        pnl_usd: float,
        rebate_usd: float,
        holding_reward_usd: float,
        spread_captured_usd: float,
        total_fill_rate: float,
    ) -> bool:
        """Send a daily P&L + rebate summary alert.

        Args:
            pnl_usd: Today's total P&L.
            rebate_usd: Today's rebates earned.
            holding_reward_usd: Today's holding rewards earned.
            spread_captured_usd: Today's spread captured.
            total_fill_rate: Today's fill rate percentage.

        Returns:
            True if sent successfully.
        """
        message = (
            f"📊 *Daily Summary*\n\n"
            f"P&L: ${pnl_usd:+.2f}\n"
            f"Spread Captured: ${spread_captured_usd:.2f}\n"
            f"Rebates Earned: ${rebate_usd:.2f}\n"
            f"Holding Rewards: ${holding_reward_usd:.4f}\n"
            f"Fill Rate: {total_fill_rate:.1f}%"
        )
        return await self.send_alert("rebate_earned", message)
