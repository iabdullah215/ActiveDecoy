# ActiveDecoy — Technical Working Document

*Autonomous Identity Threat Detection & Response (ITDR) and Active Directory Deception Framework*

---

## 1. Introduction

ActiveDecoy is an automated **Identity Threat Detection and Response (ITDR)** framework that orchestrates and deploys believable Active Directory (AD) *honey-objects* — decoy users, servers, shadow domain controllers, and credential breadcrumbs — for the purpose of proactively detecting lateral movement and credential-based attacks inside an authorized lab network.

The core hypothesis of the system is straightforward: **any interaction with a decoy object is, by definition, a high-confidence signal of malicious or unauthorized activity.** Legitimate users and workflows have no reason to authenticate against, request tickets for, or read credentials from a honey-object. ActiveDecoy therefore plants such objects throughout a directory, then watches the domain controller's security telemetry (Kerberos and logon events) for any contact with them. When contact occurs, the framework correlates it against the deployed deception plan, raises a severity-graded alert, and offers the operator a matching response playbook.

This document describes the complete technical working of the system: its architecture, every module, the data it stores, the APIs it exposes, its security model, and its deployment and testing story.

> **Scope and authorization.** ActiveDecoy is intended strictly for educational, defensive, and explicitly authorized security testing. It is designed to operate against directories the operator owns or manages. All write operations against Active Directory are gated behind explicit feature flags, policy checks, and a dedicated, isolated organizational unit (OU).

---

## 2. System Overview

At the highest level, ActiveDecoy is a **single-process FastAPI web application** with a server-rendered operator console, complemented by a small, standalone **telemetry-forwarding agent** (the *Washu Agent*) that runs on or near the monitored domain controller.

The system is organized around six functional pillars, each surfaced as a page in the console and backed by a set of engines and API routers:

| Pillar | Purpose |
|--------|---------|
| **Connection** | Detect the host, validate LDAP reachability, prepare a hypervisor bridge, and enumerate the real directory. |
| **Visualization** | Render the combined AD + honey topology as an interactive graph backed by Neo4j. |
| **Deception** | Plan honey-objects, generate graph payloads, and optionally provision them into a dedicated AD honey OU. |
| **Monitoring** | Collect authentication/Kerberos events, correlate them against the deployment, and stream live alerts. |
| **Policy / ITDR** | Enforce honey-OU and naming policy, produce deny-logon artifacts, and export alerts as evidence. |
| **Agents** | Register the Washu Agent, track heartbeats, and receive bulk telemetry ingest. |

### 2.1 Operational lifecycle

The intended operator workflow follows a linear "deploy → exercise → tear down" corridor:

1. **Authenticate** to the console (session cookie).
2. **Configure and validate** an LDAP profile (and optionally a hypervisor bridge) on the Connection page.
3. **Import** the real directory topology into Neo4j for context.
4. **Plan and deploy** a deception plan; optionally provision honey-objects into the isolated AD honey OU.
5. **Exercise** the detection pipeline, either by an actual red-team action, the built-in lab simulator, or the Washu Agent forwarding real security events.
6. **Triage** the resulting alerts, apply the recommended playbook, and export the evidence bundle.
7. **Tear down** the provisioned objects, returning the directory to its original state.

---

## 3. Architecture

### 3.1 Component topology

```
┌──────────────────────────┐
│   Operator browser       │
│   Jinja2 pages + app.js  │
└───────────┬──────────────┘
            │  session cookie (HTTPS)
┌───────────▼──────────────────────────────────────────────┐
│  ActiveDecoy console  (FastAPI, single process)           │
│                                                           │
│  Session auth + rate limit + security headers + audit     │
│  ┌──────────┬──────────┬──────────┬──────────┬─────────┐  │
│  │Connection│Deception │Monitoring│ Policy   │ Graph   │  │
│  │ engine   │ engine   │ engine   │ engine   │ store   │  │
│  └────┬─────┴────┬─────┴────┬─────┴────┬─────┴────┬────┘  │
│       │          │          │          │          │       │
│   Agent registry │          │      Playbooks   Secret     │
│                  │          │                  store       │
└───────┬──────────┼──────────┼──────────────────┼──────────┘
        │          │          │                  │
   ┌────▼───┐  ┌───▼────┐  ┌──▼──────┐      (process-local,
   │Active  │  │ Neo4j  │  │ Washu   │       never persisted)
   │Directory│ │ graph  │  │ Agent VM│
   │  (LDAP) │ │  DB    │  └──┬──────┘
   └────────┘  └────────┘     │ ingest + heartbeat
        ▲                     │
        └── DC Security log ──┘  (4768 / 4769 / 4624 / 4625)
```

### 3.2 Design principles

- **Single deployable unit.** The console is one FastAPI process. Neo4j is optional; when absent, the system degrades gracefully to a "preview" planning mode rather than failing.
- **Server-side rendering.** The UI is built with Jinja2 templates and a single custom CSS shell plus one vanilla-JavaScript file (`app.js`, ~800 lines). There is no frontend build step or SPA framework.
- **Engines are pure and testable.** Each domain engine (`DeceptionEngine`, `MonitoringEngine`, `PolicyEngine`, etc.) is a plain Python class with deterministic behavior (seeded RNG where randomness is used) and no direct dependence on the web layer. The API routers and `app/main.py` wire them to HTTP.
- **Service-layer orchestration.** Multi-step workflows (deploy, teardown, connection test, directory import) are factored into `*_service.py` modules so that routers stay thin and the orchestration is unit-testable in isolation.
- **Secrets never touch the cookie.** The signed session cookie carries only non-secret metadata; LDAP and hypervisor passwords live in a process-local secret vault keyed by an opaque session id.
- **Fail safe, not open.** AD writes require an explicit feature flag, a configured isolated OU, a passing policy gate, and a naming prefix. Teardown refuses to delete anything outside the honey OU.

### 3.3 Technology stack

