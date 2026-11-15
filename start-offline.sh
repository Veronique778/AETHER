#!/usr/bin/env sh
# API + prebuilt UI on one port. Needs only Python 3.11+ and pydantic. Open http://127.0.0.1:8000
cd "$(dirname "$0")/web/backend" && exec python3 -m app.devserver --port 8000 --static ../frontend/dist-offline
