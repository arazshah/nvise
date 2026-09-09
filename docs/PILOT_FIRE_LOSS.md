# Nvise Fire-Loss Pilot Runbook

This runbook is the operational gate for the first insurance fire-loss pilot. It assumes a private pilot with a small set of trained loss adjusters before any broad production rollout.

## 1. Go-live prerequisites

- Production runs with `DJANGO_SETTINGS_MODULE=config.settings.prod`.
- `DJANGO_SECRET_KEY` and `BALE_WEBHOOK_SECRET` are long, random, unique secrets.
- HTTPS terminates at a trusted reverse proxy and `WEB_BASE_URL` uses HTTPS.
- PostgreSQL and Redis use persistent volumes and are not exposed publicly.
- `PRIVATE_MEDIA_ROOT` is persistent, private, and backed up.
- STT and AI extraction endpoints are configured with production credentials.
- Bale webhook is registered only after `/health/ready/` returns HTTP 200.
- At least one staff operator can access Django Admin and `/admin/saas/`.
- Free/Pro plan limits are reviewed; commercial prices remain an explicit business configuration.

## 2. Backup and recovery gate

Before pilot traffic:

```bash
bash scripts/backup.sh
```

Verify `SHA256SUMS`, then perform a restore drill in a non-production environment:

```bash
NVISE_RESTORE_CONFIRM=YES bash scripts/restore.sh ./backups/<timestamp>
python manage.py migrate --check
```

Do not declare the pilot production-ready until both the database and private-media restore have been demonstrated.

## 3. Monitoring and health

- `/health/live/` checks that the web process is serving requests.
- `/health/ready/` requires PostgreSQL and Redis to be reachable.
- Every HTTP response carries `X-Request-ID` for correlation.
- Application logs are JSON and include request/task identifiers where available.
- Terminal Celery failures appear in Django Admin under Task Failures and must be triaged.
- Audit Events are append-only through the product UI and must be reviewed for critical lifecycle changes.

Suggested pilot alerts:

- readiness is non-200 for more than 2 consecutive checks;
- any unresolved terminal Celery task failure;
- repeated webhook 429 responses;
- STT or AI failure rate above the agreed pilot threshold;
- private storage usage exceeds 80% of allocated capacity;
- backup job missing or checksum validation fails.

## 4. Pilot scope

Start with fire-loss claims only. Supported evidence for the first pilot:

- text;
- Bale voice/audio;
- images and documents stored as evidence;
- structured extracted fire-loss facts;
- intelligent follow-up questions;
- expert web review;
- approved DOCX report delivery.

Do not add a second insurance vertical until fire-loss field completeness, conflicts, report quality, and operator workflow have been measured.

## 5. Golden-path acceptance test

For each pilot release, complete at least one fresh case end-to-end:

1. Start the Bale bot and create a case.
2. Send text describing insured, policy, incident time/location, cause and damage.
3. Send at least one Persian voice message.
4. Upload one document or image.
5. Finish input.
6. Confirm STT completes and transcript evidence is created.
7. Confirm AI facts include provenance to evidence.
8. Answer all supplemental questions.
9. Confirm the case reaches `READY_FOR_REVIEW`.
10. Open the one-time web review link.
11. Edit one report section and confirm a new immutable revision is created.
12. Approve the report.
13. Confirm the case reaches `APPROVED`.
14. Confirm DOCX generation succeeds and the file can be downloaded.
15. Confirm the approved DOCX is delivered through Bale.
16. Confirm Usage Records exist for case, STT, AI and document generation.
17. Confirm Audit Events exist for case creation/status changes.

## 6. Negative-path acceptance tests

Exercise these scenarios before adding real pilot users:

- duplicate Bale `update_id`;
- invalid webhook secret;
- webhook rate-limit exceeded;
- oversized webhook body;
- oversized Bale file;
- Redis temporarily unavailable;
- PostgreSQL temporarily unavailable;
- Celery worker killed during a task;
- STT provider timeout;
- AI provider timeout or malformed structured response;
- exhausted tenant quota;
- expired/reused web review token;
- user from another tenant tries to open a case review URL;
- conflicting extracted facts;
- missing required fire-loss fields;
- DOCX generation or Bale document-delivery failure.

Expected behavior: no silent data loss, no cross-tenant access, no duplicate usage charge, no implicit reassignment to finalized cases, and failures are visible through state/log/admin records.

## 7. Pilot metrics

Track at minimum:

- cases started/completed/approved;
- median time from first evidence to `READY_FOR_REVIEW`;
- STT success rate and billed seconds;
- AI extraction success rate;
- required-field completion before vs. after follow-up;
- number of conflicts per case;
- number of follow-up questions per case;
- report revision count;
- operator approval rate without manual report edit;
- DOCX generation success rate;
- terminal task failures;
- average AI/STT usage per approved case.

## 8. Release and rollback

Before release:

```bash
python manage.py check --deploy --settings=config.settings.prod
python manage.py migrate --check
```

Deploy web and worker from the same image/commit. Apply migrations before enabling pilot traffic. Verify `/health/ready/`, then register/enable Bale webhook traffic.

Rollback application code only when the database schema remains backward compatible. For destructive or incompatible migrations, restore from a tested backup instead of attempting an unverified reverse migration in production.

## 9. Exit criteria for the pilot phase

The pilot can move to broader rollout only after:

- backup and restore drill succeeds;
- no unresolved critical security or cross-tenant defects;
- no unexplained data loss or duplicate processing;
- task failures are observable and operationally handled;
- adjusters can complete the golden path without engineering intervention;
- report quality and missing-field metrics meet the agreed business threshold;
- production resource and provider costs per approved case are understood.
