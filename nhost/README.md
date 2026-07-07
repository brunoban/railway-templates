# Nhost on Railway

Deploy [Nhost](https://nhost.io) — the open-source Firebase alternative built on
GraphQL — as its real multi-service stack: Postgres, Hasura GraphQL Engine,
Hasura Auth, Hasura Storage, and MinIO, with the Nhost Dashboard as an optional
admin UI. The service set mirrors Nhost's official
[self-hosting docker-compose example](https://github.com/nhost/nhost/tree/main/examples/docker-compose),
with the dev-only pieces (Traefik, Mailhog, the hasura-cli console sidecar)
replaced by Railway-native equivalents or dropped.

```
                 browser / your app
        ┌──────────────┼────────────────┬───────────────┐
        ▼              ▼                ▼               ▼
┌──────────────┐ ┌───────────┐  ┌──────────────┐ ┌────────────┐
│    hasura    │ │   auth    │  │   storage    │ │ dashboard  │
│ GraphQL API  │ │ signup /  │  │ file upload/ │ │ (optional  │
│ + console    │ │ signin,   │  │ download,    │ │ admin UI)  │
│ :8080 public │ │ JWTs      │  │ image proc   │ │ :3000 pub  │
└──────┬───────┘ │ :4000 pub │  │ :5000 public │ └────────────┘
       │         └─────┬─────┘  └──────┬───┬───┘
       │               │   (private)   │   │ (private)
       │               ▼               │   ▼
       │        ┌────────────┐         │ ┌───────────────┐
       └───────►│  Postgres  │◄────────┘ │     minio     │
                │ (managed)  │           │ S3 backend    │
                └────────────┘           │ :9000 private │
                                         └───────────────┘
```

One shared HS256 JWT secret ties the stack together: **auth** signs tokens,
**hasura** and **storage** verify them. One admin secret guards the Hasura
console, metadata API, and storage admin endpoints. The template generates both
at deploy time — see [`TEMPLATE.md`](TEMPLATE.md) for the full wiring.

**Self-hosting notice (upstream's words, not ours):** Nhost is MIT-licensed and
100% open source, but Nhost the company "doesn't officially support
self-hosting without a support agreement" — their compose file is framed as a
demonstration. The images it runs are the same production components, and this
template hardens the demo defaults (no dev proxy, generated secrets, dev mode
off). Support beyond that is community-provided.

## What's deliberately excluded

| Component | Why it's out |
|---|---|
| **Functions runtime** (`nhost/functions`) | It loads user code from a bind-mounted project directory (`.:/opt/project` in the upstream compose). Railway can't bind-mount source into an image service, so a v1 functions service would boot with zero functions. Deploy your API as a plain Railway service instead (any Node/Go/etc. app can call Hasura with the admin secret or a service JWT), or fork this template and bake a `functions/` folder into a custom image. |
| **Traefik** | Railway's edge handles domains and TLS. Consequence: there's no `/v1 → /v1/graphql` rewrite, so point clients at the **full** GraphQL path `https://<hasura-domain>/v1/graphql`. Auth and storage serve under `/v1` natively — no rewrites needed. |
| **Mailhog** | Dev-only SMTP catcher. Bring real SMTP credentials (`AUTH_SMTP_*`) for verification/passwordless emails; until then, signups work because `AUTH_EMAIL_SIGNIN_EMAIL_VERIFIED_REQUIRED=false`. |
| **hasura-cli console sidecar** | Upstream runs a second graphql-engine container in `hasura-cli console` mode for the migrations dev workflow. Instead, this template enables Hasura's built-in console at `https://<hasura-domain>/console` (admin-secret protected). Side effect: the Dashboard's migration-backed database editing may not fully work — use the Hasura console for schema changes. |

## Environment variables you set

Everything else is wired between services by the template (full matrix in
[`TEMPLATE.md`](TEMPLATE.md)).

| Variable | Service | Default | Purpose |
|---|---|---|---|
| `HASURA_GRAPHQL_ADMIN_SECRET` | hasura (referenced by auth, storage, dashboard) | generated (`${{secret(32)}}`) | Admin access to Hasura + storage admin endpoints |
| `HASURA_GRAPHQL_JWT_SECRET` | hasura (referenced by auth) | generated — `{"type":"HS256","key":"<64 hex chars>"}` | Token signing/verification. Must be byte-identical on auth and hasura |
| `AUTH_CLIENT_URL` | auth | `http://localhost:3000` | Your frontend's URL — auth redirects here after email flows. Change it |
| `AUTH_SMTP_HOST/PORT/USER/PASS/SENDER/SECURE/AUTH_METHOD` | auth | empty/placeholder | Real SMTP for verification, passwordless, and reset emails |
| `AUTH_EMAIL_SIGNIN_EMAIL_VERIFIED_REQUIRED` | auth | `false` | Flip to `true` once SMTP works |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | minio (referenced by storage) | generated | S3 credentials — never exposed publicly |

Generating the JWT key manually (if you don't use the template's generated
value): `openssl rand -hex 32`, then wrap it:
`{"type":"HS256","key":"<output>"}`. The upstream `.env.example` documents this
exact format.

## Postgres: managed, not a custom image

Upstream's own self-host example runs **stock `postgres:16`** plus a ~10-line
init script (create `auth`/`storage` schemas, `pgcrypto` + `citext` extensions,
one trigger function) — it does not require Nhost's cloud Postgres build. So
this template uses **Railway's managed Postgres** (backups, metrics, no volume
babysitting) and runs that init script as a one-time bootstrap step after
deploy (the exact SQL is in `TEMPLATE.md`). Tradeoff: if you later want
extensions Nhost Cloud ships (e.g. pgvector), confirm they're available in
Railway's Postgres image before relying on them.

## Sizing (starting points, not gospel)

| Service | RAM estimate | Notes |
|---|---|---|
| hasura | 512MB–1GB | Haskell; the hungriest service. Scale first |
| auth | 64–128MB | Go, tiny |
| storage | 64–256MB | Go; spikes during large uploads/image manipulation |
| minio | 256–512MB | Plus a volume sized to your file storage needs |
| dashboard | 256–512MB | Next.js; optional — delete it if unused |
| Postgres | Railway managed default | Grow with data |

## Upgrading

This template pins the exact tags from upstream's example compose (fetched
2026-07-07): `nhost/auth:0.40.2`, `nhost/storage:0.7.2`,
`nhost/graphql-engine:v2.46.0-ce`, `nhost/dashboard:2.34.0`,
`minio/minio:RELEASE.2025-02-28T09-55-16Z`, Postgres 16 — a combination
upstream tested together. Docker Hub already has newer tags (auth `0.50.1`,
storage `0.15.0`, dashboard `3.0.0`, graphql-engine `v2.49.2-ce`); development
of auth/storage moved into the [nhost/nhost](https://github.com/nhost/nhost)
monorepo, so watch its releases. To upgrade: bump one service at a time
(hasura first, then auth/storage), redeploy, and let auth/storage re-run their
own migrations — they apply schema migrations automatically at startup against
the migration connection strings.

## Licenses

The Nhost monorepo and hasura-auth are MIT; hasura-storage is Apache-2.0
(verified upstream). Hasura GraphQL Engine CE and MinIO retain their own
upstream licenses — review MinIO's license terms if you redistribute this
stack commercially.
