# NyayaRAG Conventions

## Naming

- Python modules: `snake_case`
- TypeScript files: `kebab-case` for route files, `PascalCase` for React component files
- Database IDs: canonical UUIDs in `*_id` fields
- Environment variables: `UPPER_SNAKE_CASE`
- API routes: lowercase, resource-oriented, `/api/...`
- SSE event types: uppercase enum-like strings such as `STEP_START`

## Source of truth

- PostgreSQL is the canonical data store.
- Qdrant and Neo4j are projections, not the source of truth.
- Citations must resolve to canonical `doc_id` values.

## Trust rules

- No raw LLM-generated citation strings.
- No overruled/reversed authority surfaced as current law.
- No unsupported claims shown as verified.

