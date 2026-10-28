# Alpine: musl libc, no Debian packages, minimal CVE surface.
# Flask + gunicorn ship pure-Python wheels; no compiler needed.
FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/data/inventory.db

# Apply any pending Alpine security patches, create non-root user and data dir.
RUN apk upgrade --no-cache \
    && addgroup -S app \
    && adduser  -S -G app -H -D app \
    && mkdir -p /data && chown app:app /data

WORKDIR /app
COPY requirements.txt .
# pip is only needed at build time; remove it so Trivy doesn't flag its bundled libs.
RUN pip install -r requirements.txt && pip uninstall -y pip
COPY --chown=app:app app.py .

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "app:app"]
