FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=10000 \
    SLEEP_DB_PATH=/data/sleep.db \
    SLEEP_TIMEZONE=America/New_York

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup --system app \
    && adduser --system --ingroup app app \
    && mkdir -p /data \
    && chown app:app /data

COPY --chown=app:app app.py database.py ./
COPY --chown=app:app importers ./importers
COPY --chown=app:app static ./static
COPY --chown=app:app templates ./templates

USER app

EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['PORT']}/healthz\", timeout=2)"]

CMD ["/bin/sh", "-c", "exec gunicorn app:app --bind \"${HOST}:${PORT}\" --workers 2 --timeout 120"]
