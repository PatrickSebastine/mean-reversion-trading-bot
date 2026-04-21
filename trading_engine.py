"""
Mean Reversion & Momentum Crypto Trading Bot

Strategies:
1. Mean Reversion — Bollinger Bands + RSI extremes
2. Momentum — EMA crossover + RSI + volume confirmation

Supports backtesting and paper/live trading via CCXT.
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv
import ccxt

from indicators import ema, rsi, bollinger_bands
from strategies import MomentumStrategy, MeanReversionStrategy
from risk import RiskManager

logger = logging.getLogger("trading_bot")


def setup_logging(log_dir: str = "logs", level: str = "INFO"):
    """Configure logging to console and file."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(f"{log_dir}/trading.log", encoding="utf-8"),
        ],
    )


def load_config(path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    with open(path, "r") as f:
        return yaml.safe_load(f)


class TradingEngine:
    """Main trading engine supporting backtest and live modes."""

    def __init__(self, config: dict, exchange=None, log_dir: str = "logs"):
        self.config = config
        self.log_dir = log_dir
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        Path("data").mkdir(parents=True, exist_ok=True)
        Path("backtests").mkdir(parents=True, exist_ok=True)

        # Exchange setup
        if exchange:
            self.exchange = exchange
        else:
            self.exchange = self._create_exchange(config)

        # Strategies
        self.strategies = {
            "momentum": MomentumStrategy(config["strategies"]["momentum"]),
            "mean_reversion": MeanReversionStrategy(config["strategies"]["mean_reversion"]),
        }

        # Risk management
        risk_cfg = config["risk"]
        self.risk = RiskManager(
            max_position_pct=risk_cfg["max_position_pct"],
            daily_loss_limit_pct=risk_cfg["daily_loss_limit_pct"],
            max_open_positions=risk_cfg["max_open_positions"],
            stop_loss_pct=risk_cfg["stop_loss_pct"],
            take_profit_pct=risk_cfg["take_profit_pct"],
        )

        # State
        self.positions = {}
        self.trade_log = []
        self.total_pnl = 0.0
        self.win_count = 0
        self.loss_count = 0

    def _create_exchange(self, config: dict):
        """Create CCXT exchange instance from config."""
        load_dotenv(override=True)
        exchange_name = config.get("exchange", {}).get("name", "okx")
        sandbox = os.getenv("SANDBOX", "true").lower() == "true"

        credentials = {}
        prefix = exchange_name.upper().replace(".", "")

        key_mappings = {
            "apiKey": f"{prefix}_API_KEY",
            "secret": f"{prefix}_SECRET",
            "password": f"{prefix}_PASSPHRASE",
        }

        for param, env_var in key_mappings.items():
            val = os.getenv(env_var)
            if val:
                credentials[param] = val

        options = {}
        default_type = config.get("exchange", {}).get("default_type", "swap")
        if default_type:
            options["defaultType"] = default_type

        exchange = getattr(ccxt, exchange_name.lower().replace(".", ""))({
            **credentials,
            "sandbox": sandbox,
            "options": options,
        })
        exchange.load_markets()
        return exchange

    def get_balance(self) -> float:
        """Get USDT balance."""
        try:
            bal = self.exchange.fetch_balance()
            usdt = bal.get("USDT", {})
            return float(usdt.get("free", 0)) if isinstance(usdt, dict) else float(usdt or 0)
        except Exception as e:
            logger.error(f"Balance fetch failed: {e}")
            return 0.0

    def fetch_candles(self, symbol: str, limit: int = 100) -> list:
        """Fetch OHLCV candles."""
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, self.config["timeframe"], limit=limit)
            return [
                {
                    "timestamp": o[0], "open": o[1], "high": o[2],
                    "low": o[3], "close": o[4], "volume": o[5],
                }
                for o in ohlcv
            ]
        except Exception as e:
            logger.error(f"Candle fetch failed for {symbol}: {e}")
            return []

    def calculate_position_size(self, symbol: str, price: float, strength: float) -> float:
        """Position sizing scaled by signal strength."""
        balance = self.get_balance()
        max_size = balance * self.risk.max_position_pct
        size = max_size * max(strength, 0.3)
        if size < 5 or price <= 0:
            return 0
        return round(size / price, 4)

    def open_position(self, symbol: str, side: str, price: float, size: float,
                      strategy_name: str, analysis: dict) -> bool:
        """Open a position with stop loss and take profit."""
        if symbol in self.positions:
            return False
        if len(self.positions) >= self.risk.max_open_positions:
            return False
        if not self.risk.can_trade(self.daily_pnl(), self.get_balance()):
            return False

        try:
            leverage = self.config.get("exchange", {}).get("leverage", 3)
            self.exchange.set_leverage(leverage, symbol)

            margin_mode = self.config.get("exchange", {}).get("margin_mode", "isolated")
            order = self.exchange.create_market_order(
                symbol, side.lower(), size,
                params={"tdMode": margin_mode},
            )

            if order.get("status") in ("closed", "open", "new"):
                sl, tp = self.risk.calculate_sl_tp(side, price)
                self.positions[symbol] = {
                    "side": side, "entry": price, "size": size,
                    "stop": sl, "tp": tp,
                    "strategy": strategy_name,
                    "opened_at": time.time(),
                    "analysis": analysis,
                }
                logger.info(
                    f"OPENED {side} {symbol}: size={size}, entry={price:.2f}, "
                    f"SL={sl:.2f}, TP={tp:.2f}, strategy={strategy_name}"
                )
                self._log_trade("OPEN", symbol, side, price, size, strategy_name, analysis)
                return True
        except Exception as e:
            logger.error(f"Order failed {symbol} {side}: {e}")
        return False

    def close_position(self, symbol: str, reason: str = "signal"):
        """Close an open position."""
        if symbol not in self.positions:
            return

        pos = self.positions[symbol]
        close_side = "sell" if pos["side"] == "BUY" else "buy"

        try:
            margin_mode = self.config.get("exchange", {}).get("margin_mode", "isolated")
            self.exchange.create_market_order(
                symbol, close_side, pos["size"],
                params={"tdMode": margin_mode, "reduceOnly": True},
            )
        except Exception as e:
            logger.error(f"Close order failed {symbol}: {e}")

        current_price = self._get_current_price(symbol)
        pnl = self._calculate_pnl(pos, current_price)

        self.total_pnl += pnl
        if pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1

        logger.info(
            f"CLOSED {pos['side']} {symbol}: P&L=${pnl:+.2f} ({reason}) | "
            f"Session P&L: ${self.total_pnl:+.2f}"
        )
        self._log_trade("CLOSE", symbol, pos["side"], current_price, pos["size"],
                        pos["strategy"], {"reason": reason, "pnl": pnl})
        del self.positions[symbol]

    def daily_pnl(self) -> float:
        """Return current session P&L (used as daily proxy in backtest/paper mode)."""
        return self.total_pnl

    def scan_and_trade(self):
        """Main trading loop iteration."""
        if not self.risk.can_trade(self.daily_pnl(), self.get_balance()):
            logger.warning("Risk limits hit — skipping scan")
            return

        for symbol in self.config["symbols"]:
            if symbol in self.positions:
                self._check_exit(symbol)
                continue

            candles = self.fetch_candles(symbol)
            if len(candles) < 30:
                continue

            best = {"signal": "HOLD", "strength": 0, "strategy": None, "analysis": {}}
            for name, strategy in self.strategies.items():
                analysis = strategy.analyze(candles)
                if analysis["signal"] != "HOLD" and analysis["strength"] > best["strength"]:
                    best = {
                        "signal": analysis["signal"],
                        "strength": analysis["strength"],
                        "strategy": name,
                        "analysis": analysis,
                    }

            if best["signal"] != "HOLD" and best["strength"] >= 0.3:
                price = candles[-1]["close"]
                size = self.calculate_position_size(symbol, price, best["strength"])
                if size > 0:
                    self.open_position(symbol, best["signal"], price, size,
                                       best["strategy"], best["analysis"])

    def _check_exit(self, symbol: str):
        """Check if position should be closed."""
        pos = self.positions[symbol]
        price = self._get_current_price(symbol)

        if self.risk.should_stop_out(pos["side"], price, pos["stop"]):
            self.close_position(symbol, "stop_loss")
            return
        if self.risk.should_take_profit(pos["side"], price, pos["tp"]):
            self.close_position(symbol, "take_profit")
            return

        # Strategy reversal
        candles = self.fetch_candles(symbol)
        if len(candles) >= 30:
            strategy = self.strategies.get(pos["strategy"])
            if strategy:
                analysis = strategy.analyze(candles)
                if ((pos["side"] == "BUY" and analysis["signal"] == "SELL") or
                        (pos["side"] == "SELL" and analysis["signal"] == "BUY")):
                    if analysis["strength"] >= 0.3:
                        self.close_position(symbol, "strategy_reversal")

    def _get_current_price(self, symbol: str) -> float:
        try:
            return self.exchange.fetch_ticker(symbol).get("last", 0)
        except Exception:
            return 0.0

    @staticmethod
    def _calculate_pnl(position: dict, current_price: float) -> float:
        if position["side"] == "BUY":
            return (current_price - position["entry"]) * position["size"]
        return (position["entry"] - current_price) * position["size"]

    def _log_trade(self, action: str, symbol: str, side: str, price: float,
                   size: float, strategy: str, analysis: dict):
        trade = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action, "symbol": symbol, "side": side,
            "price": price, "size": size, "strategy": strategy,
            "session_pnl": self.total_pnl,
            "open_positions": len(self.positions),
        }
        self.trade_log.append(trade)
        with open("data/trades.json", "a") as f:
            f.write(json.dumps(trade) + "\n")

    def status_report(self):
        """Print current status."""
        balance = self.get_balance()
        total = self.win_count + self.loss_count
        win_rate = self.win_count / max(total, 1) * 100

        print(f"\n{'=' * 50}")
        print(f"  Trading Bot Status")
        print(f"{'=' * 50}")
        print(f"  Balance: ${balance:.2f}")
        print(f"  Session P&L: ${self.total_pnl:+.2f}")
        print(f"  Win Rate: {win_rate:.1f}% ({self.win_count}W / {self.loss_count}L)")
        print(f"  Open Positions: {len(self.positions)}")
        print(f"  Circuit Breaker: {'YES' if not self.risk.can_trade(self.daily_pnl(), balance) else 'No'}")

        for sym, pos in self.positions.items():
            price = self._get_current_price(sym)
            pnl = self._calculate_pnl(pos, price)
            print(f"    {sym}: {pos['side']} entry={pos['entry']:.2f} "
                  f"now={price:.2f} P&L=${pnl:+.2f} [{pos['strategy']}]")
        print(f"{'=' * 50}\n")


