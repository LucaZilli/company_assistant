CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS query_cache (
    id SERIAL PRIMARY KEY,
    query_hash VARCHAR(64) NOT NULL,
    query_normalized TEXT NOT NULL,
    response TEXT NOT NULL,
    routing_action VARCHAR(50) NULL,
    agent_type VARCHAR(32) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    hit_count INTEGER DEFAULT 1,
    UNIQUE (query_hash, agent_type)
);

CREATE INDEX IF NOT EXISTS idx_query_hash_agent_type ON query_cache(query_hash, agent_type);
CREATE INDEX IF NOT EXISTS idx_agent_type ON query_cache(agent_type);
CREATE INDEX IF NOT EXISTS idx_last_used ON query_cache(last_used_at);
CREATE INDEX IF NOT EXISTS idx_created_at ON query_cache(created_at);
