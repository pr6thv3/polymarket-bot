-- Proposal-driven strategy platform control plane.
-- This schema is intentionally separate from the read-only research kernel and
-- does not enable live trading by itself.

CREATE TABLE IF NOT EXISTS venues (
    venue_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    venue_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS instruments (
    instrument_id UUID PRIMARY KEY,
    venue_id TEXT NOT NULL REFERENCES venues (venue_id),
    venue_market_id TEXT NOT NULL,
    venue_token_id TEXT,
    symbol TEXT,
    canonical_question TEXT NOT NULL,
    yes_predicate TEXT,
    resolution_source TEXT,
    payout_convention TEXT,
    cutoff_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS instruments_venue_market_token_idx
    ON instruments (venue_id, venue_market_id, COALESCE(venue_token_id, ''));

CREATE TABLE IF NOT EXISTS market_relations (
    relation_id UUID PRIMARY KEY,
    relation_type TEXT NOT NULL,
    canonical_question TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('candidate', 'approved', 'rejected', 'retired')),
    confidence NUMERIC(8, 6) NOT NULL DEFAULT 0,
    review_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    reviewer TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_relation_members (
    relation_id UUID NOT NULL REFERENCES market_relations (relation_id),
    instrument_id UUID NOT NULL REFERENCES instruments (instrument_id),
    role TEXT NOT NULL DEFAULT 'member',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (relation_id, instrument_id)
);

CREATE TABLE IF NOT EXISTS strategy_configs (
    strategy_name TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK (mode IN ('disabled', 'shadow', 'paper', 'canary')),
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    owner TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS strategy_health (
    strategy_name TEXT PRIMARY KEY REFERENCES strategy_configs (strategy_name),
    status TEXT NOT NULL,
    last_heartbeat_at TIMESTAMPTZ,
    last_error TEXT,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signal_proposals (
    proposal_id UUID PRIMARY KEY,
    strategy_name TEXT NOT NULL REFERENCES strategy_configs (strategy_name),
    proposal_type TEXT NOT NULL,
    side TEXT NOT NULL,
    relation_id UUID REFERENCES market_relations (relation_id),
    edge_bps NUMERIC(18, 8) NOT NULL,
    confidence NUMERIC(8, 6) NOT NULL,
    max_notional_usd NUMERIC(18, 6) NOT NULL,
    fresh_until TIMESTAMPTZ NOT NULL,
    mode TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_events (
    risk_event_id BIGSERIAL PRIMARY KEY,
    proposal_id UUID NOT NULL REFERENCES signal_proposals (proposal_id),
    decision TEXT NOT NULL,
    reason_codes TEXT[] NOT NULL DEFAULT '{}',
    resized_notional_usd NUMERIC(18, 6),
    execution_mode TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id UUID PRIMARY KEY,
    proposal_id UUID NOT NULL REFERENCES signal_proposals (proposal_id),
    venue_id TEXT NOT NULL REFERENCES venues (venue_id),
    instrument_id UUID NOT NULL REFERENCES instruments (instrument_id),
    client_order_id TEXT NOT NULL,
    side TEXT NOT NULL,
    price NUMERIC(18, 8) NOT NULL,
    quantity NUMERIC(18, 8) NOT NULL,
    execution_mode TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'intent_created',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (venue_id, client_order_id)
);

CREATE TABLE IF NOT EXISTS fills (
    fill_id UUID PRIMARY KEY,
    order_id UUID NOT NULL REFERENCES orders (order_id),
    venue_fill_id TEXT,
    price NUMERIC(18, 8) NOT NULL,
    quantity NUMERIC(18, 8) NOT NULL,
    fee_usd NUMERIC(18, 8) NOT NULL DEFAULT 0,
    filled_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS positions (
    position_id UUID PRIMARY KEY,
    venue_id TEXT NOT NULL REFERENCES venues (venue_id),
    instrument_id UUID NOT NULL REFERENCES instruments (instrument_id),
    quantity NUMERIC(18, 8) NOT NULL,
    avg_cost NUMERIC(18, 8) NOT NULL,
    realized_pnl_usd NUMERIC(18, 8) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (venue_id, instrument_id)
);

CREATE TABLE IF NOT EXISTS llm_runs (
    llm_run_id UUID PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    input_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    output_json JSONB NOT NULL,
    allowed_actions TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
