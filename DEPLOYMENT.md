# Deployment with FastAPI Cloud

Each branch deploys to its own FastAPI Cloud app and Supabase database:

| Git branch | GitHub environment | FastAPI Cloud app | Supabase secret |
| --- | --- | --- | --- |
| `dev` | `development` | development / preview API | `DEV_DATABASE_URL` |
| `main` | `production` | production API | `PROD_DATABASE_URL` |

The `Deploy FastAPI Cloud` workflow serializes deployments per branch. It runs `alembic upgrade head` before uploading the application, so code that adds database fields is only released after the matching schema exists.

## One-time FastAPI Cloud setup

1. Create one FastAPI Cloud app for `dev` and one for `main`.
2. In each app, add the runtime environment variables below. Mark sensitive values as secrets.
3. Create a deploy token for each app.
4. In GitHub, create `development` and `production` environments and add the corresponding secrets below. Environment-scoped names may be the same, but the values must target the matching app and database.

## Runtime environment variables in FastAPI Cloud

- `DATABASE_URL` (secret): Supabase connection string. A standard `postgresql://...` URL from the FastAPI Cloud Supabase integration is accepted; the application converts it to the asyncpg driver at runtime.
- `APP_ENV`: `development` or `production`.
- `CORS_ALLOWED_ORIGINS`: comma-separated allowed frontend origins, for example `https://transhub.example.com`.
- `DATA_REFRESH_SECRET` (secret): required when the data-refresh endpoint is introduced.

`PORT` is managed by FastAPI Cloud and must not be set. The app configuration is declared in `pyproject.toml`; FastAPI Cloud starts `app.main:app` directly, so its Dockerfile is not used in deployment.

## GitHub environment secrets

Set these in both GitHub environments, with values appropriate for that environment:

- `FASTAPI_CLOUD_TOKEN`: deploy token created for that FastAPI Cloud app.
- `FASTAPI_CLOUD_APP_ID`: UUID for that FastAPI Cloud app.
- `DEV_DATABASE_URL` in `development`, or `PROD_DATABASE_URL` in `production`: async SQLAlchemy URL used by Alembic, e.g. `postgresql+asyncpg://...`.

The FastAPI Cloud application itself needs only its own runtime `DATABASE_URL`; GitHub needs a database URL separately to run migrations before deployment. Never commit either URL or a deploy token.

## Deployment behavior

FastAPI Cloud can scale to zero when idle. There is intentionally no keep-alive workflow. The service must treat its filesystem and in-memory graph/cache as ephemeral; rebuild any future cache from Supabase.

For schema evolution, use gradual migrations: add database structures before code consumes them, and remove structures only after code no longer uses them.
