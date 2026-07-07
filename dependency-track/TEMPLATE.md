# Railway composer spec — Dependency-Track

*The build-ready recipe for publishing this template in Railway's composer.
Follow top to bottom; validate with one test deploy before publishing.
Everything below is Dependency-Track **v5** (v4's `ALPINE_*` config is dead —
see gotcha 1).*

## Services (3)

### 1. `Postgres`
- **Source:** Railway database → PostgreSQL (the built-in one)
- v5 requires **PostgreSQL ≥ 14** and the `pg_trgm` extension. Railway's
  built-in Postgres satisfies the version floor, and the apiserver's Flyway
  migration runs `CREATE EXTENSION IF NOT EXISTS` itself on first boot —
  Railway's default DB user has the privileges for it (verify at test deploy,
  gotcha 7).
- **Sizing:** upstream says don't go below 4 GB / 2 cores even for evaluation;
  8 GB / 4 cores recommended for production. Postgres is v5's everything-store
  (queues, caches, metrics included) — size it, not the apiserver, as load grows.

### 2. `apiserver`
- **Source:** Docker image `ghcr.io/dependencytrack/apiserver:5.0.2`
  (GHCR, not Docker Hub — releases land on GHCR first and mirror to Docker
  Hub asynchronously; upstream says pin full `X.Y.Z` tags.)
- **Start command:** none — image CMD (`tini` → `java … org.dependencytrack.Application`) is correct as-is.
- **Variables:**
  - `DT_DATASOURCE_URL` = `jdbc:postgresql://${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}`
    (JDBC format is mandatory — you cannot pass Railway's `DATABASE_URL`
    directly because it's `postgresql://user:pass@…` form; credentials go in
    the two vars below)
  - `DT_DATASOURCE_USERNAME` = `${{Postgres.PGUSER}}`
  - `DT_DATASOURCE_PASSWORD` = `${{Postgres.PGPASSWORD}}`
  - `RAILWAY_RUN_UID` = `0` (volume-permissions workaround, gotcha 4)
  - *(optional hardening, post-deploy)* `DT_CORS_ALLOWED_ORIGINS` = `https://${{frontend.RAILWAY_PUBLIC_DOMAIN}}` — default is `*`, which works but is loose (gotcha 3)
- **Volume:** mount at `/data` — holds the secret-management KEK keyset
  (must survive redeploys; losing it orphans encrypted secrets in the DB) and
  transient file storage. Small; single volume per service is fine here.
- **Networking:** public domain **ON**, target port **8080**. The browser
  dials this service directly (see gotcha 2), so public is not optional.
  Port 9000 is the management interface (health + metrics) — leave it
  unexposed; it stays reachable only inside the container/private net.
- **Sizing:** template default **2 GB RAM** (upstream's production starting
  point is 2 GB / 4 vCPU; below 1 GB is unviable). Heap auto-scales via
  `-XX:MaxRAMPercentage=80.0` baked into the image. Never enable app sleep —
  it runs scheduled vulnerability mirroring continuously.

### 3. `frontend`
- **Source:** Docker image `ghcr.io/dependencytrack/frontend:5.0.2`
  (keep the tag in lock-step with the apiserver)
- **Start command:** none — nginx-unprivileged entrypoint is correct as-is
  (it even adds a `[::]:8080` listener itself; no host-binding surgery needed
  on this template, unlike Dagster).
- **Variables:**
  - `API_BASE_URL` = `https://${{apiserver.RAILWAY_PUBLIC_DOMAIN}}`
    — scheme **included**; this value is consumed by the deployer's browser,
    not by the container (gotcha 2)
