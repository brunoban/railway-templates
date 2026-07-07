# Dagster on Railway

Deploy [Dagster](https://dagster.io) — the data orchestrator — as a proper
production-shaped stack, not a dev-mode toy. This template mirrors Dagster's
official multi-container deployment guide:

```
┌──────────────────┐   ┌────────────────┐   ┌───────────────────┐
│ dagster-webserver│   │ dagster-daemon │   │   dagster-code    │
│  UI  (public)    │   │ schedules,     │   │ gRPC code server; │
│                  │   │ sensors, queue │   │ runs execute here │
└────────┬─────────┘   └───────┬────────┘   └─────────┬─────────┘
         │                     │                      │
         └───────────┬─────────┴──────────────────────┘
                     ▼
              ┌────────────┐
              │  Postgres  │  runs · event logs · schedule state
              └────────────┘
```

All three Dagster services share one image
(`ghcr.io/brunoban/railway-dagster`, built from this directory by CI) and
differ only in start command. State lives in Postgres — the containers are
stateless and safe to redeploy.

## Why not `dagster dev` in one container?

`dagster dev` is explicitly not for production: no run queue, no resilience,
one process doing everything. This template gives you the same shape you'd run
on your own infra — webserver, daemon, and an isolated code location — so what
you build here survives growing up.

## Environment variables

| Variable | Service(s) | Default | Purpose |
|---|---|---|---|
| `DAGSTER_PG_URL` | all three | — (wired to Postgres by the template) | Instance storage |
| `DAGSTER_CODE_HOST` | webserver, daemon | `dagster-code.railway.internal` | Code server address on the private network |
| `DAGSTER_CODE_PORT` | webserver, daemon | `4000` | Code server port |

## Bringing your own pipelines

The starter code location is [`definitions.py`](definitions.py) — a small
asset graph plus a daily schedule so the deployment works out of the box.
To ship your own:

1. Fork this repo and replace `definitions.py` (add packages to
   `requirements.txt` as needed).
2. Push — CI rebuilds the image to your fork's GHCR namespace.
3. Point the three services' image at your build and redeploy.

## Sizing

- **dagster-code** is where runs actually execute — give it the RAM your
  pipelines need. Everything else idles small (webserver ~350MB, daemon ~250MB).
- `max_concurrent_runs` is capped at 2 in [`dagster.yaml`](dagster.yaml);
  raise it together with code-server resources.
- Optional: mount a volume at `/opt/dagster/dagster_home/storage` on
  **dagster-code** to keep local artifacts/compute logs across deploys
  (run metadata is already durable in Postgres).

## Upgrading

Rebuild the image (CI does this on every push to `dagster/`) and redeploy the
three services. Dagster's Postgres schema migrates with
`dagster instance migrate` — run it as a one-off command on version bumps that
require it (release notes will say so).
