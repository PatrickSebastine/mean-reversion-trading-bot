# Mean Reversion & Momentum Crypto Trading Bot

A modular Python trading bot that runs mean reversion and momentum strategies across multiple crypto exchanges via CCXT. Includes a realistic backtesting engine with fees and slippage, paper trading, and a multi-exchange overnight trading session runner.

## Features

- **Two strategies**: Mean Reversion (Bollinger Bands + RSI) and Momentum (EMA crossover + RSI + volume)
- **Multi-exchange support**: OKX, BloFin, Binance, Bybit, Gate.io, and 100+ more via CCXT
- **Realistic backtesting**: Includes taker fees, slippage, and proper long/short simulation
- **Risk management**: Stop loss, take profit, daily loss circuit breaker, position sizing
- **Paper trading**: Run on demo/testnet accounts with zero risk
- **Overnight runner**: Multi-exchange session manager for extended paper trading
- **Pure Python indicators**: No external TA library dependencies

## Architecture

```
mean-reversion-trading-bot/
├── trading_engine.py      # Main engine (backtest + live trading)
├── overnight_trader.py    # Multi-exchange overnight session
├── strategies.py          # Strategy implementations
├── indicators.py          # Pure Python TA indicators
├── risk.py                # Risk management module
├── config.yaml            # Configuration template
├── requirements.txt
├── .env.example           # API key template
├── docs/
│   └── BACKTEST_RESULTS.md
└── LICENSE
```

## Strategies

### Mean Reversion

Identifies overextended price moves using Bollinger Bands and RSI extremes.

**BUY signal:**
- Price touches or breaks below lower Bollinger Band
- RSI below 25 (extreme oversold)

**SELL signal:**
- Price touches or breaks above upper Bollinger Band
- RSI above 75 (extreme overbought)

Signal strength scales with how far price extends beyond the bands.

### Momentum

Identifies trend changes using EMA crossovers with volume confirmation.

**BUY signal:**
- Fast EMA (9) crosses above slow EMA (21)
- RSI below 70 (not yet overbought)
- Volume above 1.5× 20-period average

**SELL signal:**
- Fast EMA crosses below slow EMA
- RSI above 30 (not yet oversold)
- Volume above 1.5× average

## Quick Start

### Prerequisites
- Python 3.10+
- Exchange API credentials (start with testnet/demo)

### Installation

```bash
git clone https://github.com/PatrickSebastine/mean-reversion-trading-bot.git
cd mean-reversion-trading-bot
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
# Edit .env with your exchange API credentials
```

Customize trading parameters in `config.yaml`:
- Exchange selection and leverage
- Trading pairs
- Strategy parameters
- Risk management settings

### Running

```bash
# Backtest both strategies on all configured symbols
python trading_engine.py backtest

# Paper trade for 60 minutes
python trading_engine.py live 60

# Multi-exchange overnight session
python overnight_trader.py
```

## Risk Management

| Parameter | Default | Description |
|-----------|---------|-------------|
| Stop Loss | 2% | Auto-placed on every trade |
| Take Profit | 4% | 2:1 reward/risk ratio |
| Daily Loss Limit | 3% | Circuit breaker halts all trading |
| Max Open Positions | 5 | Concurrent position cap |
| Position Size | 10% | Of balance per trade |
| Min Signal Strength | 0.3 | Filters weak signals |

## Backtest Configuration

Default parameters (configurable in `config.yaml`):

- **Timeframe**: 15-minute candles
- **Leverage**: 3× (isolated margin)
- **Symbols**: BTC, ETH, SOL, XRP, DOGE, ADA, AVAX, LINK vs USDT
- **Mean Reversion**: 20-period BB (2.0 σ), 14-period RSI, oversold <25, overbought >75
- **Momentum**: 9/21 EMA crossover, 14-period RSI, 1.5× volume confirmation

### Backtest Realism

The backtesting engine simulates:
- **Taker fees**: 0.05% per fill
- **Slippage**: 0.1% per fill
- **Both long and short positions**
- **Stop loss, take profit, and strategy reversal exits**

## Backtest Results

See [docs/BACKTEST_RESULTS.md](docs/BACKTEST_RESULTS.md) for detailed 7-day OKX futures backtest results.

**Key findings:**
- Mean reversion significantly outperforms momentum in ranging markets
- Mid-cap altcoins (ADA, AVAX, LINK) show the strongest mean reversion signals
- Momentum triggers are rare on 15m timeframes — consider 1h or 4h for trend strategies
- Mean reversion works best in sideways/ranging conditions; underperforms in strong trends

> **Disclaimer**: Past backtest performance does not guarantee future results. Backtests include simulated fees and slippage but cannot account for all real-world factors (liquidity, exchange downtime, network issues, etc.).

## Module Reference

| Module | Purpose |
|--------|---------|
| `trading_engine.py` | Main engine with `TradingEngine` (live) and `BacktestEngine` (backtest) classes |
| `overnight_trader.py` | Multi-exchange session runner with `ExchangeSession` class |
| `strategies.py` | `MomentumStrategy` and `MeanReversionStrategy` classes |
| `indicators.py` | Pure Python EMA, RSI, Bollinger Bands, SMA, ATR |
| `risk.py` | `RiskManager` — position sizing, SL/TP, circuit breaker |
| `config.yaml` | All configurable parameters |

## Adding a New Exchange

1. Add credentials to `.env` following the naming convention: `{EXCHANGE}_API_KEY`, `{EXCHANGE}_SECRET`, `{EXCHANGE}_PASSPHRASE`
2. Update `config.yaml` exchange section
3. For the overnight trader, add an entry to the `exchange_configs` list in `main()`

CCXT supports 100+ exchanges — most work out of the box with API key and secret.

## License

MIT License — see [LICENSE](LICENSE).

Copyright (c) 2026 Patrick Sebastine

## Disclaimer

This software is for educational and research purposes only. Trading cryptocurrencies involves substantial risk of loss. Always:
- Start with paper/demo trading
- Never trade with money you cannot afford to lose
- Use stop losses on every trade
- Monitor your bot regularly
- Comply with applicable laws and regulations in your jurisdiction
