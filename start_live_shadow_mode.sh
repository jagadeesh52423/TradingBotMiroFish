#!/bin/bash
# Start TRUE LIVE SHADOW MODE
# Production-data shadow tracking, NQ-only, real WhatsApp alerts

set -e

cd "$(dirname "$0")/market-swarm-lab"
source .venv/bin/activate

echo "======================================================"
echo "🚀 LIVE SHADOW MODE STARTUP — 2026-05-12"
echo "======================================================"
echo ""
echo "Status:"
echo "  Mode: SHADOW (live alerts, no execution)"
echo "  Feed: Rithmic (NQM6.CME@RITHMIC only)"
echo "  Bookmap: Verified running"
echo "  Time: $(date)"
echo ""

# Verify Bookmap is running
if ! pgrep -f "Bookmap.app" > /dev/null; then
    echo "❌ ERROR: Bookmap is not running"
    echo "   Please start Bookmap first"
    exit 1
fi

# Verify JSONL directory exists
mkdir -p state/orderflow/bookmap_api

# Check for today's JSONL (should be created by OrderflowRecorder)
JSONL_FILE="state/orderflow/bookmap_api/es_orderflow_2026-05-12.jsonl"
if [ ! -f "$JSONL_FILE" ]; then
    echo "⚠️  WARNING: $JSONL_FILE does not exist yet"
    echo "   This will be created when Bookmap feed connects"
    touch "$JSONL_FILE"
fi

echo ""
echo "Starting alert engine..."
echo "======================================================"
echo ""

# Run the alert engine
exec python scripts/run_live_orderflow_alerts.py \
  --watch "state/orderflow/bookmap_api/*.jsonl" \
  --spy-source cached \
  --notify whatsapp \
  --confidence-threshold 75 \
  --cooldown-minutes 10 \
  --dry-run \
  --interval 5.0
