FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home synapse
COPY requirements.txt requirements-production.txt ./
RUN pip install --no-cache-dir -r requirements-production.txt
COPY --chown=synapse:synapse server.py features.py administration.py launch.py safety.py operations.py manage.py schema.sql ./
COPY --chown=synapse:synapse web ./web
COPY --chown=synapse:synapse tools ./tools
RUN mkdir -p /app/data && chown -R synapse:synapse /app/data
USER synapse
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/api/ready',timeout=3)"
# Single worker deliberately: SQLite, upload concurrency and abuse limits are process-local.
CMD ["sh","-c","exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips ${FORWARDED_ALLOW_IPS:-127.0.0.1} --no-access-log --limit-concurrency 100"]
