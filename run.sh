#!/usr/bin/env bash
set -e

echo "Loading environment variables..."
# Public demo repo: do not commit real env files.
# Use `env.example` as a reference.
if [ -f "env.example" ]; then
  # shellcheck disable=SC1091
  source env.example
fi

RUN_MODE=${1:-api}

if [[ ${RUN_MODE} == 'api' ]]; then
  export WORKER_NAME=api
  granian --interface asgi \
          --host ${API_HOST} \
          --port ${API_PORT} \
          --workers ${API_WORKERS} \
          --reload-ignore-dirs tools \
          --loop uvloop \
          --reload \
          app.main:app

elif [[ ${RUN_MODE} == 'caption_agent_worker' ]]; then
  echo "Starting caption agent worker..."
  streaq app.workers.caption_agent_worker.worker

elif [[ ${RUN_MODE} == 'api_jobs_worker' ]]; then
  echo "Starting API jobs worker..."
  streaq app.workers.api_jobs_worker.worker

else
  echo "Invalid run mode: ${RUN_MODE}"
  exit 1
fi
