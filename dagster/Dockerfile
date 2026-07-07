# Shared image for all three Dagster services (webserver, daemon, code server).
# Which service a container becomes is decided by its start command — see TEMPLATE.md.
FROM python:3.12-slim

ENV DAGSTER_HOME=/opt/dagster/dagster_home \
    PYTHONUNBUFFERED=1

# Dependencies first for layer caching
WORKDIR /opt/dagster/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instance config lives in DAGSTER_HOME; workspace.yaml is generated there
# at container start by the entrypoint (so the code-server host is env-configurable).
RUN mkdir -p "$DAGSTER_HOME"
COPY dagster.yaml ${DAGSTER_HOME}/dagster.yaml

# Starter code location — replace definitions.py with your own pipelines
COPY definitions.py /opt/dagster/app/definitions.py

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# webserver and daemon both resolve workspace.yaml from the working directory
WORKDIR /opt/dagster/dagster_home

EXPOSE 3000 4000

ENTRYPOINT ["entrypoint.sh"]
# Default: webserver. The daemon and code-server services override this
# via Railway's custom start command (ENTRYPOINT still runs first).
CMD ["dagster-webserver", "-h", "0.0.0.0", "-p", "3000", "-w", "workspace.yaml"]
