import pandas as pd
import numpy as np
from collections import defaultdict
import json

# Load the ledger
df = pd.read_csv('/Users/laxman_2026_mac_mini/.openclaw/workspace/market-swarm-lab/exports/nq_adaptive_phase2_trade_ledger.csv')

print(f"Total trades: {len(df)}")
print(f"Trade columns: {df.columns.tolist()}\n")

# ============================================================================
# 1. EXPECTANCY DECOMPOSITION
# ============================================================================

winners = df[df['status'] == 'WIN']
losers = df[df['status'] == 'LOSS']

avg_winner = winners['pnl_ticks'].mean()
avg_loser = losers['pnl_ticks'].mean()
win_count = len(winners)
loss_count = len(losers)
win_rate = win_count / len(df)

print("=" * 70)
print("1. EXPECTANCY DECOMPOSITION")
print("=" * 70)
print(f"Wins: {win_count} | Losses: {loss_count} | Win Rate: {win_rate:.1%}")
print(f"Avg Winner: {avg_winner:.2f} ticks")
print(f"Avg Loser: {avg_loser:.2f} ticks")
print(f"Winner/Loser Ratio: {avg_winner/abs(avg_loser):.2f}x")

expectancy = (win_rate * avg_winner) + ((1 - win_rate) * avg_loser)
print(f"Expectancy (ticks): {expectancy:.2f}")
print(f"Expectancy (USD): {expectancy * 20:.2f}")

# ============================================================================
# 2. EXIT REASON BREAKDOWN
# ============================================================================

print("\n" + "=" * 70)
print("2. EXIT REASON BREAKDOWN")
print("=" * 70)

exit_breakdown = df.groupby(['status', 'exit_reason']).size().unstack(fill_value=0)
print(exit_breakdown)

stop_losses = df[df['exit_reason'] == 'STOP_LOSS']
profit_targets = df[df['exit_reason'] == 'PROFIT_TARGET']
timeouts = df[df['exit_reason'] == 'TIMEOUT']

print(f"\nProfit Targets: {len(profit_targets)} ({len(profit_targets)/len(df):.1%})")
print(f"  Wins: {len(profit_targets[profit_targets['status'] == 'WIN'])}")
print(f"  Losses: {len(profit_targets[profit_targets['status'] == 'LOSS'])}")

print(f"\nStop Losses: {len(stop_losses)} ({len(stop_losses)/len(df):.1%})")
print(f"  Wins: {len(stop_losses[stop_losses['status'] == 'WIN'])}")
print(f"  Losses: {len(stop_losses[stop_losses['status'] == 'LOSS'])}")

print(f"\nTimeouts: {len(timeouts)} ({len(timeouts)/len(df):.1%})")
print(f"  Wins: {len(timeouts[timeouts['status'] == 'WIN'])}")
print(f"  Losses: {len(timeouts[timeouts['status'] == 'LOSS'])}")

timeout_avg = timeouts['pnl_ticks'].mean()
print(f"  Timeout Avg PnL: {timeout_avg:.2f} ticks")

# ============================================================================
# 3. STOP & TARGET STRUCTURE
# ============================================================================

print("\n" + "=" * 70)
print("3. STOP & TARGET STRUCTURE")
print("=" * 70)

# For winners: profit_target should match max_profit
# For losers: stop should be around max_loss

winners_pt = profit_targets[profit_targets['status'] == 'WIN']
losers_sl = stop_losses[stop_losses['status'] == 'LOSS']

print(f"\nWinners via PROFIT_TARGET:")
print(f"  Count: {len(winners_pt)}")
print(f"  Avg PnL: {winners_pt['pnl_ticks'].mean():.2f} ticks")
print(f"  Avg MFE: {winners_pt['max_profit'].mean():.2f} ticks")
print(f"  Median MFE: {winners_pt['max_profit'].median():.2f} ticks")

