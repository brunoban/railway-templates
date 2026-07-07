# Railway composer spec — HertzBeat

*The build-ready recipe for publishing this template in Railway's composer.
Follow top to bottom; validate with one test deploy before publishing.
Everything below was extracted from Apache HertzBeat™ **1.8.0** sources and
docs on 2026-07-07 — see Sources at the bottom. Items marked **[verify]**
need confirmation during the test deploy.*

This is the production shape from upstream's own
`hertzbeat-postgresql-victoria-metrics` docker-compose variant: Postgres for
monitors/alerts/config metadata, VictoriaMetrics for metric history. The
image's built-in defaults (H2 + DuckDB, both on the ephemeral container
filesystem) are eval-only and deliberately overridden — see gotchas 1–2.

## Services (3)

### 1. `Postgres`
- **Source:** Railway database → PostgreSQL (the built-in one)
- Nothing else to configure. HertzBeat runs Flyway on boot
  (`baseline-on-migrate: true`, migrations bundled in the jar at
  `classpath:db/migration/{vendor}` with a `postgresql` vendor directory), so
  the schema is created/migrated automatically in Railway's provisioned
  database. Upstream's compose only ships an init SQL to `CREATE DATABASE
  hertzbeat` — unnecessary here because we point HertzBeat at
  `${{Postgres.PGDATABASE}}` instead (gotcha 5).

### 2. `victoria-metrics`  *(create before hertzbeat — it references this service's variables)*
- **Source:** Docker image `victoriametrics/victoria-metrics:v1.95.1`
  (exact image+tag pinned by upstream's compose file; HertzBeat docs state
  the floor is "VictoriaMetrics v1.95.1+")
- **Start command:** none. Image defaults: HTTP API on `:8428`, data at
  `/victoria-metrics-data` — exactly what upstream's compose relies on (it
  passes no flags either). Optional flags if you want them later:
  `-retentionPeriod=3` (months; default retention is 1 month) and
  `-storageDataPath` (don't change it away from the volume mount).
- **Variables:** none required.
- **Volume:** mount at `/victoria-metrics-data` — all metric history lives
  here.
- **Networking:** **no public domain** — VictoriaMetrics ships with no
  authentication; exposing it publishes every metric and allows writes.
  Private networking only, port 8428.
- **Healthcheck:** path `/-/healthy` (the endpoint upstream's compose
  healthcheck hits).
- **Sizing:** 512 MB RAM is comfortable for template-scale workloads; VM is
  famously frugal. *(estimate — verify at test deploy)*

### 3. `hertzbeat`
- **Source:** Docker image `apache/hertzbeat:1.8.0`
  (Docker Hub; `quay.io/tancloud/hertzbeat` is the documented fallback
  registry)
- **Start command:** none — the image entrypoint (`bin/entrypoint.sh`) launches
  Spring Boot with `-Dspring.config.location=/opt/hertzbeat/config/`. All
  overrides below ride Spring Boot's env-var property source, which takes
  precedence over that config directory — no file mounts needed (gotcha 2).
- **Variables:**
  - `SPRING_DATASOURCE_URL` =
    `jdbc:postgresql://${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}`
    (JDBC form composed from parts — Railway's `DATABASE_URL` is
    `postgresql://user:pass@…`, which JDBC can't parse; credentials go in the
    two vars below. Same pattern as the Dependency-Track template.)
  - `SPRING_DATASOURCE_USERNAME` = `${{Postgres.PGUSER}}`
  - `SPRING_DATASOURCE_PASSWORD` = `${{Postgres.PGPASSWORD}}`
  - `SPRING_DATASOURCE_DRIVER_CLASS_NAME` = `org.postgresql.Driver`
    (value from upstream's own Postgres compose config; the Postgres JDBC
    driver is bundled in the image — only MySQL/Oracle/DB2 need `ext-lib`
    drops, gotcha 7)
  - `SPRING_JPA_DATABASE` = `postgresql`
  - `SPRING_JPA_DATABASE_PLATFORM` =
    `org.eclipse.persistence.platform.database.PostgreSQLPlatform`
    (HertzBeat uses EclipseLink, not Hibernate — both values verbatim from
    upstream's `hertzbeat-postgresql-victoria-metrics/conf/application.yml`)
  - `WAREHOUSE_STORE_DUCKDB_ENABLED` = `false` — turns off the default local
    DuckDB history store (gotcha 1). Exact key `warehouse.store.duckdb.enabled`
    verified in 1.8.0's shipped `application.yml` and
    `DuckdbDatabaseDataStorage`'s `@ConditionalOnProperty`.
  - `WAREHOUSE_STORE_VICTORIA_METRICS_ENABLED` = `true` — key
    `warehouse.store.victoria-metrics.enabled`, verified in
    `VictoriaMetricsDataStorage`'s `@ConditionalOnProperty` and
    `VictoriaMetricsProperties`. Underscore form deliberate — see gotcha 2.
  - `WAREHOUSE_STORE_VICTORIA_METRICS_URL` =
    `http://${{victoria-metrics.RAILWAY_PRIVATE_DOMAIN}}:8428`
  - *(leave `…_USERNAME`/`…_PASSWORD` unset — single-node VictoriaMetrics has
    no auth; the file defaults `root`/`root` are sent as Basic auth headers VM
    ignores)*
  - `SURENESS_JWT_SECRET` = `${{secret(64)}}` — overrides
    `sureness.jwt.secret`, the JWT signing key whose default value is public
    in the Apache repo; without this anyone can forge admin tokens. The
    `sureness` prefix is a standard Spring `@ConfigurationProperties` binding,
    so the env override should land. **[verify]** at test deploy: log in, then
    confirm the session survives (a broken override would fall back to the
    file default silently — decode the JWT header/payload or just confirm the
    var appears in the effective config via logs).
  - `TZ` = `UTC` (image default is `Asia/Shanghai`)
  - `LANG` = `en_US.UTF-8` (explicit; also the image default)
  - `PORT` = `1157` (for Railway's edge/port detection only — the app reads
    `server.port: 1157` from its config, not `PORT`)
- **Volume:** none. With Postgres + VictoriaMetrics wired in, upstream's own
  compose variant persists nothing from the app container (it mounts only
  config/logs/ext-lib conveniences). H2 and DuckDB — the two things that
  would have written to `/opt/hertzbeat/data` — are disabled. **[verify]**
  at test deploy that nothing meaningful lands in `/opt/hertzbeat/data`.
- **Networking:** public domain **ON**, target port **1157** (UI + API).
  Port **1158** is the collector-cluster netty port — leave it unexposed;
  optional extra collectors dial it over the private network (README covers
  that extension).
- **Healthcheck:** leave Railway's HTTP healthcheck **unset** for now.
  Candidate path is `/actuator/health` (management endpoints are exposed on
  1157), but whether sureness's filter lets it through unauthenticated was
  not confirmed this session — **[verify]** with a plain curl at test deploy
  and add it if it returns 200 without credentials.
- **Sizing:** **2 GB RAM** recommended. JVM app (Temurin 21); the entrypoint
  sets no `-Xmx`, so the default max heap is ~25% of container memory —
  optionally set `JAVA_OPTS` = `-XX:MaxRAMPercentage=75.0` (the entrypoint
  appends `JAVA_OPTS` to the java command line) once 2 GB is confirmed
  comfortable. *(estimate — verify under load at test deploy)*

## Gotchas (check these during the test deploy)

1. **The single-container default is an eval-mode double trap.** Out of the
   box `apache/hertzbeat` stores metadata in **H2**
   (`jdbc:h2:./data/hertzbeat`) and metric history in **DuckDB**
   (`data/history.duckdb`) — both on the container filesystem, which on
   Railway is ephemeral: every redeploy wipes all monitors, alerts, and
   history. Upstream's own docs mark this mode "not recommended … in
   production". The six `SPRING_DATASOURCE_*`/`SPRING_JPA_*` vars and the two
   `WAREHOUSE_STORE_*` pairs above are what lift the deployment out of it —
   do not delete any of them. Note it's *DuckDB*, not the older JPA store,
   that 1.8.0 enables by default; pre-1.8 tutorials that only disable
   `warehouse.store.jpa` leave history on the container disk.
2. **Env vars replace the mounted `application.yml` — this is the template's
   central bet.** Upstream documents Postgres/VictoriaMetrics setup only as
   edits to a bind-mounted `application.yml`; Railway has no bind mounts.
   HertzBeat is a stock Spring Boot app (config loaded via
   `-Dspring.config.location`, properties consumed through
   `@ConfigurationProperties`/`@ConditionalOnProperty`), and OS env vars
   outrank config files in Spring's property-source order, so every key we
   need is overridable by env. For the dashed key `victoria-metrics`, Spring's
   relaxed binding accepts the underscore form
   (`WAREHOUSE_STORE_VICTORIA_METRICS_*`): the Binder's legacy env-var mapping
   converts dashes to underscores, and `@ConditionalOnProperty` resolution
   maps dots *and* dashes to underscores. **[verify]** this end-to-end at test
   deploy — it is the one mechanism this template cannot prove from source
   alone (upstream itself never sets these by env). Proof: monitor history
   charts render for ranges > a few minutes, and hertzbeat logs show no
   VictoriaMetrics connection errors and no `history.duckdb` writes.
   **Fallback if any binding misses** (still no custom image): put the exact
   keys in a single `SPRING_APPLICATION_JSON` variable —
   ```json
   {"spring":{"datasource":{"url":"jdbc:postgresql://${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}","username":"${{Postgres.PGUSER}}","password":"${{Postgres.PGPASSWORD}}","driver-class-name":"org.postgresql.Driver"},"jpa":{"database":"postgresql","database-platform":"org.eclipse.persistence.platform.database.PostgreSQLPlatform"}},"warehouse":{"store":{"duckdb":{"enabled":false},"victoria-metrics":{"enabled":true,"url":"http://${{victoria-metrics.RAILWAY_PRIVATE_DOMAIN}}:8428"}}}}
   ```
   Spring loads it as its own property source (also above config files), with
   property names taken literally — zero relaxed-binding ambiguity.
3. **The admin login is fixed by a file, not an env var.** Accounts live in
   `/opt/hertzbeat/config/sureness.yml` baked into the image; 1.8.0 ships
   exactly one: `admin` / `hertzbeat`. There is no env override and no UI
   password change — upstream's account-modify doc is "edit sureness.yml and
   restart". On Railway that means the login of every deploy of this template
   is public knowledge. The template mitigates what it can by env (the JWT
   signing secret, see `SURENESS_JWT_SECRET`), and the listing + README must
   say plainly: treat the deployment as secured by the obscurity of its URL
   until you either (a) remove the public domain and access it over private
   networking / tunnel, or (b) build the 5-line derivative image in the README
   that COPYies your own `sureness.yml`. Do not silently ship this fact.
4. **Private networking is IPv6-first (JVM + Go both need to behave).**
   Railway environments created after 2025-10-16 resolve `*.railway.internal`
   to IPv4 *and* IPv6, so fresh template deploys get the easy path; legacy
   environments are IPv6-only. VictoriaMetrics (Go) listens on `:8428`
   wildcard which is dual-stack by default — **[verify]** the hertzbeat→VM
   dial at test deploy. The JVM side (JDBC to `postgres.railway.internal`,
   HTTP to `victoria-metrics.railway.internal`) is the classic failure mode:
   if connections hang, set `JAVA_OPTS` = `-Djava.net.preferIPv6Addresses=true`
   on `hertzbeat` (same remedy as the Dependency-Track template).
5. **Database name differs from upstream's compose — by design.** Upstream
   init-SQL creates a database literally named `hertzbeat`; this template
   points at Railway's provisioned `${{Postgres.PGDATABASE}}` (usually
   `railway`) instead, and Flyway builds the schema there on first boot. Don't
   add init SQL, and don't hardcode `/hertzbeat` into the JDBC URL.
