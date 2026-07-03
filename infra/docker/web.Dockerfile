FROM node:20-slim

RUN npm install -g pnpm

WORKDIR /app/apps/web

COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY apps/web/ ./

EXPOSE 3000
CMD ["pnpm", "dev"]
