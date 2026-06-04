"""Whale tracker — monitors large, profitable wallets for smart money following.

Scans on-chain activity on Polygon for wallets with proven track records:
- Win rate > 60%
- Profit factor > 1.5x
- Minimum 20 trades (consistency check)

Tracks their positions and emits signals when they enter/exit markets.
The WhaleTrackingStrategy consumes these signals.

Data sources:
- Polymarket API: /activity endpoint for recent trades by address
- Polygon RPC: on-chain event logs for CLOB contract interactions
- Pre-configured whale list from config + dynamic discovery
"""

import asyncio
import json
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import aiohttp
import structlog

logger = structlog.get_logger(__name__)

# ── Defaults ────────────────────────────────────────────────────────────
MIN_TRADES_FOR_TRACKING = 20
MIN_WIN_RATE = 0.60
MIN_PROFIT_FACTOR = 1.5
WHALE_REFRESH_INTERVAL_SEC = 300.0  # 5 min between wallet scans
ACTIVITY_POLL_INTERVAL_SEC = 10.0   # 10 sec between activity checks
POSITION_TTL_SEC = 3600.0           # Stale positions removed after 1 hour

STATE_DIR = os.path.join(os.path.dirname(__file__), "..", "state")
WHALE_STATE_FILE = os.path.join(STATE_DIR, "whale_tracker.json")


@dataclass
class WhaleProfile:
    """Statistical profile of a tracked wallet."""

    address: str
    total_trades: int = 0
    winning_trades: int = 0
    total_profit_usd: float = 0.0
    total_loss_usd: float = 0.0
    first_seen_at: float = 0.0
    last_active_at: float = 0.0

    # Current positions
    positions: Dict[str, float] = field(default_factory=dict)  # market_id -> size

    @property
    def win_rate(self) -> float:
        """Win rate (0.0–1.0)."""
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def profit_factor(self) -> float:
        """Profit factor (gross profit / gross loss)."""
        if self.total_loss_usd <= 0:
            return float("inf") if self.total_profit_usd > 0 else 0.0
        return self.total_profit_usd / self.total_loss_usd

    @property
    def qualifies(self) -> bool:
        """Check if this wallet qualifies as 'smart money'."""
        return (
            self.total_trades >= MIN_TRADES_FOR_TRACKING
            and self.win_rate >= MIN_WIN_RATE
            and self.profit_factor >= MIN_PROFIT_FACTOR
        )

    @property
    def is_active(self) -> bool:
        """Check if the wallet has been active recently (last 24h)."""
        return (time.monotonic() - self.last_active_at) < 86400


@dataclass
class WhaleSignal:
    """A trading signal emitted when a whale enters/exits a market."""

    whale_address: str
    market_id: str
    action: str  # "enter" or "exit"
    side: str    # "BUY" or "SELL"
    size: float
    price: float
    timestamp: float = field(default_factory=time.monotonic)
    whale_win_rate: float = 0.0
    whale_profit_factor: float = 0.0

    @property
    def age_sec(self) -> float:
        """Seconds since this signal was created."""
        return time.monotonic() - self.timestamp


