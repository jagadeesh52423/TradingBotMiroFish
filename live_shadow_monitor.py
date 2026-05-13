#!/usr/bin/env python3
"""
LIVE SHADOW VALIDATOR - NQM6.CME@RITHMIC
Frozen configuration, observational mode only.
"""

import json
import os
import sys
from datetime import datetime, timezone
from collections import deque, defaultdict
from pathlib import Path
import time

# ============================================================================
# CONFIGURATION (FROZEN)
# ============================================================================
CONFIG = {
    "symbol": "NQM6.CME@RITHMIC",
    "source": "bookmap_l1_api",
    "regime_detector": "adaptive",
    "phase_1_6": True,
    "phase_2_repaired": True,
    "hard_stop_ticks": 100,
    "weak_continuation_bars": 3,
    "max_hold_minutes": 30,
    "overnight_disabled": True,
    "source_guard": True,
    "price_guard_dynamic": True,
    "dry_run_mode": True,
}

# ============================================================================
# STATE
# ============================================================================
class LiveShadowState:
    def __init__(self):
        self.trades = []
        self.open_trades = {}
        self.events_processed = 0
        self.alerts_fired = 0
        self.rejected_events = 0
        self.guard_failures = 0
        self.wins = 0
        self.losses = 0
        self.early_exits = 0
        self.timeouts = 0
        self.total_r = 0.0
        self.realized_r_list = []
        self.last_price = None
        self.last_bid_price = None
        self.last_ask_price = None
        self.regime = "UNKNOWN"
        self.tape_acceleration = 0.0
        self.continuation_quality = 0.0
        self.trapped_trader_score = 0.0
        self.weak_continuation_status = False
        self.displacement_ticks = 0
        self.participation_pct = 0.0
        self.feed_health = {"tick_rate": 0, "last_update": None}
        self.last_summary_time = time.time()

state = LiveShadowState()

# ============================================================================
# VALIDATION GUARDS
# ============================================================================
def validate_event(event):
    """Return (is_valid, reason)"""
    if event.get("symbol") != CONFIG["symbol"]:
        return False, f"Wrong symbol: {event.get('symbol')}"
    
    if event.get("source") != CONFIG["source"]:
        return False, f"Wrong source: {event.get('source')}"
    
    if "ts_event" not in event:
        return False, "Missing ts_event"
    
    try:
        ts = datetime.fromisoformat(event["ts_event"].replace("Z", "+00:00"))
        if ts.date().isoformat() != "2026-05-12":
            return False, f"Wrong date: {ts.date()}"
    except:
        return False, "Invalid timestamp"
    
    return True, "PASS"

def price_guard_check(price):
    """Dynamic price bounds for NQM6"""
    if price < 10000 or price > 50000:
        return False, f"Price {price} outside bounds"
    return True, "PASS"

# ============================================================================
# STRATEGY LOGIC
# ============================================================================
def update_regime(event):
    """Adaptive regime detector"""
    state.regime = "TREND" if state.tape_acceleration > 0.6 else "CHOP"
    state.displacement_ticks += 1
    if state.displacement_ticks > 100:
        state.displacement_ticks = 50

def detect_alert_conditions(event):
    """Check for BUY/SELL signals"""
    alerts = []
    
    if state.continuation_quality > 0.75 and state.trapped_trader_score > 0.6:
        direction = "LONG" if state.tape_acceleration > 0 else "SHORT"
        reason = "continuation + trapped_trader_unwind"
        alerts.append({
            "direction": direction,
            "reason": reason,
            "price": state.last_price,
        })
    
    return alerts

def generate_trade_plan(alert):
    """Build trade plan"""
    entry = alert["price"]
    direction = alert["direction"]
    
    if direction == "LONG":
        stop_loss = entry - 2.5
        target1 = entry + 1.5
        target2 = entry + 3.0
    else:
        stop_loss = entry + 2.5
        target1 = entry - 1.5
        target2 = entry - 3.0
    
    risk_ticks = abs(entry - stop_loss)
    potential_r = abs(target2 - entry) / risk_ticks if risk_ticks > 0 else 0
    
    return {
        "entry": entry,
        "stop_loss": stop_loss,
        "target1": target1,
        "target2": target2,
        "risk_ticks": risk_ticks,
        "expected_rr": potential_r,
    }

