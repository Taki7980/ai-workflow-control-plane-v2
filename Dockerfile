# syntax=docker/dockerfile:1.27.0@sha256:bde3983e9c939224420ddaf6b784cc30e09b035a4dea01f581230c50809f372e

FROM ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 AS uv

FROM python:3.15.0rc2-slim-trixie@sha256:14684656c0069b49e897c63d52bbbe7df8a4bf189911a597403fd3b4ffeaae06 AS build
ARG SOURCE_DATE_EPOCH
WORKDIR /src
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY ai_workflow ./ai_workflow
RUN uv sync --locked --only-group build \
    && uv run --locked --no-sync python -m build --wheel --no-isolation

FROM python:3.15.0rc2-slim-trixie@sha256:14684656c0069b49e897c63d52bbbe7df8a4bf189911a597403fd3b4ffeaae06 AS runtime
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
    && python -m pip uninstall -y msgpack setuptools \
    && rm -rf \
        /usr/local/lib/python3.14/site-packages/pip \
        /usr/local/lib/python3.14/site-packages/pip-*.dist-info \
        /usr/local/lib/python3.14/site-packages/msgpack \
        /usr/local/lib/python3.14/site-packages/msgpack-*.dist-info \
        /usr/local/lib/python3.14/site-packages/setuptools \
        /usr/local/lib/python3.14/site-packages/setuptools-*.dist-info \
        /usr/local/lib/python3.14/ensurepip \
        /usr/local/bin/pip \
        /usr/local/bin/pip3 \
        /usr/local/bin/pip3.14 \
        /tmp/*.whl
USER aiworkflow
WORKDIR /workspace
ENTRYPOINT ["ai-workflow"]
