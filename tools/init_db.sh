#!/bin/bash

set -e

echo "Create collections..."
python app/domain/schemas.py

echo "Load data..."
python tools/init_data.py

echo '✅ Database initialization complete'
