# ClickHouse for Laminar on Railway.
#
# Upstream's docker-compose-full.yml bind-mounts clickhouse-profiles-config.xml
# into the server as /etc/clickhouse-server/users.d/lmnr.xml
# (source: https://github.com/lmnr-ai/lmnr/blob/main/docker-compose-full.yml).
# Railway has no bind mounts, so this image bakes the same file in at the same
# path. That is the ONLY change — base image and tag match upstream's compose.
#
# The profile sets date_time_input_format=best_effort for the default profile,
# which Laminar relies on when inserting span timestamps.
FROM clickhouse/clickhouse-server:26.5

COPY clickhouse-profiles-config.xml /etc/clickhouse-server/users.d/lmnr.xml
