# Rebuild Caddy with a patched Go toolchain: upstream v2.11.9 binaries
# were compiled with Go 1.27.3 (CVE-2026-97054; fixed in 1.27.4).
FROM golang:1.27.4-alpine AS caddy_builder
RUN go version | grep -F 'go1.27.4' && \
    CGO_ENABLED=0 go install github.com/caddyserver/caddy/v2/cmd/caddy@v2.11.9 && \
    go version -m /go/bin/caddy | grep -F 'go1.27.4'

ARG CADDY_BASE_IMAGE=caddy:2.11-alpine@sha256:78bd35025c7ba85961dd149ae670315129954e77abe2383ac47c89106b35ade9
FROM ${CADDY_BASE_IMAGE}
COPY --from=caddy_builder /go/bin/caddy /usr/bin/caddy
# The upstream executable has CAP_NET_BIND_SERVICE. With cap_drop: ALL this
# file capability makes exec fail with EPERM. Ports are enabled by the
# container's ip_unprivileged_port_start sysctl; no capability is needed.
# v28.123.0: the base image is pinned by digest, so the package fixes published since are installed here.
RUN apk upgrade --no-cache && apk add --no-cache libcap && setcap -r /usr/bin/caddy
USER 10001:10001
