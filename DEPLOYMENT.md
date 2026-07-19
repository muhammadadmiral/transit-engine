# Deployment

Two branches map to two Hugging Face Docker Spaces:

| Git branch | GitHub environment | Secret holding the Space ID | Intended use |
| --- | --- | --- | --- |
| `dev` | `development` | `HF_DEV_SPACE` | integration and frontend preview |
| `main` | `production` | `HF_PROD_SPACE` | public production API |

Create both Spaces with **Docker** as their SDK. On every push, the deployment workflow first applies the matching Supabase Alembic migrations and then uploads the repository to its matching Space.

## Required GitHub secrets

- `HF_TOKEN`: Hugging Face write token with access to both Spaces.
- `HF_DEV_SPACE`: Space repository ID, for example `username/transit-engine-dev`.
- `HF_PROD_SPACE`: Space repository ID, for example `username/transit-engine`.
- `HF_PROD_SPACE_URL`: public production Space URL, used only by keep-alive.
- `DEV_DATABASE_URL`: async SQLAlchemy connection string for the development Supabase project.
- `PROD_DATABASE_URL`: async SQLAlchemy connection string for the production Supabase project.

## Required Hugging Face Space secrets

Set these independently in each Space's **Settings → Variables and secrets**:

- `DATABASE_URL`
- `DATA_REFRESH_SECRET`
- `CORS_ALLOWED_ORIGINS`
- `APP_ENV` (`development` or `production`)

`HF_TOKEN` is only needed by GitHub Actions. Do not add it to a Space or commit it to `.env`.

## Keep-alive and persistence

`.github/workflows/keep-alive.yml` requests production `GET /health` every 10 minutes. This keeps the endpoint warm and is intentionally lightweight: it never queries the database.

This service does **not** train a model. A sleeping or restarted Space only starts its Docker container again; it does not require retraining or a new deploy. Its in-memory graph/cache will be rebuilt from Supabase after startup, so transit data and route cache must never be stored only in the Space filesystem.

## Local CLI

Install the CLI into a local virtual environment:

```bash
python3.12 -m venv .venv
.venv/bin/pip install "huggingface_hub[cli]"
.venv/bin/huggingface-cli login
```

Copy `.env.development.example` to `.env` for local development. `.env.production.example` is a reference only; production values belong in Hugging Face secrets.

Supabase CLI setup and the database migration policy are documented in [SUPABASE.md](./SUPABASE.md).
