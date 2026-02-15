#!/usr/bin/env bash
# Check which Enhanced/Premium voices are installed
# Usage: bash scripts/lib/check-enhanced-voices.sh

set -euo pipefail

say -v '?' | grep -E "(Enhanced|Premium)"
