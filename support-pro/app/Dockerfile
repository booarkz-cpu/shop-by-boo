FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv
COPY requirements.txt .
# The base image is pinned by digest: the package fixes published since are installed here. The packaging tools
# are not needed to run the app and carry bundled libraries with known vulnerabilities: they are removed (v28.123.0).
RUN set -eux; apt-get update; apt-get upgrade -y --no-install-recommends; rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt \
    && (pip uninstall -y setuptools wheel || true) \
    && python -m pip uninstall -y pip \
    && useradd --uid 10001 --create-home support \
    && mkdir -p /data/uploads && chown support:support /data/uploads
COPY app ./app
COPY alembic.ini .
COPY alembic ./alembic
USER support
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
