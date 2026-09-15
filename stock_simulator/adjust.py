from __future__ import annotations

import json
import os
import re
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import DailyBar


# ---------------------------------------------------------------------------
# 前复权 / 后复权 复权模块
# ---------------------------------------------------------------------------
# 依赖：本机通达信目录下的 gbbq 权息文件 + 个股日K(.day)。
# 复权只对个股生效；指数（sh999999 等）、开市首日之前的除权事件一律跳过。
# 复权公式：
#   每股分红  = float1 / 10
#   每股送股  = float3 / 10
#   每股配股  = float4 / 10
#   配股价    = float2
#   除权参考价  = (昨收 - 每股分红 + 配股价*每股配股) / (1 + 每股送股 + 每股配股)
#   前复权因子  = 纯乘子，最靠近最新日的因子=1，越早越小（抹平除权跳空）。


# pytdx 使用的 gbbq 解密 key（4176 字节，十六进制）。已从 pytdx 源码取出并内嵌，运行时不依赖 pytdx。
GBBQ_KEY_HEX = (
    "38A7C21DE06A17E2D139A2409CBA46AF42C6FF0574EADABB89B4F844AC89D7F2987FB6BCE4F76B750504586779C86DC62B06968CFB86068BBFD6E8E187496B36C71802795325727213CC040B90240CDCDB031AD52E04855C7E8EBD02262DBD061B5034991BA22404F28835C889EAD5FB1224BBB53B29CA14A604CEA9A85802B9AAE397A3A62257BBADA0225FEB058611C3EDB13F39C236D14A43C8644DB06E3A7C516DF78EC6DFF38EA41E749DB222054D073F967F97F963B9C42B9875F6D68456DC15D3528B60F3D60EA9AD0707E9028658C2329C90BCC919BFB0547AF8CCA827638229EEFB9811BF352962919395FCF4F008E4B23AB45EB3B02E3E20C1D743597DC6295F69747FB277E10EFA85A1C9777383B3CB1C60DBE95369FCB31859150F978A7AC883F549DC1B3E86C1954546E216677F1235A0BB27FBCCF8307E4FC86DAB18B20D01CC7920807BFA37AA149E85E825E9D42D354E8FD3DEB0068D15155265E8390328090267993D13BAF3685C4C89B0E36BAE165C8825F8330319025B297B2A412D7549489BB3B6B3BFAADF8C95FE0F13B87B02BB52E11C34C39B8759E246CC22774BD7C42C31AA847C445188151ACCAE409D1F4497299845607447A10DA573F053FF01F9F49AF13607D02DA0792D812325AD4B9CC8BC12554DD4BB95B1B9BE7DA6E6A053BA838CDD7EE94BEDBA2842D8FF986935CA4E9C9D57D6CFA0895CA2E754D2AF4CFB54C4B44FC3BAF8A2586919790EA80E3DC804FD2632C8E1028BA71CC39125E5D849DBDF195F16F5A78B182304D4BFFB44C4617C796EC89015B5EB5087CA7A69472FAFA8B5A28A84C44179E8DE0CACD0D56F34C6CBA776F900244205267E7B1486597BDB1C62D5B73EF71744274BD2C66FFFC84955AD65522D43C2339B63AB3D545428E20265039A034B8F641A9252DE32D62BF0BEBE1D54B17C70419B9055DA715521B9B66890195FBCAAB4550EE6814CA3BEBC64D7590059BD0F6A571AA6A0D51A0A80D30906735A51E2DD2966ACA08629212B7A6D9E3A68D0A3DCA72B85A04CD4F0C5C443E4CF0C198130B6F6BE71F5AC25AACF429006641B4529FD3AA3B60B9D299FFA31B86DD8EC43F5927E3522E0C3D309066171DAE8360A19F62381CB89E0676EFEB1E64772635C2518E0B46585EFB51B26239089CCEEE301779563DFC4ACBFE637149915498A960291AA1D9821575E8796C7B587083F58065258178FABA84EA17A60B1695E9CBEE2D0C51259DF31EBD2195496E210118E68B41A2DD32FAB12F7FEF3A7F761FCF77CCBFC878C6A1040297B30D60D134C71CD5EAB36A2F14C05ED5388E5FF8E71795DB5AFD3676DC4446BABC1A7AA38D8701E08E6D2367B881196DBD268D9FFD8502B3AA9CC451ACACDD205C6FCA0350CEE982B5CB2396A27128F97ECCB7BB6C027F6A74875098298CA3A5DE3960CA5D2B36CA4D11FAE9967B03DD69A7A3E008BFD4532F79F287C9403DB64AA4480D227AFB373875731EB08D9BA734D2C7703BFF50F473C22DA3FB9F19A1B228316EEF418FC08E83B301C0450AA4CE32853ABDEF85F32D9E1787BF1C5A8CA85B69F891F40B82C88D7C1663445D646FD7BF372A3325523CFB5B079ABA0F1005CDBEE3F51AAAEC0898E47A5304E4BDDD6AED86D401C4E8EFB0C608D541E2F17B73AEDDEDC81F57285B7A639316F47508443C511F36A268EBA7F819831FD136B83C911614864FAE3F5392C1211C16D4D0313A6C2E0DFF5328E5B35A77F08F785270D719DB8CE9C1EBA773AF6A1A7269429C0201065756EEFAA320C66913A4E0E74E28AFEB6F817C7A7E4D835672EF083A89FA6281340A396DC498355E185ABBD4DED88FA3669A977595A9CD0A0B13DEB3116DC3E297B39015BD4FF5CE59EDAF755D53FE33B5176838E40AEE12EE83EF808B7B0242691AD824C2E2F377A34A105BD8C9A75525CCD5980CB92F8B1F8A5F22C9F4A59BFEF76A3744FE1C97C7F91D90D1205B28ED0E0BB46D45C442F656D7A1C0286FB7E7DB62A57B9DB80CD02BFE79E3521FBBE2813829FF074F79255DEF27BF2F27DF5A0140F994D25F4DC11177A776577CCBEEF9088E8FDB24E8EF526FE535D65A974470BCBE9E8719595876CFD8694A7E5FC20001E0A0AE3851724D4D0738A111E1EEF83E3D7E1BFCC98076D70373A8F3117554E60A8C8AB4F082D3776E62B58DD810FD16E9AA6553D8082999E2D169ADF4ECB3B5DDAA85308C7FF54DDC611311AB6EBA303084AFBB445ECC07C0DC6CFCB1B7846888FF46A15622F1712E6416476589678DB29B56AAEDE63416FBE9B376CC9D0EC1BF679179EFE790EB18228F20615C2BE969CE08180D700DB95874BC00D91555B1F86226474EA1B8985D2DDF79FF1D9090664FA6D5972EFCE66A703D199E8DFAED7635F605FAB6EC522C83A946A3B0072F8DB90E705DCA2890F83AA03FE42141C8AE61C9EDBD8D0CA97216CADED0AE0A29EECC1FFD1B48A9AADAB340B133FB5188D859E0DF9FBAC212EDD7ADEBF9F7EBDBF84DFF5FD1EBEE11F0FF8189D73090229B75B267E4475044DB1AA2F3ADB463812D14135912906DFC998699202F24812A971D2AE3B236D1CE26B8B75874A13A71F814D2965530A3A34CE6DE6318D7E4EDD256E7644823C47364CB9C49BF44F84431156C294537EB02E36DAEB775FC164E2CA9FBE29D8063653D06F8219DABC8C5F4D45E721379E90A6D433A8644DECBC905EFE8E8BCA177CFFAC96BB21CF3D24713BC2A1746885CF328E7F6339C5E78EA5E0CD3AF59AB8FD43D44339088E45765FDFE917545912EDD0E93D6F3F02148A0A479AD1E7FA4EA1410050EF609D4DC1CA879840E7B20F76C09D71EFD74693C12B9F11B8F905ACEDA7726BF5119B3E0A04217D06D746767BADAE9D95A6476805ADF5387CC7A55ACAB2CB4818C1F262559836390880C528B106E4FB46113C38A14F1CFEA181B7FCDB94B07AFEB574F1BB92AAFFB0FE1E318BC6BCF04F1AFE91C57A9C73094A329051018B12C020CA3CCB1483D3C77C5A1279EE561A36C409E23EDCE8CEF1C1A19E99DA644FCF1ED62B7027863ECFBE751C399BF95363C16B58CC71D2074188BB147096F168CE1375FEF4A0C885A2671849560D07941D7461890C32499D0D94734AAB1AE90FE0BAB64A34F9331DB371C2B864D70BCB19F7BDE0693E2496B1C428095F58AE8AC0839919644D443755A69BA1425084B81829B52191582388EB8F134A2409EC0F6D7DAF3EFCF7F39F343915C48403BB7E67395F2A2C6794F4A6B5023F4556790C2A9B257767C23BCCF2713B4F832A8D8C530D184954CA580EBE8B3A5374FC6F4728078EC1F553D3344B0805FFE91429401B57AD77ECE8DADA3555A77803564C7CB2ED3BB5616591DF41B45DC9B79B13824115D7B36E1CC815B4F0F33F914BA1C8907891395A2155DA6AE12CBAC93869F6AEA82B8CB714C1358235A0784756C09AA77F74146485F1B748BC558C6AA4951CCBF352F9546115275643D02795E335AA39DC2338DAEF1F27653AABF7CCBB25DB00363496D1F7C4EC4437427E171867C89C9A5B39085C3CF492F1163188FA12449E79271CC20B46ACCD1F39B89F9A56340A8586C2B1B19B31CE4757053EA7AE3F3E012DC5B9C1CBBAAB0A2AD271E4ECF80A7185CCA1CA6EEF9D8722385D8081F71A6C317B8286BD7F109D89B6F7AFE4410D4F97288034063E193A2160ED5418020F2FD5D53BA5870121381BA6993228E98D6F02356085BD64C4B0267E68D1E697B5326EB24FEB064C4DC2978E6B3022C0B43D47937867AC2742DD5C3C27ED0A6CE44A0D0FDF5263A6707609F02E58F605B2DFEEC91FCB1D110CA18B1926B8102C8148FF98EF30360C01C54AD9AC057289C73FD64DE017BABAB3D3E81B0C8CC8DF6BFE7EBA91FDF6A0CB5919B0012FD70BA0620F5FCE74B8EB4289B5BECAC9EFDA9ABBC6661BE065EED43ACED9CC0EBB8550414501BA1B29116F34115503DD0CB599563A934D4D956DCEC351E015543EFF2FA3DA59EC3D592D62FC6439D67BC880781DD7FDE80B5D8AED1A9D98CBC2EE784730AD8F64A5821223DAB33ECA4C857A80D59F4620D6EED1F933FA1FC59C8EF91E6651A54668DCB77FA85ADEE618D78C2B5DEAA8EC6B8B48C1925AC1B16A5E3782224B6AB6F040168916A581F8D41B20268635E5ADC1016EC9B5D069C50B3108515D35FC74F513047AF45710535BA4CC8B218282154B8C3D6BDA9185CBD6CF0580D0F0CF0DDF7AB499C7F8D54C765630E965B65860C1C0398A4254BC4A488BA1D95C32057A1CBB50515B7FC7752D6855E6837BC398FDE6D5B8DAA8310178F5608B1AD2FD513447FAAF23AEE2DE15A7076669359A406155259823542A50C97DA6CE74F8190C8E63E5492FF91705FD391555F4B091BF60B7B2402E7AD36886C0FC3888ABB9038A04051A9F61AEF2D3B8A429F85143CF84264A906E1327AF7B52DBF900E8AEC0B56F64035720597CF5E165A847C3BDEE722A85E2708DEA9D98D42AD570A2E976A2DAE67CB0F714D923B688C0B36F4212F4690C1581D6F70BB71BDF15E675631353B32043799034E3344880D686BB45A285DDF823643BD568AB995334C6250A877317375639BA8C0E39244BCCAA98840C2F27E6E2AC86345D1E25AEFD1EFF3C27AD26184A1AE509615D835F2CDC41A7C607555BB50B71FE86E730A1BC27AF5F24511ADD20F6329E3D646FDC43652A80CB95C4B6F0E1F3CF6CF2C29CEA81880C2DD2DA7482C6A51E98D3BC71EDE20B05DABB0EFA350A2CD5C862E7B1AF95146C837DF1CE9F136BD868C9A5F5872EA58FD75CB2C69937315AA4D0E243DFC8BEBD10C0D8226395461EE78CA861E474026CB430F3061511E62A3A0D3B2FB93BB383401879FB3938B7CE4DBAF69EAAE18F321CB168DD5C2C376561733DC63456CDEABC776AA17D6AF1F978AF0FD9C2AAD3D7A82DA86EBC198396B5A33EB3B25C54AD77CE1DE5D5AAB30D367A327D5CA360668D84A0BD4F0FA90989B8EC148A2B2B748E75775A8EB251D026D6068C9ACA31D69417F014D7431C820C0083E675055C52AB0C388FA3357752E83E3BCB4881E325B1A94012764F16F1CE3DD7238944D73F247EB74666C1167A17B22A99F1AC3CC99DC5FE89BEBF2C68BC2CA7F1C52F261ECCD1AF7DAA7DC5944A4DC487972D2B6A5E5EBF398218AB8CB9DC8083A1D180D265FE2ECC6AF10284B2366037244E5E57ADA5C5501A5EA45C31B6936057ACEBED653FBFEAC708CA130093E5E679F63720CAB46E399E834F158B15CDE78C9093B085919BAE21EF03D0A4B62AB4C6D307049254728EEC2EB3476CCE42067FE05B96F2488BFA8F83E24710A5B730F868B0FD02746F4871D7F12EDFA15261769947BE0A2FF8F2699DAD03FAE684A7CF357D8F5FC5A69B216635BC58D589B5E09F11F0A88A1FC83C24B2B7F16C8ADB3B397ACAD0EF15612272FDFC023DBD76359EE1C6D72CB259E103E0FF7A8703799F61ABCC4998C241CF6E9BAA529BD008B59E23F6C1398277165DD4E1B3ADA00C58F8E267006A0B4BD26CE1C56B9DBA3F4082C528B8C1607585EEC4FA04ED6264B62910674B9BD66C0E06626483CAF02F2DB8F60AD7D76A1C5814BE1860802902CDF6B195A56D2E279C08E31FC5C2077F637FDB82C6C685ACA6D24CF17FDB1DCF86205660C024E0C0420B4E005F8B7860FEEAEC6D31934970EB2A454F929B6C1728BB89FCC00784CCAD1B85F285185C3D5A6054AF039D9EE426D386AA0B7CA3329CC20F3AD43E1F5243A831E970FC0CB47CF5E3C76F11ED224C0C1B82CB72A495281AD41BE5C46ED7F1ECBF252CB89287A8D215793439C0BE0DC8682DF2D38E01093C4894326989D5C05DE82CE6A697594B9AC661B09EDB81DCD3F947348400CA87BE5D6D56F301023BFFFFFFFF00000000"
)
_GBBQ_KEY = bytes.fromhex(GBBQ_KEY_HEX)
assert len(_GBBQ_KEY) == 4176, f"gbbq key 长度异常: {len(_GBBQ_KEY)}"
_BINARY_CACHE_MAGIC = b"GBQ1"
_BINARY_CACHE_VERSION = 1
_BINARY_CACHE_HEADER = struct.Struct("<4sIQQII")
_BINARY_CACHE_EVENT = struct.Struct("<8sIffff")

