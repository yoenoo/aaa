#!/bin/sh
set -eu
config=/workspace/services/partner-callback-router/config/production.yaml
grep -q '^duplicate_suppression_seconds: 120$' "$config"
grep -q '^max_delivery_attempts: 4$' "$config"
printf '%s\n' 'config check passed'
