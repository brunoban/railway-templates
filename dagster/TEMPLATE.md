# Railway composer spec — Dagster

*The build-ready recipe for publishing this template in Railway's composer.
Follow top to bottom; validate with one test deploy before publishing.*

## Services (4)

### 1. `Postgres`
- **Source:** Railway database → PostgreSQL (the built-in one)
- Nothing else to configure.

### 2. `dagster-code`  *(create before webserver/daemon — they dial into it)*
- **Source:** Docker image `ghcr.io/brunoban/railway-dagster:latest`
- **Start command:** *(host form verified — see gotcha 1)*
  ```
  dagster code-server start -h '[::]' -p 4000 -f /opt/dagster/app/definitions.py
  ```
- **Variables:**
  - `DAGSTER_PG_URL` = `${{Postgres.DATABASE_URL}}`
- **Networking:** no public domain. Private networking only, port 4000.
- **Sizing:** this is where runs execute — recommend 1GB RAM in the template default.

### 3. `dagster-webserver`
- **Source:** same image
- **Start command:** none — the image default CMD is exactly this:
  ```
  dagster-webserver -h 0.0.0.0 -p 3000 -w workspace.yaml
  ```
  (Do NOT use `-h ::` here — verified broken: uvicorn logs "Serving" but
  nothing listens. `0.0.0.0` is correct; the webserver only receives public
  edge traffic, never private-network dials.)
- **Variables:**
  - `DAGSTER_PG_URL` = `${{Postgres.DATABASE_URL}}`
  - `PORT` = `3000`
- **Networking:** public domain ON (this is the UI), target port 3000.

### 4. `dagster-daemon`
- **Source:** same image
- **Start command:**
  ```
  dagster-daemon run
  ```
- **Variables:**
  - `DAGSTER_PG_URL` = `${{Postgres.DATABASE_URL}}`
- **Networking:** none (no ports at all).

## Gotchas (check these during the test deploy)

1. **Host binding forms — verified empirically (Dagster 1.13.12):**
   | Service | Flag | Result |
   |---|---|---|
   | code-server | `-h ::` | ❌ crash: builds address `:::4000`, gRPC rejects it |
   | code-server | `-h '[::]'` | ✅ boots; accepts IPv4 through the IPv6 bind (dual-stack) |
   | webserver | `-h ::` | ❌ silent failure: logs "Serving" but nothing listens |
   | webserver | `-h 0.0.0.0` | ✅ HTTP 200 |

   The code server binds `[::]` because Railway's private network is
   IPv6-first and webserver+daemon dial into it over `*.railway.internal`.
   The webserver binds `0.0.0.0` because it only receives public edge traffic.
   The daemon binds nothing (pure client).
2. **Service rename breaks discovery.** The entrypoint defaults
   `DAGSTER_CODE_HOST` to `dagster-code.railway.internal`. If the code service
   is renamed, set `DAGSTER_CODE_HOST` on webserver + daemon accordingly.
3. **Boot order.** On first deploy the webserver may come up before the code
   server finishes booting and show the code location as errored — it retries;
   "Reload location" in the UI clears it. Not a defect, but worth a line in
   the template description so users don't churn.
4. **Postgres readiness.** All three services crash-loop briefly if Postgres
   isn't ready yet; Railway restarts them and they settle. Acceptable; do not
   add init hacks.
5. **DockerRunLauncher is deliberately absent.** It requires `docker.sock`.
   The instance uses the default launcher + `QueuedRunCoordinator`, so the
   daemon dequeues and runs execute on the code server. Do not "fix" this.

## Post-deploy verification checklist

- [ ] UI loads on the public domain
- [ ] **Deployment** tab: code location `dagster-code` is loaded, no errors
- [ ] Materialize all assets → `starter_pipeline` run succeeds
- [ ] **Overview → Daemons**: run queue + scheduler daemons healthy
- [ ] Schedule `daily_starter_pipeline` can be toggled on

## Marketplace listing

- **Name:** Dagster
- **Category:** Data / Analytics (or closest available)
- **Overview (draft):** "Production-shaped Dagster: webserver + daemon +
  isolated code-location server backed by Postgres — the official
  multi-container architecture, not `dagster dev` in a box. Ships with a
  starter asset graph and a daily schedule; bring your own pipelines by
  forking the template repo."
- Enable the kickback option when publishing; support requests come through
  the Template Queue.

## Maintenance

- CI rebuilds `ghcr.io/brunoban/railway-dagster:latest` on every push to
  `dagster/**`. Redeploying template services picks up the new image.
- Watch Dagster releases for schema-migration notes (`dagster instance migrate`).
- If deploy success rate drops on the template dashboard, check upstream
  breaking changes first (env var renames have happened before).
