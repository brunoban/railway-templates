#!/bin/sh
# Generates workspace.yaml at boot so the code-server address is configurable
# via env instead of baked into the image. Defaults match the service name
# "dagster-code" on Railway's private network.
set -e

: "${DAGSTER_CODE_HOST:=dagster-code.railway.internal}"
: "${DAGSTER_CODE_PORT:=4000}"

cat > "${DAGSTER_HOME}/workspace.yaml" <<EOF
load_from:
  - grpc_server:
      host: "${DAGSTER_CODE_HOST}"
      port: ${DAGSTER_CODE_PORT}
      location_name: "dagster-code"
EOF

exec "$@"
