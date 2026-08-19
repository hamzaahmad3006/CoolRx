# CoolRx frontend — multi-stage Next.js build.
#
# The backend already had a Dockerfile; this one was missing, which meant the
# compose stack could not serve the UI and AC-20 (a public, functional demo URL)
# had no container to deploy.
#
# Three stages so the runtime image carries neither the toolchain nor the source:
# deps installs from the lockfile, builder compiles, runner ships the standalone
# output as a non-root user.

# ── deps ─────────────────────────────────────────────────────────────────────
FROM node:22-alpine AS deps
WORKDIR /app
# Copied alone so this layer is cached until the lockfile itself changes.
COPY package.json package-lock.json ./
RUN npm ci

# ── builder ──────────────────────────────────────────────────────────────────
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Public build-time configuration. NOTHING SECRET MAY APPEAR HERE: NEXT_PUBLIC_*
# values are inlined into the client bundle and are readable by anyone who opens
# the page. The FortyGuard key stays server-side, in the API container only.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ARG NEXT_PUBLIC_USE_FIXTURES=false
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_USE_FIXTURES=$NEXT_PUBLIC_USE_FIXTURES \
    NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ── runner ───────────────────────────────────────────────────────────────────
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001

# `output: "standalone"` in next.config.ts emits a self-contained server bundle;
# without it this stage would need the full node_modules tree.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
