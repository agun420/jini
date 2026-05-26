from __future__ import annotations

import math
from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


class AsymmetricSlippageEngine:
    """
    Research-only slippage model.

    This module:
    - does not submit orders
    - does not enable paper trading
    - does not enable live trading
    - does not overwrite config
    """

    def __init__(self, base_slippage_pct: float = 0.005):
        self.base_slip = float(base_slippage_pct)

    def _calc_entry_market(
        self,
        raw_price: float,
        spread_pct: float,
        volatility_penalty: float,
        atr_cap_pct: float,
    ) -> tuple[float, float, float, bool]:
        real_penalty = (spread_pct * 0.5) + volatility_penalty
        worst_penalty = spread_pct + (volatility_penalty * 1.5)
        atr_cap_applied = False

        if real_penalty > atr_cap_pct:
            real_penalty = atr_cap_pct
            atr_cap_applied = True
        if worst_penalty > (atr_cap_pct * 2.0):
            worst_penalty = atr_cap_pct * 2.0

        real_fill = raw_price * (1.0 + real_penalty)
        worst_fill = raw_price * (1.0 + worst_penalty)
        return real_fill, worst_fill, real_penalty, atr_cap_applied

    def _calc_limit_profit(
        self,
        raw_price: float,
        spread_pct: float,
        volatility_penalty: float,
        atr_cap_pct: float,
    ) -> tuple[float, float, float, bool]:
        real_penalty = max((spread_pct * 0.5) - (volatility_penalty * 0.1), 0.0)
        worst_penalty = spread_pct

        real_fill = raw_price * (1.0 - real_penalty)
        worst_fill = raw_price * (1.0 - worst_penalty)
        return real_fill, worst_fill, real_penalty, False

    def _calc_stop_panic(
        self,
        raw_price: float,
        spread_pct: float,
        volatility_penalty: float,
        atr_cap_pct: float,
    ) -> tuple[float, float, float, bool]:
        real_penalty = spread_pct + (volatility_penalty * 2.0)
        worst_penalty = (spread_pct * 1.5) + (volatility_penalty * 3.5)
        atr_cap_applied = False

        if real_penalty > atr_cap_pct:
            real_penalty = atr_cap_pct
            atr_cap_applied = True
        if worst_penalty > (atr_cap_pct * 2.5):
            worst_penalty = atr_cap_pct * 2.5

        real_fill = raw_price * (1.0 - real_penalty)
        worst_fill = raw_price * (1.0 - worst_penalty)
        return real_fill, worst_fill, real_penalty, atr_cap_applied

    def _calc_time_decay(
        self,
        raw_price: float,
        spread_pct: float,
        volatility_penalty: float,
        atr_cap_pct: float,
    ) -> tuple[float, float, float, bool]:
        real_penalty = spread_pct + (volatility_penalty * 0.5)
        worst_penalty = spread_pct + volatility_penalty

        real_fill = raw_price * (1.0 - real_penalty)
        worst_fill = raw_price * (1.0 - worst_penalty)
        return real_fill, worst_fill, real_penalty, False

    def _evaluate_execution_quality(
        self, spread_pct: float, slippage_pct: float, atr_cap_applied: bool
    ) -> tuple[bool, str | None]:
        execution_quality_pass = True
        block_reason = None

        if spread_pct > 0.025:
            execution_quality_pass = False
            block_reason = "SPREAD_TOO_WIDE"

        if slippage_pct > 0.02:
            execution_quality_pass = False
            block_reason = "SLIPPAGE_TOO_HIGH"

        if atr_cap_applied and slippage_pct > 0.015:
            execution_quality_pass = False
            block_reason = "ATR_CAPPED_SLIPPAGE_RISK"

        return execution_quality_pass, block_reason

    def generate_fill_profile(
        self,
        order_type: str,
        raw_price: float,
        spread_pct: float,
        bar_vol: float,
        avg_vol: float,
        atr: float,
    ) -> dict[str, Any]:
        raw_price = safe_float(raw_price)
        spread_pct = safe_float(spread_pct)
        bar_vol = safe_float(bar_vol)
        avg_vol = safe_float(avg_vol)
        atr = safe_float(atr)

        if raw_price <= 0 or atr <= 0 or avg_vol <= 0 or spread_pct < 0:
            safe_price = max(raw_price, 0.01)
            return {
                "order_type": str(order_type or "UNKNOWN"),
                "chart_fill": round(safe_price, 2),
                "realistic_fill": round(safe_price, 3),
                "worst_case_fill": round(safe_price, 3),
                "atr_cap_applied": False,
                "slippage_pct": 0.0,
                "execution_quality_pass": False,
                "block_reason": "INVALID_INPUT",
                "data_quality_flag": "INVALID_INPUT",
                "order_submission": False,
                "live_trading": False,
            }

        order_type = str(order_type or "UNKNOWN").upper()
        vol_ratio = min(bar_vol / max(avg_vol, 1.0), 10.0)
        volatility_penalty = self.base_slip * (1.0 + (vol_ratio ** 1.3))
        atr_cap_pct = (atr * 1.5) / raw_price

        handlers = {
            "ENTRY_MARKET": self._calc_entry_market,
            "LIMIT_PROFIT": self._calc_limit_profit,
            "STOP_PANIC": self._calc_stop_panic,
            "TIME_DECAY": self._calc_time_decay,
        }

        handler = handlers.get(order_type)
        if handler:
            real_fill, worst_fill, slippage_pct, atr_cap_applied = handler(
                raw_price, spread_pct, volatility_penalty, atr_cap_pct
            )
        else:
            real_fill = raw_price
            worst_fill = raw_price
            slippage_pct = 0.0
            atr_cap_applied = False

        execution_quality_pass, block_reason = self._evaluate_execution_quality(
            spread_pct, slippage_pct, atr_cap_applied
        )

        return {
            "order_type": order_type,
            "chart_fill": round(raw_price, 2),
            "realistic_fill": round(real_fill, 3),
            "worst_case_fill": round(worst_fill, 3),
            "atr_cap_applied": atr_cap_applied,
            "slippage_pct": round(slippage_pct, 5),
            "execution_quality_pass": execution_quality_pass,
            "block_reason": block_reason,
            "data_quality_flag": "OK",
            "inputs": {
                "raw_price": raw_price,
                "spread_pct": spread_pct,
                "bar_vol": bar_vol,
                "avg_vol": avg_vol,
                "atr": atr,
                "vol_ratio": round(vol_ratio, 4),
            },
            "order_submission": False,
            "live_trading": False,
        }
