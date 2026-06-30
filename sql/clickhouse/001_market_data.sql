-- Append-only market-data and feature store sketches for future service split.
-- The current repository does not require ClickHouse to run tests or research demos.

CREATE TABLE IF NOT EXISTS md_orderbook_l2
(
    observed_at DateTime64(3, 'UTC'),
    received_at DateTime64(3, 'UTC'),
    venue_id LowCardinality(String),
    instrument_id String,
    source_contract_version String,
    bid_prices Array(Decimal64(8)),
    bid_sizes Array(Decimal64(8)),
    ask_prices Array(Decimal64(8)),
    ask_sizes Array(Decimal64(8)),
    raw_payload_hash String,
    pair_skew_ms Nullable(UInt32),
    quote_age_ms Nullable(UInt32),
    rejection_reason Nullable(String)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(observed_at)
ORDER BY (venue_id, instrument_id, observed_at);

CREATE TABLE IF NOT EXISTS md_trades
(
    traded_at DateTime64(3, 'UTC'),
    received_at DateTime64(3, 'UTC'),
    venue_id LowCardinality(String),
    instrument_id String,
    trade_id String,
    side LowCardinality(String),
    price Decimal64(8),
    quantity Decimal64(8),
    raw_payload_hash String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(traded_at)
ORDER BY (venue_id, instrument_id, traded_at, trade_id);

CREATE TABLE IF NOT EXISTS feature_vectors
(
    computed_at DateTime64(3, 'UTC'),
    strategy_name LowCardinality(String),
    relation_id Nullable(String),
    instrument_id Nullable(String),
    feature_version String,
    features_json String,
    source_manifest_hash String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(computed_at)
ORDER BY (strategy_name, computed_at);

CREATE TABLE IF NOT EXISTS pnl_snapshots
(
    snapshot_at DateTime64(3, 'UTC'),
    strategy_name LowCardinality(String),
    mode LowCardinality(String),
    capital_usd Decimal64(6),
    unrealized_pnl_usd Decimal64(6),
    realized_pnl_usd Decimal64(6),
    drawdown_usd Decimal64(6),
    exposure_json String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(snapshot_at)
ORDER BY (strategy_name, mode, snapshot_at);