| Layer | Technology |
|-------|-----------|
| Web framework | FastAPI (ASGI), served by Uvicorn |
| Templating | Jinja2, server-rendered HTML |
| Sessions | Starlette `SessionMiddleware` (signed cookie via `itsdangerous`) |
| Directory access | `ldap3` (pure-Python LDAP client) |
| Graph database | Neo4j (`neo4j` Python driver, Bolt protocol) |
| Hypervisor bridges | `pyvmomi` (VMware), VirtualBox SDK, UTM wrapper (all optional) |
| Windows telemetry | `pywin32` on the agent host (optional) |
| Email | `smtplib` (standard library) for password-reset delivery |
| Packaging / deploy | Docker, Docker Compose, Caddy reverse proxy |
| Testing | Python `unittest`, ~124 unit/integration/E2E tests |

---

## 4. Repository Layout

```
ActiveDecoy/
├── app/
│   ├── main.py                 # App factory, pages, deception deploy routes
│   ├── api/                    # REST routers
│   │   ├── connection.py       #   LDAP profile, bridge test, enumeration
│   │   ├── graph.py            #   Neo4j nodes/topology, sync, sample import
│   │   ├── monitoring.py       #   Event feed, ingest, SSE, simulate, triage
│   │   ├── agents.py           #   Washu Agent heartbeat + registry
│   │   └── policy.py           #   ITDR status, playbooks, alert export
│   ├── core/                   # Domain engines, config, persistence
│   ├── middleware/security.py  # Security response headers
│   ├── templates/              # Jinja2 pages
│   └── static/                 # CSS, JS, logo
├── washu_agent/                # Standalone telemetry forwarder (CLI package)
├── data/                       # Sample graph, user guide, runtime JSON stores
├── scripts/                    # bootstrap, run, demo, sample ingest/import
├── tests/                      # unit / mocked-integration / E2E suites
├── deploy/                     # Caddyfile, CI workflow
├── docs/                       # ARCHITECTURE, API, RUNBOOK, etc.
├── Dockerfile, docker-compose*.yml
├── main.py                     # Root launcher (port auto-selection)
└── requirements.txt
```

The `app/core/` package is the heart of the system. It contains the configuration loader, all domain engines, the persistence stores, and the security primitives. The `app/api/` routers are thin adapters that translate HTTP requests into engine calls and back.

---

## 5. Application Bootstrap and Lifecycle

### 5.1 Launchers

Two entrypoints exist:

- **`main.py`** (repository root) is the developer-friendly launcher. It parses `--host`, `--port`, `--reload`, and `--strict-port` arguments and, crucially, performs **automatic port selection**: if the requested port is occupied, it probes the next 100 ports and binds to the first free one (unless `--strict-port` is given). It then starts `app.main:app` under Uvicorn.
- **`app/main.py`** is the FastAPI application module itself. In containers it is served directly by `uvicorn app.main:app --proxy-headers`.

### 5.2 Application factory and singletons

On import, `app/main.py` constructs the shared, process-wide singletons that hold engine state:

- `connection_manager` — host detection and LDAP/hypervisor validation.
- `deception_engine` — seeded honey-object planner (`seed=42` for reproducibility).
- `graph_store` — Neo4j wrapper.
- `monitoring_engine` — event feed, seeded and backed by `data/monitoring_events.json`.
- `agent_registry` — Washu heartbeats, backed by `data/agents.json`.
- `deployment_history` — deployment records, backed by `data/deployments.json`.
- Two `SlidingWindowRateLimiter` instances (login and forgot-password).

The routers are then built via factory functions (`build_*_router(...)`) that receive the engines and the shared `_require_auth_api` dependency by injection. This keeps the routers decoupled and testable.

### 5.3 Startup guards and lifespan

The FastAPI `lifespan` context manager runs `enforce_startup_guards(settings)` and `log_settings_summary(settings)` at boot:

- **`enforce_startup_guards`** aborts the process (`SystemExit`) when hardening is required but defaults remain. Under `ENFORCE_SECURE_DEFAULTS=true` it blocks default admin credentials or a default session secret. It also invokes **`enforce_production_guards`**, which — when `APP_ENV=production` — refuses to start unless: debug is off, the session secret is ≥ 32 chars, a Neo4j password is set, the agent ingest token is present and ≥ 16 chars, non-default admin credentials are used, an isolated honey OU is configured if AD provisioning is on, and an LDAP host exists if LDAP console auth is enabled.
- **`log_settings_summary`** emits a redacted startup banner and a list of non-fatal configuration warnings (default secrets, unconfigured Neo4j, empty ingest token, and so on).

At shutdown, the lifespan closes the Neo4j driver cleanly.

### 5.4 Middleware stack

Middleware is layered (outermost first):

