-- Run with: bq mk --dataset ${PROJECT}:groundswell
-- Then: bq query --use_legacy_sql=false < bigquery_schema.sql

CREATE TABLE IF NOT EXISTS `groundswell.products` (
    sku STRING NOT NULL,
    name STRING NOT NULL,
    category STRING,
    price FLOAT64,
    unit_cost FLOAT64,
    available_sizes ARRAY<STRING>,
    available_widths ARRAY<STRING>,
    total_stock INT64,
    description STRING,
    supplier_id STRING,
    embedding ARRAY<FLOAT64>
);

CREATE TABLE IF NOT EXISTS `groundswell.variants` (
    variant_id STRING NOT NULL,
    sku STRING NOT NULL,
    size STRING,
    width STRING,
    color STRING,
    stock_qty INT64,
    store_id STRING
);

CREATE TABLE IF NOT EXISTS `groundswell.stores` (
    store_id STRING NOT NULL,
    name STRING,
    location STRING,
    region STRING
);

CREATE TABLE IF NOT EXISTS `groundswell.sales` (
    sale_id STRING,
    sku STRING,
    variant_id STRING,
    store_id STRING,
    sale_date DATE,
    daily_units_sold INT64,
    revenue FLOAT64
);

CREATE TABLE IF NOT EXISTS `groundswell.social_signals` (
    post_id STRING,
    platform STRING,
    post_text STRING,
    sku STRING,
    engagement_score FLOAT64,
    posted_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS `groundswell.suppliers` (
    supplier_id STRING NOT NULL,
    name STRING,
    lead_time_days INT64,
    moq INT64,
    reliability_score FLOAT64
);

CREATE TABLE IF NOT EXISTS `groundswell.stockout_forecast` (
    sku STRING,
    horizon_days INT64,
    forecast_timestamp TIMESTAMP,
    forecast_value FLOAT64,
    prediction_interval_lower_bound FLOAT64,
    prediction_interval_upper_bound FLOAT64,
    computed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS `groundswell.fused_forecast` (
    sku STRING,
    baseline_units INT64,
    fused_units INT64,
    surge_multiplier FLOAT64,
    confidence FLOAT64,
    horizon_days INT64,
    computed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS `groundswell.agent_audit` (
    event_id STRING,
    ts TIMESTAMP,
    session_id STRING,
    agent STRING,
    tool STRING,
    input_hash STRING,
    output_summary STRING,
    decision STRING,
    confidence FLOAT64,
    latency_ms FLOAT64
);

-- Enterprise Knowledge Fabric: entity resolution audit trail
CREATE TABLE IF NOT EXISTS `groundswell.entity_resolutions` (
    resolution_id STRING,
    ts TIMESTAMP,
    session_id STRING,
    mention STRING,
    resolved_sku STRING,
    resolution_method STRING,  -- "alias" | "vector_search"
    confidence FLOAT64
);

-- Enterprise Context Fabric: context assembly telemetry
CREATE TABLE IF NOT EXISTS `groundswell.context_assembly_log` (
    log_id STRING,
    ts TIMESTAMP,
    session_id STRING,
    user_type STRING,
    layers_assembled ARRAY<STRING>,  -- ["session_history", "inventory", "signals", ...]
    latency_ms FLOAT64,
    signals_injected INT64,
    alerts_surfaced INT64
);
