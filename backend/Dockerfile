# Offline-capable backend image (OAAS O01).
# Default build still pulls from PyPI. For an air-gapped build:
#   1. Run scripts/offline-bundle.sh (or copy wheels into backend/wheelhouse/)
#   2. docker build --build-arg OFFLINE=1 -t solver-backend .
ARG OFFLINE=0

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# Optional local wheelhouse for offline installs (ignored when empty).
COPY wheelhouse/ /tmp/wheelhouse/

ARG OFFLINE
# Online: a dropped connection mid-download (an "SSL record layer failure" on
# a large wheel) is retried -- by pip, then the whole install up to three
# times. The pip cache lives in a BuildKit cache mount, outside the image, so
# a retry or the next rebuild does not download again what already arrived.
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$OFFLINE" = "1" ]; then \
      pip install --no-index --find-links=/tmp/wheelhouse -r requirements.txt; \
    else \
      tries=0; \
      until pip install --retries 10 --timeout 60 -r requirements.txt; do \
        tries=$((tries + 1)); \
        if [ "$tries" -ge 3 ]; then echo "pip install failed 3 times: check the network" >&2; exit 1; fi; \
        echo "pip install was interrupted; trying again ($tries/3)" >&2; sleep 5; \
      done; \
    fi \
 && rm -rf /tmp/wheelhouse

COPY . .

# The camp layout engine (camp_layout/README.md) is a package of its own in the image.
ENV PYTHONPATH=/app/camp_layout

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