print(f"\nLosers via STOP_LOSS:")
print(f"  Count: {len(losers_sl)}")
print(f"  Avg PnL: {losers_sl['pnl_ticks'].mean():.2f} ticks")
print(f"  Avg MAE: {losers_sl['max_loss'].mean():.2f} ticks")
print(f"  Median MAE: {losers_sl['max_loss'].median():.2f} ticks")

# ============================================================================
# 4. MFE/MAE ANALYSIS
# ============================================================================

print("\n" + "=" * 70)
print("4. MFE/MAE ANALYSIS - DO TRADES GO GREEN BEFORE STOPPING?")
print("=" * 70)

# Check losers: did they ever go positive before hitting stop?
losers_with_mfe = losers[losers['max_profit'] > 0]
print(f"\nLosers that went green before stopping: {len(losers_with_mfe)} / {len(losers)} ({len(losers_with_mfe)/len(losers):.1%})")
if len(losers_with_mfe) > 0:
    print(f"  Avg MFE before stop: {losers_with_mfe['max_profit'].mean():.2f} ticks")
    print(f"  Avg MAE at stop: {losers_with_mfe['max_loss'].mean():.2f} ticks")
    print(f"  MFE/MAE ratio: {losers_with_mfe['max_profit'].mean() / losers_with_mfe['max_loss'].mean():.2f}x")

# Check winners: did they go deeper into drawdown than losers stopped?
print(f"\nWinners MFE/MAE stats:")
print(f"  Avg MFE: {winners['max_profit'].mean():.2f} ticks")
print(f"  Avg MAE: {winners['max_loss'].mean():.2f} ticks")

# ============================================================================
# 5. STOP WIDTH vs NOISE
# ============================================================================

print("\n" + "=" * 70)
print("5. STOP WIDTH ANALYSIS")
print("=" * 70)

print(f"\nLoser MAE distribution (stops):")
print(losers_sl['max_loss'].describe())

# Are stops too wide? (allowing trades to go too deep)
# Are stops too tight? (being hit on noise)

# Check: winners with large MAE
winners_with_mae = winners[winners['max_loss'] > 0]
print(f"\nWinners that went into drawdown: {len(winners_with_mae)} / {len(winners)}")
if len(winners_with_mae) > 0:
    print(f"  Avg MAE: {winners_with_mae['max_loss'].mean():.2f} ticks")
    print(f"  Max MAE: {winners_with_mae['max_loss'].max():.2f} ticks")

print(f"\nComparison:")
print(f"  Winner avg MAE: {winners['max_loss'].mean():.2f} ticks")
print(f"  Loser avg MAE: {losers_sl['max_loss'].mean():.2f} ticks")
print(f"  Ratio: {losers_sl['max_loss'].mean() / winners['max_loss'].mean():.2f}x")

# ============================================================================
# 6. BARS HELD ANALYSIS (Entry Timing / Continuation Exhaustion)
# ============================================================================

print("\n" + "=" * 70)
print("6. BARS HELD ANALYSIS (ENTRY TIMING)")
print("=" * 70)

print(f"\nWinner bars held:")
print(winners['bars_held'].describe())

print(f"\nLoser bars held:")
print(losers['bars_held'].describe())

# Quick entries (1-2 bars) vs slow entries (3+ bars)
quick_wins = winners[winners['bars_held'] <= 2]
slow_wins = winners[winners['bars_held'] > 2]
quick_losses = losers[losers['bars_held'] <= 2]
slow_losses = losers[losers['bars_held'] > 2]

print(f"\nQuick trades (≤2 bars):")
print(f"  Wins: {len(quick_wins)}, avg PnL: {quick_wins['pnl_ticks'].mean():.2f}")
print(f"  Losses: {len(quick_losses)}, avg PnL: {quick_losses['pnl_ticks'].mean():.2f}")

print(f"\nSlow trades (>2 bars):")
print(f"  Wins: {len(slow_wins)}, avg PnL: {slow_wins['pnl_ticks'].mean():.2f}")
print(f"  Losses: {len(slow_losses)}, avg PnL: {slow_losses['pnl_ticks'].mean():.2f}")

