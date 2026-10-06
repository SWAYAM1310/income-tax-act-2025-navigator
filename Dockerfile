# The API (python -m statnav.api). Built by docker-compose.yml as the `api` service.
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
WORKDIR /app

# dependencies first, so code changes do not reinstall them
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

# statnav.config resolves ROOT from the source tree, so the project stays an editable install
COPY src ./src
COPY configs ./configs
COPY results ./results
RUN uv sync --locked --no-dev

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "python", "-m", "statnav.api", "--host", "0.0.0.0", "--port", "8000"]
