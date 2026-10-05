# Offline-capable backend image (OAAS O01).
# The offline bundle ships a prebuilt image. To rebuild on an air-gapped host,
# transfer/cache PYTHON_BASE and copy wheels into backend/wheelhouse/ first.
# Include Pango in PYTHON_BASE to retain PDF export; otherwise the printable
# report remains available as its documented fallback.
ARG OFFLINE=0
ARG PYTHON_BASE=python:3.12-slim

FROM ${PYTHON_BASE}

WORKDIR /app
ARG OFFLINE

# Pango and a font for WeasyPrint, which lays out the run report as a PDF (export?format=pdf).
RUN if [ "$OFFLINE" = "1" ]; then \
      echo "Offline build: skipping apt; PDF export uses its printable-report fallback unless PYTHON_BASE includes Pango and DejaVu fonts."; \
    else \
      apt-get update \
      && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fonts-dejavu-core \
      && rm -rf /var/lib/apt/lists/*; \
    fi

COPY requirements.txt .
# Optional local wheelhouse for offline installs (ignored when empty).
COPY wheelhouse/ /tmp/wheelhouse/

# Online: a connection cut mid-download (an "SSL record layer failure" on a
# large wheel such as scipy or casadi) is resumed from where it stopped, not
# started over: pip is upgraded first (a small download) to a version that
# resumes (--resume-retries, pip 25.2+). Should pip still give up, the whole
# install runs again, up to eight times. The pip cache lives in a BuildKit
# cache mount, outside the image, so finished wheels are never downloaded twice.
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$OFFLINE" = "1" ]; then \
      pip install --no-index --find-links=/tmp/wheelhouse -r requirements.txt; \
    else \
      tries=0; \
      until pip install --retries 10 --timeout 60 --upgrade "pip>=25.2" \
         && pip install --retries 10 --timeout 60 --resume-retries 50 -r requirements.txt; do \
        tries=$((tries + 1)); \
        if [ "$tries" -ge 8 ]; then echo "pip install failed 8 times: check the network (antivirus HTTPS scanning, VPN or proxy)" >&2; exit 1; fi; \
        echo "pip install was interrupted; trying again ($tries/8)" >&2; sleep 10; \
      done; \
    fi \
 && rm -rf /tmp/wheelhouse

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