# 预解析成 int 表（1044 个字），供解密循环快速索引。
_K = tuple(
    int.from_bytes(_GBBQ_KEY[offset : offset + 4], "little")
    for offset in range(0, len(_GBBQ_KEY), 4)
)


# 每条 gbbq 记录解密后的字节数：3 个 8 字节块 + 5 字节尾 = 29 字节。
_RECORD_SIZE = 29


@dataclass(frozen=True)
class AdjustEvent:
    """一条除权除息（category == 1）事件的每股口径参数。"""

    date: str  # YYYY-MM-DD
    dividend: float  # 每股分红（元）
    rights_price: float  # 配股价（元/股）
    bonus: float  # 每股送股
    rights: float  # 每股配股


def decode_gbbq(gbbq_path: str | Path) -> list[tuple]:
    """解密 gbbq 文件，返回原始记录列表（未按 code 分组）。"""
    content = Path(gbbq_path).read_bytes()
    count = struct.unpack_from("<I", content, 0)[0]
    pos = 4
    out: list[tuple] = []
    unpack = struct.unpack_from
    pack = struct.pack
    k = _K
    c = content
    add = out.append
    mask = 0xFFFFFFFF

    for _ in range(count):
        do = pos
        b1 = _decrypt_block(c, do, k, unpack, pack, mask)
        do += 8
        b2 = _decrypt_block(c, do, k, unpack, pack, mask)
        do += 8
        b3 = _decrypt_block(c, do, k, unpack, pack, mask)
        do += 8
        clear = pack("<IIIIII", b1[0], b1[1], b2[0], b2[1], b3[0], b3[1]) + c[do : do + 5]
        market, code, datetime, category, f1, f2, f3, f4 = unpack("<B7sIBffff", clear)
        code_text = code.rstrip(b"\x00").decode("utf-8", "replace")
        add((market, code_text, datetime, category, f1, f2, f3, f4))
        pos += _RECORD_SIZE
    return out