# ============================================================
# BACKTEST ENGINE
# ============================================================
class BacktestEngine:
    """Offline backtesting engine using historical candle data."""

    def __init__(self, config: dict):
        self.config = config
        self.strategies = {
            "momentum": MomentumStrategy(config["strategies"]["momentum"]),
            "mean_reversion": MeanReversionStrategy(config["strategies"]["mean_reversion"]),
        }
        self.risk = RiskManager(
            max_position_pct=config["risk"]["max_position_pct"],
            daily_loss_limit_pct=config["risk"]["daily_loss_limit_pct"],
            max_open_positions=config["risk"]["max_open_positions"],
            stop_loss_pct=config["risk"]["stop_loss_pct"],
            take_profit_pct=config["risk"]["take_profit_pct"],
        )

        # Backtest fees (taker fee on most exchanges)
        self.maker_fee = 0.0002  # 0.02%
        self.taker_fee = 0.0005  # 0.05%
        self.slippage_pct = 0.001  # 0.1%

    def run(self, candles: list, strategy_name: str, initial_balance: float = 5000.0) -> dict:
        """Run backtest on historical candle data."""
        strategy = self.strategies[strategy_name]
        balance = initial_balance
        position = None
        trades = []
        min_candles = 50

        for i in range(min_candles, len(candles)):
            window = candles[: i + 1]
            analysis = strategy.analyze(window)
            price = candles[i]["close"]

            # Apply slippage
            if position is None and analysis["signal"] == "BUY" and analysis["strength"] >= 0.3:
                entry_price = price * (1 + self.slippage_pct)
                fee = balance * self.risk.max_position_pct * max(analysis["strength"], 0.3) * self.taker_fee
                size = (balance * self.risk.max_position_pct * max(analysis["strength"], 0.3) - fee) / entry_price
                position = {
                    "side": "BUY", "entry": entry_price, "size": size,
                    "stop": entry_price * (1 - self.risk.stop_loss_pct),
                    "tp": entry_price * (1 + self.risk.take_profit_pct),
                    "idx": i, "fee_paid": fee,
                }

            elif position is None and analysis["signal"] == "SELL" and analysis["strength"] >= 0.3:
                entry_price = price * (1 - self.slippage_pct)
                fee = balance * self.risk.max_position_pct * max(analysis["strength"], 0.3) * self.taker_fee
                size = (balance * self.risk.max_position_pct * max(analysis["strength"], 0.3) - fee) / entry_price
                position = {
                    "side": "SELL", "entry": entry_price, "size": size,
                    "stop": entry_price * (1 + self.risk.stop_loss_pct),
                    "tp": entry_price * (1 - self.risk.take_profit_pct),
                    "idx": i, "fee_paid": fee,
                }

            elif position is not None:
                close_reason = None
                close_price = price

                if position["side"] == "BUY":
                    if price <= position["stop"]:
                        close_reason = "stop_loss"
                        close_price = price * (1 - self.slippage_pct)
                    elif price >= position["tp"]:
                        close_reason = "take_profit"
                        close_price = price * (1 - self.slippage_pct)
                else:
                    if price >= position["stop"]:
                        close_reason = "stop_loss"
                        close_price = price * (1 + self.slippage_pct)
                    elif price <= position["tp"]:
                        close_reason = "take_profit"
                        close_price = price * (1 + self.slippage_pct)

                if close_reason is None and analysis["signal"] != "HOLD":
                    if ((position["side"] == "BUY" and analysis["signal"] == "SELL") or
                            (position["side"] == "SELL" and analysis["signal"] == "BUY")):
                        if analysis["strength"] >= 0.3:
                            close_reason = "reversal"

                if close_reason:
                    exit_fee = position["size"] * close_price * self.taker_fee
                    total_fees = position["fee_paid"] + exit_fee

                    if position["side"] == "BUY":
                        pnl = (close_price - position["entry"]) * position["size"] - total_fees
                    else:
                        pnl = (position["entry"] - close_price) * position["size"] - total_fees

                    balance += pnl
                    trades.append({
                        "side": position["side"],
                        "entry": position["entry"],
                        "exit": close_price,
                        "pnl": pnl,
                        "fees": total_fees,
                        "reason": close_reason,
                        "bar": i,
                    })
                    position = None

        return self._build_report(strategy_name, initial_balance, balance, trades)

    def _build_report(self, strategy_name: str, initial: float, final: float,
                      trades: list) -> dict:
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        total_pnl = final - initial
        win_rate = len(wins) / max(len(trades), 1) * 100
        total_fees = sum(t["fees"] for t in trades)
        gross_profit = sum(t["pnl"] for t in wins) if wins else 0
        gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 0
        profit_factor = gross_profit / max(gross_loss, 0.01)

        return {
            "strategy": strategy_name,
            "initial_balance": initial,
            "final_balance": final,
            "total_pnl": total_pnl,
            "return_pct": total_pnl / initial * 100 if initial else 0,
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": win_rate,
            "total_fees": total_fees,
            "profit_factor": profit_factor,
            "avg_win": gross_profit / max(len(wins), 1),
            "avg_loss": -gross_loss / max(len(losses), 1) if losses else 0,
            "trade_details": trades,
        }


