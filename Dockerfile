FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY pyproject.toml alembic.ini /srv/
COPY app /srv/app
COPY migrations /srv/migrations

# Контракты и общий обвяз приезжают из своих репозиториев по версии,
# указанной в pyproject.toml, поэтому сборке нужен git. В готовом образе
# он не остаётся: ставится и удаляется одним слоем.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && pip install . \
 && apt-get purge -y --auto-remove git \
 && rm -rf /var/lib/apt/lists/*

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
 && useradd --system --uid 1005 analytics && chown -R analytics /srv
USER analytics

EXPOSE 8008
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "app"]