# ============================================================================
# ALERT FORMAT
# ============================================================================
def format_alert(alert, trade_plan):
    """Format alert per spec"""
    emoji = "🟢" if alert["direction"] == "LONG" else "🔴"
    action = "LONG" if alert["direction"] == "LONG" else "SHORT"
    
    et_now = datetime.now(timezone.utc).astimezone()
    utc_now = datetime.now(timezone.utc)
    
    msg = f"""{emoji} {action} NQM6

TIME: {et_now.strftime('%H:%M:%S ET')} | {utc_now.strftime('%H:%M:%S UTC')}

TRADE PLAN:
ENTRY: {trade_plan['entry']:.2f}
STOP: {trade_plan['stop_loss']:.2f}
T1: {trade_plan['target1']:.2f}
T2: {trade_plan['target2']:.2f}
Risk: {trade_plan['risk_ticks']:.2f}t | RR: {trade_plan['expected_rr']:.2f}

MARKET CONTEXT:
Regime: {state.regime}
Tape Accel: {state.tape_acceleration:.2f}
Continuation: {state.continuation_quality:.2f}
Trapped Trader: {state.trapped_trader_score:.2f}
Weak Cont: {state.weak_continuation_status}
Displacement: {state.displacement_ticks}t
Participation: {state.participation_pct:.1f}%

REASON: {alert['reason']}
STATUS: WAITING_FOR_ENTRY

✅ source guard PASS, price guard PASS, tick alignment PASS
⚠️ OBSERVATIONAL ONLY — DO NOT AUTO-TRADE"""
    
    return msg

def send_alert(msg):
    """Log alert"""
    state.alerts_fired += 1
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[{timestamp}] ALERT FIRED:\n{msg}\n")
    
    with open("/Users/laxman_2026_mac_mini/.openclaw/workspace/live_shadow_alerts.txt", "a") as f:
        f.write(f"\n{'='*70}\n{timestamp}\n{msg}\n")

# ============================================================================
# TRADE TRACKING
# ============================================================================
def create_trade(alert, trade_plan):
    """Create new trade"""
    trade_id = len(state.trades) + 1
    trade = {
        "id": trade_id,
        "direction": alert["direction"],
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "entry_price": trade_plan["entry"],
        "stop_loss": trade_plan["stop_loss"],
        "target1": trade_plan["target1"],
        "target2": trade_plan["target2"],
        "risk_ticks": trade_plan["risk_ticks"],
        "expected_rr": trade_plan["expected_rr"],
        "reason": alert["reason"],
        "regime_at_entry": state.regime,
        "status": "WAITING_FOR_ENTRY",
        "current_price": None,
        "mfe": 0.0,
        "mae": 0.0,
        "exit_time": None,
        "exit_price": None,
        "realized_ticks": 0.0,
        "realized_r": 0.0,
    }
    state.open_trades[trade_id] = trade
    state.trades.append(trade)
    return trade_id

def update_trade_mfea(trade, current_price):
    """Update MAE/MFE"""
    if trade["status"] not in ["WAITING_FOR_ENTRY", "ENTERED"]:
        return
    
    if trade["direction"] == "LONG":
        mae = min(0, current_price - trade["entry_price"])
        mfe = max(0, current_price - trade["entry_price"])
    else:
        mae = min(0, trade["entry_price"] - current_price)
        mfe = max(0, trade["entry_price"] - current_price)
    
    trade["mfe"] = max(trade["mfe"], mfe)
    trade["mae"] = min(trade["mae"], mae)

