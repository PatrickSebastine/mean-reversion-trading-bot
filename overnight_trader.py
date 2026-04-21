"""
Multi-Exchange Overnight Paper Trading Engine
Runs mean reversion strategy on multiple exchanges simultaneously.

Usage: python overnight_trader.py
"""

import os
import sys
import time
import json
import logging
import signal as sig_mod
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import dotenv_values
import ccxt

from indicators import rsi, bollinger_bands
from strategies import MeanReversionStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("overnight_trader")


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


class ExchangeSession:
    """Manages a trading session on a single exchange."""

    def __init__(self, name: str, exchange, symbols: list, config: dict):
        self.name = name
        self.exchange = exchange
        self.symbols = symbols

        risk = config["risk"]
        self.leverage = config.get("exchange", {}).get("leverage", 3)
        self.stop_loss_pct = risk["stop_loss_pct"]
        self.take_profit_pct = risk["take_profit_pct"]
        self.max_positions = risk["max_open_positions"]
        self.position_pct = risk["max_position_pct"]
        self.min_strength = 0.3

        self.strategy = MeanReversionStrategy(config["strategies"]["mean_reversion"])
        self.timeframe = config.get("timeframe", "15m")

        self.positions = {}
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.wins = 0
        self.losses = 0
        self.trades = []

        log_dir = f"logs/{name.lower()}"
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        self.log_file = open(f"{log_dir}/trades.jsonl", "a")

    def get_balance(self) -> float:
        try:
            bal = self.exchange.fetch_balance()
            usdt = bal.get("USDT", {})
            if isinstance(usdt, dict):
                return float(usdt.get("free", 0))
            return float(usdt) if usdt else 0
        except Exception:
            return 0

    def fetch_candles(self, symbol: str, limit: int = 100) -> list:
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, self.timeframe, limit=limit)
            return [
                {"timestamp": o[0], "open": o[1], "high": o[2],
                 "low": o[3], "close": o[4], "volume": o[5]}
                for o in ohlcv
            ]
        except Exception as e:
            logger.debug(f"{self.name} candle fetch failed {symbol}: {e}")
            return []

    def get_price(self, symbol: str) -> float:
        try:
            return self.exchange.fetch_ticker(symbol).get("last", 0)
        except Exception:
            return 0

    def scan(self):
        for symbol in self.symbols:
            if symbol in self.positions:
                self._check_exit(symbol)
                continue

            candles = self.fetch_candles(symbol)
            if len(candles) < 30:
                continue

            analysis = self.strategy.analyze(candles)
            if analysis["signal"] != "HOLD" and analysis["strength"] >= self.min_strength:
                self._open(symbol, analysis)

    def _open(self, symbol: str, analysis: dict):
        if len(self.positions) >= self.max_positions or symbol in self.positions:
            return

        price = self.get_price(symbol)
        if price <= 0:
            return

        balance = self.get_balance()
        size = (balance * self.position_pct * max(analysis["strength"], 0.3)) / price
        if size <= 0:
            return

        side = analysis["signal"]
        try:
            self.exchange.set_leverage(self.leverage, symbol)
            params = self._exchange_params(side)
            self.exchange.create_market_order(symbol, side.lower(), size, params=params)

            if side == "BUY":
                sl = price * (1 - self.stop_loss_pct)
                tp = price * (1 + self.take_profit_pct)
            else:
                sl = price * (1 + self.stop_loss_pct)
                tp = price * (1 - self.take_profit_pct)

            self.positions[symbol] = {
                "side": side, "entry": price, "size": size,
                "stop": sl, "tp": tp, "opened": time.time(),
            }
            logger.info(
                f"[{self.name}] OPEN {side} {symbol} @ {price:.4f} "
                f"size={size:.4f} SL={sl:.4f} TP={tp:.4f}"
            )
            self._log("OPEN", symbol, side, price, size, analysis)
        except Exception as e:
            logger.error(f"[{self.name}] Order failed {symbol}: {e}")

    def _check_exit(self, symbol: str):
        pos = self.positions[symbol]
        price = self.get_price(symbol)
        if price <= 0:
            return

        if pos["side"] == "BUY" and price <= pos["stop"]:
            self._close(symbol, price, "stop_loss"); return
        if pos["side"] == "SELL" and price >= pos["stop"]:
            self._close(symbol, price, "stop_loss"); return
        if pos["side"] == "BUY" and price >= pos["tp"]:
            self._close(symbol, price, "take_profit"); return
        if pos["side"] == "SELL" and price <= pos["tp"]:
            self._close(symbol, price, "take_profit"); return

        # Strategy reversal
        candles = self.fetch_candles(symbol)
        if len(candles) >= 30:
            analysis = self.strategy.analyze(candles)
            if ((pos["side"] == "BUY" and analysis["signal"] == "SELL") or
                    (pos["side"] == "SELL" and analysis["signal"] == "BUY")):
                if analysis["strength"] >= 0.3:
                    self._close(symbol, price, "reversal")

    def _close(self, symbol: str, price: float, reason: str):
        pos = self.positions[symbol]
        close_side = "sell" if pos["side"] == "BUY" else "buy"
        try:
            params = self._exchange_params(pos["side"], reduce_only=True)
            self.exchange.create_market_order(symbol, close_side, pos["size"], params=params)
        except Exception as e:
            logger.error(f"[{self.name}] Close failed {symbol}: {e}")

        pnl = (price - pos["entry"]) * pos["size"] if pos["side"] == "BUY" \
            else (pos["entry"] - price) * pos["size"]
        self.daily_pnl += pnl
        self.total_pnl += pnl
        if pnl > 0:
            self.wins += 1
        else:
            self.losses += 1

        logger.info(
            f"[{self.name}] CLOSE {pos['side']} {symbol} @ {price:.4f} "
            f"PnL=${pnl:+.2f} ({reason})"
        )
        self._log("CLOSE", symbol, pos["side"], price, pos["size"],
                  {"reason": reason, "pnl": pnl})
        del self.positions[symbol]

    def _exchange_params(self, side: str = None, reduce_only: bool = False) -> dict:
        """Build exchange-specific order parameters."""
        params = {}
        if self.name == "OKX":
            params["tdMode"] = "isolated"
            if side:
                params["posSide"] = "long" if side == "BUY" else "short"
            if reduce_only:
                params["reduceOnly"] = True
        elif self.name in ("BloFin", "Bybit"):
            params["tdMode"] = "isolated"
            if reduce_only:
                params["reduceOnly"] = True
        return params

    def _log(self, action: str, symbol: str, side: str, price: float,
             size: float, extra: dict):
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "exchange": self.name, "action": action,
            "symbol": symbol, "side": side,
            "price": price, "size": size,
            "daily_pnl": self.daily_pnl, "total_pnl": self.total_pnl,
            "open_positions": len(self.positions),
        }
        if isinstance(extra, dict):
            entry.update(extra)
        self.trades.append(entry)
        self.log_file.write(json.dumps(entry) + "\n")
        self.log_file.flush()

    def status(self) -> str:
        balance = self.get_balance()
        total = self.wins + self.losses
        wr = self.wins / max(total, 1) * 100
        lines = [
            f"  [{self.name}] Balance: ${balance:.2f} | Daily: ${self.daily_pnl:+.2f} | "
            f"Total: ${self.total_pnl:+.2f} | WR: {wr:.0f}% ({self.wins}W/{self.losses}L) | "
            f"Open: {len(self.positions)}"
        ]
        for sym, p in self.positions.items():
            price = self.get_price(sym)
            pnl = (price - p["entry"]) * p["size"] if p["side"] == "BUY" \
                else (p["entry"] - price) * p["size"]
            lines.append(f"    {sym}: {p['side']} entry={p['entry']:.4f} "
                         f"now={price:.4f} PnL=${pnl:+.2f}")
        return "\n".join(lines)

    def close(self):
        self.log_file.close()


