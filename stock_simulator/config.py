from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path

from .storage_safety import ensure_writable, preserve_invalid_file


CONFIG_DIR_NAME = "大A日K股票模拟训练器"
PORTABLE_MARKER_FILE_NAME = "portable_mode.flag"
PORTABLE_DATA_DIR_NAME = "portable_data"
PORTABLE_MARKET_DIR_NAME = "market_data"
INDEX_CACHE_FILE_NAME = "shanghai_index_daily.json"
MARKET_STATS_CACHE_FILE_NAME = "market_stats_daily.json"
MAIN_MA_PERIODS = (5, 10, 20, 60, 120, 250)


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def portable_data_directory() -> Path | None:
    root = application_directory()
    if (root / PORTABLE_MARKER_FILE_NAME).is_file():
        return root / PORTABLE_DATA_DIR_NAME
    return None


def bundled_market_directory() -> Path:
    return application_directory() / PORTABLE_MARKET_DIR_NAME


def resolve_market_setting(value: str) -> str:
    if not value.strip():
        bundled = bundled_market_directory()
        return str(bundled) if (bundled / "vipdoc").is_dir() else ""
    path = Path(value)
    return str(path if path.is_absolute() else application_directory() / path)


def portable_market_setting(value: str) -> str:
    if value and Path(value).resolve() == bundled_market_directory().resolve():
        return PORTABLE_MARKET_DIR_NAME
    return value


def default_config_path() -> Path:
    portable_root = portable_data_directory()
    if portable_root is not None:
        return portable_root / "settings.json"
    if getattr(sys, "frozen", False):
        roaming = os.environ.get("APPDATA")
        base = Path(roaming) if roaming else Path.home() / "AppData" / "Roaming"
        return base / CONFIG_DIR_NAME / "settings.json"
    return Path(__file__).resolve().parent.parent / "config" / "settings.json"


CONFIG_PATH = default_config_path()


@dataclass
class AppSettings:
    tdx_root: str = ""
    initial_cash: float = 100000.0
    slot_count: int = 4
    window_width: int = 1360
    window_height: int = 860
    window_maximized: bool = False
    main_splitter_sizes: list[int] = field(default_factory=lambda: [960, 400])
    sector_splitter_sizes: list[int] = field(default_factory=lambda: [520, 830])
    sector_chart_splitter_sizes: list[int] = field(default_factory=lambda: [470, 270])
    sector_table_widths: list[int] = field(default_factory=lambda: [48, 122, 68, 68, 68, 68, 68])
    stock_table_widths: list[int] = field(
        default_factory=lambda: [48, 78, 108, 78, 78, 84, 88, 88, 88, 84, 84, 84, 84, 84, 110, 84, 140, 230]
    )
    sector_sub_pane_indicators: list[str] = field(default_factory=lambda: ["volume", "macd"])
    sector_pane_height_ratios: list[float] = field(default_factory=lambda: [0.62, 0.20, 0.18])
    sector_chart_window_size: int = 70
    show_stock_identity: bool = True
    hidden_ma_periods: list[int] = field(default_factory=lambda: list(MAIN_MA_PERIODS))
    sub_pane_indicators: list[str] = field(default_factory=lambda: ["volume", "macd"])
    pane_height_ratios: list[float] = field(default_factory=lambda: [0.62, 0.20, 0.18])
    hidden_volume_ma_periods: list[int] = field(default_factory=lambda: [5, 10, 20, 30, 60, 120])
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    kdj_n: int = 9
    kdj_k: int = 3
    kdj_d: int = 3
    pane_macd_params: list[list[int]] = field(default_factory=lambda: [[12, 26, 9] for _ in range(4)])
    pane_kdj_params: list[list[int]] = field(default_factory=lambda: [[9, 3, 3] for _ in range(4)])
    main_overlay_mode: str = "none"
    boll_n: int = 20
    boll_k: float = 2.0
    buy_budget: float = 25000.0
    sell_budget: float = 0.0
    selected_buy_ratio: float | None = 0.25
    selected_sell_ratio: float | None = 0.5
    commission_rate: float = 0.00025
    stamp_tax_rate: float = 0.0005
    min_commission: float = 5.0
    training_mode: str = "continuous"
    continuous_compound_mode: bool = True
    performance_handle_visible: bool = True
    adjust_type: str = "qfq"
    random_training_horizon: str = "6m"
    favorite_sectors: list[str] = field(default_factory=list)
    favorite_stocks: list[str] = field(default_factory=list)
    board_filters: list[str] = field(
        default_factory=lambda: ["main", "gem", "star", "bj", "st"]
    )


