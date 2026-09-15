from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class MarketContext:
    root: str
    date: str
    closed: bool
    locked: bool = False

    def __post_init__(self):
        if date.fromisoformat(self.date).isoformat() != self.date:
            raise ValueError('日期格式必须为 YYYY-MM-DD')


@dataclass(frozen=True)
class TrainingRequest:
    code: str
    context: MarketContext


class TrainingAPI(Protocol):
    def market_context(self) -> MarketContext: ...
    def open_training(self, request: TrainingRequest) -> bool: ...
    def advance_market(self) -> None: ...
