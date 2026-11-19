# syntax=docker/dockerfile:1
ARG NODE_IMAGE=node:22.22.1-alpine
ARG NGINX_IMAGE=nginx:stable-alpine
FROM ${NODE_IMAGE} AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY index.html tsconfig.json vite.config.ts vitest.config.ts ./
COPY src/ ./src/
COPY public/ ./public/
# Same-origin path is fixed for this image. No Docker hostname in the browser.
ENV VITE_API_BASE_URL=/api
RUN npm run build

FROM ${NGINX_IMAGE} AS runtime
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist/ /usr/share/nginx/html/
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/nginx-health || exit 1
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
