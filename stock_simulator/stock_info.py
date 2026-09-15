from __future__ import annotations

from bisect import bisect_right
import struct
from dataclasses import dataclass
from pathlib import Path
import re

from .tdx_reader import TdxDayReader


PINYIN_INITIAL_BOUNDARIES = (
    (-20319, "A"), (-20283, "B"), (-19775, "C"), (-19218, "D"),
    (-18710, "E"), (-18526, "F"), (-18239, "G"), (-17922, "H"),
    (-17417, "J"), (-16474, "K"), (-16212, "L"), (-15640, "M"),
    (-15165, "N"), (-14922, "O"), (-14914, "P"), (-14630, "Q"),
    (-14149, "R"), (-14090, "S"), (-13318, "T"), (-12838, "W"),
    (-12556, "X"), (-11847, "Y"), (-11055, "Z"),
)
PINYIN_INITIAL_CODES = tuple(item[0] for item in PINYIN_INITIAL_BOUNDARIES)
TNF_HEADER_SIZE = 50
TNF_RECORD_SIZE = 360


def stock_name_initials(name: str) -> str:
    cleaned = re.sub(r"^(?:S\*?ST|\*ST|ST|N|C)", "", name.strip(), flags=re.IGNORECASE)
    initials: list[str] = []
    for position, character in enumerate(cleaned):
        # “银行”的“行”读 hang；逐字编码表只会得到 xing。
        if character == "行" and position > 0 and cleaned[position - 1] == "银":
            initials.append("H")
            continue
        if character.isascii() and character.isalpha():
            initials.append(character.upper())
            continue
        try:
            encoded = character.encode("gbk")
        except UnicodeEncodeError:
            continue
        if len(encoded) != 2:
            continue
        signed_code = encoded[0] * 256 + encoded[1] - 65536
        index = bisect_right(PINYIN_INITIAL_CODES, signed_code) - 1
        if 0 <= index < len(PINYIN_INITIAL_BOUNDARIES):
            initials.append(PINYIN_INITIAL_BOUNDARIES[index][1])
    return "".join(initials)


@dataclass(frozen=True)
class StockInfo:
    code: str
    name: str = ""
    float_a_shares: int | None = None


