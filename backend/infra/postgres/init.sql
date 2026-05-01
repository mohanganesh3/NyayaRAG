-- NyayaRAG PostgreSQL Init
-- Extensions needed for full-text search and vector ops
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Performance settings for bulk ingestion
ALTER SYSTEM SET synchronous_commit = 'off';
ALTER SYSTEM SET checkpoint_timeout = '15min';
ALTER SYSTEM SET max_wal_size = '4GB';
SELECT pg_reload_conf();
