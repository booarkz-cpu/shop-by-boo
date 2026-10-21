ARG NODE_BASE_IMAGE=node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402
ARG NGINX_BASE_IMAGE=nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de
FROM ${NODE_BASE_IMAGE} AS build
# The Mini App is the customer cabinet built for the Telegram surface.
ARG VITE_API_URL=""
ENV NEXT_PUBLIC_API_URL=$VITE_API_URL \
    NEXT_PUBLIC_SURFACE=miniapp \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /src
COPY cabinet/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --ignore-scripts --no-audit --no-fund; else npm install --package-lock=false --ignore-scripts --no-audit --no-fund; fi
COPY cabinet/ .
RUN npm run build:miniapp
FROM ${NGINX_BASE_IMAGE}
COPY --from=build /src/dist /usr/share/nginx/html
COPY miniapp/nginx.conf /etc/nginx/nginx.conf
COPY miniapp/default.conf /etc/nginx/conf.d/default.conf
USER 101:101
EXPOSE 80
CMD ["/bin/sh", "-c", "mkdir -p /tmp/nginx/client_temp /tmp/nginx/proxy_temp /tmp/nginx/fastcgi_temp /tmp/nginx/uwsgi_temp /tmp/nginx/scgi_temp && chmod 1777 /tmp/nginx /tmp/nginx/client_temp /tmp/nginx/proxy_temp /tmp/nginx/fastcgi_temp /tmp/nginx/uwsgi_temp /tmp/nginx/scgi_temp && exec nginx -g 'daemon off;'"]