6. **Boot order / readiness.** Upstream's compose gates hertzbeat on Postgres
   and VM healthchecks; Railway has no `depends_on`. Expect hertzbeat to
   crash-loop briefly on first deploy until Postgres accepts connections —
   Railway restarts it and it settles, then Flyway migrates. Same story as
   the Dagster/Keep/Dependency-Track templates — do not add init hacks.
7. **`ext-lib` is unreachable without a fork.** Oracle and DB2 monitoring
   need JDBC drivers dropped into `/opt/hertzbeat/ext-lib` (and MySQL-family
   JDBC mode prefers `mysql-connector-j` there); upstream assumes a bind
   mount. On Railway that requires a derivative image with a `COPY` — note it
   in the listing FAQ rather than pre-building one; the built-in engines
   cover the common cases.
8. **Renames break references.** All cross-service wiring uses
   `${{Postgres.*}}` / `${{victoria-metrics.RAILWAY_PRIVATE_DOMAIN}}`;
   renaming a service in the composer means fixing every reference to it.
9. **Never expose `victoria-metrics` or port 1158 publicly.** VM is unauthenticated
   read/write; 1158 is the collector cluster protocol, useful only over
   private networking (or to remote collectors you deliberately invite — in
   that case front it with its own domain and understand the exposure).

