FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir . && useradd --create-home appuser \
    && mkdir -p /app/data && chown appuser:appuser /app/data
COPY alembic.ini ./
COPY migrations ./migrations
COPY tests ./tests
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim AS test
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir '.[dev]' \
    && mkdir -p /app/data && chown 1000:1000 /app/data
COPY alembic.ini ./
COPY migrations ./migrations
COPY tests ./tests
CMD ["pytest"]
