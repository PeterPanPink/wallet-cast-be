#!/usr/bin/env bash
set -e

if [[ ${RUN_MODE} == 'api' ]]; then
  export WORKER_NAME=api
  export API_PORT=${API_PORT:-8000}
  granian --interface asgi \
          --host 0.0.0.0 \
          --port ${API_PORT} \
          --workers ${API_WORKERS} \
          --loop uvloop \
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
