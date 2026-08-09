# CoolRx API + worker. One image, two commands.
#
# The system packages below are the single most common half-day loss in a project
# like this, so they are pinned here and the image is built on day 1 rather than
# on deploy day (SRS §24.3):
#
#   libgdal-dev / gdal-bin / libgeos-dev / libproj-dev
#       → rasterio, rasterstats, shapely, pyproj, geopandas
#   libpango / libcairo / libgdk-pixbuf
#       → WeasyPrint (PDF rendering)
#
# Python is pinned to 3.12: the geospatial and ML wheels lag newest-Python by
# months, and on 3.14 pip falls back to building GDAL from source.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        # Geospatial
        libgdal-dev \
        gdal-bin \
        libgeos-dev \
        libproj-dev \
        # WeasyPrint
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        shared-mime-info \
        # Build toolchain for any sdist fallback
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first so the layer caches independently of source changes.
COPY pyproject.toml ./
RUN pip install --upgrade pip uv && uv pip install --system --no-cache .

# Application code, model artifacts and the intervention catalog.
COPY . .

# Run unprivileged.
RUN useradd --create-home --shell /usr/sbin/nologin coolrx \
    && chown -R coolrx:coolrx /app
USER coolrx

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

# API. The worker overrides this with:
#   rq worker --url "$REDIS_URL" coolrx
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
