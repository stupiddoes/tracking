#!/bin/sh
# Serve HTTPS on 8443 only when a Cloudflare Origin Certificate is mounted, so a missing
# certificate never stops the site; Cloudflare can stay on "Flexible" over port 80 until then.
set -eu
CERT=/etc/nginx/certs/origin.pem
KEY=/etc/nginx/certs/origin-key.pem
mkdir -p /tmp/nginx-ssl
if [ -r "$CERT" ] && [ -r "$KEY" ]; then
  printf 'listen 8443 ssl;\nhttp2 on;\nssl_certificate %s;\nssl_certificate_key %s;\n' "$CERT" "$KEY" > /tmp/nginx-ssl/listen.conf
  echo "origin-cert: HTTPS enabled on 8443"
else
  rm -f /tmp/nginx-ssl/listen.conf
  echo "origin-cert: no certificate in /etc/nginx/certs, serving HTTP only"
fi
