#!/usr/bin/env bash
# Generate a self-signed TLS certificate for localhost.
# Required because Yahoo OAuth only allows https:// redirect URIs.
#
# Usage: bash auth/gen_cert.sh
# Outputs: auth/localhost.crt and auth/localhost.key

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT="$SCRIPT_DIR/localhost.crt"
KEY="$SCRIPT_DIR/localhost.key"

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$KEY" \
  -out "$CERT" \
  -days 365 \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

echo ""
echo "Certificate generated:"
echo "  $CERT"
echo "  $KEY"
echo ""
echo "Next steps:"
echo "  1. Register https://localhost:8000/auth/callback in your Yahoo Developer app"
echo "  2. Run: uv run python auth/web_server.py"
echo "  3. Visit https://localhost:8000 (accept the browser cert warning)"
