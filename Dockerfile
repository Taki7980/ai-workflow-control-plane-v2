# syntax=docker/dockerfile:1

FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY ai_workflow ./ai_workflow
RUN python -m pip install --no-cache-dir "uv==0.12.14" \
    && uv sync --locked --only-group build \
    && uv run --locked --no-sync python -m build --wheel --no-isolation

FROM python:3.12-slim AS runtime
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 aiworkflow
COPY --from=build /src/dist/*.whl /tmp/
RUN python -m pip install --no-cache-dir --no-deps /tmp/*.whl \
    && rm -f /tmp/*.whl
USER aiworkflow
WORKDIR /workspace
ENTRYPOINT ["ai-workflow"]
