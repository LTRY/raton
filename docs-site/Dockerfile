# Build context is the repository root: the site reads ../docs/spec. See docs/spec/04-configuration-et-deploiement.md.
FROM node:22-alpine AS build
WORKDIR /site
COPY docs-site/package.json docs-site/package-lock.json ./
RUN npm ci
COPY docs-site/ ./
COPY docs/spec /docs/spec
RUN npm test && npm run build

FROM nginx:1.27-alpine
COPY --from=build /site/dist /usr/share/nginx/html
