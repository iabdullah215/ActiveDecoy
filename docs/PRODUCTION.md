# Production deployment

Deploy ActiveDecoy with TLS, hardened sessions, LDAP console login, and mandatory secrets validation.

## Prerequisites

- Docker Compose v2
- DNS or hosts entry for `CONSOLE_DOMAIN`
- Dedicated AD honey OU
- Rotated secrets (never use `.env.example` defaults)

## Quick production start

```bash
cp .env.production.example .env
# Edit ALL replace-with-* values and LDAP/AD settings

docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

- **HTTPS:** `https://<CONSOLE_DOMAIN>` (Caddy terminates TLS; automatic certs for public domains)
- **HTTP:** port 80 redirects to HTTPS when using a real domain
- **Local TLS testing:** set `CONSOLE_DOMAIN=localhost` (Caddy uses internal CA)

## What production mode enforces

When `APP_ENV=production`, startup **fails** unless:

| Requirement | Variable |
|-------------|----------|
| Strong session secret (≥32 chars) | `SESSION_SECRET` |
| Neo4j password set | `NEO4J_PASSWORD` |
| Agent ingest token (≥16 chars) | `AGENT_INGEST_TOKEN` |
| No default break-glass creds (if env auth on) | `ADMIN_USERNAME` / `ADMIN_PASSWORD` |
| Honey OU when AD provision enabled | `AD_HONEY_OU` |
| LDAP host when LDAP login enabled | `LDAP_HOST` |
| Debug off | `APP_DEBUG=false` |

Also sets by default:

- `ENFORCE_SECURE_DEFAULTS=true`
- `SESSION_HTTPS_ONLY=true`, `SESSION_SAME_SITE=strict`
- `CONSOLE_AUTH_MODE=ldap,env`
- `AD_HARDEN_ON_PROVISION=true` (disabled account + `userWorkstations` lock)

## Authentication

| Mode | Use |
|------|-----|
| `ldap` | Operators sign in with AD credentials (`user@CONSOLE_LDAP_DOMAIN`) |
| `env` | Break-glass local admin from `.env` |
| `ldap,env` | Both (recommended) |

## Honey account hardening

When `AD_HARDEN_ON_PROVISION=true`, provisioned honey users receive:

- `userAccountControl` = disabled
- `userWorkstations` = `AD_HONEY_WORKSTATIONS_LOCK` (non-existent host)

Apply the deny-logon GPO from the Policy page for defense in depth.

## Operations

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f app caddy
curl -k https://localhost/api/health
```

## Local production test (no Caddy)

For CI or dev validation of production guards without TLS:

```bash
export APP_ENV=production
export ENFORCE_SECURE_DEFAULTS=true
export SESSION_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
export AGENT_INGEST_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
export NEO4J_PASSWORD=prod-test-neo4j-pass
export ADMIN_USERNAME=prod-admin
export ADMIN_PASSWORD=prod-admin-pass-change-me
export CONSOLE_AUTH_MODE=env
export APP_DEBUG=false
python -c "from app.main import app; print(app.version)"
```

## Rollback

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
```

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) and [RUNBOOK.md](RUNBOOK.md).
