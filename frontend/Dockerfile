# Offline-capable frontend image (OAAS O01).
# Default build uses the public npm registry. For an air-gapped build:
#   1. Transfer/cache both base images and populate frontend/npm-cache
#      (scripts/offline-bundle.sh ships built images; it does not fill this cache)
#   2. docker build --build-arg OFFLINE=1 -t solver-frontend .
ARG OFFLINE=0

FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
# Optional npm cache for offline installs.
COPY npm-cache/ /tmp/npm-cache/

ARG OFFLINE
RUN if [ "$OFFLINE" = "1" ]; then \
      npm ci --offline --cache /tmp/npm-cache; \
    else \
      npm install; \
    fi
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