def load_settings() -> AppSettings:
    if not CONFIG_PATH.exists():
        return AppSettings(tdx_root=resolve_market_setting(""))
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        preserve_invalid_file(CONFIG_PATH)
        return AppSettings()
    if not isinstance(data, dict):
        preserve_invalid_file(CONFIG_PATH)
        return AppSettings()
    defaults = AppSettings()
    base = AppSettings()
    for key, value in data.items():
        if hasattr(base, key):
            setattr(base, key, value)
    base.tdx_root = base.tdx_root if isinstance(base.tdx_root, str) else defaults.tdx_root
    base.tdx_root = resolve_market_setting(base.tdx_root)
    base.initial_cash = _safe_number(base.initial_cash, defaults.initial_cash, minimum=0.01)
    base.slot_count = _safe_integer(base.slot_count, defaults.slot_count, minimum=1, maximum=20)
    base.window_width = _safe_integer(base.window_width, defaults.window_width, minimum=800, maximum=10000)
    base.window_height = _safe_integer(base.window_height, defaults.window_height, minimum=600, maximum=10000)
    if not isinstance(base.window_maximized, bool):
        base.window_maximized = defaults.window_maximized
    base.main_splitter_sizes = _safe_size_list(
        base.main_splitter_sizes, defaults.main_splitter_sizes, 2
    )
    base.sector_splitter_sizes = _safe_size_list(
        base.sector_splitter_sizes, defaults.sector_splitter_sizes, 2
    )
    base.sector_chart_splitter_sizes = _safe_size_list(
        base.sector_chart_splitter_sizes, defaults.sector_chart_splitter_sizes, 2
    )
    base.sector_table_widths = _safe_size_list(
        base.sector_table_widths, defaults.sector_table_widths, 7
    )
    base.stock_table_widths = _safe_size_list(
        base.stock_table_widths, defaults.stock_table_widths, 18
    )
    sector_indicators = (
        list(base.sector_sub_pane_indicators)
        if isinstance(base.sector_sub_pane_indicators, list)
        else []
    )
    sector_indicators = [
        value for value in sector_indicators
        if isinstance(value, str) and value in {"volume", "macd", "kdj"}
    ]
    base.sector_sub_pane_indicators = (sector_indicators or ["volume", "macd"])[:4]
    sector_pane_count = len(base.sector_sub_pane_indicators)
    sector_default_ratios = {
        1: [0.72, 0.28],
        2: [0.62, 0.20, 0.18],
        3: [0.52, 0.17, 0.16, 0.15],
        4: [0.44, 0.15, 0.14, 0.14, 0.13],
    }[sector_pane_count]
    sector_ratios = (
        list(base.sector_pane_height_ratios)
        if isinstance(base.sector_pane_height_ratios, list)
        else []
    )
    if (
        len(sector_ratios) != sector_pane_count + 1
        or any(
            not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
            for value in sector_ratios
        )
        or sum(float(value) for value in sector_ratios) <= 0
    ):
        base.sector_pane_height_ratios = sector_default_ratios
    else:
        base.sector_pane_height_ratios = [float(value) for value in sector_ratios]
    base.sector_chart_window_size = _safe_integer(
        base.sector_chart_window_size, defaults.sector_chart_window_size,
        minimum=1, maximum=750,
    )
    base.buy_budget = _safe_number(base.buy_budget, defaults.buy_budget, minimum=0.0)
    base.sell_budget = _safe_number(base.sell_budget, defaults.sell_budget, minimum=0.0)
    base.commission_rate = _safe_number(base.commission_rate, defaults.commission_rate, minimum=0.0, maximum=1.0)
    base.stamp_tax_rate = _safe_number(base.stamp_tax_rate, defaults.stamp_tax_rate, minimum=0.0, maximum=1.0)
    base.min_commission = _safe_number(base.min_commission, defaults.min_commission, minimum=0.0)
    base.macd_fast = _safe_integer(base.macd_fast, defaults.macd_fast, minimum=1)
    base.macd_slow = _safe_integer(base.macd_slow, defaults.macd_slow, minimum=base.macd_fast + 1)
    base.macd_signal = _safe_integer(base.macd_signal, defaults.macd_signal, minimum=1)
    base.kdj_n = _safe_integer(base.kdj_n, defaults.kdj_n, minimum=1)
    base.kdj_k = _safe_integer(base.kdj_k, defaults.kdj_k, minimum=1)
    base.kdj_d = _safe_integer(base.kdj_d, defaults.kdj_d, minimum=1)
    base.boll_n = _safe_integer(base.boll_n, defaults.boll_n, minimum=2)
    base.boll_k = _safe_number(base.boll_k, defaults.boll_k, minimum=0.1)
    for name in ("show_stock_identity", "performance_handle_visible"):
        if not isinstance(getattr(base, name), bool):
            setattr(base, name, getattr(defaults, name))
    for name in ("selected_buy_ratio", "selected_sell_ratio"):
        value = getattr(base, name)
        if value is not None:
            setattr(base, name, _safe_number(value, getattr(defaults, name), minimum=0.0, maximum=1.0))
    hidden_periods = base.hidden_ma_periods if isinstance(base.hidden_ma_periods, list) else []
    normalized_hidden_periods: set[int] = set()
    for value in hidden_periods:
        try:
            period = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if period in MAIN_MA_PERIODS:
            normalized_hidden_periods.add(period)
    base.hidden_ma_periods = sorted(normalized_hidden_periods)
    volume_periods = base.hidden_volume_ma_periods if isinstance(base.hidden_volume_ma_periods, list) else []
    valid_volume_periods = {5, 10, 20, 30, 60, 120}
    normalized_volume_periods: set[int] = set()
    for value in volume_periods:
        try:
            period = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if period in valid_volume_periods:
            normalized_volume_periods.add(period)
    base.hidden_volume_ma_periods = sorted(normalized_volume_periods)
    indicators = list(base.sub_pane_indicators) if isinstance(base.sub_pane_indicators, list) else []
    if any(not isinstance(value, str) for value in indicators):
        preserve_invalid_file(CONFIG_PATH)
    indicators = [value for value in indicators if isinstance(value, str) and value in {"volume", "macd", "kdj"}]
    base.sub_pane_indicators = (indicators or ["volume", "macd"])[:4]
    pane_count = len(base.sub_pane_indicators)
    default_ratios = {
        1: [0.72, 0.28],
        2: [0.62, 0.20, 0.18],
        3: [0.52, 0.17, 0.16, 0.15],
        4: [0.44, 0.15, 0.14, 0.14, 0.13],
    }[pane_count]
    ratios = list(base.pane_height_ratios) if isinstance(base.pane_height_ratios, list) else []
    valid_ratios = (
        len(ratios) == pane_count + 1
        and all(isinstance(value, (int, float)) and math.isfinite(float(value)) and value >= 0 for value in ratios)
        and sum(ratios) > 0
    )
    if not valid_ratios:
        base.pane_height_ratios = default_ratios
    else:
        base.pane_height_ratios = [float(value) for value in ratios]
    if "pane_macd_params" not in data:
        base.pane_macd_params = [[base.macd_fast, base.macd_slow, base.macd_signal] for _ in range(4)]
    else:
        base.pane_macd_params = _safe_parameter_rows(
            base.pane_macd_params,
            [base.macd_fast, base.macd_slow, base.macd_signal],
            macd=True,
        )
    if "pane_kdj_params" not in data:
        base.pane_kdj_params = [[base.kdj_n, base.kdj_k, base.kdj_d] for _ in range(4)]
    else:
        base.pane_kdj_params = _safe_parameter_rows(
            base.pane_kdj_params,
            [base.kdj_n, base.kdj_k, base.kdj_d],
            macd=False,
        )
    if not isinstance(base.main_overlay_mode, str) or base.main_overlay_mode not in {"none", "ma", "boll", "gma"}:
        base.main_overlay_mode = "none"
    raw_training_mode = data.get("training_mode")
    if not isinstance(raw_training_mode, str) or raw_training_mode not in {"single", "independent", "continuous"}:
        raw_training_mode = "continuous" if bool(base.continuous_compound_mode) else "single"
    base.training_mode = raw_training_mode
    # Keep the former boolean field readable for older session/config versions.
    base.continuous_compound_mode = base.training_mode == "continuous"
    if not isinstance(base.adjust_type, str) or base.adjust_type not in {"none", "qfq", "hfq"}:
        base.adjust_type = defaults.adjust_type
    if not isinstance(base.random_training_horizon, str) or base.random_training_horizon not in {"1m", "3m", "6m", "1y"}:
        base.random_training_horizon = "6m"
    for name in ("favorite_sectors", "favorite_stocks"):
        value = getattr(base, name)
        if not isinstance(value, list):
            setattr(base, name, [])
        else:
            setattr(base, name, [item for item in value if isinstance(item, str)][:500])
    if isinstance(base.board_filters, list):
        allowed = {"main", "gem", "star", "bj", "st"}
        base.board_filters = [
            item for item in base.board_filters if isinstance(item, str) and item in allowed
        ]
    else:
        base.board_filters = list(defaults.board_filters)
    return base