# ============================================================================
# 7. POSITION SIZE / R DISTRIBUTION
# ============================================================================

print("\n" + "=" * 70)
print("7. POSITION SIZE / R DISTRIBUTION")
print("=" * 70)

print(f"\nPnL distribution:")
print(df['pnl_ticks'].describe())
print(f"\nSkew: {df['pnl_ticks'].skew():.3f}")
print(f"Kurtosis: {df['pnl_ticks'].kurtosis():.3f}")

# Fat-tail analysis: largest losses
largest_losses = losers_sl.nsmallest(5, 'pnl_ticks')
print(f"\nTop 5 largest losses:")
print(largest_losses[['entry_bar', 'bars_held', 'pnl_ticks', 'max_profit', 'max_loss']])

# Are a few large losses dominating?
top_losses_pnl = largest_losses['pnl_ticks'].sum()
total_losses = losers['pnl_ticks'].sum()
print(f"\nTop 5 losses contribute {top_losses_pnl:.0f} ticks of {total_losses:.0f} total loss ({abs(top_losses_pnl/total_losses):.1%})")

# ============================================================================
# 8. TRADE ANATOMY CLASSIFICATION
# ============================================================================

print("\n" + "=" * 70)
print("8. TRADE ANATOMY - DETAILED CLASSIFICATION")
print("=" * 70)

def classify_trade(row):
    """Classify each trade by pattern"""
    
    if row['status'] == 'WIN':
        # Winners
        if row['exit_reason'] == 'TIMEOUT':
            return 'timeout_grind'
        elif row['bars_held'] == 1:
            if row['pnl_ticks'] > 60:
                return 'quick_breakout_win'
            else:
                return 'quick_scalp_win'
        elif row['bars_held'] > 5:
            return 'sustained_win'
        else:
            return 'normal_win'
    else:
        # Losers
        if row['exit_reason'] == 'TIMEOUT':
            return 'timeout_decay'
        elif row['max_profit'] > 0 and row['max_profit'] > abs(row['pnl_ticks'] * 0.5):
            return 'reversed_from_winning'
        elif row['pnl_ticks'] < -100:
            return 'catastrophic_loss'
        else:
            return 'normal_loss'

df['trade_class'] = df.apply(classify_trade, axis=1)

print("\nTrade class distribution:")
print(df['trade_class'].value_counts().sort_values(ascending=False))

print("\nAvg PnL by trade class:")
class_stats = df.groupby('trade_class').agg({
    'pnl_ticks': ['count', 'mean', 'min', 'max'],
    'bars_held': 'mean'
}).round(2)
print(class_stats)

# ============================================================================
# 9. TIMEOUT IMPACT
# ============================================================================

print("\n" + "=" * 70)
print("9. TIMEOUT IMPACT ON EXPECTANCY")
print("=" * 70)

timeout_wins = timeouts[timeouts['status'] == 'WIN']
timeout_losses = timeouts[timeouts['status'] == 'LOSS']

print(f"Timeout wins: {len(timeout_wins)}, avg PnL: {timeout_wins['pnl_ticks'].mean():.2f}")
print(f"Timeout losses: {len(timeout_losses)}, avg PnL: {timeout_losses['pnl_ticks'].mean():.2f}")
print(f"Total timeout expectancy: {timeouts['pnl_ticks'].sum():.2f} ticks")

# Without timeouts
df_no_timeout = df[df['exit_reason'] != 'TIMEOUT']
exp_no_timeout = df_no_timeout['pnl_ticks'].mean()
print(f"\nExpectancy without timeouts: {exp_no_timeout:.2f} ticks")
print(f"Expectancy with timeouts: {expectancy:.2f} ticks")
print(f"Timeout impact: {expectancy - exp_no_timeout:.2f} ticks")

# ============================================================================
# 10. WINNER QUALITY
# ============================================================================

