# syntax=docker/dockerfile:1
FROM python:3.11.9-slim-bookworm@sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317 AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --only-binary=:all: --no-cache-dir -r requirements.txt && pip check \
    && useradd --uid 10002 --create-home portal
COPY portal/ ./portal/
COPY alembic.ini ./
COPY migrations/ ./migrations/
USER portal
EXPOSE 8000
CMD ["uvicorn", "portal.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--no-proxy-headers"]

FROM runtime AS test
USER root
COPY requirements-test.txt ./
RUN pip install --only-binary=:all: --no-cache-dir -r requirements-test.txt
COPY tests/ ./tests/
COPY pytest.ini ./
USER portal