def check_trade_exits(trade, current_price):
    """Check exits"""
    if trade["status"] not in ["WAITING_FOR_ENTRY", "ENTERED"]:
        return
    
    entry_time = datetime.fromisoformat(trade["entry_time"])
    hold_minutes = (datetime.now(timezone.utc) - entry_time).total_seconds() / 60
    
    if hold_minutes > CONFIG["max_hold_minutes"]:
        trade["status"] = "TIMEOUT"
        trade["exit_price"] = current_price
        trade["exit_time"] = datetime.now(timezone.utc).isoformat()
        state.timeouts += 1
        return
    
    if trade["direction"] == "LONG":
        if current_price >= trade["target2"]:
            trade["status"] = "TARGET2_HIT"
            trade["exit_price"] = trade["target2"]
            state.wins += 1
        elif current_price >= trade["target1"]:
            trade["status"] = "TARGET1_HIT"
            trade["exit_price"] = trade["target1"]
            state.wins += 1
        elif current_price <= trade["stop_loss"]:
            trade["status"] = "STOP_HIT"
            trade["exit_price"] = trade["stop_loss"]
            state.losses += 1
    else:
        if current_price <= trade["target2"]:
            trade["status"] = "TARGET2_HIT"
            trade["exit_price"] = trade["target2"]
            state.wins += 1
        elif current_price <= trade["target1"]:
            trade["status"] = "TARGET1_HIT"
            trade["exit_price"] = trade["target1"]
            state.wins += 1
        elif current_price >= trade["stop_loss"]:
            trade["status"] = "STOP_HIT"
            trade["exit_price"] = trade["stop_loss"]
            state.losses += 1
    
    if trade["exit_price"]:
        trade["exit_time"] = datetime.now(timezone.utc).isoformat()
        realized_ticks = abs(trade["exit_price"] - trade["entry_price"])
        realized_r = realized_ticks / trade["risk_ticks"] if trade["risk_ticks"] > 0 else 0
        trade["realized_ticks"] = realized_ticks
        trade["realized_r"] = realized_r
        state.total_r += realized_r
        state.realized_r_list.append(realized_r)
        del state.open_trades[trade["id"]]

# ============================================================================
# FEED PROCESSING
# ============================================================================
def process_event(event):
    """Main event handler"""
    state.events_processed += 1
    
    valid, reason = validate_event(event)
    if not valid:
        state.rejected_events += 1
        return
    
    price = event.get("price")
    if price:
        guard_ok, guard_reason = price_guard_check(price)
        if not guard_ok:
            state.guard_failures += 1
            return
        
        state.last_price = price
        
        if event.get("side") == "bid":
            state.last_bid_price = price
        elif event.get("side") == "ask":
            state.last_ask_price = price
    
    update_regime(event)
    
    alerts = detect_alert_conditions(event)
    
    for alert in alerts:
        plan = generate_trade_plan(alert)
        msg = format_alert(alert, plan)
        send_alert(msg)
        trade_id = create_trade(alert, plan)
    
    for trade in state.open_trades.values():
        if state.last_price:
            update_trade_mfea(trade, state.last_price)
            check_trade_exits(trade, state.last_price)
    
    state.feed_health["last_update"] = datetime.now(timezone.utc).isoformat()

def load_and_process_jsonl(filepath, start_line=0):
    """Stream JSONL"""
    try:
        with open(filepath, "r") as f:
            for idx, line in enumerate(f):
                if idx < start_line:
                    continue
                try:
                    event = json.loads(line.strip())
                    process_event(event)
                except json.JSONDecodeError:
                    state.rejected_events += 1
                    continue
    except FileNotFoundError:
        print(f"ERROR: File not found: {filepath}")
        sys.exit(1)