print("\n" + "=" * 70)
print("10. WINNER QUALITY - ARE WINNERS BEING CUT TOO EARLY?")
print("=" * 70)

print(f"\nWinner PnL vs MFE:")
print(f"  Avg winner PnL: {avg_winner:.2f} ticks")
print(f"  Avg winner MFE: {winners['max_profit'].mean():.2f} ticks")
print(f"  Pct of MFE captured: {(avg_winner / winners['max_profit'].mean() * 100):.1f}%")

# Are targets leaving money on table?
winners_leaving_mfe = winners[winners['max_profit'] > (winners['pnl_ticks'] * 1.2)]
print(f"\nWinners leaving >20% MFE on table: {len(winners_leaving_mfe)} / {len(winners)}")
if len(winners_leaving_mfe) > 0:
    mfe_gap = winners_leaving_mfe['max_profit'] - winners_leaving_mfe['pnl_ticks']
    print(f"  Avg uncaptured MFE: {mfe_gap.mean():.2f} ticks")

# ============================================================================
# 11. LOSERS THAT WENT GREEN
# ============================================================================

print("\n" + "=" * 70)
print("11. LOSER ANALYSIS - TRADES THAT WENT GREEN BEFORE STOPPING")
print("=" * 70)

green_then_stopped = losers[(losers['max_profit'] > 0) & (losers['max_loss'] < 0)]
print(f"Losers that went positive before reversing: {len(green_then_stopped)} / {len(losers)}")

if len(green_then_stopped) > 0:
    print(f"  Avg max profit: {green_then_stopped['max_profit'].mean():.2f} ticks")
    print(f"  Avg final loss: {green_then_stopped['pnl_ticks'].mean():.2f} ticks")
    print(f"  Avg max drawdown: {green_then_stopped['max_loss'].mean():.2f} ticks")
    
    # These are reversals - could we have exited at max_profit?
    potential_salvage = green_then_stopped['max_profit'].sum()
    actual_loss = green_then_stopped['pnl_ticks'].sum()
    print(f"\n  If exited at max profit:")
    print(f"    Current loss: {actual_loss:.2f} ticks")
    print(f"    Potential gain: {potential_salvage:.2f} ticks")
    print(f"    Swing: {potential_salvage - actual_loss:.2f} ticks")

# ============================================================================
# 12. FINAL VERDICT
# ============================================================================

print("\n" + "=" * 70)
print("12. KEY METRICS FOR VERDICT")
print("=" * 70)

print(f"\nOverall stats:")
print(f"  Total trades: {len(df)}")
print(f"  Wins/Losses: {win_count}/{loss_count}")
print(f"  Win rate: {win_rate:.1%}")
print(f"  Expectancy: {expectancy:.2f} ticks ({expectancy*20:.0f} USD)")

print(f"\nExpectancy by exit type:")
pt_exp = profit_targets['pnl_ticks'].mean()
sl_exp = stop_losses['pnl_ticks'].mean()
to_exp = timeouts['pnl_ticks'].mean()
print(f"  Profit targets: {pt_exp:.2f} ticks ({len(profit_targets)} trades)")
print(f"  Stop losses: {sl_exp:.2f} ticks ({len(stop_losses)} trades)")
print(f"  Timeouts: {to_exp:.2f} ticks ({len(timeouts)} trades)")

print(f"\nRisk metrics:")
print(f"  Max single loss: {df['pnl_ticks'].min():.2f} ticks")
print(f"  Max single win: {df['pnl_ticks'].max():.2f} ticks")
print(f"  Std dev: {df['pnl_ticks'].std():.2f} ticks")

print(f"\nCatastrophic losses (< -100 ticks):")
catastrophic = df[df['pnl_ticks'] < -100]
print(f"  Count: {len(catastrophic)}")
if len(catastrophic) > 0:
    print(f"  Total impact: {catastrophic['pnl_ticks'].sum():.2f} ticks")
    print(catastrophic[['entry_bar', 'bars_held', 'pnl_ticks', 'max_loss']])
