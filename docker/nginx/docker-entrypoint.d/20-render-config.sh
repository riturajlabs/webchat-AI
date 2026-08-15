#!/bin/sh
# WebChat AI - render nginx vhost configs from templates (Railway adaptation).
#
# The same image runs in two topologies:
#   * docker compose (defaults):   upstreams api:8000 / widget:80 / dashboard:3000,
#                                  HTTP on port 80 (or ${PORT:-80}).
#   * Railway public gateway:      PORT injected by Railway, NGINX_*_UPSTREAM set
#                                  to the private service URLs, ENABLE_TLS=0
#                                  (Railway terminates HTTPS).
#
# Substitution uses a FIXED allowlist of variable names, so nginx runtime
# variables ($host, $scheme, $remote_addr, $proxy_add_x_forwarded_for, ...)
# are never treated as shell environment variables by envsubst.
set -eu

TPL_DIR=/etc/nginx/conf.d.tpl
CONF_DIR=/etc/nginx/conf.d

# Defaults for the rendered variables (Railway overrides PORT and the
# upstreams via env; docker compose passes explicit values already).
export PORT="${PORT:-80}"
export NGINX_HTTPS_PORT="${NGINX_HTTPS_PORT:-443}"
export NGINX_API_UPSTREAM="${NGINX_API_UPSTREAM:-api:8000}"
export NGINX_WIDGET_UPSTREAM="${NGINX_WIDGET_UPSTREAM:-widget:80}"
export NGINX_DASHBOARD_UPSTREAM="${NGINX_DASHBOARD_UPSTREAM:-dashboard:3000}"

# Allowlist of variable names substituted into the templates.
SUBST_VARS='$PORT $NGINX_HTTPS_PORT $NGINX_API_UPSTREAM $NGINX_WIDGET_UPSTREAM $NGINX_DASHBOARD_UPSTREAM'

render() {
    src="$1"
    dst="$2"
    mkdir -p "$CONF_DIR"
    # envsubst replaces only the variables listed above; every other
    # $reference in the config (e.g. $host, $scheme) is left untouched.
    # shellcheck disable=SC2016
    envsubst "$SUBST_VARS" <"$src" >"$dst"
    echo "[nginx] rendered $(basename "$dst")"
}

render "$TPL_DIR/http.conf.template" "$CONF_DIR/http.conf"

if [ "${ENABLE_TLS:-0}" = "1" ]; then
    render "$TPL_DIR/tls.conf.template" "$CONF_DIR/tls.conf"
    echo "[nginx] ENABLE_TLS=1 - serving HTTPS on \${NGINX_HTTPS_PORT:-443} (certs at /etc/nginx/tls)"
else
    rm -f "$CONF_DIR/tls.conf"
    echo "[nginx] ENABLE_TLS=0 - plain HTTP vhost only (no certificate files required)"
fi