def _decrypt_block(c, do, k, unpack, pack, mask) -> tuple[int, int]:
    """解密 gbbq 中一个 8 字节块，返回 (numold, num)。"""
    num = (k[17] ^ unpack("<I", c, do)[0]) & mask
    numold = unpack("<I", c, do + 4)[0]
    for j in range(64, 3, -4):  # 16 次轮换
        ebx = (num & 0xFF0000) >> 16
        eax = k[274 + ebx]
        ebx = num >> 24
        eax = (eax + k[18 + ebx]) & mask
        ebx = (num & 0xFF00) >> 8
        eax = (eax ^ k[530 + ebx]) & mask
        ebx = num & 0xFF
        eax = (eax + k[786 + ebx]) & mask
        eax = (eax ^ k[j >> 2]) & mask
        ebx = num
        num = (numold ^ eax) & mask
        numold = ebx
    numold = (numold ^ k[0]) & mask
    return numold, num


def build_adjust_events(records: Iterable[tuple]) -> dict[str, list[AdjustEvent]]:
    """把解码记录按 code 分组，只保留 category == 1（除权除息）事件。"""
    events: dict[str, list[AdjustEvent]] = {}
    for market, code, datetime, category, f1, f2, f3, f4 in records:
        if category != 1 or not code:
            continue
        normalized = _normalize_gbbq_code(market, code)
        if normalized is None:
            continue
        date_text = _date_int_to_text(datetime)
        if not date_text:
            continue
        events.setdefault(normalized, []).append(
            AdjustEvent(
                date=date_text,
                dividend=round(f1 / 10, 6),
                rights_price=round(f2, 6),
                bonus=round(f3 / 10, 6),
                rights=round(f4 / 10, 6),
            )
        )
    for code in events:
        events[code].sort(key=lambda item: item.date)
    return events


