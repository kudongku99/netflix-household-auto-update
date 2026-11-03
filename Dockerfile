FROM python:3.12.16-slim@sha256:962f801b08c870ac2a51b72bf02dae38c9a4162319e5e882ec244e198188d54e

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/* /tmp/requirements.txt

WORKDIR /app
COPY src/ .

CMD ["sh", "-c", "exec gunicorn --bind \":${PORT:-8080}\" --workers 1 --threads 1 --timeout 120 main:app"]