def fetch_historical_candles(exchange, symbol: str, timeframe: str,
                             days: int) -> list:
    """Fetch historical candles for backtesting."""
    since = exchange.parse8601(
        (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
    )
    all_candles = []
    target = days * 24 * (60 // int(timeframe.rstrip("hm")) if "h" in timeframe else
                          60 // int(timeframe.rstrip("m")))

    while len(all_candles) < target:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=100)
        if not batch:
            break
        all_candles.extend([
            {"timestamp": o[0], "open": o[1], "high": o[2],
             "low": o[3], "close": o[4], "volume": o[5]}
            for o in batch
        ])
        since = batch[-1][0] + 1

    return all_candles


def print_backtest_report(report: dict, symbol: str, days: int, candle_count: int):
    """Print formatted backtest report."""
    print(f"\n{'=' * 50}")
    print(f"  BACKTEST RESULTS")
    print(f"{'=' * 50}")
    print(f"  Strategy: {report['strategy']}")
    print(f"  Symbol: {symbol}")
    print(f"  Period: {days} days ({candle_count} candles)")
    print(f"  Starting Balance: ${report['initial_balance']:.2f}")
    print(f"  Final Balance: ${report['final_balance']:.2f}")
    print(f"  Total P&L: ${report['total_pnl']:+.2f} ({report['return_pct']:+.2f}%)")
    print(f"  Total Trades: {report['total_trades']}")
    print(f"  Win Rate: {report['win_rate']:.1f}% ({report['wins']}W / {report['losses']}L)")
    print(f"  Total Fees: ${report['total_fees']:.2f}")
    print(f"  Profit Factor: {report['profit_factor']:.2f}")
    if report['total_trades'] > 0:
        print(f"  Avg Win: ${report['avg_win']:+.2f}")
        print(f"  Avg Loss: ${report['avg_loss']:+.2f}")
    print(f"{'=' * 50}")


# ============================================================
# MAIN
# ============================================================
def main():
    config = load_config()
    setup_logging(level=config.get("logging", {}).get("level", "INFO"))

    mode = sys.argv[1] if len(sys.argv) > 1 else "backtest"

    if mode == "backtest":
        engine = TradingEngine(config, log_dir="logs")
        backtester = BacktestEngine(config)
        results = {}

        for strategy in ["mean_reversion", "momentum"]:
            for symbol in config["symbols"]:
                try:
                    print(f"Fetching {symbol} data for {strategy}...")
                    candles = fetch_historical_candles(
                        engine.exchange, symbol, config["timeframe"], days=7
                    )
                    if not candles:
                        print(f"  No data for {symbol}, skipping")
                        continue

                    report = backtester.run(candles, strategy)
                    results[f"{strategy}_{symbol}"] = report
                    print_backtest_report(report, symbol, 7, len(candles))
                except Exception as e:
                    logger.error(f"Backtest failed {strategy} {symbol}: {e}")

        # Summary
        print(f"\n\n{'=' * 70}")
        print("  STRATEGY COMPARISON SUMMARY")
        print(f"{'=' * 70}")
        print(f"  {'Strategy':<35} {'P&L':>10} {'Return':>10} {'WR':>8} {'Trades':>8} {'Fees':>10}")
        print(f"  {'-' * 81}")
        sorted_results = sorted(results.items(), key=lambda x: x[1]["total_pnl"], reverse=True)
        for name, r in sorted_results:
            print(f"  {name:<35} ${r['total_pnl']:>8.2f} {r['return_pct']:>9.2f}% "
                  f"{r['win_rate']:>7.0f}% {r['total_trades']:>7} ${r['total_fees']:>8.2f}")
        print(f"{'=' * 70}")

        # Save results
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        with open(f"backtests/summary_{timestamp}.json", "w") as f:
            # Remove trade details for summary
            summary = {k: {kk: vv for kk, vv in v.items() if kk != "trade_details"}
                       for k, v in results.items()}
            json.dump(summary, f, indent=2)

    elif mode == "live":
        duration = int(sys.argv[2]) if len(sys.argv) > 2 else 60
        engine = TradingEngine(config, log_dir="logs")

        print(f"\n>> Starting Trading Bot")
        print(f"   Balance: ${engine.get_balance():.2f}")
        print(f"   Symbols: {', '.join(config['symbols'])}")
        print(f"   Strategies: {', '.join(engine.strategies.keys())}")
        print(f"   Timeframe: {config['timeframe']}")
        print(f"   Duration: {duration} minutes")

        end_time = time.time() + duration * 60
        iteration = 0
        scan_interval = config.get("scan_interval", 60)

        while time.time() < end_time:
            iteration += 1
            try:
                logger.info(f"--- Scan #{iteration} ---")
                engine.scan_and_trade()
                if iteration % 5 == 0:
                    engine.status_report()
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Scan error: {e}", exc_info=True)

            remaining = end_time - time.time()
            if remaining <= 0:
                break
            time.sleep(scan_interval)

        engine.status_report()
        print(f"\n>> Session complete. P&L: ${engine.total_pnl:+.2f}")

    else:
        print("Usage: python trading_engine.py [backtest|live] [duration_minutes]")


if __name__ == "__main__":
    main()
