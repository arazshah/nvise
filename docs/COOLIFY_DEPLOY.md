# Nvise deployment on Coolify

This deployment uses `docker-compose.prod.yml` and does **not** publish any host ports.
Coolify's reverse proxy routes the public domain to the internal Gunicorn port `8000`.

## Coolify resource

- Source: GitHub repository `arazshah/nvise`
- Branch: `master`
- Build pack / deployment type: Docker Compose
- Compose file: `docker-compose.prod.yml`
- Public service: `web` only
- Domain for `web`: `https://nvise.ir:8000`
- Do not assign a domain to `worker`, `db`, or `redis`.
- Do not add host port mappings.

The `:8000` in the Coolify domain is the internal container routing port. Public traffic still uses normal HTTPS/443.

## DNS

Point the `A` record for `nvise.ir` to the public IPv4 address of the Coolify server.
Optionally point `www.nvise.ir` to the same server and add `https://www.nvise.ir:8000` as another domain in Coolify.

Coolify should provision TLS automatically once DNS resolves correctly.

## Required environment variables

Set these in Coolify Environment Variables / Developer View.

```env
DJANGO_SECRET_KEY=REPLACE_WITH_LONG_RANDOM_SECRET
DJANGO_ALLOWED_HOSTS=nvise.ir,www.nvise.ir
WEB_BASE_URL=https://nvise.ir

POSTGRES_DB=nvise
POSTGRES_USER=nvise
POSTGRES_PASSWORD=REPLACE_WITH_RANDOM_DATABASE_PASSWORD
DATABASE_URL=postgresql://nvise:REPLACE_WITH_SAME_DATABASE_PASSWORD@db:5432/nvise

REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

BALE_BOT_TOKEN=REPLACE_WITH_REAL_BALE_BOT_TOKEN
BALE_BOT_ID=primary
BALE_WEBHOOK_SECRET=REPLACE_WITH_LONG_RANDOM_WEBHOOK_SECRET

STT_PROVIDER=http
STT_HTTP_ENDPOINT=REPLACE_WITH_REAL_STT_ENDPOINT
STT_API_KEY=REPLACE_IF_PROVIDER_REQUIRES_IT
STT_TIMEOUT_SECONDS=120

AI_EXTRACTION_PROVIDER=http
AI_EXTRACTION_ENDPOINT=REPLACE_WITH_REAL_AI_EXTRACTION_ENDPOINT
AI_EXTRACTION_API_KEY=REPLACE_IF_PROVIDER_REQUIRES_IT
AI_EXTRACTION_TIMEOUT_SECONDS=120
```

Recommended optional values:

```env
REVIEW_LINK_TTL_MINUTES=15
BALE_WEBHOOK_RATE_LIMIT_PER_MINUTE=120
MAX_WEBHOOK_BODY_BYTES=1048576
MAX_PROVIDER_FILE_BYTES=20971520
CELERY_TASK_TIME_LIMIT=300
CELERY_TASK_SOFT_TIME_LIMIT=270
CELERY_WORKER_CONCURRENCY=2
GUNICORN_WORKERS=3
GUNICORN_THREADS=2
GUNICORN_TIMEOUT=120
```

`DJANGO_SETTINGS_MODULE`, `DJANGO_DEBUG`, and `PRIVATE_MEDIA_ROOT` are already set by the production Compose file and do not need to be entered in Coolify.

## Generate safe secrets

Use secrets without URL-reserved characters for the PostgreSQL password so `DATABASE_URL` does not need URL encoding.

```bash
openssl rand -hex 32   # POSTGRES_PASSWORD
openssl rand -hex 48   # DJANGO_SECRET_KEY
openssl rand -hex 32   # BALE_WEBHOOK_SECRET
```

Use the exact same generated PostgreSQL password in both `POSTGRES_PASSWORD` and `DATABASE_URL`.

## Persistent storage

The Compose stack defines named Docker volumes for:

- PostgreSQL data: `postgres_data`
- Redis persistence: `redis_data`
- private attachments and generated DOCX files: `private_media`

Do not remove these volumes during normal redeployments.

## Database migrations

Before switching production traffic to a new release, run:

```bash
python manage.py migrate --noinput
```

This can be configured as a Coolify pre-deployment command or executed in the `web` container after the first deployment.

## Pilot readiness check

After deployment, run inside the web container:

```bash
python manage.py pilot_readiness
```

It should exit successfully before starting the real fire-loss pilot.

## Health checks

Public liveness:

```text
https://nvise.ir/health/live/
```

Readiness (PostgreSQL + Redis):

```text
https://nvise.ir/health/ready/
```

The Docker healthcheck also uses the internal readiness endpoint.

## Bale webhook

After deployment and after `BALE_WEBHOOK_SECRET` is configured, the callback URL is:

```text
https://nvise.ir/webhooks/bale/<BALE_WEBHOOK_SECRET>/
```

Register that URL with Bale using the actual secret value. Never publish the webhook URL or secret in logs or documentation.

## Services that must remain private

Only `web` receives a Coolify domain.

These services must not receive domains or host port mappings:

- `db`
- `redis`
- `worker`

They communicate through the private Compose network using the service names `db` and `redis`.

## First production verification

1. Confirm `https://nvise.ir/health/live/` returns HTTP 200.
2. Confirm `https://nvise.ir/health/ready/` returns HTTP 200.
3. Run `python manage.py migrate --noinput`.
4. Run `python manage.py pilot_readiness`.
5. Create the first Django superuser if needed: `python manage.py createsuperuser`.
6. Open `https://nvise.ir/admin/`.
7. Register the Bale webhook.
8. Send `/start` to the Bale bot.
9. Run one controlled fire-loss test case before inviting pilot users.
