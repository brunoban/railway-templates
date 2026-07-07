# Dependency-Track on Railway

Deploy [Dependency-Track](https://dependencytrack.org) — OWASP's Component
Analysis platform for SBOMs and software supply-chain risk — as the same
three-service stack upstream ships in its official quickstart compose:

```
        your browser                    CI / SBOM uploaders
             │                                 │
   loads SPA │          calls REST API         │
             ▼                ┌────────────────┤
   ┌──────────────────┐       ▼                ▼
   │     frontend     │   ┌──────────────────────┐
   │ static SPA, nginx│   │      apiserver       │
   │     (public)     │   │ REST API + analysis  │
   └──────────────────┘   │  engine   (public)   │
                          └──────────┬───────────┘
                                     │ JDBC, private network
                                     ▼
                              ┌────────────┐
                              │  Postgres  │  projects · vulns · queues
                              └────────────┘  caches · metrics — everything
```

Both official images (`ghcr.io/dependencytrack/apiserver`,
`ghcr.io/dependencytrack/frontend`) are used unmodified — this template needs
no custom image. This is **Dependency-Track v5** (GA June 2026): Postgres-only,
container-only, no Kafka, no embedded H2, and background work runs through
Postgres-backed queues — which is exactly why it maps onto Railway so cleanly.

## Why *both* web services are public

The frontend is a static single-page app. At boot its entrypoint writes
`API_BASE_URL` into a `config.json` that is fetched by **the browser** — every
API call is made browser → apiserver directly, never frontend → apiserver.
So `API_BASE_URL` must be the apiserver's **public** Railway domain (with the
`https://` scheme), and the apiserver needs a public domain of its own. The
template wires this with `https://${{apiserver.RAILWAY_PUBLIC_DOMAIN}}`.
Cross-origin is fine out of the box: v5's CORS defaults to enabled with `*`
origins (lock it down later — see the env table).

## Environment variables

| Variable | Service | Default | Purpose |
|---|---|---|---|
| `DT_DATASOURCE_URL` | apiserver | — (wired to Postgres by the template) | JDBC URL, `jdbc:postgresql://host:5432/db` |
| `DT_DATASOURCE_USERNAME` | apiserver | — (wired) | Database user |
| `DT_DATASOURCE_PASSWORD` | apiserver | — (wired) | Database password |
| `RAILWAY_RUN_UID` | apiserver | `0` (set by the template) | Lets the non-root image (UID 1000) write to the Railway volume at `/data` |
| `API_BASE_URL` | frontend | — (wired to apiserver's public domain) | API origin the **browser** calls; must be publicly reachable, scheme included |
| `DT_CORS_ALLOWED_ORIGINS` | apiserver | `*` | Optional hardening: set to `https://<frontend domain>` once deployed |
| `EXTRA_JAVA_OPTIONS` | apiserver | *(empty)* | Extra JVM flags, appended after the image defaults |

Legacy v4 `ALPINE_*` variables are gone — the v5 apiserver **refuses to start**
if it sees one, precisely so stale configs fail loudly instead of silently.

## Sizing — and what it costs you

The v4-era "fixed 4.5 GB JVM heap" problem no longer exists: the v5 image runs
with `-XX:MaxRAMPercentage=80.0`, so the heap scales to whatever memory you
give the service. Upstream's production guidance:

- **apiserver** — starting point **2 GB RAM / 4 vCPU**; below 1 GB is
  unviable, and under 2 cores the concurrency model can't stretch its legs.
  Add memory before adding instances if large BOMs push GC pauses up.
- **frontend** — static files behind nginx; 256 MB is generous.
- **Postgres** — upstream recommends 8 GB / 4 cores for production and says
  not to go below 4 GB / 2 cores *even for evaluation*. On Railway you can
  start smaller for a trial, but Postgres is where v5 keeps everything
  (queues, caches, metrics time-series included) — it's the component to feed
  as usage grows.

Be honest with yourself about the bill: the apiserver **never idles**. It
schedules vulnerability-database mirroring and analysis continuously, so it
runs (and is billed) 24/7 — do not enable app sleep on it. A 2 GB always-on
service plus a properly-fed Postgres is the real monthly cost of this stack;
check [Railway's pricing](https://railway.com/pricing) for current per-GB
rates on your plan.

## Persistence

Durable state lives almost entirely in Postgres (v5 even dropped the local
Lucene index). The apiserver still gets a small volume at `/data` for one
critical file: the **secret-management KEK keyset**
(`…/keys/secret-management-kek.json`) — the key that envelope-encrypts stored
credentials (repository tokens, notification secrets). Lose it and those
encrypted secrets become unreadable. The volume also hosts transient file
storage (uploaded BOMs mid-processing). It stays tiny — megabytes, not
gigabytes.

## First login

Browse to the frontend's public domain, sign in as `admin` / `admin`, and
you'll be forced to set a new password before anything else works.

## Upgrading

- Upstream says pin a full `X.Y.Z` tag (or digest) — this template pins both
  images to the same version, currently `5.0.2`. **Bump apiserver and
  frontend together.**
- Schema migrations run automatically at startup (Flyway init task); no
  manual step for routine upgrades, but read the per-version
  [upgrade guides](https://dependencytrack.github.io/docs/next/guides/) before
  jumping minors.
- Coming from an existing **v4** install? This template is v5-native. v4 data
  needs upstream's dedicated `dependencytrack/v4-migrator` image and the
  [migration guide](https://dependencytrack.github.io/docs/next/guides/administration/migrating-from-v4/)
  (v4 must be ≥ 4.14.2 and offline during the cutover) — that's a manual
  operation, not something a fresh template deploy does for you.