def _normalize_gbbq_code(market: int, code: str) -> str | None:
    if not re.fullmatch(r"\d{6}", code):
        return None
    if market == 0:
        return f"sz{code}"
    if market == 1:
        return f"sh{code}"
    if market == 2:
        return f"bj{code}"
    return None


def _date_int_to_text(value: int) -> str:
    text = str(int(value))
    if not re.fullmatch(r"\d{8}", text):
        return ""
    return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"


def build_adjust_factors(bars: list[DailyBar], events: list[AdjustEvent], adjust_type: str) -> list[float]:
    """返回与 bars 等长的复权因子序列。

    adjust_type: "qfq" 前复权（越早越小，最新段=1）；"hfq" 后复权（最早段=1，越新越大）。
    """
    if adjust_type not in ("qfq", "hfq") or not bars or not events:
        return [1.0] * len(bars)

    ratios: list[tuple[str, float]] = []
    for event in events:
        prev_close = _prev_close_before(bars, event.date)
        if prev_close is None or prev_close <= 0:
            continue
        denominator = 1.0 + event.bonus + event.rights
        if denominator <= 0:
            continue
        reference = (prev_close - event.dividend + event.rights_price * event.rights) / denominator
        if reference <= 0:
            continue
        ratio = reference / prev_close
        if ratio <= 0 or ratio > 20:  # 防御异常值
            continue
        ratios.append((event.date, ratio))
    ratios.sort(key=lambda item: item[0])

    # 先算前复权因子：越早越小、最新段=1（用于抹平除权跳空）。
    factors = [1.0] * len(bars)
    m = 1.0
    e = len(ratios) - 1
    for i in range(len(bars) - 1, -1, -1):
        date = bars[i].date
        while e >= 0 and ratios[e][0] > date:
            m *= ratios[e][1]
            e -= 1
        factors[i] = m
    if adjust_type == "hfq":
        # 后复权 = 前复权因子整体归一化，使最早一根的因子 = 1（最新价被放大）。
        base = factors[0] if factors[0] > 0 else 1.0
        factors = [factor / base for factor in factors]
    return [max(1e-6, factor) for factor in factors]


