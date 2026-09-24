#!/bin/bash
# English OS dev servers: FastAPI (8770) + Vite (5173). Ctrl-C stops both.
cd "$(dirname "$0")/.."
.venv/bin/uvicorn app.server:app --port 8770 &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT
cd frontend && exec npm run dev