1. **`ProxyHeadersMiddleware`** — trusts `X-Forwarded-*` only from configured proxy hosts (enabled when `TRUSTED_PROXY_HOSTS` is set).
2. **`SecurityHeadersMiddleware`** — sets `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, `X-Permitted-Cross-Domain-Policies: none`, and — over HTTPS — HSTS.
3. **`SessionMiddleware`** — signed cookie sessions, with `same_site`, `https_only`, and `max_age` driven by environment (stricter defaults in production).
4. **`CORSMiddleware`** — origin allowlist from `CORS_ORIGINS`; credentials allowed; methods limited to GET/POST/OPTIONS.

Static assets are mounted at `/static`; templates are served through a shared `_render()` helper that always injects the navigation, current bridge state, and connection checklist into the page context.

---

## 6. Configuration Subsystem

Configuration is centralized in `app/core/config.py`, which loads a project-root `.env` (via `python-dotenv`, with `override=True` so a local file wins over stale shell exports) and exposes an immutable, frozen `Settings` dataclass built by `get_settings()`.

Key characteristics:

- **Environment-derived defaults.** Many defaults switch based on `APP_ENV`. For example, session cookies become `https_only` and `same_site=strict` in production, the session lifetime drops from 7 days to 8 hours, and `ENFORCE_SECURE_DEFAULTS` defaults on.
- **Typed accessors.** Helpers `_env`, `_env_bool`, `parse_cors_origins`, and `parse_trusted_proxies` normalize raw environment strings into typed values.
- **Derived properties.** `is_production`, `neo4j_configured`, `using_default_session_secret`, and `using_default_admin_credentials` centralize policy decisions.
- **Validation vs. enforcement.** `validate_settings()` returns *non-fatal warnings* for operator visibility, while `enforce_startup_guards()` raises *fatal* errors that stop boot.
- **Test bootstrapping.** When run under `unittest`, `_bootstrap_unittest_env()` injects a known-safe lab configuration so the suite is deterministic and independent of the developer's `.env` (unless `TEST_USE_ENV=1`).

The `Settings` object carries every tunable in the system — admin credentials, session, Neo4j, LDAP, hypervisor, rate limits, agent token/staleness, AD provisioning policy, SMTP, and password-reset TTL — giving a single source of truth consumed by every engine.

---

## 7. Authentication and Security Model

### 7.1 Console authentication

`app/core/console_auth.py` implements a pluggable, multi-backend login controlled by `CONSOLE_AUTH_MODE` (a comma-separated list such as `env` or `ldap,env`):

- **`env` mode** compares the submitted username against `ADMIN_USERNAME` using a constant-time comparison (`secrets.compare_digest`) and verifies the password via `verify_env_admin_password`.
- **`ldap` mode** attempts a real LDAP bind against the configured directory. It builds candidate principals from the username (`user@domain` UPN form, then bare user) and treats a successful bind as authentication. The resolved actor is the short username.

Modes are tried in order; the first success wins, and the result carries which `method` succeeded.

### 7.2 Break-glass admin password store

`app/core/console_credentials.py` provides an optional on-disk password override so the admin password can be rotated (e.g., via the reset flow) without editing `.env`:

- Passwords are hashed with **PBKDF2-HMAC-SHA256, 260,000 iterations**, and a 16-byte random salt, stored as JSON at `data/admin_password.json` with `0o600` permissions.
- `verify_env_admin_password` prefers the on-disk hash when present, otherwise falls back to the constant-time comparison against `ADMIN_PASSWORD`.
- `validate_new_password` enforces a 12-character minimum and forbids reusing the current password.

### 7.3 Password reset (forgot-password)

`app/core/password_reset.py` implements a signed, time-limited token flow:

- Tokens are `itsdangerous.URLSafeTimedSerializer` payloads keyed to the session secret with a dedicated salt, encoding the requester's email, and expiring after `PASSWORD_RESET_TTL_SECONDS` (default 1 hour).
- A reset is only issued when the requesting email matches the configured `ADMIN_EMAIL` — but the UI always returns the same neutral "if an account exists…" message to avoid account enumeration.
- Delivery goes through `app/core/mailer.py`, which sends via `smtplib` (STARTTLS optional). In development, `SMTP_DEV_LOG=true` logs the email (including the reset link) instead of sending, so the flow can be exercised without a mail server.
- Completion validates the token, re-checks the email, validates the new password, and writes the new PBKDF2 hash via `set_admin_password`.

### 7.4 Rate limiting

`app/core/rate_limit.py` is a thread-safe **sliding-window limiter** keyed by an arbitrary string (the client IP). It maintains a per-key `deque` of monotonic timestamps, prunes entries older than the window, and reports `retry_after` when the cap is reached. Two instances protect the login and forgot-password endpoints (`LOGIN_RATE_LIMIT` attempts per `LOGIN_RATE_WINDOW_SECONDS`). On a successful login the limiter is reset for that IP; on a rate-limited request the endpoint returns HTTP 429 with a `Retry-After` header.

### 7.5 Session and secret separation

This is a deliberate and important security control, implemented across `connection_profile.py` and `secret_store.py`:

- The **signed session cookie** stores only non-secret data: authentication flag, username, auth method, redacted bridge state, connection-profile metadata, and the last deployment summary.
- **Passwords are never written to the cookie.** Instead, `save_session_profile` stashes LDAP/hypervisor passwords in a **process-local `SecretStore`** keyed by an opaque, random `connection_secret_id` that *is* stored in the cookie. On load, `load_session_profile` re-hydrates the passwords from the vault into the in-memory profile.
- **Legacy migration.** If an older session cookie is found still carrying a password, it is transparently moved into the vault and stripped from the cookie.
- **Redaction on the wire.** `redact_bridge_state` and `bridge_state_to_dict` replace any password with an empty string plus a boolean `password_set` marker before serialization or API return.
- On logout, `clear_session_secrets` purges the vault entry and clears the session.

### 7.6 Audit logging

`app/core/audit.py` emits structured, single-line JSON audit records to the dedicated `activedecoy.audit` logger. Every sensitive action — login (success/failure/rate-limited), logout, connection save/test, directory enumeration, deception deploy/teardown, graph sync/import, monitoring simulate/acknowledge/ingest, agent heartbeat, and password-reset request/complete — produces an audit line containing a UTC timestamp, action, actor, outcome, client IP, request path, and action-specific details. Secrets are never included. `client_ip` prefers the `X-Forwarded-For` header (first hop) when present, else the direct peer.

---

## 8. Connection Subsystem

The Connection subsystem establishes and validates the "bridge" between the console and the authorized lab.

### 8.1 Host detection

`ConnectionManager` (in `connection_manager.py`) detects the host environment at startup via `platform`/`socket`, recording OS name, release, hostname, and whether the host is Windows or Windows Server. This drives `detect_connection_mode()`, which returns either a `windows_server_local_bridge` (when running directly on a DC-class host) or a `hypervisor_bridge` (the more common lab case, where the DC is a guest VM).

### 8.2 LDAP validation

`validate_ldap_connection` performs a lightweight, defensive probe:

1. It dynamically imports `ldap3` (returning a helpful message if the library is absent).
2. It creates a `Server` object and binds with the supplied credentials (`auto_bind=True`, bounded `receive_timeout`).
3. It either runs a scoped subtree probe against the configured base DN (size-limited to 1 entry) or a **root DSE** query for naming-context discovery.
4. It returns a structured result with `success`, a human message, a server summary, and a `debug` trail of every step.

`validate_ldap_connection_with_retry` wraps this with a bounded retry loop (`CONNECTION_RETRIES`, `CONNECTION_RETRY_DELAY`) to absorb transient network or directory delays, annotating each attempt in the debug trail.

### 8.3 Hypervisor bridge

The manager can validate a hypervisor session for labs where the DC runs as a guest. Three families are supported, each degrading gracefully if its SDK is not installed:

- **VMware** via `pyvmomi` (`SmartConnectNoSSL` + `RetrieveContent`).
- **VirtualBox** via its Python bindings (`vboxapi`).
- **UTM** via a trusted local `wrapper_command --health-check` subprocess.

### 8.4 Connection profiles and the checklist

`connection_profile.py` defines the `ConnectionProfile` dataclass, the canonical representation of a lab bridge configuration (LDAP host/port/SSL/bind DN/base DN + hypervisor type/endpoint/credentials/VM name/wrapper). It offers:

- Construction from `Settings` (`from_settings`) or from a session mapping (`from_mapping`, which strips any legacy passwords).
- `merge_secrets` — when a form submits an empty password field, the previously stored password is retained.
- Converters to `LDAPConfig` and `HypervisorConfig`, and `to_public_dict`/`to_session_dict` that redact secrets.

`connection_service.py` orchestrates a full test: it validates LDAP (with retries) and the hypervisor, then computes an overall **bridge status** via `compute_bridge_status` — `not_connected`, `failed`, `degraded` (LDAP OK but hypervisor failing), or `connected` — and assembles a three-part **checklist** (LDAP / hypervisor / bridge) that the UI renders.

### 8.5 Directory enumeration

`directory_enumerator.py` reads the *real* directory over LDAP (read-only) so it can be visualized and used as attack-surface context. It:

- Enumerates **users, groups, computers, and trusts** with tailored LDAP filters and attribute lists.
- Uses **paged searches** (`paged_size` up to `LDAP_PAGE_SIZE`, capped at `LDAP_MAX_OBJECTS` per category via the `1.2.840.113556.1.4.319` paging control), marking results `truncated` when the cap is hit.
- Derives **memberships** from both the `memberOf` (user side) and `member` (group side) attributes, then de-duplicates them.
- Decodes bit-flag attributes: account enabled/disabled from `userAccountControl` (the `0x2 ACCOUNTDISABLE` bit) and trust direction codes (inbound/outbound/bidirectional).
- Discovers the base DN from the root DSE when one is not explicitly configured.

The result is a typed `DirectorySnapshot` with a compact `summary()`. `directory_service.py` then optionally imports the snapshot into Neo4j (see §9), returning counts and a human summary. The router keeps only a compact summary and a 25-row preview per category in the session to bound cookie size.

---

## 9. Graph Subsystem (Neo4j)

### 9.1 GraphStore

`graph_store.py` is a thin, lazily-initialized wrapper over the official Neo4j driver. Neo4j is treated as optional infrastructure: `health()` reports `configured` (credentials present) and `connected` (reachable) independently, and every consumer checks these before use.

The store defines the graph schema through two label groups:

- **Honey labels:** `HoneyUser`, `HoneyServer`, `HoneyDC`, `Breadcrumb`.
- **AD labels:** `ADUser`, `ADGroup`, `ADComputer`, `ADTrust`, `ADDomain`.

`health()` returns node counts split by honey vs. AD, which feed the dashboard tiles.

### 9.2 Topology import

`sync_directory_snapshot` upserts an enumerated `DirectorySnapshot` into Neo4j using idempotent `MERGE` statements:

- Optionally **replaces** the existing AD subgraph (`DETACH DELETE` of all AD-labelled nodes) so re-imports are clean.
- Creates an `ADDomain` anchor node, then merges users, groups, computers, and trusts, each linked `IN_DOMAIN` to the domain.
- Establishes `MEMBER_OF` relationships from memberships (only when both endpoints exist) and `TRUSTS` relationships (carrying direction) for trust objects.
- Colors nodes for the canvas (`slate` for AD, `amber` for trusts).

### 9.3 Fetching nodes and topology

`fetch_nodes` and `fetch_topology` read back nodes and relationships for the visualization. The read queries use `coalesce` to project a uniform node shape (`id`, `object_type`, `name`, `role`, `color`, `dn`, `enabled`) regardless of the underlying label, and `fetch_topology` returns edges restricted to the set of returned nodes so the canvas never references a missing endpoint. Honey Cypher is executed via `execute_queries`/`import_cypher_file`, which split on statements and report per-statement errors.

### 9.4 Visualization filtering

`graph_view.py` contains the pure filtering logic shared by the graph API and the server-rendered page. `topology_payload` applies scope (`all`/`honey`/`ad`), free-text query (name or type), role substring, active-only, and honey-only filters, guarantees every node has a stable id, prunes edges to surviving nodes, and computes summary counts. This separation means the exact same filtering is used whether data comes from Neo4j or from the preview generator.

### 9.5 Preview (Neo4j-less) mode

When Neo4j is not connected, the graph router synthesizes a small preview topology from the last deployment (or a fresh sample plan) so the visualization and deception pages remain functional for planning and demos. Every graph API response is tagged with its `source`: `neo4j`, `preview`, or `error`.

---

## 10. Deception Engine

The deception subsystem is the framework's raison d'être: it plans decoy objects, expresses them as graph payloads, and — when authorized — writes them into Active Directory.

### 10.1 Honey-object model and planning

`deception_engine.py` defines a `HoneyObject` (type, name, role, color, notes, attributes) and a `DeceptionEngine` that builds a plan from selected modules. The engine uses a **seeded RNG** for reproducible names. Four module types are supported:

| Module | Object type | Purpose | Notes |
|--------|-------------|---------|-------|
| `honey_users` | `HoneyUser` | Privilege-bait accounts | Generated as `first.last`, marked inactive, tagged for deny-logon. |
| `honey_servers` | `HoneyServer` | Kerberoasting bait | Carry fake SPNs (`HTTP/…`, `MSSQLSvc/…:1433`). |
| `honey_dc` | `HoneyDC` | Shadow domain controller | Advertises a DC persona without real replication. |
| `breadcrumbs` | `Breadcrumb` | Decoy credentials/registry markers | Randomized artifact type (registry key / flat file / share marker). |

`to_cypher` serializes each object into an idempotent `MERGE … SET n += {…}` statement, with a `_cypher_value` helper that safely escapes strings, renders booleans/numbers/lists, and prevents injection into the generated Cypher.

### 10.2 Deployment orchestration

`deception_service.py` is the conductor for `run_deception_deploy`, which executes the full pipeline:

1. **Build** the plan from the selected modules.
2. **Stamp names** with the safety prefix (`stamp_provision_names`), recording both original and provisioned names.
3. **Regenerate Cypher** for the stamped objects.
4. **Evaluate policy** (`PolicyEngine.evaluate`) and attach the report.
5. If AD provisioning is requested, run the **policy gate** (`gate_provision`). A failing gate short-circuits into a `plan_only` record with a clear reason — no directory writes occur.
6. **Provision** honey users and bait computers into AD (or record a skip when provisioning is off).
7. **Register** the plan with the monitoring engine so future events can be correlated.
8. Optionally **sync** the Cypher into Neo4j.
9. **Record** a `DeploymentRecord` in the on-disk history, with a computed status of `active`, `plan_only`, or `torn_down`.

`run_deception_teardown` reverses a prior deployment by id, and `run_preflight` runs the AD honey-OU checks without writing anything.

### 10.3 Active Directory provisioner

`ad_provisioner.py` is the LDAP *write* path, and it is deliberately conservative:

- **Preflight (`preflight`).** Before any write, it binds, discovers/validates the base DN, confirms the honey OU is *under* the base DN, and confirms the honey OU actually exists. Any failure aborts with a specific message and a `checks` map (bind OK, OU configured, OU exists, under base DN).
- **Naming safety (`_ensure_prefix`).** Provisionable object names are sanitized to a safe character set and forced to carry the configured prefix (default `hw_`), making decoys identifiable and preventing collisions with production objects.
- **Honey users.** Created as disabled accounts — `userAccountControl` = `NORMAL_ACCOUNT | ACCOUNTDISABLE` (`0x0202`) — tagged with a descriptive `description`, given a UPN under the derived domain, and optionally hardened with a `userWorkstations` lock to a non-existent host. A long random password is set best-effort (disabled bait accounts never log on interactively). Existing objects are refreshed rather than duplicated.
- **Bait computers.** Created as disabled computer accounts (`WORKSTATION_TRUST_ACCOUNT | ACCOUNTDISABLE`, `0x1002`) carrying the monitored SPNs, so a Kerberoasting attempt against them produces a clean 4769 signal.
- **Non-provisionable modules.** Shadow DCs and breadcrumbs remain plan/graph-only; the provisioner explicitly skips them.
- **Dry run.** Every write path has a dry-run branch that reports the intended action (`would_create`, `would_delete`) without touching the directory.
- **Safe teardown (`teardown_objects`).** Deletion is guarded by `_is_safe_dn`, which refuses to delete any object whose DN is not inside the honey OU *and* does not carry the required prefix. This is the last line of defense against an accidental or malicious teardown targeting real objects.

`new_deployment_id()` mints a timestamped, random deployment id (`dep-<UTC>-<hex>`) used throughout history and teardown.

### 10.4 Deployment history

`deployment_history.py` provides a thread-safe, JSON-backed store (`data/deployments.json`, capped at 100 records) of `DeploymentRecord`s. Records capture the modules, stamped objects, provisioned objects (with DNs, for teardown), sync/provision flags, dry-run flag, status, and notes — but never passwords. It supports listing, lookup by id, insert, and `mark_torn_down`. Writes are atomic (temp file + `replace`).

---

## 11. Monitoring Subsystem

The monitoring subsystem is where detection actually happens. It maintains a rolling event feed, correlates events against the deployed deception plan, streams alerts live, and supports triage and export.

### 11.1 Event model and severities

`monitoring_engine.py` defines a `MonitoringEvent` dataclass and focuses on four Windows security Event IDs central to identity attacks:

| Event ID | Meaning | Typical relevance |
|----------|---------|-------------------|
| **4768** | Kerberos TGT requested | AS-REP / initial Kerberos auth against an identity. |
| **4769** | Kerberos service ticket requested | Kerberoasting / SPN targeting. |
| **4625** | Failed logon | Password spray / stuffing. |
| **4624** | Successful logon | Credential use — critical when it involves bait creds. |

Severities are ordered `critical`, `high`, `medium`, `info`. The engine is thread-safe (a single lock guards the event list, honey registry, and subscriber list) and bounds the feed to `MAX_EVENTS = 500`.

### 11.2 Baseline seeding and persistence

On first run (no persisted state), the engine seeds a small set of realistic **baseline** events — routine logons, standard TGT issuance, a benign failed logon — so the console is never empty and operators can see the difference between ambient noise and a real honey trigger. State is persisted to `data/monitoring_events.json` via `MonitoringStore` (atomic JSON writes) and restored on startup, including the UID counter and honey registry.

### 11.3 Honey-object registration and correlation

When a deception plan is deployed, `register_deployment` records the (cleaned) honey-object list. The correlation core, `_correlate`, then inspects every incoming event: if the event's target or actor matches a honey object's name (or one of its SPNs), the event is flagged with the honey object, its type, and an **elevated severity**:

- `HoneyUser`, `HoneyServer`, `HoneyDC` matches → **critical**.
- Breadcrumb matches → **critical** on success (4624), **high** on a failed attempt.

The correlation is substring- and SPN-aware, so a service-ticket request naming a bait SPN is caught even when the raw target is the SPN string rather than the object name.

### 11.4 Ingest, simulation, and record

Three ways to feed events exist:

- **`record_event`** — the single-event path, with optional auto-correlation.
- **`ingest_events`** — the bulk path used by the ingest API. It validates each item (event id, actor, target), coerces severity/source/timestamp, marks events `ingested`, records the forwarding agent id, and returns an accepted count plus per-item errors.
- **`simulate_honey_interaction`** — the lab exerciser. It requires at least one registered honey object, picks a random attacker host, and synthesizes plausible interaction events tailored to each object type (e.g., a TGT or failed logon for a honey user; a 4769 for a bait SPN; a directory-service ticket for a shadow DC; a breadcrumb-credential use for a breadcrumb). This lets an operator exercise the entire detection → alert → triage pipeline end-to-end without a live attacker.

### 11.5 Live stream (SSE)

The monitoring engine implements a lightweight **publish/subscribe** mechanism: consumers `subscribe` a callback and receive a `_notify` for every new event. The `/api/monitoring/stream` endpoint (in `api/monitoring.py`) bridges this into **Server-Sent Events**. It registers a thread-safe callback that pushes events onto an `asyncio.Queue`, emits a `ready` event immediately, streams `monitoring` events as they arrive, sends `keepalive` comments every 15 seconds, and reliably unsubscribes on client disconnect. The browser's `app.js` consumes this stream to update the feed in real time.

### 11.6 Querying and triage

- **`list_events`** supports filtering by severity, event id, honey-only, `since_uid` (for incremental polling), and an `exclude_baseline` flag that keeps only honey triggers, agent-ingested, or simulated events (dropping ambient seed noise).
- **`stats`** computes a rollup: totals by severity, honey-trigger count, unacknowledged count, registered honey objects, ingested count, and the latest event timestamp — surfaced on the Monitoring page tiles.
- **`acknowledge` / `acknowledge_all`** mark honey-trigger alerts as handled during triage.

---

## 12. Policy and ITDR Engine

`policy.py` encodes the framework's ITDR posture and, critically, **gates AD writes**.

### 12.1 Policy evaluation

`PolicyEngine.evaluate` produces a `PolicyReport` — a scored list of `PolicyCheck`s (each `pass`/`warn`/`fail`/`info`) covering:

- **Dedicated honey OU** configured (a `fail` when provisioning is requested without one).
- **Naming prefix** enforcement enabled.
- **Object naming convention** — verifies every provisionable object in the plan carries the prefix.
- **Deny-logon artifacts** readiness.
- **AD provisioning feature flag** state.
- **Agent / SIEM ingest** — pass only when a token is set and at least one healthy agent has checked in.
- **Monitored domains** — derived from the honey OU, LDAP base DN, and `AD_MONITORED_DOMAINS`.

A numeric **score** (percentage of passing scored checks) and an overall `ok` flag summarize posture.

### 12.2 Provisioning gate

`gate_provision` is the hard control invoked before any live AD write. It re-evaluates policy in "provision" mode and, if any check is a `fail`, returns `blocked=True` with the reasons — which the deployment service honors by refusing to write and recording a `plan_only` deployment. Dry runs bypass the block (nothing is written anyway) but still surface the report.

### 12.3 Deny-logon artifacts

`deny_logon_artifacts` generates concrete, copy-pasteable operator guidance for ensuring honey accounts have no legitimate logon path: a proposed GPO name, the exact User Rights Assignment navigation path, a PowerShell skeleton, an LGPO-style `.inf` snippet setting the four `SeDeny*LogonRight` privileges, and a step-by-step checklist. This bridges the gap between the automated provisioner (which disables accounts) and the manual GPO hardening an operator should apply.

### 12.4 Response playbooks

`playbooks.py` provides a static catalog of incident-response playbooks keyed to Event IDs (4768/4769/4625/4624) plus a generic fallback. Each playbook carries a title, severity, summary, an ordered list of containment steps, and reference tags. `playbook_for_event` selects the best match for a given monitoring event (by event id, then a honey-generic fallback) and enriches it with the triggering event's context. The Policy API exposes both the full catalog and per-event lookup.

### 12.5 Alert export

`export.py` renders alerts in three formats for evidence retention and SIEM handoff:

- **JSON bundle** — a versioned `activedecoy.alerts.json.v1` envelope with export timestamp and count.
- **STIX 2.1 bundle** — `indicator` + `observed-data` objects per event, with STIX patterns targeting the honey account/user-account and an IP-or-domain observable for the actor.
- **Syslog** — RFC 5424-ish single-line records suitable for lab SIEM intake, with proper escaping.

The Policy export endpoint enriches each event with its matched playbook id before rendering, and supports inline JSON or a downloadable attachment.

---

## 13. Agent Subsystem and the Washu Agent

### 13.1 Agent registry (console side)

`agent_registry.py` is a thread-safe registry of forwarding agents, persisted to `data/agents.json`. Each `AgentRecord` tracks agent id, hostname, version, status, bound VM name, capabilities, last-seen timestamp, forwarded-event count, and free-form meta. `heartbeat` upserts a record and stamps `last_seen`; `note_ingest` increments the forwarded count when events are accepted. `_enrich` derives a **health** classification from staleness:

- `healthy` — last seen within `AGENT_STALE_SECONDS` (default 90s).
- `stale` — older than that.
- `unhealthy` — the agent self-reports an error/offline status.
- `unknown` — never seen.

`summary()` rolls these up for the Monitoring page and the public health probe.

### 13.2 Agent-facing API and token auth

The agent APIs (`/api/agents/heartbeat`, `/api/monitoring/ingest`) are protected not by the session cookie but by a **shared bearer token**, `AGENT_INGEST_TOKEN`. The `_require_agent_token` guard accepts the token via either an `X-Agent-Token` header or an `Authorization: Bearer …` header, compares it in constant time, and returns 503 when ingest is disabled (no token configured) or 401 on mismatch. The ingest endpoint validates payloads via Pydantic models (`IngestEventItem`, `IngestRequest`), caps a request at 100 events, records accepted events through the monitoring engine, and updates the agent's forwarded count.

### 13.3 The Washu Agent package

`washu_agent/` is a self-contained, dependency-light CLI forwarder meant to run on or near the monitored domain controller. It uses only the Python standard library for HTTP (`urllib`), so it can run in a minimal environment.

- **`config.py`** — loads settings from environment/dotenv (`WASHU_*`, falling back to shared `AGENT_INGEST_TOKEN`/`HYPERVISOR_VM_NAME`), producing an immutable `AgentConfig` with console URL, token, agent id, hostname, VM name, heartbeat/poll intervals, event source, and a dry-run flag.
- **`collectors.py`** — pluggable event sources that all normalize to a `CollectedEvent` restricted to the four watched Event IDs:
  - **`WinlogCollector`** — reads the Windows Security event log via `win32evtlog` (available only on Windows with `pywin32`), tracks the last record number to avoid re-sending, and parses account/source fields out of the message text.
  - **`FileEventCollector`** — tails a newline-delimited JSON file (a lab or SIEM export), remembering its byte offset and handling truncation/rotation.
  - **`DemoCollector`** — emits synthetic honey interactions for corridor demos.
  - `build_collectors` auto-selects sources based on `WASHU_EVENT_SOURCE` (`auto`/`winlog`/`file`/`demo`), and `collect_events` polls them all into ingest-ready dicts.
- **`client.py`** — a thin `urllib` client that posts heartbeats and event batches with the agent token, raising clear errors on HTTP/connection failure, and offering an unauthenticated reachability probe against `/openapi.json`. In dry-run mode it returns simulated responses without any network call.
- **`service.py`** — the `AgentService` loop. It sends an immediate heartbeat (so the console shows healthy before the first poll), then loops: collect → ingest → periodic heartbeat, tracking a running forwarded total and reflecting collection/forward errors in its self-reported status. It installs SIGINT/SIGTERM handlers for clean shutdown. `run_once()` performs a single cycle (used by tests and the `once` command).
- **`__main__.py`** — the CLI. Subcommands: `check` (probe reachability), `heartbeat` (send one heartbeat), `once` (one full cycle), and `run` (continuous loop). Command-line flags override environment variables.

---

## 14. Frontend / Presentation Layer

The UI is intentionally lightweight and framework-free:

- **Templates (`app/templates/`).** A `base.html` shell provides the navigation and layout; each pillar has its own page (`home`, `connection`, `visualization`, `deception`, `monitoring`, `policy`, `guide`), plus the auth pages (`login`, `forgot_password`, `reset_password`) and a `partials/page_header.html`. Pages are rendered by the shared `_render()` helper, which injects navigation, redacted bridge state, and the connection checklist.
- **Styling (`app/static/css/app.css`).** A single custom CSS shell — no CSS framework.
- **Behavior (`app/static/js/app.js`, ~800 lines).** Vanilla JavaScript drives the interactive pieces: the connection test/save forms, the directory-import trigger, the native graph canvas with its scope/name/role/active filters and synchronized inventory table, the deception deploy form with live payload preview, and the monitoring console — which subscribes to the SSE stream, refreshes stats, and performs triage acknowledgements. Optionally, a NeoDash embed can be shown on the visualization page for external dashboards.
- **User guide.** The `/guide` page renders `data/user_guide.md` (the in-console workflow walkthrough) directly from Markdown.

---

## 15. Persistence Summary

ActiveDecoy keeps runtime state in flat JSON files under `data/` (all atomic-written via temp-file + rename, and all gitignored), plus the process-local secret vault:

| Store | Location | Contents | Secrets? |
|-------|----------|----------|----------|
| Deployment history | `data/deployments.json` | Deployment records, provisioned DNs (for teardown) | No |
| Monitoring events | `data/monitoring_events.json` | Event feed, honey registry, UID counter | No |
| Agent registry | `data/agents.json` | Washu heartbeats and health | No |
| Admin password override | `data/admin_password.json` | PBKDF2 hash + salt (0o600) | Hashed only |
| Session cookie | Client browser (signed) | Auth flag, username, profile metadata, last deployment summary | No |
| Secret vault | Process memory | LDAP/hypervisor passwords, keyed by opaque session id | In-memory only |
| Graph | Neo4j (optional) | AD topology + honey objects | No |

The clear rule: **plaintext secrets exist only in process memory (the vault) or the operator's `.env`; they are never written to disk stores or the session cookie.**

---

## 16. REST API Surface

The API is organized by OpenAPI tags and documented interactively at `/docs`. A representative summary:

| Method & path | Tag | Auth | Purpose |
|---------------|-----|------|---------|
| `POST /login`, `GET /logout` | — | public / session | Console session lifecycle |
| `GET/POST /forgot-password`, `/reset-password` | — | public | Password recovery |
| `GET /api/health` | system | public | Liveness + graph/agent summary |
| `GET /api/system-state` | system | session | Redacted bridge state |
| `POST /api/connection/save`, `/test`, `/retest`, `/disconnect` | connection | session | Profile + bridge validation |
| `GET /api/connection/profile`, `/status` | connection | session | Current profile/checklist |
| `POST /api/connection/enumerate` | connection | session | Enumerate directory + graph import |
| `GET /api/graph/health`, `/nodes`, `/topology`, `/preview` | graph | session | Read graph inventory/topology |
| `POST /api/graph/sync`, `/import-sample` | graph | session | Write honey Cypher to Neo4j |
| `GET /api/monitoring/events`, `/stats` | monitoring | session | Event feed + rollups |
| `GET /api/monitoring/stream` | monitoring | session | Live SSE alert stream |
| `POST /api/monitoring/simulate`, `/acknowledge` | monitoring | session | Exercise + triage |
| `POST /api/monitoring/ingest` | monitoring | agent token | Bulk telemetry ingest |
| `POST /api/agents/heartbeat` | agents | agent token | Agent heartbeat |
| `GET /api/agents/`, `/{agent_id}` | agents | session | Agent registry views |
| `GET /api/policy/status`, `/deny-logon`, `/playbooks`, `/playbook` | policy | session | ITDR posture + guidance |
| `GET /api/policy/export` | policy | session | JSON / STIX / syslog export |
| `POST /api/deception/deploy`, `/teardown` | deception | session | Deploy / tear down plans |
| `GET /api/deception/history`, `/preflight` | deception | session | History + AD preflight |

Two authentication regimes coexist: **session cookies** for the human operator (all UI and read APIs) and a **shared bearer token** for machine-to-machine agent traffic (ingest and heartbeat only).

---

## 17. Security Model and Trust Boundaries

ActiveDecoy defines four trust boundaries, each with its own controls:

1. **Console** — an administrative session that must live on a management network. Protected by session auth, login rate limiting, CORS allowlisting, security headers, and audit logging.
2. **Honey OU** — an isolated AD container. Honey accounts are created disabled, prefixed, and (per the Policy page) linked to a deny-logon GPO. Provisioning is gated by policy checks and a feature flag; teardown refuses to touch anything outside this OU.
3. **Washu Agent** — read-only toward DC logs and push-only toward the ingest API, authenticated by a bearer token that is validated in constant time.
4. **Neo4j** — a graph *mirror* only; there is no path from the graph back into a directory write.

Additional defensive controls threaded throughout the system: constant-time credential comparisons, PBKDF2 password hashing, secret/cookie separation, redaction on every serialization boundary, atomic file writes, production startup guards that refuse to boot with weak configuration, and neutral responses on the password-reset path to prevent account enumeration.

---

## 18. Deployment and Operations

### 18.1 Docker and Compose

The `Dockerfile` builds a slim Python 3.12 image, creates an unprivileged `activedecoy` user, installs pinned dependencies, copies the app/agent/data, and runs Uvicorn with `--proxy-headers`. A container `HEALTHCHECK` polls `/api/health`.

`docker-compose.yml` brings up two services on a private bridge network:

- **`neo4j`** (Neo4j 5 Community) with a persistent volume and a readiness healthcheck.
- **`app`** (the console), which waits for Neo4j to be healthy, wires the full environment (Neo4j, session, admin, LDAP, hypervisor, AD provisioning, agent) from `.env` with sensible defaults, and exposes port 8000.

A separate `docker-compose.prod.yml` and `.env.production.example` support a hardened production profile.

### 18.2 Reverse proxy and CI

`deploy/Caddyfile` provides a TLS-terminating reverse proxy configuration, and `deploy/ci.yml` (mirrored in `.github/workflows/`) runs the automated test suite. The console reads `X-Forwarded-*` only from trusted proxy hosts.

### 18.3 Local development

`scripts/bootstrap.sh` creates the virtual environment, installs dependencies, and copies `.env`; `scripts/run.sh` (or `python main.py --reload`) launches the reloading dev server. Optional connectors (`pyvmomi`, VirtualBox bindings, `pywin32`, `impacket`) are documented but not installed by default — operators install only what their lab requires. `scripts/demo_walkthrough.sh`, `forward_sample_events.py`, and `import_sample_graph.py` support corridor demos and sample data loading.

---

## 19. Testing Strategy

The `tests/` suite contains roughly **124 tests** across ~19 modules, run with Python's `unittest`. Coverage spans:

- **Engine unit tests** — deception planning and Cypher generation, monitoring correlation/simulation, policy scoring and gating, rate limiting, export formats.
- **Mocked integration** — LDAP validation/enumeration and Neo4j graph operations against mocked drivers, and AD provisioning/teardown safety.
- **Security tests** — console auth (env + LDAP), password reset, session/secret separation, production startup guards, and security headers.
- **Agent tests** — collectors, client, and the service loop (`run_once`), including dry-run behavior.
- **End-to-end API tests** — full console flows through the FastAPI app, plus documentation and visualization checks.

The `config.py` test-bootstrap ensures the suite runs against a deterministic, safe lab configuration regardless of the developer's local `.env`.

---

## 20. Extension Points and Future Work

The codebase is explicitly designed to be extended in an operator's own environment. Documented extension points include:

- **Real GPO application** — today the framework produces deny-logon artifacts and a checklist; a future integration could apply the GPO programmatically.
- **Federated console login** — OIDC or richer LDAP/AD console authentication beyond the current env-admin + LDAP-bind modes.
- **Multi-DC correlation** — the monitoring pipeline currently handles single-lab ingest with `AD_MONITORED_DOMAINS` tracking; multi-domain-controller event correlation is a natural extension.
- **Additional collectors** — the Washu Agent's collector interface makes it straightforward to add new telemetry sources (e.g., cloud identity providers or additional SIEM export formats).

---

## 21. Conclusion

ActiveDecoy demonstrates a complete, self-contained ITDR-and-deception pipeline: from validating and enumerating a real directory, through planning and safely provisioning believable honey-objects, to detecting and correlating any interaction with them, and finally triaging and exporting the resulting high-confidence alerts. Its architecture favors clarity and safety — pure, testable engines; strict separation of secrets from state; explicit, policy-gated write paths; and graceful degradation when optional infrastructure is absent. Together these properties make the framework suitable both as an educational reference for identity-threat detection and as a foundation for authorized, lab-scoped deception deployments.
