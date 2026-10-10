FROM python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 appuser

COPY --chown=appuser:appuser auth_service ./auth_service
COPY --chown=appuser:appuser migrations ./migrations
COPY --chown=appuser:appuser alembic.ini ./alembic.ini
COPY --chown=appuser:appuser architecture.html TEST_REPORT.md ./
COPY --chown=appuser:appuser tests ./tests
USER appuser

CMD ["sh", "-c", "alembic upgrade head && uvicorn auth_service.main:app --host 0.0.0.0 --port 8002"]