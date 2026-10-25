# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS build
WORKDIR /app
# package-lock.json is copied when present so the build is reproducible. Generate and commit it
# once with `npm run lockfile`; until then the build falls back to `npm install` and says so.
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; \
    else echo "WARNING: no package-lock.json, dependency versions are not locked" >&2; npm install --no-audit --no-fund; fi
COPY . .
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