- **Networking:** public domain **ON**, target port **8080** (nginx-unprivileged
  default; the image runs as UID 101 and can't bind 80).
- **Sizing:** static files behind nginx — 256 MB is plenty.

## Gotchas (check these during the test deploy)

1. **This is v5 — every v4 tutorial on the internet is now a trap.**
   Config keys were renamed wholesale (`ALPINE_DATABASE_URL` →
   `DT_DATASOURCE_URL` etc.) and the v5 apiserver **refuses to start** when it
   encounters a legacy `ALPINE_*` key, by design. If a deploy crash-loops with
   a config error, look for copy-pasted v4 variables first.
2. **`API_BASE_URL` is a browser-side setting.** The frontend entrypoint
   writes it into `static/config.json`, which the SPA fetches; all API calls
   are browser → apiserver. Therefore: apiserver must have a public domain,
   the URL must carry `https://` (bare domains and `http://` fail — the SPA
   page is https, mixed content is blocked), and pointing it at
   `apiserver.railway.internal` can never work.
3. **CORS works out of the box, deliberately loose.** v5 defaults
   `dt.cors.enabled=true` with `dt.cors.allowed-origins=*`, so the split-origin
   frontend↔apiserver setup needs zero CORS config on day one. After the test
   deploy, set `DT_CORS_ALLOWED_ORIGINS` to the frontend's exact origin.
4. **Volume ownership vs non-root image.** The apiserver runs as UID 1000 and
   must write `/data`, but Railway volumes mount root-owned for non-root
   containers; Railway's documented workaround is `RAILWAY_RUN_UID=0`, which
   the template sets. **Verify at test deploy** that the KEK keyset appears
   under the volume and survives a redeploy; if upstream ever ships a
   friendlier fix, drop the override.
5. **JDBC over Railway's IPv6-first private network.** `PGHOST` resolves to
   `postgres.railway.internal` (AAAA-only). The JVM should happily use IPv6
   when no A record exists, but this is the classic Railway failure mode —
   **verify at test deploy**. If connections hang, set
   `EXTRA_JAVA_OPTIONS` = `-Djava.net.preferIPv6Addresses=true` on the
   apiserver.
6. **Railway HTTP healthcheck path — verify at test deploy.** Real health
   endpoints (`/health`, `/health/live`, `/health/ready`) live on the
   management port 9000, which Railway's edge healthcheck can't reach (it
   probes the target port, 8080). Whether v4's unauthenticated `/api/version`
   still exists on 8080 in v5 could not be confirmed from upstream docs this
   session — test it, and leave the Railway healthcheck unset if it's gone
   (the image's own Docker HEALTHCHECK against `127.0.0.1:9000/health` still
   guards the container).
7. **First boot is slow and slightly dramatic.** The apiserver may crash-loop
   briefly until Postgres is ready (Railway restarts settle it — no init
   hacks), then Flyway builds the full schema including
   `CREATE EXTENSION IF NOT EXISTS pg_trgm` (**verify** it succeeds under
   Railway's default DB user), then vulnerability-database mirroring starts
   chewing. Give it several minutes before judging the deploy failed.
8. **Deploy order barely matters, rename does.** Reference variables
   (`${{apiserver.RAILWAY_PUBLIC_DOMAIN}}`, `${{Postgres.PGHOST}}`) re-resolve
   automatically, but renaming a service breaks every reference to it —
   fix all `${{…}}` occurrences if you rename.

## Post-deploy verification checklist

- [ ] Frontend loads on its public domain
- [ ] Browser devtools → `config.json` request shows `API_BASE_URL` = apiserver's public https domain; no CORS errors in console
- [ ] Login `admin` / `admin` → forced password change succeeds
- [ ] UI "About" shows version 5.0.2, API server reachable
- [ ] Apiserver deploy logs: Flyway migrations completed, `pg_trgm` created, no `ALPINE_*` config errors
- [ ] Create a project and upload a test SBOM (CycloneDX) via the UI → components appear and analysis runs
- [ ] Redeploy the apiserver → still boots clean, KEK keyset persisted on the volume (no "cannot decrypt" errors), admin password still set
- [ ] Vulnerability datasource mirroring visible in logs (NVD/OSV sync activity)

## Marketplace listing

- **Name:** Dependency-Track
- **Category:** Security / DevOps (or closest available)
- **Overview (draft):** "OWASP Dependency-Track v5 — the Component Analysis
  platform for SBOMs and supply-chain risk — deployed the way upstream ships
  it: official apiserver + frontend images backed by Postgres. No Kafka, no
  custom images, no H2 toy mode; v5's Postgres-backed architecture on three
  Railway services. Upload a CycloneDX SBOM and get continuous vulnerability
  analysis against NVD, OSV, GitHub Advisories and more."
- Note in the listing that the apiserver is an always-on 2 GB service so
  deployers aren't surprised by usage costs.
- Enable the kickback option when publishing; support requests come through
  the Template Queue.

## Maintenance

- No CI builds for this template — both images are upstream's, pinned to
  `5.0.2`. Maintenance = watching
  [releases](https://github.com/DependencyTrack/dependency-track/releases)
  and bumping **both** tags together (apiserver and frontend version in
  lock-step), then re-running the verification checklist.
- Read the per-version upgrade guides before minor bumps; migrations are
  automatic (Flyway on startup) but upstream flags manual steps when needed.
- v4 reached feature-end with 4.14.x; expect docs and community answers to
  drift v5-ward — and expect deployers to arrive with stale v4 configs
  (gotcha 1) when deploy success rate dips.

## Sources

Fetched July 2026:

- https://dependencytrack.github.io/docs/next/tutorials/quickstart/ — v5 quickstart, default `admin`/`admin` + forced password change
- https://dependencytrack.org/docker-compose.yml → redirects to https://raw.githubusercontent.com/DependencyTrack/docs/refs/heads/main/docs/tutorials/docker-compose.quickstart.yml — official compose: images/tags, `DT_DATASOURCE_*`, `/data` volume, 2g limit
- https://dependencytrack.github.io/docs/next/concepts/changes-in-v5/ — v5 architecture: Postgres-backed queues, Lucene index removed, container-only
- https://dependencytrack.github.io/docs/next/reference/container-images/ — registries, tag scheme, "pin X.Y.Z" guidance, v4-migrator image
- https://dependencytrack.github.io/docs/next/reference/configuration/datasources/ — `dt.datasource.url/username/password`, pool properties
- https://dependencytrack.github.io/docs/next/reference/configuration/properties/ — CORS defaults, `dt.management.port=9000`, `dt.data-directory`, KEK keyset path
- https://dependencytrack.github.io/docs/next/reference/configuration/application/ — env-var name mapping, `JAVA_OPTIONS` defaults incl. `MaxRAMPercentage=80.0`, `EXTRA_JAVA_OPTIONS`
- https://dependencytrack.github.io/docs/next/reference/configuration/database/ — PostgreSQL ≥ 14, `pg_trgm`, Flyway on startup
- https://dependencytrack.github.io/docs/next/reference/configuration/file-storage/ — local file storage under `/data`, transient files
- https://dependencytrack.github.io/docs/next/guides/administration/deploying-to-production/ — sizing (2 GB/4 cores apiserver, 8 GB/4 cores DB), probes on 9000, TLS at proxy
- https://dependencytrack.github.io/docs/next/guides/administration/configuring-observability/ — `/health/live|ready|started`, `/metrics` on 9000
- https://dependencytrack.github.io/docs/next/guides/administration/scaling/ — pool of 30/instance, memory-before-instances guidance
- https://dependencytrack.github.io/docs/next/reference/api/v5-breaking-changes/ — v1 API largely retained; `/api/version` availability unconfirmed (gotcha 6)
- https://raw.githubusercontent.com/DependencyTrack/dependency-track/5.0.2/apiserver/src/main/docker/Dockerfile — `DATA_DIR=/data`, UID 1000, EXPOSE 8080+9000, JVM defaults, HEALTHCHECK `:9000/health`
- https://raw.githubusercontent.com/DependencyTrack/frontend/5.0.2/docker/Dockerfile.alpine + docker/etc/nginx/templates/default.conf.template + docker/docker-entrypoint.d/30-oidc-configuration.sh — nginx-unprivileged on 8080 (dual-stack), entrypoint writes `API_BASE_URL`/OIDC vars into browser-fetched `config.json`
- https://github.com/DependencyTrack/dependency-track/releases — 5.0.2 latest (June 2026), 4.14.2 latest v4
- https://github.com/DependencyTrack/dependency-track/discussions/6159 + V5_MIGRATION.md — v5 GA announcement, migration pointers
- https://docs.railway.com/reference/volumes — `RAILWAY_RUN_UID=0` workaround, one volume per service
