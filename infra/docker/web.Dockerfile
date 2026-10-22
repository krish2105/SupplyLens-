FROM node:24-slim AS base
# Extra root certificates (TLS-inspecting proxy) are handed to Node directly: node:slim has no update-ca-certificates.
COPY infra/docker/ca/ /usr/local/share/ca-certificates/extra/
RUN if ls /usr/local/share/ca-certificates/extra/*.crt >/dev/null 2>&1; then cat /usr/local/share/ca-certificates/extra/*.crt > /etc/extra-ca.pem; else : > /etc/extra-ca.pem; fi
ENV NODE_EXTRA_CA_CERTS=/etc/extra-ca.pem

FROM base AS deps
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
FROM base AS build
WORKDIR /web
COPY --from=deps /web/node_modules ./node_modules
COPY apps/web ./
# the API contract the client is typed from (tsconfig path @contracts -> ../../packages/contracts)
COPY packages/contracts /packages/contracts
ARG SUPPLYLENS_API_URL=http://api:8000
ENV SUPPLYLENS_API_URL=$SUPPLYLENS_API_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build
FROM base
WORKDIR /web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /web ./
USER node
EXPOSE 3100
CMD ["npm", "run", "start"]
