# NyayaRAG

NyayaRAG monorepo bootstrap for the trust-first Indian legal research platform.

## Workspace

- `frontend/`: Next.js 14 App Router client
- `backend/`: FastAPI services
- `infrastructure/`: Docker Compose for local infra
- `data/`: local corpus, processed outputs, graphs, and benchmarks
- `docs/`: shared engineering conventions

## Quick start

```bash
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
pnpm bootstrap
pnpm infra:up
pnpm dev:backend
pnpm dev:frontend
```

## Quality commands

```bash
pnpm lint
pnpm typecheck
pnpm test
```

