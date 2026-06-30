"""Stable enum vocabulary for proposal-driven strategy services."""

from __future__ import annotations

from enum import StrEnum


class VenueId(StrEnum):
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"


class StrategyMode(StrEnum):
    DISABLED = "disabled"
    SHADOW = "shadow"
    PAPER = "paper"
    CANARY = "canary"


class ExecutionMode(StrEnum):
    PAPER = "paper"
    CANARY = "canary"


class ProposalType(StrEnum):
    CROSS_VENUE_ARB = "cross_venue_arb"
    BASKET_ARB = "basket_arb"
    AI_NEWS = "ai_news"
    WHALE_FLOW = "whale_flow"
    ORDERBOOK_IMBALANCE = "orderbook_imbalance"
    MARKET_MAKING = "market_making"
    REWARD_FARMING_SIM = "reward_farming_sim"


class ProposalSide(StrEnum):
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    SELL_YES = "sell_yes"
    SELL_NO = "sell_no"
    QUOTE_BOTH = "quote_both"
    BASKET_BUY = "basket_buy"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class RiskDecisionStatus(StrEnum):
    APPROVED = "approved"
    RESIZED = "resized"
    REJECTED = "rejected"
    SHADOW_ONLY = "shadow_only"
