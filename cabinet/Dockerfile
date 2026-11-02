ARG NODE_BASE_IMAGE=node:26-alpine@sha256:c6ad9e9c1d80f6eb607c26b4b0a132ff7a2344fad1c78ea3baa2a7d4c8de6d94
ARG NGINX_BASE_IMAGE=nginx:1.30-alpine@sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949
FROM ${NODE_BASE_IMAGE} AS build
ARG VITE_API_URL=""
ENV NEXT_PUBLIC_API_URL=$VITE_API_URL \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /src
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --ignore-scripts --no-audit --no-fund; else npm install --package-lock=false --ignore-scripts --no-audit --no-fund; fi
COPY . .
RUN npm run build
FROM ${NGINX_BASE_IMAGE}
COPY --from=build /src/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
COPY default.conf /etc/nginx/conf.d/default.conf
USER 101:101
EXPOSE 80
CMD ["/bin/sh", "-c", "mkdir -p /tmp/nginx/client_temp /tmp/nginx/proxy_temp /tmp/nginx/fastcgi_temp /tmp/nginx/uwsgi_temp /tmp/nginx/scgi_temp && chmod 1777 /tmp/nginx /tmp/nginx/client_temp /tmp/nginx/proxy_temp /tmp/nginx/fastcgi_temp /tmp/nginx/uwsgi_temp /tmp/nginx/scgi_temp && exec nginx -g 'daemon off;'"]
