# HertzBeat on Railway

Deploy [Apache HertzBeat™](https://hertzbeat.apache.org) — the open-source
real-time monitoring and alerting system — in the production shape upstream
ships, not the eval-only single container. HertzBeat monitors websites, APIs,
SSL certificates, databases, middleware, operating systems and more with
**agentless** collectors and 100+ built-in monitor templates, evaluates
threshold alert rules, and notifies via webhook, email, Slack, Discord,
Telegram and friends.

```
                       ┌───────────────────────────┐
  https://…  ────────▶ │         hertzbeat         │
  UI + API  :1157      │   manager + built-in      │──── probes your
                       │   collector (JVM)         │     targets, agentless
                       └───────┬───────────┬───────┘
                    JDBC :5432 │           │ HTTP :8428
                     (private) │           │ (private)
                               ▼           ▼
                     ┌────────────┐   ┌──────────────────┐
                     │  Postgres  │   │ victoria-metrics │
                     │ monitors · │   │  metric history  │
                     │ alerts ·   │   │  (volume-backed) │
                     │ config     │   │                  │
                     └────────────┘   └──────────────────┘
```

This mirrors upstream's own `hertzbeat-postgresql-victoria-metrics`
docker-compose variant: **PostgreSQL** holds everything you configure
(monitors, alert rules, notice receivers), **VictoriaMetrics** holds the
metric history your charts are drawn from. All three services talk over
Railway's private network; only the HertzBeat UI gets a public domain.

## Why not the one-container quickstart?

`docker run apache/hertzbeat` stores metadata in embedded **H2** and history
in a local **DuckDB** file — both on the container's own filesystem. Upstream
marks that mode "not recommended in production", and on Railway it's worse
than that: container filesystems are ephemeral, so *every redeploy erases
every monitor, alert rule and chart*. This template overrides both stores via
environment variables (no config-file mounts needed — HertzBeat is a standard
Spring Boot app and env vars outrank its config files), so the app container
is stateless and safe to redeploy.

## Environment variables

All wiring is done by the template with Railway reference variables; you
shouldn't need to touch anything to get started.

| Variable | Service | Value (template default) | Purpose |
|---|---|---|---|
| `SPRING_DATASOURCE_URL` | hertzbeat | `jdbc:postgresql://${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}` | Metadata DB (JDBC form) |
| `SPRING_DATASOURCE_USERNAME` | hertzbeat | `${{Postgres.PGUSER}}` | DB user |
| `SPRING_DATASOURCE_PASSWORD` | hertzbeat | `${{Postgres.PGPASSWORD}}` | DB password |
| `SPRING_DATASOURCE_DRIVER_CLASS_NAME` | hertzbeat | `org.postgresql.Driver` | Bundled Postgres driver |
| `SPRING_JPA_DATABASE` | hertzbeat | `postgresql` | EclipseLink dialect switch |
| `SPRING_JPA_DATABASE_PLATFORM` | hertzbeat | `org.eclipse.persistence.platform.database.PostgreSQLPlatform` | EclipseLink platform |
| `WAREHOUSE_STORE_DUCKDB_ENABLED` | hertzbeat | `false` | Disable local-file history store |
| `WAREHOUSE_STORE_VICTORIA_METRICS_ENABLED` | hertzbeat | `true` | Enable VictoriaMetrics history |
| `WAREHOUSE_STORE_VICTORIA_METRICS_URL` | hertzbeat | `http://${{victoria-metrics.RAILWAY_PRIVATE_DOMAIN}}:8428` | VM endpoint (private net) |
| `SURENESS_JWT_SECRET` | hertzbeat | generated (`${{secret(64)}}`) | Replaces the publicly-known default JWT signing key |
| `TZ` / `LANG` | hertzbeat | `UTC` / `en_US.UTF-8` | Locale (image default TZ is Asia/Shanghai) |
| `JAVA_OPTS` | hertzbeat | *(unset)* | Extra JVM flags, e.g. `-XX:MaxRAMPercentage=75.0` or `-Djava.net.preferIPv6Addresses=true` |

The `victoria-metrics` service needs no variables; its volume at
`/victoria-metrics-data` is where history lives (default retention 1 month —
add a start command flag `-retentionPeriod=3` for three months, etc.).

## First login — read this

Log in with **`admin` / `hertzbeat`** (upstream's default), then add your
first monitor: **Monitors → New monitor → HTTP API**, point it at any URL you
care about, and watch the availability/latency charts fill in.

**Security note, plainly:** HertzBeat 1.8.0 keeps its user accounts in a file
inside the image (`config/sureness.yml`), not in the database. There is no
UI or environment variable to change the admin password — so every deploy of
this template has the same well-known login. The template *does* replace the
JWT signing secret with a generated one (so tokens can't be forged), but the
password itself stays `hertzbeat` until you either:

- **keep the deployment private** — remove the public domain and reach the UI
  over Railway private networking / `railway connect`-style tunneling, or
- **fork with your own accounts** — a 5-line derivative image:

  ```dockerfile
  FROM apache/hertzbeat:1.8.0
  # your copy of https://github.com/apache/hertzbeat/blob/1.8.0/script/sureness.yml
  # with the account credentials changed (supports MD5+salt hashes)
  COPY sureness.yml /opt/hertzbeat/config/sureness.yml
  ```

  Point the `hertzbeat` service at your image and redeploy.

## Sizing

- **hertzbeat** — a JVM app on Temurin 21. Template default **2 GB RAM**.
  The launcher sets no `-Xmx`, so the JVM takes ~25% of container memory as
  max heap by default; if you monitor hundreds of targets, raise memory and
  add `JAVA_OPTS=-XX:MaxRAMPercentage=75.0`. Don't enable app sleep — it's a
  monitoring scheduler; sleeping it is missing data and false alerts.
- **victoria-metrics** — famously light; **512 MB** is comfortable at
  template scale. Disk grows with (metrics × retention); the default 1-month
  retention keeps it small.
- **Postgres** — Railway's defaults are fine; it stores configuration, not
  metrics.

## Scaling out: extra collectors (optional)

The manager includes a built-in collector, which is all most deployments
need. For probing from another network or spreading load, upstream ships
`apache/hertzbeat-collector:1.8.0`: run it as an additional Railway service
with `MANAGER_HOST=<hertzbeat private domain>`, `MANAGER_PORT=1158`,
`IDENTITY=<unique name>`, `MODE=public` — it dials the manager's private
port 1158; nothing extra needs public exposure.

## Upgrading

Bump the `apache/hertzbeat` image tag and redeploy — schema migrations run
automatically (Flyway) on boot. Apache publishes per-release Docker upgrade
guides; read them before major version jumps (some past upgrades required a
manual SQL step). Keep `victoria-metrics` bumps separate and deliberate; the
pinned `v1.95.1` is upstream's own compose pin and the documented minimum.
Since all state lives in Postgres and the VM volume, the app container can be
re-created freely.

## Naming and trademarks

This is a community-maintained Railway template that deploys unmodified
upstream images of Apache HertzBeat™. Apache HertzBeat, HertzBeat, Apache,
and the HertzBeat logo are trademarks of the [Apache Software
Foundation](https://www.apache.org/foundation/marks/). This template is not
produced, affiliated with, or endorsed by the ASF.
