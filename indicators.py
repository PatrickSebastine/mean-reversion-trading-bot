"""
Technical indicators — pure Python implementations.
No external TA library dependencies.
"""

from typing import List, Optional, Tuple


def ema(data: List[float], period: int) -> List[Optional[float]]:
    """Exponential Moving Average."""
    if len(data) < period:
        return [None] * len(data)
    multiplier = 2 / (period + 1)
    result = [sum(data[:period]) / period]
    for price in data[period:]:
        result.append((price - result[-1]) * multiplier + result[-1])
    return [None] * (period - 1) + result


def rsi(data: List[float], period: int = 14) -> List[Optional[float]]:
    """Relative Strength Index."""
    if len(data) < period + 1:
        return [None] * len(data)
    gains, losses = [], []
    for i in range(1, len(data)):
        change = data[i] - data[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    result = []
    if avg_loss == 0:
        result.append(100.0)
    else:
        result.append(100 - (100 / (1 + avg_gain / avg_loss)))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            result.append(100 - (100 / (1 + avg_gain / avg_loss)))

    return [None] * period + result


def bollinger_bands(data: List[float], period: int = 20,
                    std_mult: float = 2.0) -> Tuple[List[Optional[float]],
                                                      List[Optional[float]],
                                                      List[Optional[float]]]:
    """Bollinger Bands. Returns (upper, middle, lower)."""
    if len(data) < period:
        return [None] * len(data), [None] * len(data), [None] * len(data)

    upper, middle, lower = [], [], []
    for i in range(len(data)):
        if i < period - 1:
            upper.append(None)
            middle.append(None)
            lower.append(None)
        else:
            window = data[i - period + 1: i + 1]
            mid = sum(window) / period
            variance = sum((x - mid) ** 2 for x in window) / period
            std = variance ** 0.5
            middle.append(mid)
            upper.append(mid + std_mult * std)
            lower.append(mid - std_mult * std)
    return upper, middle, lower


def sma(data: List[float], period: int) -> List[Optional[float]]:
    """Simple Moving Average."""
    if len(data) < period:
        return [None] * len(data)
    result = []
    for i in range(len(data)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(data[i - period + 1: i + 1]) / period)
    return result


def atr(candles: List[dict], period: int = 14) -> List[Optional[float]]:
    """Average True Range from candle dicts with 'high', 'low', 'close'."""
    if len(candles) < 2:
        return [None] * len(candles)

    true_ranges = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return [None] * len(candles)

    result = [None]  # First candle has no TR
    result.extend([None] * (len(true_ranges) - 1))  # Placeholder

    atr_val = sum(true_ranges[:period]) / period
    result[period] = atr_val

    for i in range(period, len(true_ranges)):
        atr_val = (atr_val * (period - 1) + true_ranges[i]) / period
        result[i + 1] = atr_val

    return result
