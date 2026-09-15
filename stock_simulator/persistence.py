from __future__ import annotations

import json
import math
import os
from pathlib import Path

from . import config as config_module
from .storage_safety import ensure_writable, preserve_invalid_file
from .models import (
    EquityPoint,
    PositionSlot,
    RoundRecord,
    TradeSegment,
    TradeNode,
    TradeResult,
)


SESSION_FILE_NAME = "session_state.json"
PERFORMANCE_HISTORY_FILE_NAME = "performance_history.json"


def session_path() -> Path:
    return config_module.CONFIG_PATH.parent / SESSION_FILE_NAME


def save_document(payload: dict) -> None:
    path = session_path()
    ensure_writable(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_document() -> dict | None:
    path = session_path()
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(document, dict):
            raise ValueError("session root must be an object")
        return document
    except (OSError, UnicodeError, ValueError):
        preserve_invalid_file(path)
        return None


def delete_document() -> None:
    ensure_writable(session_path())
    try:
        session_path().unlink()
    except OSError:
        pass


def round_to_dict(record: RoundRecord) -> dict:
    return {
        "index": record.index,
        "code": record.code,
        "name": record.name,
        "profit": record.profit,
        "start_date": record.start_date,
        "end_date": record.end_date,
        "source": record.source,
        "trades": [trade_to_dict(trade) for trade in record.trades],
        "ranges": [list(item) for item in record.ranges],
        "start_cash": record.start_cash,
        "end_asset": record.end_asset,
        "start_node": record.start_node.value,
        "end_node": record.end_node.value,
        "equity_points": [equity_point_to_dict(point) for point in record.equity_points],
        "segments": [trade_segment_to_dict(segment) for segment in record.segments],
        "mode": record.mode,
        "status": record.status,
    }


def round_from_dict(data: dict) -> RoundRecord:
    return RoundRecord(
        index=int(data.get("index", 0)),
        code=str(data.get("code", "")),
        name=str(data.get("name", "")),
        profit=float(data.get("profit", 0.0)),
        start_date=str(data.get("start_date", "")),
        end_date=str(data.get("end_date", "")),
        source=str(data.get("source", "tdx")),
        trades=[trade_from_dict(item) for item in data.get("trades", [])],
        ranges=[tuple(item) for item in data.get("ranges", [])],
        start_cash=float(data.get("start_cash", 0.0)),
        end_asset=float(data.get("end_asset", 0.0)),
        start_node=TradeNode(data.get("start_node", "open")),
        end_node=TradeNode(data.get("end_node", "close")),
        equity_points=[equity_point_from_dict(item) for item in data.get("equity_points", [])],
        segments=[trade_segment_from_dict(item) for item in data.get("segments", [])],
        mode=str(data.get("mode", "continuous")),
        status=str(data.get("status", "completed")),
    )


def equity_point_to_dict(point: EquityPoint) -> dict:
    return {
        "date": point.date,
        "node": point.node.value,
        "total_asset": point.total_asset,
        "code": point.code,
    }


def equity_point_from_dict(data: dict) -> EquityPoint:
    return EquityPoint(
        date=str(data.get("date", "")),
        node=TradeNode(data.get("node", "close")),
        total_asset=float(data.get("total_asset", 0.0)),
        code=str(data.get("code", "")),
    )


def trade_segment_to_dict(segment: TradeSegment) -> dict:
    return {
        "index": segment.index,
        "start_date": segment.start_date,
        "end_date": segment.end_date,
        "start_node": segment.start_node.value,
        "end_node": segment.end_node.value,
        "start_asset": segment.start_asset,
        "end_asset": segment.end_asset,
        "profit": segment.profit,
        "return_rate": segment.return_rate,
        "holding_days": segment.holding_days,
        "buy_count": segment.buy_count,
        "sell_count": segment.sell_count,
        "fee": segment.fee,
        "tax": segment.tax,
    }


def trade_segment_from_dict(data: dict) -> TradeSegment:
    return TradeSegment(
        index=int(data.get("index", 0)),
        start_date=str(data.get("start_date", "")),
        end_date=str(data.get("end_date", "")),
        start_node=TradeNode(data.get("start_node", "open")),
        end_node=TradeNode(data.get("end_node", "close")),
        start_asset=float(data.get("start_asset", 0.0)),
        end_asset=float(data.get("end_asset", 0.0)),
        profit=float(data.get("profit", 0.0)),
        return_rate=float(data.get("return_rate", 0.0)),
        holding_days=int(data.get("holding_days", 0)),
        buy_count=int(data.get("buy_count", 0)),
        sell_count=int(data.get("sell_count", 0)),
        fee=float(data.get("fee", 0.0)),
        tax=float(data.get("tax", 0.0)),
    )


def performance_history_path() -> Path:
    return config_module.CONFIG_PATH.parent / PERFORMANCE_HISTORY_FILE_NAME


def load_performance_history() -> list[RoundRecord]:
    path = performance_history_path()
    if not path.exists():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, TypeError, ValueError):
        preserve_invalid_file(path)
        return []
    if not isinstance(document, dict) or not isinstance(document.get("ordinary_records", []), list):
        preserve_invalid_file(path)
        return []
    rows = document.get("ordinary_records", [])
    records: list[RoundRecord] = []
    damaged = False
    for item in rows:
        if not isinstance(item, dict):
            damaged = True
            continue
        try:
            records.append(round_from_dict(item))
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            # One damaged row must not prevent the application from starting or
            # hide every other usable performance record.
            damaged = True
    if damaged:
        preserve_invalid_file(path)
    return records


