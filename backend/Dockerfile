ARG PYTHON_BASE_IMAGE=python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9
FROM ${PYTHON_BASE_IMAGE}
# pg_dump must not be older than the server: install the PostgreSQL 18 client from the
# official PGDG repository (Debian ships an older major). The signing key is checked by fingerprint.
ARG PG_CLIENT_MAJOR=18
ARG PGDG_KEY_FINGERPRINT=B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl openssl ca-certificates gnupg; \
    install -d /usr/share/postgresql-common/pgdg; \
    curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc; \
    gpg --show-keys --with-colons /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc | grep -q "^fpr:::::::::${PGDG_KEY_FINGERPRINT}:"; \
    . /etc/os-release; \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends "postgresql-client-${PG_CLIENT_MAJOR}"; \
    apt-get purge -y --auto-remove gnupg; \
    rm -rf /var/lib/apt/lists/*; \
    pg_dump --version | grep -q "PostgreSQL) ${PG_CLIENT_MAJOR}\."
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN addgroup --system --gid 10001 app && adduser --system --uid 10001 --ingroup app app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY app ./app
COPY worker.py ./worker.py
COPY scripts/staging-e2e.sh ./staging-e2e.sh
COPY entrypoint.sh ./entrypoint.sh
RUN chmod 0555 ./entrypoint.sh ./staging-e2e.sh
RUN mkdir -p /data/media /data/backups /data/app-packages && chown -R 10001:10001 /data
USER 10001:10001
ENTRYPOINT ["./entrypoint.sh"]
