# syntax=docker/dockerfile:1.27.0@sha256:bde3983e9c939224420ddaf6b784cc30e09b035a4dea01f581230c50809f372e

FROM ghcr.io/astral-sh/uv:0.12.14@sha256:1946145b8706ad9e5c0e79a513f9e324b58d5e38126bb2c8b7dbfca61febeb45 AS uv

FROM python:3.12.14-slim-trixie@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9 AS build
WORKDIR /src
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY ai_workflow ./ai_workflow
RUN uv sync --locked --only-group build \
    && uv run --locked --no-sync python -m build --wheel --no-isolation

FROM python:3.12.14-slim-trixie@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9 AS runtime
COPY packaging/container/debian.sources /etc/apt/sources.list.d/debian.sources
COPY packaging/container/runtime-packages.txt /tmp/runtime-packages.txt
RUN rm -f /etc/apt/sources.list \
    && apt-get update \
    && xargs -r apt-get install -y --no-install-recommends < /tmp/runtime-packages.txt \
    && rm -rf /var/lib/apt/lists/* /tmp/runtime-packages.txt \
    && useradd --create-home --uid 10001 aiworkflow
COPY --from=build /src/dist/*.whl /tmp/
RUN python -m pip install --no-cache-dir --no-deps /tmp/*.whl \
    && rm -f /tmp/*.whl
USER aiworkflow
WORKDIR /workspace
ENTRYPOINT ["ai-workflow"]
