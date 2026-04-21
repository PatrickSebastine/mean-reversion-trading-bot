"""
Trading strategy implementations.
"""

from indicators import ema, rsi, bollinger_bands


class MomentumStrategy:
    """EMA crossover + RSI + volume confirmation."""

    def __init__(self, params: dict):
        self.ema_fast = params["ema_fast"]
        self.ema_slow = params["ema_slow"]
        self.rsi_period = params["rsi_period"]
        self.rsi_ob = params["rsi_overbought"]
        self.rsi_os = params["rsi_oversold"]
        self.vol_mult = params["volume_mult"]

    def analyze(self, candles: list) -> dict:
        min_required = max(self.ema_slow, self.rsi_period) + 5
        if len(candles) < min_required:
            return {"signal": "HOLD", "strength": 0}

        closes = [c["close"] for c in candles]
        volumes = [c["volume"] for c in candles]

        ema_f = ema(closes, self.ema_fast)
        ema_s = ema(closes, self.ema_slow)
        rsi_vals = rsi(closes, self.rsi_period)
        avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 1

        fast_now = ema_f[-1]
        fast_prev = ema_f[-2]
        slow_now = ema_s[-1]
        slow_prev = ema_s[-2]
        rsi_now = rsi_vals[-1] if rsi_vals[-1] is not None else 50
        vol_now = volumes[-1]

        signal = "HOLD"
        strength = 0

        if all(v is not None for v in [fast_prev, slow_prev, fast_now, slow_now]):
            # Bullish crossover
            if fast_prev <= slow_prev and fast_now > slow_now:
                if rsi_now < self.rsi_ob and vol_now > avg_vol * self.vol_mult:
                    signal = "BUY"
                    strength = min((self.rsi_ob - rsi_now) / 50, 1.0)

            # Bearish crossover
            elif fast_prev >= slow_prev and fast_now < slow_now:
                if rsi_now > self.rsi_os and vol_now > avg_vol * self.vol_mult:
                    signal = "SELL"
                    strength = min((rsi_now - self.rsi_os) / 50, 1.0)

        return {
            "signal": signal,
            "strength": strength,
            "ema_fast": fast_now,
            "ema_slow": slow_now,
            "rsi": rsi_now,
            "volume_ratio": vol_now / avg_vol if avg_vol else 0,
        }


class MeanReversionStrategy:
    """Bollinger Band + RSI extreme mean reversion."""

    def __init__(self, params: dict):
        self.bb_period = params["bb_period"]
        self.bb_std = params["bb_std"]
        self.rsi_period = params["rsi_period"]
        self.rsi_low = params["rsi_extreme_low"]
        self.rsi_high = params["rsi_extreme_high"]

    def analyze(self, candles: list) -> dict:
        if len(candles) < self.bb_period + 5:
            return {"signal": "HOLD", "strength": 0}

        closes = [c["close"] for c in candles]
        rsi_vals = rsi(closes, self.rsi_period)
        bb_upper, bb_middle, bb_lower = bollinger_bands(
            closes, self.bb_period, self.bb_std
        )

        price = closes[-1]
        rsi_now = rsi_vals[-1] if rsi_vals[-1] is not None else 50
        lower = bb_lower[-1]
        upper = bb_upper[-1]
        mid = bb_middle[-1]

        signal = "HOLD"
        strength = 0

        if lower is not None and upper is not None and mid is not None:
            if price <= lower and rsi_now < self.rsi_low:
                signal = "BUY"
                strength = min((lower - price) / (upper - lower) * 10, 1.0) if upper != lower else 0.5

            elif price >= upper and rsi_now > self.rsi_high:
                signal = "SELL"
                strength = min((price - upper) / (upper - lower) * 10, 1.0) if upper != lower else 0.5

        return {
            "signal": signal,
            "strength": strength,
            "bb_upper": upper,
            "bb_lower": lower,
            "bb_middle": mid,
            "rsi": rsi_now,
        }
