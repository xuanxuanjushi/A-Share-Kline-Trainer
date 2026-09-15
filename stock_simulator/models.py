from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TradeNode(str, Enum):
    OPEN = "open"
    CLOSE = "close"


@dataclass(frozen=True)
class DailyBar:
    code: str
    date: str
    open: float
    high: float
    low: float
    close: float
    amount: float
    volume: int

    def price_at(self, node: TradeNode) -> float:
        if node == TradeNode.OPEN:
            return self.open
        return self.close


@dataclass
class PositionSlot:
    index: int
    quantity: int = 0
    cost: float = 0.0
    buy_date: str = ""
    today_quantity: int = 0

    @property
    def is_empty(self) -> bool:
        return self.quantity <= 0

    @property
    def avg_price(self) -> float:
        if self.quantity <= 0:
            return 0.0
        return self.cost / self.quantity

    @property
    def sellable_quantity(self) -> int:
        return max(0, self.quantity - self.today_quantity)


@dataclass(frozen=True)
class TradeResult:
    accepted: bool
    message: str
    side: str = ""
    slot_index: int = -1
    date: str = ""
    node: TradeNode = TradeNode.OPEN
    price: float = 0.0
    quantity: int = 0
    amount: float = 0.0
    fee: float = 0.0
    tax: float = 0.0


@dataclass(frozen=True)
class AccountSnapshot:
    date: str
    node: TradeNode
    cash: float
    position_value: float
    position_profit: float
    position_profit_rate: float
    total_asset: float
    total_profit: float
    profit_rate: float
    slots: tuple[PositionSlot, ...]


@dataclass(frozen=True)
class EquityPoint:
    """One observed account-equity point with its market phase."""

    date: str
    node: TradeNode
    total_asset: float
    code: str = ""


@dataclass(frozen=True)
class TradeSegment:
    """One complete zero-position -> holding -> zero-position cycle."""

    index: int
    start_date: str
    end_date: str
    start_node: TradeNode
    end_node: TradeNode
    start_asset: float
    end_asset: float
    profit: float
    return_rate: float
    holding_days: int
    buy_count: int
    sell_count: int
    fee: float
    tax: float


@dataclass(frozen=True)
class RoundRecord:
    """One finished stock round in continuous-compounding mode."""

    index: int
    code: str
    name: str
    profit: float
    start_date: str = ""
    end_date: str = ""
    source: str = "tdx"
    trades: list[TradeResult] = field(default_factory=list)
    ranges: list[tuple[int, int, float]] = field(default_factory=list)
    start_cash: float = 0.0
    end_asset: float = 0.0
    start_node: TradeNode = TradeNode.OPEN
    end_node: TradeNode = TradeNode.CLOSE
    equity_points: list[EquityPoint] = field(default_factory=list)
    segments: list[TradeSegment] = field(default_factory=list)
    mode: str = "continuous"
    status: str = "completed"
