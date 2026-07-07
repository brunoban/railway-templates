# railway-templates

Production-shaped [Railway](https://railway.com) templates for open-source
software that deserves a proper one-click deploy — multi-service, wired the way
the upstream project actually recommends, not single-container demos.

## Templates

| Template | Status | What you get |
|---|---|---|
| [**Dagster**](dagster/) | 🚧 scaffold ready, publishing soon | Full 4-service deployment: webserver + daemon + code-location server + Postgres |

More on the way: Dependency-Track, Laminar, HertzBeat, Keep, Nhost.

## Design principles

- **The real architecture.** If upstream's production guidance is four services,
  the template is four services — no "it boots" single-container shortcuts.
- **Official images or transparent builds.** Custom images are built in this
  repo by CI ([`.github/workflows`](.github/workflows)) and published to GHCR —
  auditable Dockerfiles, no mystery layers.
- **Documented, supported, maintained.** Each template has a README covering
  env vars, sizing, and upgrade paths. Stale templates get archived, not abandoned.

## Structure

Each template lives in its own directory:

```
<template>/
├── README.md        — deployer-facing docs
├── TEMPLATE.md      — Railway composer spec (services, env wiring, gotchas)
├── Dockerfile       — image source (built by CI → GHCR), if a custom image is needed
└── ...              — config and starter code baked into the image
```

## License

[MIT](LICENSE) — applies to the template code in this repo. Each deployed
application keeps its own upstream license.
