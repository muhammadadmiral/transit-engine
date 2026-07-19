# Supabase CLI and database workflow

This service is the sole database owner. Supabase provides hosted PostgreSQL/PostGIS; the API connects through SQLAlchemy and `asyncpg` only.

## CLI setup

The CLI is project-scoped, so it is installed with the repository rather than globally:

```bash
npm install
npx supabase login
npx supabase link --project-ref <development-project-ref>
```

The CLI's local state is ignored. Run `link` separately when you switch between the `dev` and `main` branches, because each branch targets a different Supabase project.

## Migration authority

**Alembic is the only schema-migration authority in this repository.** Do not create a second, competing schema history in `supabase/migrations/` and do not run `supabase db push` for application tables.

Use the Supabase CLI for login, project inspection, local stack operations when needed, and direct project linking. Use these commands for schema changes:

```bash
alembic revision --autogenerate -m "describe_change"
alembic upgrade head
```

This preserves the architecture specified for `transit-engine` while still making Supabase operations available through the official CLI. Direct changes through the Supabase dashboard are prohibited after migrations begin; capture every schema change in Alembic first.

## Environments

Create separate Supabase projects for `dev` and `main`:

| Git branch | Supabase project | GitHub secret |
| --- | --- | --- |
| `dev` | development/staging | `DEV_DATABASE_URL` |
| `main` | production | `PROD_DATABASE_URL` |

The GitHub migration workflow uses the matching secret and runs Alembic after a successful push. Database URLs must use the async SQLAlchemy form in runtime (`postgresql+asyncpg://...`); the migration environment converts it to the synchronous PostgreSQL driver automatically.

