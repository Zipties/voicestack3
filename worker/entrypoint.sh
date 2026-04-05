#!/bin/sh
# Seed model cache from image layer to persistent volume on first start
cp -rn /app/model_cache/* /data/model_cache/ 2>/dev/null || true
exec python worker.py