## Post-deploy verification checklist

- [ ] `hertzbeat` public URL serves the UI; login `admin` / `hertzbeat` works
- [ ] Deploy logs: Flyway migration output against **PostgreSQL** (not H2),
      no `history.duckdb` mentions, no VictoriaMetrics connection errors
- [ ] `SURENESS_JWT_SECRET` override effective **[verify per gotcha — inspect
      an issued JWT or the effective config]**
- [ ] Add a first monitor (Monitors → New → **HTTP API**, target
      `https://hertzbeat.apache.org` or the deployment's own public URL) →
      status turns green, real-time metrics render
- [ ] Wait ~10 minutes → the monitor's **history** chart renders across the
      range (this is the VictoriaMetrics write→read round-trip; the eval-mode
      deploy would show only in-memory recency)
- [ ] Create a threshold alert rule on that monitor + a notice receiver
      (e.g. webhook) → trigger it (point the monitor at a dead URL) → alert
      fires and lands in Alerts
- [ ] Redeploy the `hertzbeat` service → monitors, alert rules, **and**
      history charts all survive (Postgres + VM state; the container itself
      held nothing)
- [ ] Confirm `victoria-metrics` has no public domain; optionally probe
      `/-/healthy` from the hertzbeat container over private networking
- [ ] If `/actuator/health` returned 200 unauthenticated, set it as the
      Railway healthcheck path on `hertzbeat`

## Marketplace listing

- **Name:** HertzBeat
- **Category:** Monitoring / Observability (or closest available)
- **Overview (draft):** "Deploys Apache HertzBeat™, the open-source real-time
  monitoring and alerting system with agentless collectors, 100+ built-in
  monitor types (HTTP, SSL, databases, middleware, OS, custom), threshold
  alerting and status pages — in upstream's production shape: HertzBeat
  manager backed by PostgreSQL for configuration and VictoriaMetrics for
  metric history, on Railway private networking. Not the eval-only
  single-container H2 mode: state survives redeploys. Default login is
  `admin`/`hertzbeat` — see the README's security note before sharing your
  URL. Apache HertzBeat, HertzBeat, Apache, and the HertzBeat logo are
  trademarks of the Apache Software Foundation. This template is a community
  packaging and is not affiliated with or endorsed by the ASF."
- The trademark line is not optional — ASF policy permits nominative use
  ("template that deploys Apache HertzBeat™") but not implied endorsement.
  Keep the template name exactly "HertzBeat", no Apache feather/logo assets
  in the template artwork.
- Note in the listing that the manager is an always-on ~2 GB service so
  deployers aren't surprised by usage costs.
- Enable the kickback option when publishing; support requests come through
  the Template Queue.

## Maintenance

- No CI for this template — all three images are upstream's, pinned. Watch
  [apache/hertzbeat releases](https://github.com/apache/hertzbeat/releases)
  (1.8.0 as of 2026-02) and bump `apache/hertzbeat` deliberately; upstream
  publishes per-release Docker upgrade guides (schema migrations are Flyway,
  automatic on boot, but 1.6.0-era bumps needed manual SQL — read the guide
  before major bumps).
- Re-check the **default store** on every bump: 1.8.0 silently changed the
  local history default from JPA/H2 to DuckDB. If a future version renames
  `warehouse.store.*` keys, this template's env overrides go stale — re-diff
  `script/application.yml` first when a deploy stops writing history.
- VictoriaMetrics is pinned to `v1.95.1` because that's what upstream's
  compose pins and docs set as the floor; VM itself is far ahead (v1.147.x,
  July 2026) and has LTS lines. Bumping VM is low-risk (HertzBeat speaks the
  plain Prometheus-compatible HTTP API) but do it deliberately and re-run the
  history-chart check.
- If deploy success rate drops on the template dashboard: check Docker Hub
  availability of `apache/hertzbeat` (fallback registry:
  `quay.io/tancloud/hertzbeat`), then upstream env/key renames.

## Sources (fetched 2026-07-07)

- https://hertzbeat.apache.org/docs/start/docker-compose-deploy — compose variants, recommended PG+VM solution, port 1157, default login `admin`/`hertzbeat`
- https://hertzbeat.apache.org/docs/start/docker-deploy — docker run reference: image, ports 1157/1158, H2 "not recommended in production", volume paths, collector env vars (`IDENTITY`, `MODE`, `MANAGER_HOST`, `MANAGER_PORT`)
- https://hertzbeat.apache.org/docs/start/postgresql-change — exact `spring.datasource.*` / `spring.jpa.*` values for Postgres (EclipseLink `PostgreSQLPlatform`)
- https://hertzbeat.apache.org/docs/start/victoria-metrics-init — `warehouse.store.victoria-metrics.*` keys, VM floor v1.95.1+, VM docker run with `/victoria-metrics-data`
- https://hertzbeat.apache.org/docs/start/account-modify — accounts + JWT secret: sureness.yml is the only documented account mechanism; `sureness.jwt.secret` lives in application.yml
- https://raw.githubusercontent.com/apache/hertzbeat/master/script/docker-compose/hertzbeat-postgresql-victoria-metrics/docker-compose.yaml — service set: `postgres:15`, `victoriametrics/victoria-metrics:v1.95.1`, `apache/hertzbeat:1.8.0`, ports, volumes, healthchecks (`/-/healthy`)
- https://raw.githubusercontent.com/apache/hertzbeat/master/script/docker-compose/hertzbeat-postgresql-victoria-metrics/conf/application.yml — the mounted config this template replicates via env (datasource, jpa, warehouse values verbatim)
- https://raw.githubusercontent.com/apache/hertzbeat/master/script/docker-compose/hertzbeat-postgresql-victoria-metrics/conf/sql/schema.sql — upstream init SQL = `CREATE DATABASE hertzbeat` only (gotcha 5)
- https://raw.githubusercontent.com/apache/hertzbeat/1.8.0/script/application.yml — 1.8.0 shipped defaults: H2 datasource, **duckdb enabled by default**, full `warehouse.store.victoria-metrics` block, `sureness.jwt.secret` default, `server.port: 1157`, `scheduler.server.port: 1158`, Flyway `db/migration/{vendor}`
- https://raw.githubusercontent.com/apache/hertzbeat/1.8.0/script/sureness.yml — single active account `admin`/`hertzbeat`, role/resource map
- https://raw.githubusercontent.com/apache/hertzbeat/1.8.0/script/docker/server/Dockerfile — Temurin 21 base, `WORKDIR /opt/hertzbeat/`, `EXPOSE 1157 1158 22`, entrypoint
- https://raw.githubusercontent.com/apache/hertzbeat/1.8.0/script/assembly/server/bin/entrypoint.sh — `-Dspring.config.location=config/`, honors `JAVA_OPTS`, no `-Xmx`
- apache/hertzbeat source via GitHub code search (master, cross-checked against 1.8.0 paths):
  `hertzbeat-warehouse/.../tsdb/vm/VictoriaMetricsDataStorage.java` (`@ConditionalOnProperty(prefix = "warehouse.store.victoria-metrics", name = "enabled", havingValue = "true")`),
  `.../vm/VictoriaMetricsProperties.java` (`@ConfigurationProperties`, fields enabled/url/username/password/insert),
  `hertzbeat-warehouse/.../constants/WarehouseConstants.java` (1.8.0: HistoryName strings `"victoria-metrics"`, `"duckdb"`, `"jpa"`…),
  `.../tsdb/duckdb/DuckdbDatabaseDataStorage.java` (`warehouse.store.duckdb.enabled` gate),
  `hertzbeat-startup/src/main/resources/db/migration` (Flyway vendor dirs, cited by upstream upgrade guides)
- dromara/sureness `support/spring-boot3-starter-sureness/.../SurenessProperties.java` — `@ConfigurationProperties(prefix = "sureness")` with `jwt` property (basis for the `SURENESS_JWT_SECRET` override; no account list in Spring config)
- https://github.com/apache/hertzbeat-helm-chart — official chart also mounts application.yml/sureness.yml via ConfigMap (upstream has no env-based reference config; reinforces gotcha 2's [verify])
- Docker Hub tag lists: `apache/hertzbeat` (1.8.0 = latest, pushed 2026-02-06; 1.7.3 2025-09), `apache/hertzbeat-collector` (1.8.0 exists), `victoriametrics/victoria-metrics` (v1.147.0 current as of 2026-07-06)
- https://github.com/apache/hertzbeat/releases — 1.8.0 is the latest release
- https://docs.railway.com/networking/private-networking/how-it-works — environments created after 2025-10-16 resolve `*.railway.internal` to IPv4 **and** IPv6; legacy are IPv6-only
- https://docs.railway.com/guides/create — `${{secret(length, alphabet?)}}` template function, reference-variable guidance
