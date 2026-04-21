"""
Risk management — position sizing, stop loss/take profit, circuit breaker.
"""


class RiskManager:
    """Centralized risk management for the trading engine."""

    def __init__(
        self,
        max_position_pct: float = 0.10,
        daily_loss_limit_pct: float = 0.03,
        max_open_positions: int = 5,
        stop_loss_pct: float = 0.02,
        take_profit_pct: float = 0.04,
    ):
        self.max_position_pct = max_position_pct
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.max_open_positions = max_open_positions
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    def calculate_sl_tp(self, side: str, entry_price: float) -> tuple:
        """Calculate stop loss and take profit prices."""
        if side == "BUY":
            stop = entry_price * (1 - self.stop_loss_pct)
            tp = entry_price * (1 + self.take_profit_pct)
        else:
            stop = entry_price * (1 + self.stop_loss_pct)
            tp = entry_price * (1 - self.take_profit_pct)
        return stop, tp

    def should_stop_out(self, side: str, current_price: float, stop_price: float) -> bool:
        """Check if stop loss has been hit."""
        if side == "BUY":
            return current_price <= stop_price
        return current_price >= stop_price

    def should_take_profit(self, side: str, current_price: float, tp_price: float) -> bool:
        """Check if take profit has been hit."""
        if side == "BUY":
            return current_price >= tp_price
        return current_price <= tp_price

    def can_trade(self, session_pnl: float, balance: float) -> bool:
        """Check if trading is allowed (circuit breaker)."""
        if balance <= 0:
            return False
        if session_pnl < -(balance * self.daily_loss_limit_pct):
            return False
        return True

    def position_size(self, balance: float, price: float, strength: float) -> float:
        """Calculate position size scaled by signal strength."""
        max_size = balance * self.max_position_pct
        size = max_size * max(strength, 0.3)
        if size < 5 or price <= 0:
            return 0
        return round(size / price, 4)
