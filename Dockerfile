# syntax=docker/dockerfile:1.27.0@sha256:bde3983e9c939224420ddaf6b784cc30e09b035a4dea01f581230c50809f372e

FROM ghcr.io/astral-sh/uv:0.12.17@sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc AS uv

FROM python:3.14.6-slim-trixie@sha256:7bec7ddcddeff7975d6ba9b4be7dd6f6b2f55e7491539145e2978f7f97ce9144 AS build
ARG SOURCE_DATE_EPOCH
WORKDIR /src
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY ai_workflow ./ai_workflow
RUN uv sync --locked --only-group build \
    && uv run --locked --no-sync python -m build --wheel --no-isolation

FROM python:3.14.6-slim-trixie@sha256:7bec7ddcddeff7975d6ba9b4be7dd6f6b2f55e7491539145e2978f7f97ce9144 AS runtime
ARG SOURCE_DATE_EPOCH
COPY packaging/container/debian.sources /etc/apt/sources.list.d/debian.sources
COPY packaging/container/runtime-packages.txt /tmp/runtime-packages.txt
RUN rm -f /etc/apt/sources.list \
    && apt-get update \
    && xargs -r apt-get install -y --no-install-recommends < /tmp/runtime-packages.txt \
    && rm -rf \
        /var/lib/apt/lists/* \
        /var/cache/apt/* \
        /var/cache/ldconfig/aux-cache \
        /var/log/apt/* \
        /var/log/dpkg.log \
        /var/log/alternatives.log \
        /tmp/runtime-packages.txt \
    && useradd --no-log-init --create-home --uid 10001 aiworkflow
COPY --from=build /src/dist/*.whl /tmp/
RUN python -m pip install --no-cache-dir --no-deps /tmp/*.whl \
    && rm -f /tmp/*.whl
USER aiworkflow
WORKDIR /workspace
ENTRYPOINT ["ai-workflow"]
