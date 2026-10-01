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
RUN if [ "$OFFLINE" = "1" ]; then \
      pip install --no-cache-dir --no-index --find-links=/tmp/wheelhouse -r requirements.txt; \
    else \
      pip install --no-cache-dir -r requirements.txt; \
    fi \
 && rm -rf /tmp/wheelhouse

COPY . .

# The camp layout engine (camp_layout/README.md) is a package of its own in the image.
ENV PYTHONPATH=/app/camp_layout

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
