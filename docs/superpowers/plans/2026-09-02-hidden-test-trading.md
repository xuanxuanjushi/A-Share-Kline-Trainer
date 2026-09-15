# Hidden Test Trading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a hidden, disposable historical test-trading session launched by right-button double-clicking a candle body in stock browse mode.

**Architecture:** Keep the existing normal training paths intact and add an explicit transient test-session flag plus a saved browse context. Reuse `DailySimulationEngine` for fills and account calculations, while guarding persistence/archive paths and separating the chart window anchor from the engine's trading date.

**Tech Stack:** Python 3.12, PySide6, unittest

**Spec:** `docs/superpowers/specs/2026-09-02-hidden-test-trading-design.md`

## Global Constraints

- Normal training behavior and saved sessions must remain unchanged.
- Test trades are never persisted or archived.
- Existing right-drag panning and drawing interactions remain available.
- Existing files are backed up before modification.

---

### Task 1: Pure test-mode rules

**Files:**
- Create: `stock_simulator/test_trade.py`
- Create: `tests/test_test_trade.py`

**Interfaces:**
- Produces: `menu_presentation(active: bool) -> tuple[str, bool]`
- Produces: `test_window_anchor(selected_index: int, previous_anchor: int, bar_count: int, window_size: int) -> tuple[int, int]`
- Produces: `point_hits_candle_body(...) -> bool`

- [x] Write failing tests for inactive/active menu presentation, future-visible anchor selection, and body-only hit testing.
- [x] Run `py run_tests.py` and confirm failure because `stock_simulator.test_trade` does not exist.
- [x] Implement the minimal pure helpers.
- [x] Run `py run_tests.py` and confirm the helper tests pass.

### Task 2: K-line gesture and history boundary

**Files:**
- Modify: `stock_simulator/kline_widget.py`
- Modify: `tests/test_test_trade.py`

**Interfaces:**
- Consumes: `point_hits_candle_body(...)`
- Produces: right-button double-click callback `parent_window.start_test_trade_from_bar(date)`
- Produces: optional `history_unmask_start_index` in `KLineWidget.set_data(...)`

- [x] Add a failing widget-level test proving a right-button double-click on a body invokes the parent callback while a wick hit does not.
- [x] Run the focused test and confirm the missing behavior.
- [x] Add body hit routing and the explicit history-unmask boundary.
- [x] Run the focused and full tests.

### Task 3: Transient application session and UI

**Files:**
- Modify: `stock_simulator/app.py`
- Modify: `tests/test_test_trade.py`

**Interfaces:**
- Produces: `MainWindow.start_test_trade_from_bar(date: str) -> bool`
- Produces: `MainWindow.exit_test_trade_mode(...) -> bool`
- Produces: `PlaybackAdvanceButton.set_test_mode(active: bool) -> None`

- [x] Add failing tests for start/exit state, menu text/enabled state, account activation, and browse restoration.
- [x] Run focused tests and confirm failures for the missing methods/state.
- [x] Implement saved browse context, independent engine activation, menu action, two-line button badge, full-future chart window, and account rendering.
- [x] Run focused and full tests.

### Task 4: Exit and persistence safety

**Files:**
- Modify: `stock_simulator/app.py`
- Modify: `tests/test_test_trade.py`

**Interfaces:**
- Consumes: `exit_test_trade_mode(...)`
- Produces: guarded browse, return-to-trading, random-switch, archive, persist, and close paths.

- [x] Add failing tests proving test data is discarded and the formal return context is not overwritten.
- [x] Run focused tests and confirm the unsafe path fails.
- [x] Route every exit path through the transient-session cleanup and suppress test persistence/archive.
- [x] Run full tests, Python compilation, and an offscreen UI smoke test.
