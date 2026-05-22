# mdflow — CPU-only image.
#
# Includes LibreOffice (legacy doc/ppt -> PDF) and CJK fonts for soffice
# rendering. pyhwp (HWP 5.0) uses lxml, so no xsltproc/libxslt system dep is
# needed. GPU / Marker (marker-pdf + torch) is a separate image/tag, deferred
# with milestone M2b.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        libreoffice-impress \
        libreoffice-calc \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Build the package from source. Only pyproject + src are needed for the
# hatchling wheel; the rest is excluded via .dockerignore.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir ".[hwp]"

ENV MDFLOW_CACHE_DIR=/var/cache/mdflow
EXPOSE 8000

CMD ["mdflow", "serve", "--host", "0.0.0.0", "--port", "8000"]
