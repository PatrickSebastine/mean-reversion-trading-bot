# Mean Reversion Bot — Market Research & Parameter Recommendations

**Date:** 2026-04-21
**Context:** Pre-Upwork portfolio preparation

---

## Current Market Conditions (April 2026)

### Macro
- BTC at ~$74,000, down 19% YTD
- ETH at ~$2,330, down 27% YTD
- BTC dominance stable at 58.3% (57–59% range since Sep 2025)
- ETH/BTC declining (ETH share dropped from 14.6% to 10.8%)
- Market is in a **ranging/consolidation phase** — favorable for mean reversion

### Key Insight
The current regime is **range-bound with declining volatility** — ideal conditions for mean reversion strategies. BTC and major altcoins are oscillating within well-defined ranges without strong directional momentum.

## Strategy Parameter Assessment

### Current Parameters (from config.yaml)
- BB period: 20, std: 2.0
- RSI period: 14, low: 25, high: 75
- SL: 2%, TP: 4% (2:1 R:R)
- Position size: 10% of balance
- Timeframe: 15m

### Recommendations

**Keep as-is:**
- BB(20, 2.0) — standard, well-tested
- RSI(14) — standard period
- 2:1 R:R — solid for mean reversion

**Consider optimizing:**
1. **RSI thresholds**: Test 20/80 instead of 25/75 for stricter entry, fewer but higher-quality signals
2. **ATR-based stops**: Replace fixed 2% SL with 1.5× ATR — adapts to current volatility
3. **Timeframe**: Add 1h as an option. 15m generates more noise; 1h produces cleaner mean reversion signals
4. **Symbol selection**: Current mix is good. ADA, AVAX, DOGE, LINK are the best performers for MR
5. **Position sizing**: 10% is aggressive for live. Consider 5% for live trading with real capital

**Do NOT change before more testing:**
- Leverage (3× is reasonable for futures MR)
- Max positions (5 is fine)
- Daily loss limit (3% is standard)

## Backtest Issues Found & Fixed

### Original Issues
1. **No fees or slippage** — overstated returns by ~10-20%
2. **No short simulation** — only tested long positions
3. **100% win rate** — not realistic, likely a favorable 7-day window
4. **"Projected monthly returns"** — misleading, removed from docs

### Fixed In Refactored Code
1. ✅ BacktestEngine now includes 0.05% taker fees + 0.1% slippage per fill
2. ✅ Both long and short positions simulated
3. ✅ Removed misleading projections from docs
4. ✅ Added honest caveats about small sample size and market regime dependency

## Before Going Live / Upwork

### Must Do
1. **Re-run backtests with updated engine** (needs OKX testnet API keys)
2. **Extend to 30+ day backtest** — 7 days is not statistically significant
3. **Test across multiple market regimes** — trending up, trending down, ranging
4. **Add unit tests** for indicators and strategies
5. **Verify on at least 2 exchanges** for consistency

### Nice to Have
1. ATR-based dynamic stops
2. Equity curve monitoring (drawdown tracking)
3. Trade journaling with screenshots
4. Performance dashboard (can use existing trading dashboard)

## Market Regime Signal

**Current regime: RANGING** ✅ (favorable for mean reversion)

Indicators:
- BTC stuck in $70K–$80K range
- Low volume, declining volatility
- Altcoins following BTC with higher beta
- No major catalysts imminent

**Risk**: A breakout above $80K or below $70K would shift to trending regime, hurting mean reversion performance. The circuit breaker (3% daily loss limit) provides protection.

---

*Research compiled for portfolio preparation. Not financial advice.*