def save_performance_history(records: list[RoundRecord]) -> None:
    path = performance_history_path()
    ensure_writable(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {"version": 1, "ordinary_records": [round_to_dict(record) for record in records]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def slot_to_dict(slot: PositionSlot) -> dict:
    return {
        "quantity": slot.quantity,
        "cost": slot.cost,
        "buy_date": slot.buy_date,
        "today_quantity": slot.today_quantity,
    }


def slot_from_dict(data: dict, index: int) -> PositionSlot:
    return PositionSlot(
        index=index,
        quantity=int(data.get("quantity", 0)),
        cost=float(data.get("cost", 0.0)),
        buy_date=str(data.get("buy_date", "")),
        today_quantity=int(data.get("today_quantity", 0)),
    )


def trade_to_dict(trade: TradeResult) -> dict:
    return {
        "accepted": trade.accepted,
        "message": trade.message,
        "side": trade.side,
        "slot_index": trade.slot_index,
        "date": trade.date,
        "node": trade.node.value,
        "price": trade.price,
        "quantity": trade.quantity,
        "amount": trade.amount,
        "fee": trade.fee,
        "tax": trade.tax,
    }


def trade_from_dict(data: dict) -> TradeResult:
    return TradeResult(
        accepted=bool(data.get("accepted", True)),
        message=str(data.get("message", "")),
        side=str(data.get("side", "")),
        slot_index=int(data.get("slot_index", -1)),
        date=str(data.get("date", "")),
        node=TradeNode(data.get("node", "open")),
        price=float(data.get("price", 0.0)),
        quantity=int(data.get("quantity", 0)),
        amount=float(data.get("amount", 0.0)),
        fee=float(data.get("fee", 0.0)),
        tax=float(data.get("tax", 0.0)),
    )


def validate_session_document(document: dict) -> None:
    """Validate all restored fields before the window changes its live account."""
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError("不支持的续作文件结构或版本")
    active = document.get("active")
    if not isinstance(active, dict) or not isinstance(active.get("code"), str) or not active["code"]:
        raise ValueError("续作账户信息无效")

    def number(value, *, minimum=None, integer=False):
        if isinstance(value, bool):
            raise ValueError("数值不能是布尔值")
        numeric = float(value)
        if not math.isfinite(numeric) or (minimum is not None and numeric < minimum):
            raise ValueError("续作数值超出范围")
        if integer and not numeric.is_integer():
            raise ValueError("续作整数无效")

    def rows(owner, key):
        value = owner.get(key, [])
        if not isinstance(value, list):
            raise ValueError(f"{key} 必须为列表")
        return value

    for owner, key, minimum, integer in (
        (document, "account_initial_cash", 0.01, False),
        (document, "cumulative_holding_days_base", 0, True),
        (active, "cash", 0, False),
        (active, "current_index", 0, True),
        (active, "engine_epoch", 0, True),
    ):
        # Older saves explicitly wrote null before the account baseline locked.
        if key == "account_initial_cash" and owner.get(key) is None:
            continue
        if key in owner:
            number(owner[key], minimum=minimum, integer=integer)
    for key in ("round_start_cash", "active_cycle_start_cash", "first_buy_price", "first_buy_index"):
        if active.get(key) is not None:
            number(active[key], minimum=0, integer=key == "first_buy_index")
    mode = document.get("training_mode")
    if mode is not None and not isinstance(mode, str):
        raise ValueError("训练模式无效")
    for key in ("current_node", "round_start_node", "first_buy_node"):
        if active.get(key) is not None:
            TradeNode(active[key])
        elif key in active and key != "first_buy_node":
            raise ValueError("交易阶段不能为空")
    for key in ("current_date", "round_start_date", "name"):
        if key in active and not isinstance(active[key], str):
            raise ValueError("日期或名称格式无效")
    for index, item in enumerate(rows(active, "slots")):
        slot = slot_from_dict(item, index)
        for key in ("quantity", "today_quantity"):
            number(item.get(key, 0), minimum=0, integer=True)
        number(slot.cost, minimum=0)
        if slot.today_quantity > slot.quantity:
            raise ValueError("当天持仓超过总持仓")
    for item in rows(active, "trades"):
        trade_from_dict(item)
    for item in rows(document, "round_records"):
        round_from_dict(item)
    for key in ("equity_points", "round_equity_points"):
        for item in rows(document, key):
            equity_point_from_dict(item)
    for value in rows(document, "equity_curve"):
        number(value)
    for item in rows(active, "completed_trade_ranges"):
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            raise ValueError("交易区间格式无效")
        number(item[0], minimum=0, integer=True)
        number(item[1], minimum=0, integer=True)
        number(item[2])
    metrics = active.get("frozen_position_metrics")
    if metrics is not None and not isinstance(metrics, dict):
        raise ValueError("持仓指标格式无效")
