from __future__ import annotations

from dataclasses import replace
import math

from .models import AccountSnapshot, DailyBar, PositionSlot, TradeNode, TradeResult


class DailySimulationEngine:
    def __init__(
        self,
        bars: list[DailyBar],
        initial_cash: float,
        slot_count: int,
        commission_rate: float = 0.00025,
        stamp_tax_rate: float = 0.0005,
        min_commission: float = 5.0,
        t_plus_one: bool = True,
        start_index: int = 0,
    ):
        if not bars:
            raise ValueError("bars cannot be empty")
        if not math.isfinite(initial_cash) or initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if slot_count <= 0:
            raise ValueError("slot_count must be positive")
        if any(not math.isfinite(value) or value < 0 for value in (commission_rate, stamp_tax_rate, min_commission)):
            raise ValueError("fees must be finite and non-negative")

        self.bars = bars
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.start_index = max(0, min(start_index, len(bars) - 1))
        self.current_index = self.start_index
        self.commission_rate = commission_rate
        self.stamp_tax_rate = stamp_tax_rate
        self.min_commission = min_commission
        self.t_plus_one = t_plus_one
        self.slots = [PositionSlot(index=i) for i in range(slot_count)]
        self.trades: list[TradeResult] = []

    def start(self) -> AccountSnapshot:
        self.current_index = self.start_index
        self.cash = self.initial_cash
        self.slots = [PositionSlot(index=i) for i in range(len(self.slots))]
        self.trades = []
        return self.snapshot(TradeNode.OPEN)

    @property
    def current_bar(self) -> DailyBar:
        return self.bars[self.current_index]

    def next_day(self) -> bool:
        if self.current_index >= len(self.bars) - 1:
            return False
        self.current_index += 1
        for slot in self.slots:
            slot.today_quantity = 0
        return True

    def buy(self, slot_index: int, node: TradeNode, budget: float) -> TradeResult:
        quantity = self.buy_quantity_for_budget(node, budget)
        if quantity <= 0:
            return self._rejected("现金不足，至少需要买入 100 股")
        return self.buy_quantity(slot_index, node, quantity)

    def buy_quantity_for_budget(self, node: TradeNode, budget: float) -> int:
        if not self._valid_price(node) or not self._finite_number(budget) or float(budget) <= 0:
            return 0
        price = self.current_bar.price_at(node)
        spendable = min(float(budget), self.cash)
        quantity = int(spendable // (price * 100)) * 100
        while quantity > 0 and round(price * quantity + self._commission(price * quantity), 2) > spendable:
            quantity -= 100
        return quantity

    def buy_quantity(self, slot_index: int, node: TradeNode, quantity: int) -> TradeResult:
        slot = self._slot(slot_index)
        if not self._valid_price(node):
            return self._rejected("交易阶段或价格无效")
        if not self._valid_quantity(quantity):
            return self._rejected("买入数量必须是 100 股的整数倍")
        quantity = int(quantity)

        price = self.current_bar.price_at(node)
        amount = round(price * quantity, 2)
        fee = self._commission(amount)
        total_cost = round(amount + fee, 2)
        if not math.isfinite(total_cost):
            return self._rejected("交易金额超出有效范围")
        if total_cost > self.cash:
            return self._rejected("现金不足")

        self.cash = round(self.cash - total_cost, 2)
        slot.quantity += quantity
        slot.cost = round(slot.cost + total_cost, 2)
        slot.today_quantity += quantity
        slot.buy_date = self.current_bar.date
        result = TradeResult(True, "买入成功", "buy", slot_index, self.current_bar.date, node, price, quantity, amount, fee, 0.0)
        self.trades.append(result)
        return result

    def sell(
        self,
        slot_index: int,
        node: TradeNode,
        budget: float | None = None,
        quantity: int | None = None,
    ) -> TradeResult:
        slot = self._slot(slot_index)
        if not self._valid_price(node):
            return self._rejected("交易阶段或价格无效")
        if slot.is_empty:
            return self._rejected("这个分仓没有持仓")
        sellable_quantity = slot.sellable_quantity if self.t_plus_one else slot.quantity
        if sellable_quantity <= 0:
            return self._rejected("T+1 限制：当天买入不能当天卖出")

        price = self.current_bar.price_at(node)
        sell_quantity = sellable_quantity
        if quantity is not None:
            if not self._valid_quantity(quantity):
                return self._rejected("卖出数量必须是 100 股的整数倍")
            sell_quantity = int(quantity)
            if sell_quantity > sellable_quantity:
                return self._rejected("卖出数量超过当前可卖数量")
        elif budget is not None:
            if not self._finite_number(budget):
                return self._rejected("卖出金额无效")
            sell_budget = float(budget)
            if sell_budget <= 0:
                return self._rejected("卖出金额必须大于 0")
            capped_budget = round(min(sell_budget, round(price * sellable_quantity, 2)), 2)
            lot_value = round(price * 100, 2)
            sell_quantity = int((capped_budget + 0.000001) // lot_value) * 100
            if sell_quantity <= 0:
                return self._rejected("卖出金额不足，至少需要卖出 100 股")
        amount = round(price * sell_quantity, 2)
        fee = self._commission(amount)
        tax = round(amount * self.stamp_tax_rate, 2)
        received = round(amount - fee - tax, 2)
        if not math.isfinite(received):
            return self._rejected("交易金额超出有效范围")
        self.cash = round(self.cash + received, 2)
        result = TradeResult(True, "卖出成功", "sell", slot_index, self.current_bar.date, node, price, sell_quantity, amount, fee, tax)
        sold_cost = round(slot.avg_price * sell_quantity, 2)
        slot.quantity -= sell_quantity
        slot.cost = max(0.0, round(slot.cost - sold_cost, 2))
        if slot.quantity <= 0:
            slot.quantity = 0
            slot.cost = 0.0
            slot.today_quantity = 0
            slot.buy_date = ""
        self.trades.append(result)
        return result

    def snapshot(self, node: TradeNode) -> AccountSnapshot:
        price = self.current_bar.price_at(node)
        position_value = round(sum(slot.quantity * price for slot in self.slots), 2)
        position_cost = round(sum(slot.cost for slot in self.slots if slot.quantity), 2)
        position_profit = round(position_value - position_cost, 2)
        position_profit_rate = round(position_profit / position_cost * 100, 2) if position_cost else 0.0
        total_asset = round(self.cash + position_value, 2)
        total_profit = round(total_asset - self.initial_cash, 2)
        profit_rate = round(total_profit / self.initial_cash * 100, 2)
        return AccountSnapshot(
            date=self.current_bar.date,
            node=node,
            cash=round(self.cash, 2),
            position_value=position_value,
            position_profit=position_profit,
            position_profit_rate=position_profit_rate,
            total_asset=total_asset,
            total_profit=total_profit,
            profit_rate=profit_rate,
            slots=tuple(replace(slot) for slot in self.slots),
        )

    def _slot(self, slot_index: int) -> PositionSlot:
        if slot_index < 0 or slot_index >= len(self.slots):
            raise IndexError("slot_index out of range")
        return self.slots[slot_index]

    def _commission(self, amount: float) -> float:
        return round(max(amount * self.commission_rate, self.min_commission), 2)

    @staticmethod
    def _finite_number(value) -> bool:
        try:
            return not isinstance(value, bool) and math.isfinite(float(value))
        except (TypeError, ValueError, OverflowError):
            return False

    @classmethod
    def _valid_quantity(cls, value) -> bool:
        return cls._finite_number(value) and float(value) > 0 and float(value) % 100 == 0

    def _valid_price(self, node) -> bool:
        if node not in (TradeNode.OPEN, TradeNode.CLOSE):
            return False
        price = self.current_bar.price_at(node)
        return self._finite_number(price) and float(price) > 0

    @staticmethod
    def _rejected(message: str) -> TradeResult:
        return TradeResult(False, message)
