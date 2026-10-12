FROM python:3.12-slim@sha256:9e01bf1ae5db7649a236da7be1e94ffbbbdd7a93f867dd0d8d5720d9e1f89fab
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --gid 10001 keyholder && useradd --uid 10001 --gid 10001 --no-create-home keyholder
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir uv==0.13.0 && uv sync --frozen --no-dev --no-editable
COPY alembic.ini ./
COPY migrations ./migrations
RUN mkdir /data && chown 10001:10001 /data
USER 10001:10001
EXPOSE 18000
CMD ["/app/.venv/bin/uvicorn", "keyholder.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "18000", "--workers", "1", "--no-access-log", "--no-proxy-headers", "--log-level", "info"]
