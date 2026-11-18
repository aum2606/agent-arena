FROM node:26-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5 AS build
WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
# next.config.ts bakes the API address into the /api rewrite at build time.
ARG API_URL=http://api:8000
ENV API_URL=$API_URL
RUN npm run build

FROM node:26-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
# The image's own unprivileged user, not root (D-068).
USER node
EXPOSE 3000
CMD ["node", "server.js"]