class StockInfoReader:
    def __init__(self, tdx_root: str | Path):
        self.tdx_root = Path(tdx_root)
        self._cache: dict[str, StockInfo] | None = None
        self._name_cache: dict[str, str] | None = None
        self._single_name_cache: dict[str, str] = {}
        self._tnf_bytes_cache: dict[str, bytes] = {}

    def get(self, code: str) -> StockInfo:
        normalized = TdxDayReader.normalize_code(code)
        cache = self._load_cache()
        return cache.get(normalized, StockInfo(code=normalized))

    def name_for(self, code: str) -> str:
        """Read only the stock name table, without parsing the heavier DBF."""
        normalized = TdxDayReader.normalize_code(code)
        if self._name_cache is not None:
            return self._name_cache.get(normalized, "")
        if normalized in self._single_name_cache:
            return self._single_name_cache[normalized]
        filename = {"sh": "shs.tnf", "sz": "szs.tnf", "bj": "bjs.tnf"}.get(normalized[:2], "szs.tnf")
        path = self.tdx_root / "T0002" / "hq_cache" / filename
        try:
            data = self._tnf_bytes_cache.get(filename)
            if data is None:
                data = path.read_bytes()
                self._tnf_bytes_cache[filename] = data
        except OSError:
            data = b""
        name = ""
        if len(data) >= TNF_HEADER_SIZE and (len(data) - TNF_HEADER_SIZE) % TNF_RECORD_SIZE == 0:
            target = normalized[2:].encode("ascii")
            for start in range(TNF_HEADER_SIZE, len(data), TNF_RECORD_SIZE):
                if data[start : start + 6] != target:
                    continue
                name = data[start + 31 : start + 64].split(b"\0", 1)[0].decode("gbk", "ignore").strip()
                break
        if not name:
            name = self._load_name_cache().get(normalized, "")
        self._single_name_cache[normalized] = name
        return name

    def turnover_rate(self, code: str, volume: int) -> float | None:
        info = self.get(code)
        if not info.float_a_shares:
            return None
        return round(volume / info.float_a_shares * 100, 2)

    def resolve_code_query(self, query: str, available_codes: list[str] | None = None) -> str:
        cleaned = query.strip()
        if re.fullmatch(r"(?:sh|sz)?\d{6}", cleaned, flags=re.IGNORECASE):
            return TdxDayReader.normalize_code(cleaned)
        if not re.fullmatch(r"[A-Za-z]+", cleaned):
            raise ValueError("股票请输入6位代码，或中文名称的拼音首字母缩写。")

        abbreviation = cleaned.upper()
        matches = self.find_code_matches(abbreviation, available_codes)
        if not matches:
            raise ValueError(
                f"没有找到首字母为 {abbreviation} 的本地股票。"
                "请确认通达信基础资料已更新，或直接输入6位股票代码。"
            )
        if len(matches) > 1:
            choices = "、".join(f"{item.name}({item.code[2:]})" for item in matches[:6])
            raise ValueError(f"首字母 {abbreviation} 匹配到多只股票：{choices}。请改用6位股票代码。")
        return matches[0].code

    def find_code_matches(self, query: str, available_codes: list[str] | None = None) -> list[StockInfo]:
        """返回名称拼音首字母完全匹配的本地股票，供界面展示候选。"""
        abbreviation = query.strip().upper()
        if not abbreviation or not re.fullmatch(r"[A-Z]+", abbreviation):
            return []
        available = set(available_codes) if available_codes is not None else None
        matches = [
            StockInfo(code=code, name=name)
            for code, name in self._load_name_cache().items()
            if stock_name_initials(name) == abbreviation and (available is None or code in available)
        ]
        return sorted(matches, key=lambda item: item.code)

    def _load_cache(self) -> dict[str, StockInfo]:
        if self._cache is not None:
            return self._cache
        path = self.tdx_root / "T0002" / "hq_cache" / "base.dbf"
        self._cache = {}
        if not path.exists():
            return self._cache

        data = path.read_bytes()
        if len(data) < 32:
            return self._cache
        record_count = struct.unpack("<I", data[4:8])[0]
        header_len = struct.unpack("<H", data[8:10])[0]
        record_len = struct.unpack("<H", data[10:12])[0]
        fields = self._read_fields(data, header_len)
        offsets = {}
        pos = 1
        for name, _kind, length, _decimals in fields:
            offsets[name] = (pos, length)
            pos += length
        if "GPDM" not in offsets or "LTAG" not in offsets:
            return self._cache
        name_cache = self._load_name_cache()

        for row in range(record_count):
            start = header_len + row * record_len
            record = data[start : start + record_len]
            if len(record) < record_len or record[:1] == b"*":
                continue
            raw_code = self._field_text(record, offsets["GPDM"])
            raw_float_a = self._field_text(record, offsets["LTAG"])
            if not raw_code:
                continue
            try:
                float_a_shares = int(float(raw_float_a) * 10000)
            except ValueError:
                float_a_shares = None
            code = TdxDayReader.normalize_code(raw_code)
            self._cache[code] = StockInfo(code=code, name=name_cache.get(code, ""), float_a_shares=float_a_shares)
        return self._cache

    def _name_for_code(self, code: str) -> str:
        return self.name_for(code)

    def _load_name_cache(self) -> dict[str, str]:
        if self._name_cache is not None:
            return self._name_cache
        self._name_cache = {}
        self._load_tnf_names("shs.tnf", "sh")
        self._load_tnf_names("szs.tnf", "sz")
        self._load_tnf_names("bjs.tnf", "bj")
        return self._name_cache

    def _load_tnf_names(self, filename: str, prefix: str) -> None:
        path = self.tdx_root / "T0002" / "hq_cache" / filename
        if not path.exists():
            return
        try:
            data = path.read_bytes()
        except OSError:
            return
        if len(data) >= TNF_HEADER_SIZE and (len(data) - TNF_HEADER_SIZE) % TNF_RECORD_SIZE == 0:
            for start in range(TNF_HEADER_SIZE, len(data), TNF_RECORD_SIZE):
                record = data[start : start + TNF_RECORD_SIZE]
                raw_code = record[:6]
                if len(raw_code) != 6 or not raw_code.isdigit():
                    continue
                name = record[31:64].split(b"\0", 1)[0].decode("gbk", "ignore").strip()
                if name:
                    self._name_cache[f"{prefix}{raw_code.decode('ascii')}"] = name
            return
        for match in re.finditer(rb"(?<!\d)(\d{6})\x00{8,}", data):
            raw_code = match.group(1).decode("ascii")
            raw_name = data[match.start() + 31 : match.start() + 64]
            name = raw_name.split(b"\0", 1)[0].decode("gbk", "ignore").strip()
            if name:
                self._name_cache[f"{prefix}{raw_code}"] = name

    @staticmethod
    def _read_fields(data: bytes, header_len: int) -> list[tuple[str, str, int, int]]:
        fields: list[tuple[str, str, int, int]] = []
        offset = 32
        while offset + 32 <= header_len and data[offset] != 13:
            raw = data[offset : offset + 32]
            name = raw[:11].split(b"\0", 1)[0].decode("gbk", "ignore")
            fields.append((name, chr(raw[11]), raw[16], raw[17]))
            offset += 32
        return fields

    @staticmethod
    def _field_text(record: bytes, field: tuple[int, int]) -> str:
        start, length = field
        return record[start : start + length].decode("gbk", "ignore").strip()


BOARD_CATEGORIES = frozenset({'main', 'gem', 'star', 'bj', 'st'})
BOARD_CATEGORY_LABELS = (
    ('main', '主板'),
    ('gem', '创业板'),
    ('star', '科创板'),
    ('bj', '北交所'),
    ('st', 'ST'),
)


def stock_category(code: str, name: str = '') -> str:
    """股票分类（五类互斥）：st 风险警示 / main 主板 / gem 创业板 / star 科创板 / bj 北交所。"""
    if 'ST' in (name or '').upper():
        return 'st'
    if code.startswith('bj'):
        return 'bj'
    if code.startswith('sz30'):
        return 'gem'
    if code.startswith('sh68'):
        return 'star'
    return 'main'
