# CoolRx API + worker. One image, two commands.
#
# ## Why almost nothing is installed from apt
#
# This file used to install libgdal-dev, gdal-bin, libgeos-dev, libproj-dev,
# libpango, libcairo and libgdk-pixbuf, on the reasoning that the geospatial
# stack is "the single most common half-day loss in a project like this". That
# was true for years. It is not true here, and those packages cost 482 MB.
#
# **The wheels bundle their own libraries.** Checked inside the built image:
#
#   rasterio 1.5.1  ships GDAL 3.12.4 in rasterio.libs
#   pyproj   3.7.2  ships PROJ 25.9.5 in pyproj.libs
#   shapely  2.1.2  ships GEOS 3.13.1 in shapely.libs
#
# Debian bookworm's libgdal is 3.6 — not merely redundant, but a *different and
# older* GDAL than the one the code actually calls. Installing it changed nothing
# except the image size.
#
# **WeasyPrint is not a dependency.** pyproject.toml says so explicitly and gives
# the reason: "reportlab rather than weasyprint: weasyprint renders HTML through
# Pango... reportlab ships pure-Python wheels and draws the document directly".
# Pango, Cairo and gdk-pixbuf were being installed for a library the project had
# deliberately chosen not to use.
#
# Anything added back here should come with a demonstration that an import fails
# without it.
#
# Python is pinned to 3.12: the geospatial and ML wheels lag newest-Python by
# months, and on 3.14 pip falls back to building GDAL from source.

# ── builder ──────────────────────────────────────────────────────────────────
#
# A separate stage so the compiler toolchain never reaches the runtime image.
# Every current dependency resolves to a manylinux wheel, so build-essential is
# belt and braces — but one sdist fallback in a future dependency bump would
# otherwise fail the build somewhere nobody can debug it.

FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first so the layer caches independently of source changes.
#
# `-r pyproject.toml` installs the declared dependencies WITHOUT building the
# project. Installing `.` here instead fails with "package directory 'agent'
# does not exist": pyproject lists the top-level packages explicitly, and at this
# point only pyproject.toml has been copied. Copying the source first would fix
# the error and destroy the caching this layer exists for.
COPY pyproject.toml ./
RUN pip install --upgrade pip uv \
    && uv pip install --system --no-cache -r pyproject.toml

# ── runtime ──────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Two packages, each with a reason.
#
#   curl        the HEALTHCHECK below, and nothing else
#   libexpat1   rasterio's bundled GDAL links against the *system* expat rather
#               than vendoring it. It used to arrive as a transitive dependency
#               of libgdal-dev; dropping that package took it too, and
#               `import rasterio` then failed with
#               "libexpat.so.1: cannot open shared object file".
#
# Found by running ldd across every bundled .so in site-packages/*.libs and
# keeping the entries with no wheel hash suffix: a name like
# libgeos-3ef06f11.so.3.13.1 resolves through RPATH inside its own wheel, while
# a bare libexpat.so.1 is a genuine system dependency.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libexpat1 \
    && rm -rf /var/lib/apt/lists/*

# The resolved environment, without the toolchain that produced it.
# /usr/local/bin carries the console scripts the container is started with:
# uvicorn, rq, alembic.
COPY --from=builder /usr/local/lib/python3.12/site-packages \
                    /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

WORKDIR /app

# Application code, model artifacts and the intervention catalog.
COPY . .

# Now the packages exist, so the project itself can be installed. --no-deps
# because the builder already resolved them, and re-resolving here would reach
# the network and could pick a different version than the one tested.
RUN pip install --no-cache-dir --no-deps .

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
