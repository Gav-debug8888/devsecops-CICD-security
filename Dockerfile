# Hardened image: slim base, non-root user, no build tools, healthcheck.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/data/inventory.db

RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app && useradd --system --gid app --home /app app \
    && mkdir -p /data && chown app:app /data

WORKDIR /app
COPY requirements.txt .
# pip is only needed at build time. Its vendored libraries (urllib3, msgpack,
# pkg_resources) carry their own CVEs that Trivy flags, so remove it afterwards.
RUN pip install -r requirements.txt && pip uninstall -y pip
COPY --chown=app:app app.py .

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "app:app"]