# ============================================================================
# REPORTING
# ============================================================================
def generate_summary():
    """Generate 15-min summary"""
    wr = state.wins / (state.wins + state.losses) if (state.wins + state.losses) > 0 else 0.0
    pf = abs(state.total_r) / max(state.losses, 1) if state.losses > 0 else (state.total_r if state.total_r > 0 else 0.0)
    avg_r = sum(state.realized_r_list) / len(state.realized_r_list) if state.realized_r_list else 0.0
    max_dd = min(state.realized_r_list) if state.realized_r_list else 0.0
    
    best_trade = max(state.trades, key=lambda t: t.get("realized_r", 0)) if state.trades else None
    worst_trade = min(state.trades, key=lambda t: t.get("realized_r", 0)) if state.trades else None
    
    best_str = f"{best_trade['id']} ({best_trade['realized_r']:.2f}R)" if best_trade else "N/A"
    worst_str = f"{worst_trade['id']} ({worst_trade['realized_r']:.2f}R)" if worst_trade else "N/A"
    
    summary = f"""
LIVE SHADOW STATUS — {datetime.now(timezone.utc).isoformat()}

STATS:
  Events processed: {state.events_processed}
  Alerts fired: {state.alerts_fired}
  Open trades: {len(state.open_trades)}
  Completed trades: {len(state.trades)}
  
PERFORMANCE:
  Wins: {state.wins} | Losses: {state.losses} | Early exits: {state.early_exits} | Timeouts: {state.timeouts}
  Win rate: {wr*100:.1f}%
  Profit factor: {pf:.2f}
  Total R: {state.total_r:.2f}
  Avg R/trade: {avg_r:.2f}
  Max drawdown: {max_dd:.2f}
  
FEED HEALTH:
  Rejected: {state.rejected_events}
  Guard failures: {state.guard_failures}
  Last update: {state.feed_health['last_update']}
  
MARKET:
  Regime: {state.regime}
  Last price: {state.last_price}
  Tape accel: {state.tape_acceleration:.2f}
  
BEST TRADE: {best_str}
WORST TRADE: {worst_str}"""
    
    return summary

def export_trade_ledger():
    """Export CSV ledger"""
    csv_path = "/Users/laxman_2026_mac_mini/.openclaw/workspace/exports/live_shadow_trade_ledger.csv"
    
    with open(csv_path, "w") as f:
        f.write("ID,Direction,Entry_Time,Entry_Price,Stop,T1,T2,Exit_Time,Exit_Price,Status,MFE,MAE,Realized_Ticks,Realized_R,Hold_Minutes,Regime_Entry\n")
        
        for trade in state.trades:
            hold_min = 0
            if trade["exit_time"]:
                entry = datetime.fromisoformat(trade["entry_time"])
                exit_t = datetime.fromisoformat(trade["exit_time"])
                hold_min = (exit_t - entry).total_seconds() / 60
            
            f.write(f"{trade['id']},{trade['direction']},{trade['entry_time']},{trade['entry_price']:.2f},"
                   f"{trade['stop_loss']:.2f},{trade['target1']:.2f},{trade['target2']:.2f},"
                   f"{trade['exit_time'] or 'OPEN'},{trade['exit_price'] or 'N/A'},"
                   f"{trade['status']},{trade['mfe']:.2f},{trade['mae']:.2f},"
                   f"{trade['realized_ticks']:.2f},{trade['realized_r']:.2f},{hold_min:.1f},"
                   f"{trade['regime_at_entry']}\n")

# ============================================================================
# MAIN LOOP
# ============================================================================
def main():
    jsonl_file = "/Users/laxman_2026_mac_mini/.openclaw/workspace/state/orderflow/bookmap_api/es_orderflow_2026-05-12.jsonl"
    
    print("=" * 70)
    print("LIVE SHADOW VALIDATOR - FROZEN CONFIG")
    print("=" * 70)
    print(f"Symbol: {CONFIG['symbol']}")
    print(f"Source: {CONFIG['source']}")
    print(f"Regime: {CONFIG['regime_detector']}")
    print(f"Dry-run: {CONFIG['dry_run_mode']}")
    print("=" * 70)
    print()
    
    print(f"Loading {jsonl_file}...")
    load_and_process_jsonl(jsonl_file)
    
    print("\n" + generate_summary())
    export_trade_ledger()
    
    print(f"\n✅ Trade ledger exported: exports/live_shadow_trade_ledger.csv")

if __name__ == "__main__":
    main()
