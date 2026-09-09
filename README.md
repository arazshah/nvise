# Nvise

Nvise is a bot-first, case-centric, profession-aware SaaS for turning conversational field inputs into structured, evidence-backed professional reports.

## Architecture principles

- Bot-first, web-assisted
- Case-centric domain model
- Provider-independent messaging layer
- Structured AI extraction before report generation
- Evidence-backed facts and reports
- Multi-tenant SaaS foundation

## MVP scope

The initial MVP targets insurance loss adjusters, starting with fire-loss assessment. The first supported channel is Bale.

## Local development

```bash
cp .env.example .env
docker compose up --build
```

The web application will be available at `http://localhost:8000` and the health endpoint at `http://localhost:8000/health/`.

## Roadmap

1. Foundation
2. Bale integration
3. Case engine
4. Attachments and async processing
5. Speech-to-text
6. Structured AI extraction
7. Report and DOCX generation
8. Web portal
9. Subscription/admin/security
10. Pilot and hardening