def _safe_number(value, default: float, *, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    if not math.isfinite(numeric):
        return float(default)
    if minimum is not None and numeric < minimum:
        return float(default)
    if maximum is not None and numeric > maximum:
        return float(default)
    return numeric


def _safe_integer(
    value,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    numeric = _safe_number(value, float(default))
    integer = int(numeric)
    if minimum is not None and integer < minimum:
        return int(default)
    if maximum is not None and integer > maximum:
        return int(default)
    return integer


def _safe_size_list(value, default: list[int], length: int) -> list[int]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        return list(default)
    result: list[int] = []
    for item in value:
        try:
            number = int(item)
        except (TypeError, ValueError, OverflowError):
            return list(default)
        if number <= 0:
            return list(default)
        result.append(number)
    return result


def _safe_parameter_rows(value, default: list[int], *, macd: bool) -> list[list[int]]:
    source = value if isinstance(value, list) else []
    result: list[list[int]] = []
    for index in range(4):
        row = source[index] if index < len(source) else default
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            row = default
        try:
            numbers = [int(item) for item in row]
        except (TypeError, ValueError, OverflowError):
            numbers = list(default)
        if any(number <= 0 for number in numbers) or (macd and numbers[1] <= numbers[0]):
            numbers = list(default)
        result.append(numbers)
    return result


def save_settings(settings: AppSettings) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    document = asdict(settings)
    document["tdx_root"] = portable_market_setting(settings.tdx_root)
    mode = document.get("training_mode")
    if not isinstance(mode, str) or mode not in {"single", "independent", "continuous"}:
        mode = "continuous" if bool(document.get("continuous_compound_mode")) else "single"
    document["training_mode"] = mode
    document["continuous_compound_mode"] = mode == "continuous"
    _atomic_write_bytes(
        CONFIG_PATH,
        json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8"),
    )


def ensure_packaged_user_files(
    config_path: Path | None = None,
    bundled_index_data: bytes | None = None,
    bundled_market_data: bytes | None = None,
    is_packaged: bool | None = None,
) -> None:
    """Create safe first-run AppData files without overwriting user data."""
    packaged = getattr(sys, "frozen", False) if is_packaged is None else is_packaged
    if not packaged:
        return
    target_config = config_path or CONFIG_PATH
    try:
        target_config.parent.mkdir(parents=True, exist_ok=True)
        if not target_config.exists():
            _atomic_write_bytes(
                target_config,
                json.dumps(asdict(AppSettings()), ensure_ascii=False, indent=2).encode("utf-8"),
            )
    except OSError:
        return

    _seed_packaged_json(
        target_config.parent / INDEX_CACHE_FILE_NAME,
        INDEX_CACHE_FILE_NAME,
        bundled_index_data,
        lambda document: document.get("bars", []) if isinstance(document, dict) else document,
    )
    # Market statistics belong to the user's selected TDX directory. Do not
    # seed the distributor's statistics or source paths into a fresh profile.


def _seed_packaged_json(path: Path, resource_name: str, supplied_data: bytes | None, rows_getter) -> None:
    if path.exists():
        return
    try:
        data = supplied_data
        if data is None:
            data = resources.files("stock_simulator.assets").joinpath(resource_name).read_bytes()
        document = json.loads(data.decode("utf-8-sig"))
        rows = rows_getter(document)
        if not isinstance(rows, (list, dict)) or not rows:
            return
        _atomic_write_bytes(path, data)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    ensure_writable(path)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_bytes(data)
    os.replace(temporary_path, path)
