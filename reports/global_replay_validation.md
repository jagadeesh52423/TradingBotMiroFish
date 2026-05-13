# Global Replay Validation Report
**Generated:** 2026-05-11T19:10:10.038662
**Dataset:** es_orderflow_2026-05-06.jsonl (36.3M events)
**Date:** 2026-05-06
**Configuration:** Phase 1.6 + Phase 2 (FIXED, NO OPTIMIZATION)

## Executive Summary

Strategy tested at scale across full trading day on ES and NQ futures.
Fixed Phase 1.6 (regime gating) + Phase 2 (trapped trader detection) configuration.
NO threshold optimization per day. Results reflect true robustness.

## Global Performance

| Metric | Value |
|--------|-------|
| **Total Trades** | 4162 |
| **Win Rate** | 18.9% |
| **Profit Factor** | 0.94x |
| **Total R** | -71.50R |
| **Avg R/Trade** | -0.02R |
| **Max Consecutive Losses** | 35 |
| **Max Drawdown** | -143.00R |

## Breakdown by Symbol

### ESM6.CME@RITHMIC

| Metric | Value |
|--------|-------|
| Trades | 2571 |
| Win Rate | 4.1% |
| Profit Factor | 0.46x |
| Total R | -186.50R |

### NQM6.CME@RITHMIC

| Metric | Value |
|--------|-------|
| Trades | 1591 |
| Win Rate | 42.7% |
| Profit Factor | 1.13x |
| Total R | +115.00R |


## Breakdown by Regime

### BALANCE

| Metric | Value |
|--------|-------|
| Trades | 4158 |
| Win Rate | 18.8% |
| Profit Factor | 0.94x |
| Total R | -72.50R |

### BULL_TRANSITION

| Metric | Value |
|--------|-------|
| Trades | 4 |
| Win Rate | 50.0% |
| Profit Factor | 1.50x |
| Total R | +1.00R |


## Breakdown by Direction

### LONG

| Metric | Value |
|--------|-------|
| Trades | 2035 |
| Win Rate | 20.5% |
| Profit Factor | 1.08x |
| Total R | +47.50R |

### SHORT

| Metric | Value |
|--------|-------|
| Trades | 2127 |
| Win Rate | 17.3% |
| Profit Factor | 0.82x |
| Total R | -119.00R |


## Breakdown by Exit Type

### NO_EXIT

| Metric | Value |
|--------|-------|
| Count | 2125 |
| Win Rate | 0.0% |

### STOP

| Metric | Value |
|--------|-------|
| Count | 1252 |
| Win Rate | 0.0% |

### TARGET1

| Metric | Value |
|--------|-------|
| Count | 783 |
| Win Rate | 100.0% |

### TARGET2

| Metric | Value |
|--------|-------|
| Count | 2 |
| Win Rate | 100.0% |