# ============================================================
# EXCHANGE FACTORY
# ============================================================
def create_exchange(name: str, env_path: str, sandbox: bool = True):
    """Create an exchange instance from environment config."""
    env = dotenv_values(env_path)
    prefix = name.upper().replace(".", "")

    credentials = {
        "apiKey": env.get(f"{prefix}_API_KEY"),
        "secret": env.get(f"{prefix}_SECRET"),
        "password": env.get(f"{prefix}_PASSPHRASE"),
    }
    credentials = {k: v for k, v in credentials.items() if v}

    exchange_class_name = name.lower().replace(".", "")
    exchange_class = getattr(ccxt, exchange_class_name)
    return exchange_class({**credentials, "sandbox": sandbox})


# ============================================================
# MAIN
# ============================================================
def main():
    config = load_config()

    symbols = config["symbols"]
    sessions = []

    exchange_configs = [
        ("OKX", "okx/.env"),
        ("BloFin", "blofin/.env"),
    ]

    for name, env_path in exchange_configs:
        try:
            ex = create_exchange(name, env_path, sandbox=True)
            ex.load_markets()
            sessions.append(ExchangeSession(name, ex, symbols, config))
            logger.info(f"{name} connected")
        except Exception as e:
            logger.error(f"{name} failed: {e}")

    # Gate.io spot (different symbol format)
    try:
        ex = create_exchange("gateio", "gateio/.env", sandbox=True)
        ex.load_markets()
        gateio_symbols = [s.replace(":USDT", "") for s in symbols]
        gate_config = {**config, "risk": {**config["risk"], "stop_loss_pct": 0.03, "take_profit_pct": 0.06}}
        sessions.append(ExchangeSession("Gate.io", ex, gateio_symbols, gate_config))
        logger.info("Gate.io connected (spot mode)")
    except Exception as e:
        logger.error(f"Gate.io failed: {e}")

    if not sessions:
        logger.error("No exchanges connected. Exiting.")
        return

    print(f"\n{'=' * 60}")
    print(f"  OVERNIGHT PAPER TRADING SESSION")
    print(f"  Started: {datetime.now().isoformat()}")
    print(f"  Exchanges: {', '.join(s.name for s in sessions)}")
    print(f"  Strategy: Mean Reversion (BB + RSI)")
    print(f"  Timeframe: {config.get('timeframe', '15m')}")
    print(f"{'=' * 60}\n")

    scan_interval = config.get("scan_interval", 60)
    iteration = 0
    running = True

    def shutdown(sig, frame):
        nonlocal running
        running = False
        logger.info("Shutdown signal received")

    sig_mod.signal(sig_mod.SIGINT, shutdown)
    sig_mod.signal(sig_mod.SIGTERM, shutdown)

    while running:
        iteration += 1
        try:
            for s in sessions:
                logger.info(f"--- Scan #{iteration} [{s.name}] ---")
                s.scan()

            if iteration % 10 == 0:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Status (Scan #{iteration}):")
                for s in sessions:
                    print(s.status())
        except Exception as e:
            logger.error(f"Scan error: {e}", exc_info=True)

        time.sleep(scan_interval)

    # Shutdown
    print(f"\n{'=' * 60}")
    print(f"  SESSION COMPLETE — {datetime.now().isoformat()}")
    print(f"{'=' * 60}")
    for s in sessions:
        print(s.status())
        s.close()

    summary = {
        "ended": datetime.now().isoformat(),
        "iterations": iteration,
        "exchanges": {
            s.name: {
                "total_pnl": s.total_pnl,
                "wins": s.wins,
                "losses": s.losses,
                "total_trades": len(s.trades),
            }
            for s in sessions
        },
    }
    with open("overnight_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved to overnight_summary.json")


if __name__ == "__main__":
    main()