def _prev_close_before(bars: list[DailyBar], date: str) -> float | None:
    previous = None
    for bar in bars:
        if bar.date >= date:
            break
        previous = bar.close
    return previous


def apply_adjust_bars(bars: list[DailyBar], events: list[AdjustEvent], adjust_type: str) -> list[DailyBar]:
    """把 bars 按复权因子重算开高低收，返回新的 DailyBar 列表。"""
    if adjust_type not in ("qfq", "hfq") or not events:
        return list(bars)
    factors = build_adjust_factors(bars, events, adjust_type)
    adjusted: list[DailyBar] = []
    for bar, factor in zip(bars, factors):
        adjusted.append(
            DailyBar(
                code=bar.code,
                date=bar.date,
                open=_scale_price(bar.open, factor),
                high=_scale_price(bar.high, factor),
                low=_scale_price(bar.low, factor),
                close=_scale_price(bar.close, factor),
                amount=bar.amount,
                volume=bar.volume,
            )
        )
    return adjusted


def _scale_price(price: float, factor: float) -> float:
    scaled = round(price * factor, 3)
    # 前复权可能把极早期价格调到很小，但不允许为非正数，避免破坏图表/交易逻辑。
    return max(0.01, scaled)


class GbbqProvider:
    """负责 gbbq 解码、磁盘缓存与按 code 提供复权事件。

    设计为可后台解码：先调用 initialize()（首次约 10 秒），完成后 ready=True；
    之后 apply() 只做内存索引 + 乘因子，秒级完成。缓存文件放配置目录，避免被程序更新覆盖。
    """

    def __init__(self, gbbq_path: str | Path, cache_path: str | Path | None = None):
        self.gbbq_path = Path(gbbq_path)
        self.cache_path = Path(cache_path) if cache_path else None
        self.events_by_code: dict[str, list[AdjustEvent]] = {}
        self._binary_cache_data: bytes | None = None
        self._binary_event_offsets: dict[str, list[int]] = {}
        self.ready = False
        self.error: str | None = None
        self._lock = threading.RLock()

    def initialize(self, force: bool = False) -> None:
        """加载事件（优先磁盘缓存；缓存缺失或过期则解码）。线程安全，可后台调用。"""
        with self._lock:
            if self.ready and not force:
                return
            self.ready = False
            self.error = None
            try:
                if not self.gbbq_path.exists():
                    self.error = f"未找到复权文件：{self.gbbq_path}"
                    return
                if not force and self._load_from_cache():
                    self.ready = True
                    return
                records = decode_gbbq(self.gbbq_path)
                self.events_by_code = build_adjust_events(records)
                self._save_cache()
                self.ready = True
            except Exception as exc:  # noqa: BLE001
                self.error = str(exc)
                self.ready = False

    def events_for(self, code: str) -> list[AdjustEvent]:
        normalized = code.strip().lower()
        with self._lock:
            if normalized not in self.events_by_code and self._binary_cache_data is not None:
                loaded: list[AdjustEvent] = []
                for offset in self._binary_event_offsets.get(normalized, []):
                    try:
                        _raw_code, raw_date, dividend, rights_price, bonus, rights = _BINARY_CACHE_EVENT.unpack_from(
                            self._binary_cache_data,
                            offset,
                        )
                    except struct.error:
                        continue
                    date_text = _date_int_to_text(raw_date)
                    if not date_text:
                        continue
                    loaded.append(
                        AdjustEvent(
                            date=date_text,
                            dividend=round(float(dividend), 6),
                            rights_price=round(float(rights_price), 6),
                            bonus=round(float(bonus), 6),
                            rights=round(float(rights), 6),
                        )
                    )
                if loaded:
                    self.events_by_code[normalized] = loaded
            return list(self.events_by_code.get(normalized, []))

    def apply(self, bars: list[DailyBar], code: str, adjust_type: str) -> list[DailyBar] | None:
        """若该 code 有除权事件且复权开关开启，返回复权后的 bars；否则返回 None（保持原样）。"""
        if adjust_type not in ("qfq", "hfq") or not bars or not self.ready:
            return None
        events = self.events_for(code)
        if not events:
            return None
        return apply_adjust_bars(bars, events, adjust_type)

    def is_index_or_ineligible(self, code: str) -> bool:
        """指数及非 6/0/3/4/8 开头的代码不参与复权。"""
        normalized = code.strip().lower()
        return not (
            normalized.startswith("sh60")
            or normalized.startswith("sh68")
            or normalized.startswith("sz00")
            or normalized.startswith("sz30")
            or normalized.startswith("bj")
        )

    def _load_from_cache(self) -> bool:
        if self.cache_path is None:
            return False
        if self._load_from_binary_cache():
            return True
        if not self.cache_path.exists():
            return False
        try:
            document = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return False
        if document.get("gbbq_path") != str(self.gbbq_path):
            return False
        info = _file_info(self.gbbq_path)
        if document.get("size") != info["size"] or document.get("mtime_ns") != info["mtime_ns"]:
            return False
        raw_events = document.get("events", {})
        if not isinstance(raw_events, dict):
            return False
        events_by_code: dict[str, list[AdjustEvent]] = {}
        for code, rows in raw_events.items():
            if not isinstance(rows, list):
                continue
            code_events: list[AdjustEvent] = []
            for row in rows:
                try:
                    code_events.append(
                        AdjustEvent(
                            date=str(row["date"]),
                            dividend=float(row["dividend"]),
                            rights_price=float(row["rights_price"]),
                            bonus=float(row["bonus"]),
                            rights=float(row["rights"]),
                        )
                    )
                except (TypeError, ValueError, KeyError):
                    continue
            if code_events:
                events_by_code[code] = code_events
        self.events_by_code = events_by_code
        self._save_binary_cache()
        return True

    def _binary_cache_path(self) -> Path | None:
        if self.cache_path is None:
            return None
        return self.cache_path.with_suffix(".bin")

    def _load_from_binary_cache(self) -> bool:
        binary_path = self._binary_cache_path()
        if binary_path is None or not binary_path.exists():
            return False
        try:
            data = binary_path.read_bytes()
            magic, version, size, mtime_ns, path_length, event_count = _BINARY_CACHE_HEADER.unpack_from(data, 0)
        except (OSError, struct.error):
            return False
        info = _file_info(self.gbbq_path)
        if magic != _BINARY_CACHE_MAGIC or version != _BINARY_CACHE_VERSION:
            return False
        if (size, mtime_ns) != (info["size"], info["mtime_ns"]):
            return False
        path_start = _BINARY_CACHE_HEADER.size
        path_end = path_start + path_length
        records_end = path_end + event_count * _BINARY_CACHE_EVENT.size
        if records_end != len(data):
            return False
        try:
            cached_path = data[path_start:path_end].decode("utf-8")
        except UnicodeDecodeError:
            return False
        if cached_path != str(self.gbbq_path):
            return False
        event_offsets: dict[str, list[int]] = {}
        offset = path_end
        try:
            for _ in range(event_count):
                raw_code = data[offset : offset + 8]
                record_offset = offset
                offset += _BINARY_CACHE_EVENT.size
                code = raw_code.rstrip(b"\0").decode("ascii")
                if code:
                    event_offsets.setdefault(code, []).append(record_offset)
        except UnicodeDecodeError:
            return False
        self.events_by_code = {}
        self._binary_cache_data = data
        self._binary_event_offsets = event_offsets
        return True

    def _save_binary_cache(self) -> None:
        binary_path = self._binary_cache_path()
        if binary_path is None:
            return
        info = _file_info(self.gbbq_path)
        path_data = str(self.gbbq_path).encode("utf-8")
        event_count = sum(len(events) for events in self.events_by_code.values())
        payload = bytearray(
            _BINARY_CACHE_HEADER.size
            + len(path_data)
            + event_count * _BINARY_CACHE_EVENT.size
        )
        _BINARY_CACHE_HEADER.pack_into(
            payload,
            0,
            _BINARY_CACHE_MAGIC,
            _BINARY_CACHE_VERSION,
            info["size"],
            info["mtime_ns"],
            len(path_data),
            event_count,
        )
        offset = _BINARY_CACHE_HEADER.size
        payload[offset : offset + len(path_data)] = path_data
        offset += len(path_data)
        for code, events in self.events_by_code.items():
            raw_code = code.encode("ascii", "ignore")[:8].ljust(8, b"\0")
            for event in events:
                _BINARY_CACHE_EVENT.pack_into(
                    payload,
                    offset,
                    raw_code,
                    int(event.date.replace("-", "")),
                    event.dividend,
                    event.rights_price,
                    event.bonus,
                    event.rights,
                )
                offset += _BINARY_CACHE_EVENT.size
        temporary_path = binary_path.with_suffix(binary_path.suffix + ".tmp")
        try:
            binary_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_bytes(payload)
            os.replace(temporary_path, binary_path)
        except OSError:
            try:
                temporary_path.unlink()
            except OSError:
                pass

    def _save_cache(self) -> None:
        if self.cache_path is None:
            return
        info = _file_info(self.gbbq_path)
        payload = {
            "gbbq_path": str(self.gbbq_path),
            "size": info["size"],
            "mtime_ns": info["mtime_ns"],
            "events": {
                code: [
                    {
                        "date": event.date,
                        "dividend": event.dividend,
                        "rights_price": event.rights_price,
                        "bonus": event.bonus,
                        "rights": event.rights,
                    }
                    for event in events
                ]
                for code, events in self.events_by_code.items()
            },
        }
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
            temporary_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary_path, self.cache_path)
        except OSError:
            pass
        self._save_binary_cache()


def _file_info(path: Path) -> dict:
    try:
        stat = path.stat()
        return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    except OSError:
        return {"size": -1, "mtime_ns": -1}


def locate_gbbq_path(tdx_root: str | Path) -> Path:
    return Path(tdx_root) / "T0002" / "hq_cache" / "gbbq"


def default_cache_path() -> Path:
    from .config import CONFIG_PATH

    return CONFIG_PATH.parent / "gbbq_events.json"
