# Production image for blockless-api.
#
# Build from the repo root:
#   git submodule update --init --recursive   # third_party/browser-micropython-skills is a submodule
#   docker build -t blockless-api .
# The COPY below copies whatever is on disk, so the submodule MUST be initialized first or the
# image ships an empty skills dir and the app fails validate_config at startup (app/main.py).
# Render initializes public submodules during clone; CI uses actions/checkout submodules: recursive.
# The app resolves content/, contracts/, and browser skills from /app.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PORT=8080 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_PREFERENCE=only-system \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install deps first so the layer caches independently of source changes.
# psycopg[binary] ships its own libpq wheel; no apt build deps needed.
# uv installs the locked, prod-only (--no-dev) set into /app/.venv (UV_PROJECT_ENVIRONMENT);
# the PATH above puts that venv first so `uvicorn` in the CMD resolves to it.
COPY --from=ghcr.io/astral-sh/uv:0.11.13 /uv /bin/uv
COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-dev

# Copy preserving the path geometry the code expects (see header note).
COPY app /app/app
COPY content /app/content
COPY pyproject.toml /app/pyproject.toml
COPY third_party/browser-micropython-skills /app/third_party/browser-micropython-skills
COPY contracts /app/contracts

# Drop privileges. Code is read-only at runtime (state lives in Postgres).
RUN useradd --create-home --uid 10001 app
USER app

# Liveness probe for `docker run`.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8080')+'/v1/health')" || exit 1

# Shell form so ${PORT}/${WEB_CONCURRENCY} expand; exec so uvicorn gets PID 1 signals.
# Default to ONE worker: the app keeps OAuth codes, rate-limit counters, the LLM
# concurrency/breaker state, and the recipe cache in-process, so >1 worker silently
# splits that state. Override WEB_CONCURRENCY only after moving that state to the DB.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers ${WEB_CONCURRENCY:-1}"]
