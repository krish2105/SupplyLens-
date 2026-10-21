FROM node:24-slim AS deps
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
FROM node:24-slim AS build
WORKDIR /web
COPY --from=deps /web/node_modules ./node_modules
COPY apps/web ./
ARG SUPPLYLENS_API_URL=http://api:8000
ENV SUPPLYLENS_API_URL=$SUPPLYLENS_API_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build
FROM node:24-slim
WORKDIR /web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /web ./
USER node
EXPOSE 3100
CMD ["npm", "run", "start"]