class WhaleTracker:
    """Monitors profitable wallets and emits trade signals.

    Architecture:
    1. Load whale list from config + persisted state
    2. Periodically scan whale activity via Polymarket API
    3. Detect new positions (entries) and closed positions (exits)
    4. Emit WhaleSignal objects to an asyncio.Queue for strategy consumption
    5. Persist whale profiles to disk for cross-session continuity

    Dynamic discovery:
    - When a configured whale enters a market, also track other large
      traders in the same market (potential new whales)
    - New wallets must pass the qualification check before being followed
    """

    def __init__(self, config: dict) -> None:
        """Initialize the whale tracker.

        Args:
            config: Full config dict (reads from strategies.whale_tracking section).
        """
        self.config = config
        wt_cfg = config.get("strategies", {}).get("whale_tracking", {})
        feeds_cfg = config.get("data_feeds", {}).get("whale_tracker", {})

        self.enabled = wt_cfg.get("enabled", False)
        self.min_win_rate = wt_cfg.get("min_win_rate", MIN_WIN_RATE)
        self.min_profit_factor = wt_cfg.get("min_profit_factor", MIN_PROFIT_FACTOR)
        self.min_trades = wt_cfg.get("min_trades", MIN_TRADES_FOR_TRACKING)
        self.max_whales = wt_cfg.get("max_whales", 50)

        # API settings
        self._polymarket_base_url = feeds_cfg.get(
            "polymarket_api_url", "https://clob.polymarket.com"
        )
        self._polygon_rpc_url = feeds_cfg.get(
            "polygon_rpc_url", os.environ.get("POLYGON_RPC_URL", "")
        )

        # Whale list from config
        self._config_whales: Set[str] = set(
            wt_cfg.get("whale_addresses", [])
        )

        # Runtime state
        self._whales: Dict[str, WhaleProfile] = {}
        self._signals: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._session: Optional[aiohttp.ClientSession] = None

        # Previous positions cache (for change detection)
        self._prev_positions: Dict[str, Dict[str, float]] = {}  # addr -> {market_id: size}

        # Dynamic discovery
        self._discovery_enabled = wt_cfg.get("dynamic_discovery", True)
        self._discovery_candidates: Dict[str, WhaleProfile] = {}

        # Activity polling
        self._activity_interval = feeds_cfg.get(
            "activity_poll_sec", ACTIVITY_POLL_INTERVAL_SEC
        )
        self._refresh_interval = feeds_cfg.get(
            "whale_refresh_sec", WHALE_REFRESH_INTERVAL_SEC
        )

        # Callback for signals
        self._on_signal: Optional[Callable] = None

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Initialize the tracker: load state, create session, seed whales."""
        if not self.enabled:
            logger.info("Whale tracker disabled")
            return

        # Load persisted whale profiles
        self._load_state()

        # Seed config whales
        for addr in self._config_whales:
            if addr not in self._whales:
                self._whales[addr] = WhaleProfile(
                    address=addr,
                    first_seen_at=time.monotonic(),
                    last_active_at=time.monotonic(),
                )

        # Create HTTP session
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15.0),
        )

        logger.info(
            "Whale tracker initialized",
            whales_tracked=len(self._whales),
            config_whales=len(self._config_whales),
        )

    async def close(self) -> None:
        """Save state and close connections."""
        self._save_state()
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("Whale tracker closed")

    # ── Core scanning ──────────────────────────────────────────────────

    async def scan_whale_activity(self) -> List[WhaleSignal]:
        """Scan all tracked whales for new activity.

        Returns:
            List of WhaleSignal objects for new entries/exits.
        """
        if not self.enabled or not self._session:
            return []

        signals = []

        for addr, profile in list(self._whales.items()):
            if not profile.is_active and profile.last_active_at > 0:
                # Skip inactive whales (but not newly added ones)
                continue

            try:
                new_signals = await self._scan_wallet(addr, profile)
                signals.extend(new_signals)
            except Exception as exc:
                logger.warning(
                    "Whale scan failed",
                    address=addr[:10] + "...",
                    error=str(exc),
                )

        # Clean up stale positions
        self._cleanup_stale_positions()

        # Dynamic discovery
        if self._discovery_enabled:
            await self._discover_new_whales(signals)

        if signals:
            logger.info("Whale signals generated", count=len(signals))

        return signals

    async def _scan_wallet(
        self, address: str, profile: WhaleProfile
    ) -> List[WhaleSignal]:
        """Scan a single wallet for position changes.

        Uses the Polymarket activity API to get recent trades.

        Args:
            address: Wallet address.
            profile: Whale profile to update.

        Returns:
            List of signals for this wallet.
        """
        signals = []

        try:
            # Fetch recent activity
            url = f"{self._polymarket_base_url}/activity"
            params = {
                "address": address,
                "limit": 50,
            }

            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []

                data = await resp.json()
                trades = data.get("activity", data.get("trades", []))

            # Update profile stats
            profile.last_active_at = time.monotonic()

            # Build current positions from trades
            current_positions: Dict[str, float] = {}
            for trade in trades:
                market_id = trade.get("market", trade.get("asset", ""))
                side = trade.get("side", "BUY")
                size = float(trade.get("size", 0))
                price = float(trade.get("price", 0))
                outcome = trade.get("outcome", "YES")

                # Calculate P&L for closed trades
                if trade.get("status") == "resolved":
                    payout = float(trade.get("payout", 0))
                    cost = size * price
                    pnl = payout - cost
                    profile.total_trades += 1
                    if pnl > 0:
                        profile.winning_trades += 1
                        profile.total_profit_usd += pnl
                    else:
                        profile.total_loss_usd += abs(pnl)

                # Track current positions
                if market_id:
                    if side == "BUY":
                        current_positions[market_id] = current_positions.get(market_id, 0) + size
                    else:
                        current_positions[market_id] = current_positions.get(market_id, 0) - size

            # Detect position changes vs previous scan
            prev = self._prev_positions.get(address, {})
            new_signals = self._detect_position_changes(
                address=address,
                profile=profile,
                prev_positions=prev,
                current_positions=current_positions,
            )
            signals.extend(new_signals)

            # Update positions
            profile.positions = {k: v for k, v in current_positions.items() if abs(v) > 1e-8}
            self._prev_positions[address] = dict(current_positions)

        except Exception as exc:
            logger.debug(
                "Wallet scan error",
                address=address[:10] + "...",
                error=str(exc),
            )

        return signals

    def _detect_position_changes(
        self,
        address: str,
        profile: WhaleProfile,
        prev_positions: Dict[str, float],
        current_positions: Dict[str, float],
    ) -> List[WhaleSignal]:
        """Detect new entries and exits by comparing position snapshots.

        Args:
            address: Wallet address.
            profile: Whale profile.
            prev_positions: Previous position snapshot.
            current_positions: Current position snapshot.

        Returns:
            List of WhaleSignal objects.
        """
        signals = []
        all_markets = set(prev_positions.keys()) | set(current_positions.keys())

        for market_id in all_markets:
            prev_size = prev_positions.get(market_id, 0.0)
            curr_size = current_positions.get(market_id, 0.0)
            delta = curr_size - prev_size

            if abs(delta) < 1e-8:
                continue

            # Determine action
            if prev_size == 0 and abs(curr_size) > 1e-8:
                action = "enter"
            elif abs(curr_size) < 1e-8 and abs(prev_size) > 1e-8:
                action = "exit"
            else:
                # Position change (increase/decrease)
                action = "enter" if abs(curr_size) > abs(prev_size) else "exit"

            side = "BUY" if delta > 0 else "SELL"

            signal = WhaleSignal(
                whale_address=address,
                market_id=market_id,
                action=action,
                side=side,
                size=abs(delta),
                price=0.0,  # Price not available from position diff
                whale_win_rate=profile.win_rate,
                whale_profit_factor=profile.profit_factor,
            )

            signals.append(signal)

            # Put signal in queue for consumers
            try:
                self._signals.put_nowait(signal)
            except asyncio.QueueFull:
                # Drop oldest signal to make room
                try:
                    self._signals.get_nowait()
                    self._signals.put_nowait(signal)
                except asyncio.QueueEmpty:
                    pass

        return signals

    # ── Dynamic discovery ──────────────────────────────────────────────

    async def _discover_new_whales(self, signals: List[WhaleSignal]) -> None:
        """Discover new potential whales from market participants.

        When a qualified whale enters a market, look at other large
        traders in that market as potential new whales to track.

        Args:
            signals: Recently generated signals.
        """
        if len(self._whales) >= self.max_whales:
            return

        for signal in signals:
            if signal.action != "enter":
                continue

            try:
                # Fetch top traders for the market
                url = f"{self._polymarket_base_url}/markets/{signal.market_id}/leaderboard"
                async with self._session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()

                for trader in data.get("leaderboard", [])[:10]:
                    addr = trader.get("address", "")
                    if not addr or addr in self._whales:
                        continue

                    # Create candidate profile
                    if addr not in self._discovery_candidates:
                        self._discovery_candidates[addr] = WhaleProfile(
                            address=addr,
                            first_seen_at=time.monotonic(),
                        )

                    candidate = self._discovery_candidates[addr]
                    candidate.total_trades = int(trader.get("total_trades", 0))
                    candidate.winning_trades = int(trader.get("winning_trades", 0))
                    candidate.total_profit_usd = float(trader.get("profit_usd", 0))
                    candidate.total_loss_usd = float(trader.get("loss_usd", 0))

                    # Qualification check
                    if candidate.qualifies:
                        self._whales[addr] = candidate
                        del self._discovery_candidates[addr]
                        logger.info(
                            "New whale discovered",
                            address=addr[:10] + "...",
                            win_rate=f"{candidate.win_rate:.1%}",
                            profit_factor=f"{candidate.profit_factor:.2f}x",
                        )

                        if len(self._whales) >= self.max_whales:
                            return

            except Exception as exc:
                logger.debug("Discovery scan error", error=str(exc))

    # ── Signal consumption ─────────────────────────────────────────────

    def get_signal_queue(self) -> asyncio.Queue:
        """Get the signal queue for strategy consumption.

        Returns:
            asyncio.Queue containing WhaleSignal objects.
        """
        return self._signals

    async def get_recent_signals(self, max_age_sec: float = 60.0) -> List[WhaleSignal]:
        """Get recent signals from the queue.

        Args:
            max_age_sec: Maximum signal age in seconds.

        Returns:
            List of recent WhaleSignal objects.
        """
        signals = []
        while not self._signals.empty():
            try:
                signal = self._signals.get_nowait()
                if signal.age_sec < max_age_sec:
                    signals.append(signal)
            except asyncio.QueueEmpty:
                break
        return signals

    def on_signal(self, callback: Callable) -> None:
        """Register a callback for new whale signals.

        Args:
            callback: Async callable(WhaleSignal).
        """
        self._on_signal = callback

    # ── Queries ────────────────────────────────────────────────────────

    def get_qualified_whales(self) -> List[WhaleProfile]:
        """Get all whales that currently qualify as smart money.

        Returns:
            List of qualified WhaleProfile objects.
        """
        return [w for w in self._whales.values() if w.qualifies]

    def get_whale(self, address: str) -> Optional[WhaleProfile]:
        """Get a whale profile by address.

        Args:
            address: Wallet address.

        Returns:
            WhaleProfile or None.
        """
        return self._whales.get(address)

    def get_whale_positions(self, market_id: str) -> Dict[str, float]:
        """Get all whale positions for a specific market.

        Args:
            market_id: Market to check.

        Returns:
            Dict of whale_address -> position_size for the market.
        """
        result = {}
        for addr, profile in self._whales.items():
            if market_id in profile.positions and profile.qualifies:
                result[addr] = profile.positions[market_id]
        return result

    def get_aggregate_whale_direction(self, market_id: str) -> Optional[str]:
        """Get the aggregate whale direction for a market.

        Args:
            market_id: Market to check.

        Returns:
            "long" if net whale position is positive, "short" if negative, None if no positions.
        """
        positions = self.get_whale_positions(market_id)
        if not positions:
            return None

        net = sum(positions.values())
        if net > 0:
            return "long"
        elif net < 0:
            return "short"
        return None

    # ── Maintenance ────────────────────────────────────────────────────

    def _cleanup_stale_positions(self) -> None:
        """Remove stale positions from whale profiles."""
        now = time.monotonic()
        for profile in self._whales.values():
            stale = [
                mid for mid, size in profile.positions.items()
                if abs(size) < 1e-8
            ]
            for mid in stale:
                del profile.positions[mid]

    # ── State persistence ──────────────────────────────────────────────

    def _load_state(self) -> bool:
        """Load whale profiles from persisted state file.

        Returns:
            True if state was loaded successfully.
        """
        if not os.path.exists(WHALE_STATE_FILE):
            return False

        try:
            with open(WHALE_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            for addr, wdata in data.get("whales", {}).items():
                self._whales[addr] = WhaleProfile(
                    address=addr,
                    total_trades=wdata.get("total_trades", 0),
                    winning_trades=wdata.get("winning_trades", 0),
                    total_profit_usd=wdata.get("total_profit_usd", 0.0),
                    total_loss_usd=wdata.get("total_loss_usd", 0.0),
                    first_seen_at=wdata.get("first_seen_at", time.monotonic()),
                    last_active_at=wdata.get("last_active_at", time.monotonic()),
                )

            logger.info("Whale state loaded", whales=len(self._whales))
            return True

        except Exception as exc:
            logger.error("Failed to load whale state", error=str(exc))
            return False

    def _save_state(self) -> None:
        """Save whale profiles to disk."""
        try:
            os.makedirs(os.path.dirname(WHALE_STATE_FILE), exist_ok=True)

            data = {
                "whales": {
                    addr: {
                        "total_trades": w.total_trades,
                        "winning_trades": w.winning_trades,
                        "total_profit_usd": w.total_profit_usd,
                        "total_loss_usd": w.total_loss_usd,
                        "first_seen_at": w.first_seen_at,
                        "last_active_at": w.last_active_at,
                    }
                    for addr, w in self._whales.items()
                },
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }

            with open(WHALE_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            logger.debug("Whale state saved", whales=len(self._whales))

        except Exception as exc:
            logger.error("Failed to save whale state", error=str(exc))
