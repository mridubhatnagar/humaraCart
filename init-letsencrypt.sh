#!/bin/sh
# One-time bootstrap for the nginx + certbot TLS setup (docker-compose.prod.yml).
#
# Chicken-and-egg fix: nginx.conf's HTTPS server block references a cert file
# that doesn't exist yet, so nginx can't start with the real config as-is.
# This creates a throwaway dummy cert first so nginx *can* start, requests
# the real one from Let's Encrypt via that now-running nginx, then reloads.
#
# Run once, from the repo root on the instance, after `git clone` and after
# .env.local is set up. Not part of the normal `docker compose up` flow —
# ongoing renewal is handled by the `certbot` service's renewal loop.

set -e

DOMAIN=humaracart.mridulabs.dev
EMAIL="${LETSENCRYPT_EMAIL:?Set LETSENCRYPT_EMAIL first, e.g. LETSENCRYPT_EMAIL=you@example.com ./init-letsencrypt.sh}"
RSA_KEY_SIZE=4096
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

echo "Creating dummy certificate for $DOMAIN..."
$COMPOSE run --rm --entrypoint "\
  mkdir -p /etc/letsencrypt/live/$DOMAIN && \
  openssl req -x509 -nodes -newkey rsa:$RSA_KEY_SIZE -days 1 \
    -keyout '/etc/letsencrypt/live/$DOMAIN/privkey.pem' \
    -out '/etc/letsencrypt/live/$DOMAIN/fullchain.pem' \
    -subj '/CN=localhost'" certbot

echo "Starting postgres, app, and nginx..."
$COMPOSE up -d postgres app nginx

echo "Deleting dummy certificate..."
$COMPOSE run --rm --entrypoint "\
  rm -rf /etc/letsencrypt/live/$DOMAIN && \
  rm -rf /etc/letsencrypt/archive/$DOMAIN && \
  rm -rf /etc/letsencrypt/renewal/$DOMAIN.conf" certbot

echo "Requesting real certificate for $DOMAIN..."
$COMPOSE run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  -d "$DOMAIN" \
  --email "$EMAIL" \
  --rsa-key-size $RSA_KEY_SIZE \
  --agree-tos \
  --no-eff-email \
  --force-renewal

echo "Reloading nginx..."
$COMPOSE exec nginx nginx -s reload

echo "Starting the certbot renewal loop..."
$COMPOSE up -d certbot

echo "Done. Check: curl -I https://$DOMAIN/health"
