FROM node:20-slim AS build

RUN npm install -g pnpm@10.34.4

WORKDIR /app/apps/web

COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY apps/web/ ./

# Empty means same-origin. The container web server proxies /api to FastAPI,
# so production does not expose or bake an internal backend address into JS.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN pnpm build

FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY infra/docker/web.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/web/dist /usr/share/nginx/html

EXPOSE 8080
