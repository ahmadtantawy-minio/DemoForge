# ── Stage 1: deps ────────────────────────────────────────────────────────
FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

# ── Stage 2: build (Vite production bundle) ───────────────────────────────
FROM deps AS builder
# Baked into import.meta.env (see vite.config.ts). hub-push.sh passes the repo's git describe.
ARG VITE_DEMOFORGE_RELEASE_VERSION=unknown
ENV VITE_DEMOFORGE_RELEASE_VERSION=$VITE_DEMOFORGE_RELEASE_VERSION
ENV NODE_ENV=production
COPY . .
RUN npm run build

# ── Stage 3: dev (Vite HMR) — NOT the default image; use: docker build --target dev
FROM deps AS dev
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]

# ── Stage 4: serve (production) — MUST be last: hub-push / docker build default ──
FROM nginx:alpine AS prod
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
