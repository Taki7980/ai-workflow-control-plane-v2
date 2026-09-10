# syntax=docker/dockerfile:1

FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY ai_workflow ./ai_workflow
RUN python -m pip install --no-cache-dir build \
    && python -m build --wheel

FROM python:3.12-slim AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 aiworkflow
COPY --from=build /src/dist/*.whl /tmp/
RUN python -m pip install --no-cache-dir /tmp/*.whl \
    && rm -f /tmp/*.whl
USER aiworkflow
WORKDIR /workspace
ENTRYPOINT ["ai-workflow"]
