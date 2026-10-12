#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
img2save.py —— 把图片转换成 The Powder Toy(粉末玩具)沙盘文件(.cps)

生成的 .cps 可以直接拖进游戏窗口, 或放进 TPT 的 saves 目录里打开。

常见用法:
    python3 tools/img2save.py photo.png                 # 生成 photo.cps(真彩色, DMND + 装饰色)
    python3 tools/img2save.py photo.jpg -W 400          # 限制宽度 400, 高度按比例
    python3 tools/img2save.py logo.png -m palette --dither floyd --paused
    python3 tools/img2save.py art.png -e WOOD --preview 预览.png --verify

两种着色方式:
    deco(默认)  每个像素放一个元素粒子, 并用"装饰色"染成图片的原始颜色,
                画面和原图几乎一模一样, 但元素本身是同一种(默认 DMND 钻石)。
    palette     只用真实元素自身的颜色去"拼"图片(不做染色), 更有 TPT 味道,
                可以配合 --dither floyd 抖动来减轻色带。

依赖: 只用到标准库。装了 Pillow 时可以读 jpg/webp/bmp 等任意格式;
      没装 Pillow 时脚本会退回自带的纯 Python PNG 解码器(只支持 PNG)。
"""

import argparse
import bz2
import os
import re
import struct
import sys
import zlib

# --------------------------------------------------------------------------
# 存档格式相关常量(与 src/SimulationConfig.h、src/client/GameSave.cpp 保持一致)
# --------------------------------------------------------------------------

CELL = 4                  # 一个"墙格"覆盖 4x4 像素
MAX_W, MAX_H = 612, 384   # 游戏画布尺寸 XRES x YRES
SAVE_VERSION = 97         # PSv 格式能写的最高版本号(GameSave::readPSv 拒绝 > 97)
ROOM_TEMP = 295           # 默认温度(开尔文, 约 22 度)

# 存档里除了常规字段外, 这些元素还要多存 1 字节 ctype(见 GameSave::readPSv)
CTYPE_ELEMENTS = ("CLNE", "PCLN", "BCLN", "SPRK", "LAVA",
                  "PIPE", "LIFE", "PBCN", "WIRE", "STOR", "CONV")
# 这些元素还要多存 1 字节 tmp2
TMP2_ELEMENTS = ("PBCN", "TRON")

# 空气/重力模式的取值, 与 src/simulation/SimulationSettings.h 的枚举一致
AIR_MODES = {"on": 0, "pressure-off": 1, "velocity-off": 2, "off": 3, "no-update": 4}
GRAVITY_MODES = {"vertical": 0, "off": 1, "radial": 2, "custom": 3}

# --------------------------------------------------------------------------
# 元素表: 名称 -> (编号, 颜色)
#
# 优先从本仓库的源码里现读(src/simulation), 这样元素编号和本版本完全一致;
# 找不到源码(比如把脚本单独拷走用)时, 用下面这份内置表兜底。
# --------------------------------------------------------------------------

_FALLBACK_ELEMENTS = {
    "NONE": (0, 0x000000), "DUST": (1, 0xFFE0A0), "WATR": (2, 0x2030D0),
    "OIL": (3, 0x404010), "FIRE": (4, 0xFF1000), "STNE": (5, 0xA0A0A0),
    "LAVA": (6, 0xE05010), "GUNP": (7, 0xC0C0D0), "NITR": (8, 0x20E010),
    "CLNE": (9, 0xFFD010), "GAS": (10, 0xE0FF20), "PLEX": (11, 0x808040),
    "GOO": (12, 0x804000), "ICEI": (13, 0xC0E0FF), "METL": (14, 0x404060),
    "SPRK": (15, 0xFFFF80), "SNOW": (16, 0xC0E0FF), "WOOD": (17, 0xC0A040),
    "NEUT": (18, 0x20E0FF), "PLUT": (19, 0x407020), "PLNT": (20, 0x0CAC00),
    "ACID": (21, 0xED55FF), "VOID": (22, 0x790B0B), "WTRV": (23, 0xA0A0FF),
    "CNCT": (24, 0xC0C0C0), "DSTW": (25, 0x1020C0), "SALT": (26, 0xFFFFFF),
    "SLTW": (27, 0x4050F0), "DMND": (28, 0xCCFFFF), "BMTL": (29, 0x505070),
    "BRMT": (30, 0x705060), "PHOT": (31, 0xFFFFFF), "URAN": (32, 0x707020),
    "WAX": (33, 0xF0F0BB), "MWAX": (34, 0xE0E0AA), "PSCN": (35, 0x805050),
    "NSCN": (36, 0x505080), "LNTG": (37, 0xE0FF20), "INSL": (38, 0x9EA3B6),
    "BHOL": (39, 0x202020), "WHOL": (40, 0xFFFFFF), "RBDM": (41, 0xCCCCCC),
    "LRBD": (42, 0xAAAAAA), "NTCT": (43, 0x505040), "SAND": (44, 0xFFD090),
    "GLAS": (45, 0x404040), "PTCT": (46, 0x405050), "BGLA": (47, 0x606060),
    "THDR": (48, 0xFFFFA0), "PLSM": (49, 0xBB99FF), "ETRD": (50, 0x404040),
    "NICE": (51, 0xC0E0FF), "NBLE": (52, 0xEB4917), "BTRY": (53, 0x858505),
    "LCRY": (54, 0x505050), "STKM": (55, 0xFFE0A0), "SWCH": (56, 0x103B11),
    "SMKE": (57, 0x222222), "DESL": (58, 0x440000), "COAL": (59, 0x222222),
    "LO2": (60, 0x4A5EFF), "O2": (61, 0x4A5EFF), "INWR": (62, 0x544141),
    "YEST": (63, 0xEEE0C0), "DYST": (64, 0xBBB0A0), "THRM": (65, 0xA08090),
    "GLOW": (66, 0x445464), "BRCK": (67, 0x808080), "CFLM": (68, 0x8080FF),
    "FIRW": (69, 0xFFA040), "FUSE": (70, 0x0A5706), "AMTR": (72, 0x808080),
    "BCOL": (73, 0x333333), "PCLN": (74, 0x3B3B0A), "HSWC": (75, 0x3B0A0A),
    "IRON": (76, 0x707070), "MORT": (77, 0xE0E0E0), "LIFE": (78, 0x0CAC00),
    "DLAY": (79, 0x753590), "CO2": (80, 0x666666), "DRIC": (81, 0xE0E0E0),
    "CBNW": (82, 0x5A5A5A), "STOR": (83, 0x50DFDF), "PVOD": (84, 0x792020),
    "CONV": (85, 0x0AAB0A), "CAUS": (86, 0x80FFA0), "LIGH": (87, 0xFFFFC0),
    "TESC": (88, 0x707040), "DEST": (89, 0xFF3311), "SPNG": (90, 0xFFBE30),
    "RIME": (91, 0xCCCCCC), "FOG": (92, 0xAAAAAA), "BCLN": (93, 0xFFD040),
    "LOVE": (94, 0xFF30FF), "DEUT": (95, 0x00153F), "WARP": (96, 0x101010),
    "PUMP": (97, 0x0A0A3B), "FWRK": (98, 0x666666), "PIPE": (99, 0x444444),
    "FRZZ": (100, 0xC0E0FF), "BIZR": (103, 0x00FF77), "BIZRG": (104, 0x00FF77),
    "BIZRS": (105, 0x00FF77), "INST": (106, 0x404039), "ISOZ": (107, 0xAA30D0),
    "ISZS": (108, 0x662089), "PRTI": (109, 0xEB5917), "PRTO": (110, 0x0020EB),
    "PSTE": (111, 0xAA99AA), "PSTS": (112, 0x776677), "ANAR": (113, 0xFFFFEE),
    "VINE": (114, 0x079A00), "INVIS": (115, 0x141414), "E116": (116, 0xFF0000),
    "LOLZ": (123, 0x569212), "WIFI": (124, 0x40A060), "FILT": (125, 0x000056),
    "BRAY": (127, 0xFFFFFF), "BOMB": (129, 0xFFF288), "SING": (131, 0x242424),
    "QRTZ": (132, 0xAADDDD), "PQRT": (133, 0x88BBBB), "EMP": (134, 0x66AAFF),
    "BREC": (135, 0x808080), "ELEC": (136, 0xDFEFFF), "ACEL": (137, 0x0099CC),
    "DCEL": (138, 0x99CC00), "BANG": (139, 0xFFEED0), "IGNT": (140, 0xFFA040),
    "BOYL": (141, 0x0A3200), "GEL": (142, 0xFF9900), "TRON": (143, 0xA9FF00),
    "TTAN": (144, 0x909090), "EXOT": (145, 0x247BFE), "EMBR": (146, 0xFFF288),
    "SOAP": (148, 0xF5F5DC), "MERC": (151, 0x736B6D), "PBCN": (152, 0x3B1D0A),
    "GPMP": (153, 0x0A3B3B), "CLST": (154, 0xE4A4A4), "WIRE": (155, 0x808080),
    "GBMB": (156, 0x1144BB), "FIGH": (157, 0xFFE0A0), "FRAY": (158, 0x00BBFF),
    "RPEL": (159, 0x99CC00), "PPIP": (160, 0x444466), "DTEC": (161, 0xFD9D18),
    "DMG": (162, 0x88FF88), "TSNS": (163, 0xFD00D5), "VIBR": (164, 0x005000),
    "BVBR": (165, 0x005000), "CRAY": (166, 0xBBFF00), "PSTN": (167, 0xAA9999),
    "FRME": (168, 0x999988), "GOLD": (169, 0xDCAD2C), "TUNG": (170, 0x505050),
    "PSNS": (171, 0xDB2020), "PROT": (172, 0x990000), "VIRS": (173, 0xFE11F6),
    "VRSS": (174, 0xD408CD), "VRSG": (175, 0xFE68FE), "GRVT": (176, 0x00EE76),
    "DRAY": (177, 0xFFAA22), "CRMC": (178, 0xD6D1D4), "HEAC": (179, 0xCB6351),
    "SAWD": (180, 0xF0F0A0), "POLO": (181, 0x506030), "RFRG": (182, 0x72D2D4),
    "RFGL": (183, 0x84C2CF), "LSNS": (184, 0x336699), "LDTC": (185, 0x66FF66),
    "SLCN": (186, 0xBCCDDF), "PTNM": (187, 0xD5E0EB), "VSNS": (188, 0x7C9C00),
    "ROCK": (189, 0x727272), "LITH": (190, 0xB6AABF), "RSST": (191, 0xF95B49),
    "RSSS": (192, 0xC43626), "BASE": (193, 0x90D5FF), "SEED": (194, 0x88E788),
}

# 内置调色板
# default: 颜色分得比较开, 兼顾亮/暗、冷/暖, 会有会流动/燃烧的元素(更"活")
DEFAULT_PALETTE = [
    "DMND", "WHOL", "WAX", "SAND", "DUST", "GOLD", "THDR", "FIRW", "GEL",
    "LAVA", "RSST", "FIRE", "BRMT", "WOOD", "OIL", "SEED", "NITR", "PLNT",
    "VINE", "LOLZ", "STOR", "PQRT", "QRTZ", "ICEI", "BASE", "SLTW", "WATR",
    "DSTW", "EXOT", "DLAY", "LOVE", "INSL", "TTAN", "STNE", "METL", "IRON",
    "ROCK", "BCOL", "COAL",
]

# solid: 只挑静态固体, 画面不会自己动, 适合做"不会塌"的画像
SOLID_PALETTE = [
    "DMND", "WHOL", "CRMC", "PTNM", "SLCN", "QRTZ", "PQRT", "ICEI", "SNOW",
    "SAWD", "WAX", "GOLD", "STNE", "TTAN", "PSTN", "LITH", "ROCK", "IRON",
    "METL", "BMTL", "TUNG", "GLAS", "INSL", "WOOD", "BRMT", "SPNG", "BCOL",
    "COAL",
]

# 不能拿来画画的"特殊"元素
UNUSABLE_ELEMENTS = {"NONE", "SPAWN", "SPAWN2", "STKM", "STKM2", "FIGH",
                     "PRTI", "PRTO", "E116", "INVIS", "SHLD1", "SHLD2",
                     "SHLD3", "SHLD4", "C5", "PVOD", "VIRS", "VRSS", "VRSG",
                     "PROT", "LOVE", "WARP", "WHOL", "BHOL", "ANAR"}


class Element(object):
    """一个元素: 存档编号 + 游戏里的显示颜色"""

    __slots__ = ("name", "number", "colour")

    def __init__(self, name, number, colour):
        self.name = name
        self.number = number
        self.colour = colour

    @property
    def rgb(self):
        return ((self.colour >> 16) & 0xFF, (self.colour >> 8) & 0xFF, self.colour & 0xFF)


def find_repo_root():
    """从脚本所在目录往上找仓库根目录(含 src/simulation/elements/meson.build)"""
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        if os.path.isfile(os.path.join(here, "src", "simulation", "elements", "meson.build")):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return None


def load_element_table(root=None):
    """读元素编号和颜色。优先读源码, 失败则用内置表。"""
    table = {}
    root = root or find_repo_root()
    if root:
        try:
            table = _parse_elements_from_source(root)
        except Exception as exc:  # 源码结构变了也不该让脚本挂掉
            sys.stderr.write("警告: 读取源码中的元素表失败(%s), 改用内置元素表\n" % exc)
    if not table:
        table = dict((name, Element(name, num, col))
                     for name, (num, col) in _FALLBACK_ELEMENTS.items())
    return table


def _parse_elements_from_source(root):
    mb_path = os.path.join(root, "src", "simulation", "elements", "meson.build")
    with open(mb_path, "r", encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    block = re.search(r"simulation_elem_names\s*=\s*\[(.*?)\]", text, re.S)
    if not block:
        raise ValueError("meson.build 里找不到 simulation_elem_names")
    names = re.findall(r"'([A-Za-z0-9_]+)'", block.group(1))
    numbers = dict((name, index) for index, name in enumerate(names))

    elements_dir = os.path.join(root, "src", "simulation", "elements")
    table = {}
    for filename in sorted(os.listdir(elements_dir)):
        if not filename.endswith(".cpp"):
            continue
        with open(os.path.join(elements_dir, filename), "r",
                  encoding="utf-8", errors="replace") as handle:
            source = handle.read()
        name_match = re.search(r'Name\s*=\s*"([A-Za-z0-9_]+)"', source)
        if not name_match:
            continue
        name = name_match.group(1).upper()
        if name not in numbers:
            continue
        colour_match = re.search(r"Colour\s*=\s*0x([0-9A-Fa-f]{6})_rgb", source)
        if colour_match:
            colour = int(colour_match.group(1), 16)
        elif name in _FALLBACK_ELEMENTS:
            colour = _FALLBACK_ELEMENTS[name][1]  # 颜色是运行时算出来的, 用内置值
        else:
            continue
        table[name] = Element(name, numbers[name], colour)
    # 有些元素的 Colour 是运行时表达式，正则无法直接读取；用内置颜色补齐，
    # 元素编号仍取当前源码中的位置，而不是内置表中的旧编号。
    for name, (_fallback_number, colour) in _FALLBACK_ELEMENTS.items():
        if name in numbers and name not in table:
            table[name] = Element(name, numbers[name], colour)
    if not table:
        raise ValueError("没有解析到任何元素")
    return table


def resolve_palette(spec, table):
    """把 --palette 参数解析成元素列表"""
    spec = (spec or "default").strip()
    lowered = spec.lower()
    if lowered == "default":
        names = DEFAULT_PALETTE
    elif lowered in ("solid", "static"):
        names = SOLID_PALETTE
    elif lowered == "all":
        names = [name for name in sorted(table) if name not in UNUSABLE_ELEMENTS]
    else:
        names = [chunk.strip().upper() for chunk in spec.split(",") if chunk.strip()]
        unknown = [name for name in names if name not in table]
        if unknown:
            raise SystemExit("未知元素: %s(用 --list-elements 查看可用元素)" % ", ".join(unknown))
    elements = []
    for name in names:
        element = table.get(name)
        if element is not None:
            elements.append(element)
    if not elements:
        raise SystemExit("调色板是空的")
    return elements


# --------------------------------------------------------------------------
# 读图: 有 Pillow 就用 Pillow, 否则用自带的纯 Python PNG 解码器
# --------------------------------------------------------------------------

def load_image(path):
    """返回 (宽, 高, RGBA 字节)"""
    try:
        from PIL import Image  # noqa: F401  (只是探测一下有没有装)
    except ImportError:
        if os.path.splitext(path)[1].lower() != ".png":
            raise SystemExit(
                "没有安装 Pillow, 只能读 PNG。\n"
                "请执行: pip install Pillow    (或把图片先转成 PNG)")
        return read_png_rgba(path)

    from PIL import Image
    with Image.open(path) as image:
        if getattr(image, "is_animated", False):
            image.seek(0)
        rgba = image.convert("RGBA")
        return rgba.size[0], rgba.size[1], bytearray(rgba.tobytes())


def read_png_rgba(path):
    """纯 Python 的 PNG 解码器, 覆盖常见的非隔行 PNG(灰度/索引/RGB/RGBA, 8/16 位)"""
    with open(path, "rb") as handle:
        blob = handle.read()
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit("不是合法的 PNG 文件: %s" % path)

    position = 8
    header = None
    palette = None
    transparency = None
    idat = bytearray()
    while position + 8 <= len(blob):
        (length,) = struct.unpack(">I", blob[position:position + 4])
        kind = blob[position + 4:position + 8]
        payload = blob[position + 8:position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", payload)
        elif kind == b"PLTE":
            palette = payload
        elif kind == b"tRNS":
            transparency = payload
        elif kind == b"IDAT":
            idat += payload
        elif kind == b"IEND":
            break

    if not header:
        raise SystemExit("PNG 缺少 IHDR: %s" % path)
    width, height, depth, colour_type, _comp, _filt, interlace = header
    if interlace:
        raise SystemExit("暂不支持隔行扫描(interlaced)的 PNG, 请 pip install Pillow 或重新导出图片")
    if width == 0 or height == 0:
        raise SystemExit("图片尺寸为 0")

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour_type)
    if channels is None:
        raise SystemExit("不支持的 PNG 颜色类型: %d" % colour_type)
    if depth not in (1, 2, 4, 8, 16):
        raise SystemExit("不支持的 PNG 位深: %d" % depth)

    raw = zlib.decompress(bytes(idat))
    if depth < 8:
        bits_per_pixel = 1  # PNG 滤波的 bpp 以字节计，亚字节像素向上取整为 1
    else:
        bits_per_pixel = channels * depth // 8
    stride = (width * channels * depth + 7) // 8

    scanlines = bytearray(height * stride)
    previous = bytearray(stride)
    cursor = 0
    for row in range(height):
        if cursor + 1 + stride > len(raw):
            raise SystemExit("PNG 数据不完整")
        filter_type = raw[cursor]
        cursor += 1
        line = bytearray(raw[cursor:cursor + stride])
        cursor += stride
        _png_unfilter(filter_type, line, previous, bits_per_pixel)
        scanlines[row * stride:(row + 1) * stride] = line
        previous = line

    if depth < 8:
        # 灰度采样要拉伸到 0..255；索引色必须保留原始调色板编号。
        scanlines = _unpack_subbyte(scanlines, width, height, stride, depth,
                                    scale_samples=(colour_type == 0))
        samples_per_row = width * channels
    else:
        samples_per_row = width * channels

    out = bytearray(width * height * 4)
    bytes_per_sample = 2 if depth == 16 else 1
    for row in range(height):
        base = row * samples_per_row * bytes_per_sample
        for column in range(width):
            dst = (row * width + column) * 4
            if colour_type == 0:      # 灰度
                value = scanlines[base + column * bytes_per_sample]
                alpha = 255
                if transparency and len(transparency) >= 2:
                    grey_key = (transparency[0] << 8) | transparency[1]
                    alpha = 0 if value == grey_key else 255
                out[dst:dst + 4] = bytes((value, value, value, alpha))
            elif colour_type == 2:    # RGB
                src = base + column * 3 * bytes_per_sample
                out[dst:dst + 3] = scanlines[src:src + 3 * bytes_per_sample:bytes_per_sample]
                out[dst + 3] = 255
            elif colour_type == 3:    # 索引色
                index = scanlines[base + column * bytes_per_sample]
                if palette is not None and index * 3 + 2 < len(palette):
                    out[dst:dst + 3] = palette[index * 3:index * 3 + 3]
                alpha = 255
                if transparency is not None and index < len(transparency):
                    alpha = transparency[index]
                out[dst + 3] = alpha
            elif colour_type == 4:    # 灰度 + alpha
                src = base + column * 2 * bytes_per_sample
                grey = scanlines[src]
                out[dst:dst + 3] = bytes((grey, grey, grey))
                out[dst + 3] = scanlines[src + bytes_per_sample]
            else:                     # RGBA
                src = base + column * 4 * bytes_per_sample
                out[dst:dst + 4] = scanlines[src:src + 4 * bytes_per_sample:bytes_per_sample]
    return width, height, out


def _png_unfilter(filter_type, line, previous, bpp):
    """按 PNG 规范还原一行像素(就地修改 line)"""
    size = len(line)
    if filter_type == 0:
        return
    if filter_type == 1:
        for i in range(bpp, size):
            line[i] = (line[i] + line[i - bpp]) & 0xFF
    elif filter_type == 2:
        for i in range(size):
            line[i] = (line[i] + previous[i]) & 0xFF
    elif filter_type == 3:
        for i in range(size):
            left = line[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
    elif filter_type == 4:
        for i in range(size):
            a = line[i - bpp] if i >= bpp else 0
            b = previous[i]
            c = previous[i - bpp] if i >= bpp else 0
            pa = abs(b - c)
            pb = abs(a - c)
            pc = abs(a + b - 2 * c)
            if pa <= pb and pa <= pc:
                predicted = a
            elif pb <= pc:
                predicted = b
            else:
                predicted = c
            loop = (line[i] + predicted) & 0xFF
            line[i] = loop
    else:
        raise SystemExit("不支持的 PNG 滤波器: %d" % filter_type)


def _unpack_subbyte(scanlines, width, height, stride, depth, scale_samples=True):
    """把位深 1/2/4 的打包数据拆成一个字节一个采样值"""
    per_byte = 8 // depth
    mask = (1 << depth) - 1
    scale = (255 // mask) if scale_samples else 1
    out = bytearray(width * height)
    cursor = 0
    for row in range(height):
        base = row * stride
        for column in range(width):
            byte_index = base + column // per_byte
            shift = 8 - depth * (column % per_byte + 1)
            out[cursor] = ((scanlines[byte_index] >> shift) & mask) * scale
            cursor += 1
    return out


# --------------------------------------------------------------------------
# 缩放(纯 Python, 缩小时做区域平均, 放大时最近邻)
# --------------------------------------------------------------------------

def resize_rgba(pixels, width, height, new_width, new_height, on_progress=None):
    if (new_width, new_height) == (width, height):
        return pixels
    if new_width < width:
        if on_progress:
            on_progress("横向缩放 %d -> %d" % (width, new_width))
        pixels = _box_shrink_h(pixels, width, height, new_width)
        width = new_width
    elif new_width > width:
        pixels = _nearest_h(pixels, width, height, new_width)
        width = new_width
    if new_height < height:
        if on_progress:
            on_progress("纵向缩放 %d -> %d" % (height, new_height))
        pixels = _box_shrink_v(pixels, width, height, new_height)
    elif new_height > height:
        pixels = _nearest_v(pixels, width, height, new_height)
    return pixels


def _box_shrink_h(pixels, width, height, new_width):
    bounds = []
    for target in range(new_width):
        x0 = target * width // new_width
        x1 = max(x0 + 1, (target + 1) * width // new_width)
        bounds.append((x0 * 4, x1 * 4, x1 - x0))
    out = bytearray(new_width * height * 4)
    for row in range(height):
        line = pixels[row * width * 4:(row + 1) * width * 4]
        offset = row * new_width * 4
        for start, stop, count in bounds:
            out[offset] = sum(line[start:stop:4]) // count
            out[offset + 1] = sum(line[start + 1:stop:4]) // count
            out[offset + 2] = sum(line[start + 2:stop:4]) // count
            out[offset + 3] = sum(line[start + 3:stop:4]) // count
            offset += 4
    return out


def _box_shrink_v(pixels, width, height, new_height):
    out = bytearray(width * new_height * 4)
    stride4 = width * 4
    for row in range(new_height):
        y0 = row * height // new_height
        y1 = max(y0 + 1, (row + 1) * height // new_height)
        count = y1 - y0
        base = row * stride4
        for column in range(width):
            offset = base + column * 4
            out[offset] = sum(pixels[(y0 * width + column) * 4:(y1 * width + column) * 4:stride4]) // count
            out[offset + 1] = sum(pixels[(y0 * width + column) * 4 + 1:(y1 * width + column) * 4 + 1:stride4]) // count
            out[offset + 2] = sum(pixels[(y0 * width + column) * 4 + 2:(y1 * width + column) * 4 + 2:stride4]) // count
            out[offset + 3] = sum(pixels[(y0 * width + column) * 4 + 3:(y1 * width + column) * 4 + 3:stride4]) // count
    return out


def _nearest_h(pixels, width, height, new_width):
    mapping = [target * width // new_width for target in range(new_width)]
    out = bytearray(new_width * height * 4)
    for row in range(height):
        line = pixels[row * width * 4:(row + 1) * width * 4]
        offset = row * new_width * 4
        for target in range(new_width):
            source = mapping[target] * 4
            out[offset:offset + 4] = line[source:source + 4]
            offset += 4
    return out


def _nearest_v(pixels, width, height, new_height):
    mapping = [row * height // new_height for row in range(new_height)]
    out = bytearray(width * new_height * 4)
    stride4 = width * 4
    for row in range(new_height):
        source = mapping[row] * stride4
        out[row * stride4:(row + 1) * stride4] = pixels[source:source + stride4]
    return out


# --------------------------------------------------------------------------
# 图像 -> 粒子平面
# --------------------------------------------------------------------------

def _nearest_palette_entry(colours, cache, red, green, blue):
    key = (red >> 1, green >> 1, blue >> 1)
    found = cache.get(key)
    if found is not None:
        return found
    best_index = 0
    best_distance = 1 << 30
    for index, (pr, pg, pb) in enumerate(colours):
        # 人眼对绿色更敏感的加权距离
        distance = ((red - pr) * (red - pr) * 3 +
                    (green - pg) * (green - pg) * 4 +
                    (blue - pb) * (blue - pb) * 2)
        if distance < best_distance:
            best_distance = distance
            best_index = index
    cache[key] = best_index
    return best_index


def build_plane(pixels, width, height, elements, mode, dither,
                alpha_threshold, key_colour, key_tolerance, on_progress=None):
    """
    把 RGBA 像素转成粒子平面:
    返回值 (plane, stats), plane 长度 width*height, 每项为 None 或 (元素编号, 装饰色)
    """
    total = width * height
    plane = [None] * total

    # 先算出每个像素是否留空, 以及它的目标颜色
    if mode == "palette":
        colours = [element.rgb for element in elements]
    else:
        colours = None

    if on_progress:
        on_progress("映射 %d x %d 像素" % (width, height))

    if dither == "floyd" and mode == "palette":
        return _build_plane_dither(plane, pixels, width, height, elements, colours,
                                   alpha_threshold, key_colour, key_tolerance)

    cache = {}
    empty = 0
    for index in range(total):
        red = pixels[index * 4]
        green = pixels[index * 4 + 1]
        blue = pixels[index * 4 + 2]
        alpha = pixels[index * 4 + 3]
        if alpha < alpha_threshold:
            empty += 1
            continue
        if key_colour is not None:
            distance = (abs(red - key_colour[0]) + abs(green - key_colour[1]) +
                        abs(blue - key_colour[2]))
            if distance <= key_tolerance:
                empty += 1
                continue
        if mode == "palette":
            element = elements[_nearest_palette_entry(colours, cache, red, green, blue)]
            plane[index] = (element.number, 0)
        else:
            plane[index] = (elements[0].number, (0xFF << 24) | (red << 16) | (green << 8) | blue)
    stats = {"pixels": total, "empty": empty, "particles": total - empty}
    return plane, stats


def _build_plane_dither(plane, pixels, width, height, elements, colours,
                        alpha_threshold, key_colour, key_tolerance):
    """Floyd-Steinberg 抖动版(只在 palette 模式下有意义)"""
    total = width * height
    buffer = [0.0] * (total * 3)
    for index in range(total):
        buffer[index * 3] = float(pixels[index * 4])
        buffer[index * 3 + 1] = float(pixels[index * 4 + 1])
        buffer[index * 3 + 2] = float(pixels[index * 4 + 2])

    cache = {}
    empty = 0
    for index in range(total):
        alpha = pixels[index * 4 + 3]
        red = pixels[index * 4]
        green = pixels[index * 4 + 1]
        blue = pixels[index * 4 + 2]
        if alpha < alpha_threshold:
            empty += 1
            continue
        if key_colour is not None:
            distance = (abs(red - key_colour[0]) + abs(green - key_colour[1]) +
                        abs(blue - key_colour[2]))
            if distance <= key_tolerance:
                empty += 1
                continue

        slot = index * 3
        source_red = buffer[slot]
        source_green = buffer[slot + 1]
        source_blue = buffer[slot + 2]
        red = _clamp_byte(source_red)
        green = _clamp_byte(source_green)
        blue = _clamp_byte(source_blue)
        choice = _nearest_palette_entry(colours, cache, red, green, blue)
        plane[index] = (elements[choice].number, 0)

        error_red = source_red - colours[choice][0]
        error_green = source_green - colours[choice][1]
        error_blue = source_blue - colours[choice][2]

        x = index % width
        y = index // width
        neighbours = []
        if x + 1 < width:
            neighbours.append((index + 1, 7.0 / 16.0))
        if y + 1 < height:
            if x > 0:
                neighbours.append((index + width - 1, 3.0 / 16.0))
            neighbours.append((index + width, 5.0 / 16.0))
            if x + 1 < width:
                neighbours.append((index + width + 1, 1.0 / 16.0))
        for target, weight in neighbours:
            slot = target * 3
            buffer[slot] += error_red * weight
            buffer[slot + 1] += error_green * weight
            buffer[slot + 2] += error_blue * weight

    stats = {"pixels": total, "empty": empty, "particles": total - empty}
    return plane, stats


def _clamp_byte(value):
    value = int(value + 0.5)
    if value < 0:
        return 0
    if value > 255:
        return 255
    return value


# --------------------------------------------------------------------------
# 写 .cps(PSv 格式)
# --------------------------------------------------------------------------

def build_cps(plane, width, height, table, paused=False, gravity_mode=0,
              air_mode=0, temp=ROOM_TEMP, signs=None):
    """按 GameSave::readPSv 的读取顺序拼出存档数据"""
    if width % CELL or height % CELL:
        raise ValueError("宽高必须是 %d 的倍数" % CELL)
    block_width = width // CELL
    block_height = height // CELL
    if width > MAX_W or height > MAX_H:
        raise SystemExit("沙盘太大了: 当前游戏画布最大为 %d x %d 像素" % (MAX_W, MAX_H))
    if block_width > 255 or block_height > 255:
        raise SystemExit("沙盘太大了(PSv 格式最大 %d x %d 像素)" %
                         (255 * CELL, 255 * CELL))

    ctype_numbers = set()
    for name in CTYPE_ELEMENTS:
        element = table.get(name)
        if element:
            ctype_numbers.add(element.number)
    tmp2_numbers = set()
    for name in TMP2_ELEMENTS:
        element = table.get(name)
        if element:
            tmp2_numbers.add(element.number)

    # 粒子出现的顺序 = 行优先扫描顺序(读档时所有属性段都用这个顺序)
    particle_types = bytearray(width * height)
    ordered = []
    for index in range(width * height):
        item = plane[index]
        if item is None:
            continue
        number = item[0]
        if number <= 0 or number > 255:
            raise SystemExit("元素编号 %d 超出 PSv 格式的范围" % number)
        particle_types[index] = number
        ordered.append(item)

    count = len(ordered)
    out = bytearray()
    out += bytes(block_width * block_height)          # 墙格(全空, 没有墙/风扇)
    out += particle_types                             # 粒子类型图
    out += bytes([127]) * count                       # vx = 0
    out += bytes([127]) * count                       # vy = 0
    out += bytes(2 * count)                           # life(2 字节, 大端)
    out += bytes(2 * count)                           # tmp(2 字节, 大端)
    out += bytes(sum(1 for item in ordered if item[0] in tmp2_numbers))   # tmp2
    out += bytes((item[1] >> 24) & 0xFF for item in ordered)              # 装饰色 alpha
    out += bytes((item[1] >> 16) & 0xFF for item in ordered)              # R
    out += bytes((item[1] >> 8) & 0xFF for item in ordered)               # G
    out += bytes(item[1] & 0xFF for item in ordered)                      # B
    out += struct.pack(">H", max(0, min(65535, int(temp)))) * count       # 温度
    out += bytes(sum(1 for item in ordered if item[0] in ctype_numbers))  # ctype

    signs = signs or []
    if signs:  # 没有标签时一个字节都不写, 读档端靠 p == dataLength 判断
        out += bytes((len(signs),))
        for sign in signs:
            out += _encode_sign(sign)

    flags = 0
    if paused:
        flags |= 1 << 1
    flags |= (gravity_mode & 0x03) << 2
    flags |= (air_mode & 0x07) << 4
    flags |= 1 << 7  # gravityEnable

    header = b"PSv" + bytes((flags, SAVE_VERSION, CELL, block_width, block_height))
    header += struct.pack("<I", len(out))
    return bytes(header) + bz2.compress(bytes(out), 9)


def _encode_sign(sign):
    """sign = (x, y, 对齐方式 0=左 1=中 2=右 3=无, 文本)"""
    x, y, justification, text = sign
    payload = text.encode("utf-8")[:254]
    return (struct.pack("<HHBB", max(0, min(65535, int(x))), max(0, min(65535, int(y))),
                        justification & 0xFF, len(payload)) + payload)


# --------------------------------------------------------------------------
# 回读校验: 按 readPSv 的逻辑把存档再解开, 和原图对比
# --------------------------------------------------------------------------

def parse_cps(blob):
    """按 GameSave::readPSv 的顺序把存档解开(用于 --verify 自校验)"""
    if len(blob) < 16:
        raise ValueError("存档太短")
    magic = blob[:3]
    if magic == b"PSv":
        new_format = 1
    elif magic == b"fuC":
        new_format = 0
    else:
        raise ValueError("不认识的存档标识: %r" % magic)
    version = blob[4]
    cell = blob[5]
    block_width = blob[6]
    block_height = blob[7]
    (size,) = struct.unpack("<I", blob[8:12])
    data = bz2.decompress(blob[12:])
    if size != len(data):
        raise ValueError("解压后长度 %d 与头部记录的 %d 不一致" % (len(data), size))
    if cell != CELL:
        raise ValueError("CELL 应为 %d, 实际为 %d" % (CELL, cell))

    width, height = block_width * cell, block_height * cell
    position = 0

    def take(amount):
        nonlocal position
        if position + amount > len(data):
            raise ValueError("存档数据在第 %d 字节处被截断" % position)
        chunk = data[position:position + amount]
        position += amount
        return chunk

    walls = take(block_width * block_height)                  # 墙格
    fan_count = sum(1 for byte in walls if byte in (4, 127))  # WL_FAN 的数量
    take(2 * fan_count)                                       # 风扇速度

    type_map = take(width * height)                           # 粒子类型图
    # 读档时粒子按行优先顺序编号, 后面每个属性段都按这个顺序写一遍
    slots = [index for index in range(width * height) if type_map[index]]
    count = len(slots)
    ordered_types = [type_map[index] for index in slots]

    take(count)                                               # vx
    take(count)                                               # vy
    if version >= 44:
        take(2 * count)                                       # life
        take(2 * count)                                       # tmp
    else:
        take(count)                                           # life(老格式 1 字节)
    if version >= 53:
        take(sum(1 for number in ordered_types if number in (152, 143)))   # tmp2(PBCN/TRON)
    if version >= 49:
        alpha = take(count)                                   # 装饰色 A
        red = take(count)                                     # R
        green = take(count)                                   # G
        blue = take(count)                                    # B
    else:
        alpha = red = green = blue = bytes(count)
    if version >= 42:
        temps = take(2 * count) if new_format else take(count)
    else:
        temps = bytes(count)
    take(sum(1 for number in ordered_types if number in _CTYPE_NUMBERS))    # ctype

    types = {}
    deco = {}
    for order, index in enumerate(slots):
        types[index] = ordered_types[order]
        deco[index] = ((alpha[order] << 24) | (red[order] << 16) |
                       (green[order] << 8) | blue[order])
    if new_format:
        temp_values = [(temps[i * 2] << 8) | temps[i * 2 + 1] for i in range(count)]
    else:
        temp_values = list(temps)

    signs = []
    if position < len(data):
        sign_count = data[position]
        position += 1
        for _ in range(sign_count):
            x = int.from_bytes(take(2), "little")
            y = int.from_bytes(take(2), "little")
            justification = take(1)[0]
            length = take(1)[0]
            signs.append((x, y, justification, take(length).decode("utf-8", "replace")))
    if position != len(data):
        raise ValueError("解析结束后还剩 %d 字节(存档字段顺序可能有误)" % (len(data) - position))

    return {
        "version": version,
        "width": width,
        "height": height,
        "types": types,
        "deco": deco,
        "temps": temp_values,
        "signs": signs,
    }


# 存档里需要额外一字节 ctype 的元素编号(见 CTYPE_ELEMENTS)
_CTYPE_NUMBERS = {9, 74, 93, 15, 6, 99, 78, 152, 155, 83, 85}

def verify_cps(blob, plane, width, height):
    """解回存档并和内存里的粒子平面逐格对比, 返回信息字符串"""
    parsed = parse_cps(blob)
    if parsed["width"] != width or parsed["height"] != height:
        raise ValueError("尺寸不符: 存档 %dx%d, 期望 %dx%d" %
                         (parsed["width"], parsed["height"], width, height))
    expected_count = sum(1 for item in plane if item is not None)
    if len(parsed["types"]) != expected_count:
        raise ValueError("粒子数不符: 存档 %d, 期望 %d" %
                         (len(parsed["types"]), expected_count))
    for index, item in enumerate(plane):
        if item is None:
            if index in parsed["types"]:
                raise ValueError("第 %d 格本该是空的" % index)
            continue
        number, decoration = item
        if parsed["types"].get(index) != number:
            raise ValueError("第 %d 格元素不符: 存档 %r, 期望 %r" %
                             (index, parsed["types"].get(index), number))
        if parsed["deco"].get(index) != decoration:
            raise ValueError("第 %d 格装饰色不符: 存档 %08X, 期望 %08X" %
                             (index, parsed["deco"].get(index) or 0, decoration))
    return "回读 %d 个粒子, 逐格一致" % len(parsed["types"])


# --------------------------------------------------------------------------
# 预览图(纯 Python 写 PNG)
# --------------------------------------------------------------------------

def write_preview_png(path, plane, width, height, table):
    """按"游戏里看起来的样子"画一张 PNG(装饰色优先, 否则用元素本色)"""
    colour_by_number = {}
    for element in table.values():
        colour_by_number[element.number] = element.rgb

    raw = bytearray()
    for row in range(height):
        raw.append(0)  # 滤波器: None
        line = bytearray(width * 3)
        for column in range(width):
            item = plane[row * width + column]
            if item is None:
                red = green = blue = 0
            else:
                number, decoration = item
                base = colour_by_number.get(number, (255, 0, 255))
                alpha = (decoration >> 24) & 0xFF
                if alpha:
                    # 和 Renderer 一样: deco alpha=255 时完全替换颜色
                    weight = alpha + 1
                    red = (weight * ((decoration >> 16) & 0xFF) + (256 - weight) * base[0]) >> 8
                    green = (weight * ((decoration >> 8) & 0xFF) + (256 - weight) * base[1]) >> 8
                    blue = (weight * (decoration & 0xFF) + (256 - weight) * base[2]) >> 8
                else:
                    red, green, blue = base
            offset = column * 3
            line[offset] = max(0, min(255, red))
            line[offset + 1] = max(0, min(255, green))
            line[offset + 2] = max(0, min(255, blue))
        raw += line
    write_png(path, width, height, bytes(raw))


def write_png(path, width, height, filtered_rows):
    def chunk(kind, payload):
        return (struct.pack(">I", len(payload)) + kind + payload +
                struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n")
        handle.write(chunk(b"IHDR", header))
        handle.write(chunk(b"IDAT", zlib.compress(bytes(filtered_rows), 6)))
        handle.write(chunk(b"IEND", b""))


# --------------------------------------------------------------------------
# 命令行
# --------------------------------------------------------------------------

def parse_colour(text):
    text = text.strip().lstrip("#")
    if len(text) != 6:
        raise argparse.ArgumentTypeError("颜色要写成 RRGGBB, 例如 FF0000")
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        raise argparse.ArgumentTypeError("颜色要写成十六进制 RRGGBB")


def round_to_cell(value, minimum=CELL, maximum=None):
    value = int(round(float(value)))
    value = max(minimum, int((value + CELL - 1) // CELL) * CELL)
    value = max(CELL, value)
    if maximum:
        value = min(maximum, value)
    return value


def build_parser():
    parser = argparse.ArgumentParser(
        prog="img2save.py",
        description="把图片转换成 The Powder Toy 沙盘文件(.cps)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python3 tools/img2save.py photo.png
      真彩色转换, 生成 photo.cps

  python3 tools/img2save.py photo.jpg -o 作品.cps -W 400
      宽度 400, 高度按比例自动算

  python3 tools/img2save.py logo.png -m palette --dither floyd --paused
      用真实元素配色 + 抖动, 打开时暂停

  python3 tools/img2save.py art.png -e WOOD --key-color FFFFFF --preview 预览.png
      木材质感的剪影, 去掉白色背景, 顺便导出预览图
""")
    parser.add_argument("image", nargs="?", help="输入图片(png/jpg/...)")
    parser.add_argument("-o", "--output", help="输出的 .cps 文件名(默认 图片名.cps)")
    parser.add_argument("-W", "--width", type=int, help="沙盘宽度(像素, 会自动取整到 4 的倍数)")
    parser.add_argument("-H", "--height", type=int, help="沙盘高度(像素, 会自动取整到 4 的倍数)")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="在自动算出的尺寸上再乘一个系数(默认 1.0)")
    parser.add_argument("--upscale", action="store_true",
                        help="允许把小图放大(默认只会缩小, 不会放大)")
    parser.add_argument("-m", "--mode", choices=("deco", "palette"), default="deco",
                        help="deco=装饰色真彩色(默认); palette=只用元素本色")
    parser.add_argument("-e", "--element", default="DMND",
                        help="deco 模式下用哪种元素当作画布(默认 DMND 钻石)")
    parser.add_argument("--palette", default="default",
                        help="palette 模式的调色板: default / solid / all / 逗号分隔的元素名")
    parser.add_argument("--dither", choices=("none", "floyd"), default="none",
                        help="palette 模式下的抖动方式(默认 none)")
    parser.add_argument("--alpha-threshold", type=int, default=128,
                        help="透明度低于该值(0-255)的像素留空(默认 128)")
    parser.add_argument("--key-color", type=parse_colour, default=None,
                        help="把该颜色(RRGGBB)当作透明处理, 例如去掉白底 FFFFFF")
    parser.add_argument("--key-tolerance", type=int, default=24,
                        help="--key-color 的容差(默认 24)")
    parser.add_argument("--temp", type=int, default=ROOM_TEMP,
                        help="粒子温度, 单位开尔文(默认 %d)" % ROOM_TEMP)
    parser.add_argument("--paused", action="store_true", help="存档打开时处于暂停状态")
    parser.add_argument("--gravity", choices=sorted(GRAVITY_MODES), default="vertical",
                        help="重力模式(默认 vertical)")
    parser.add_argument("--air", choices=sorted(AIR_MODES), default="on",
                        help="空气模式(默认 on)")
    parser.add_argument("--sign", default=None, help="在左下角加一行说明文字(支持中文)")
    parser.add_argument("--preview", default=None, help="同时导出一张 PNG 预览图")
    parser.add_argument("--verify", action="store_true", help="写完后回读存档做逐格校验")
    parser.add_argument("--list-elements", action="store_true", help="列出可用元素后退出")
    parser.add_argument("-q", "--quiet", action="store_true", help="少输出一点信息")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    table = load_element_table()

    if args.list_elements:
        print("共 %d 个元素(编号 颜色 名称):" % len(table))
        for name in sorted(table, key=lambda key: table[key].number):
            element = table[name]
            print("  %3d  #%06X  %s" % (element.number, element.colour, name))
        return 0

    def log(message):
        if not args.quiet:
            print(message)

    if not args.image:
        raise SystemExit("请指定一张图片(或用 --list-elements / -h 查看帮助)")
    if not os.path.isfile(args.image):
        raise SystemExit("找不到图片: %s" % args.image)

    # 1) 读图
    width, height, pixels = load_image(args.image)
    log("读入图片 %s (%d x %d)" % (os.path.basename(args.image), width, height))

    # 2) 决定沙盘尺寸
    out_width, out_height = _target_size(width, height, args)
    log("沙盘尺寸 %d x %d" % (out_width, out_height))
    if out_width > MAX_W or out_height > MAX_H:
        raise SystemExit("指定尺寸 %d x %d 超过游戏画布上限 %d x %d" %
                         (out_width, out_height, MAX_W, MAX_H))
    pixels = resize_rgba(pixels, width, height, out_width, out_height,
                         on_progress=log if not args.quiet else None)

    # 3) 决定用哪些元素
    if args.mode == "palette":
        elements = resolve_palette(args.palette, table)
    else:
        name = args.element.strip().upper()
        element = table.get(name)
        if element is None:
            raise SystemExit("未知元素: %s(用 --list-elements 查看可用元素)" % name)
        elements = [element]

    # 4) 生成粒子平面
    if args.dither == "floyd" and args.mode != "palette":
        log("提示: 抖动只在 palette 模式下有意义, 已忽略")
    plane, stats = build_plane(pixels, out_width, out_height, elements, args.mode,
                               args.dither, args.alpha_threshold,
                               args.key_color, args.key_tolerance,
                               on_progress=log if not args.quiet else None)
    if not stats["particles"]:
        raise SystemExit("一个粒子都没有生成, 试试调低 --alpha-threshold 或去掉 --key-color")
    log("生成 %d 个粒子(留空 %d 格)" % (stats["particles"], stats["empty"]))

    # 5) 写存档
    signs = []
    if args.sign:
        signs.append((4, out_height - 8, 0, args.sign[:250]))
    blob = build_cps(plane, out_width, out_height, table,
                     paused=args.paused,
                     gravity_mode=GRAVITY_MODES[args.gravity],
                     air_mode=AIR_MODES[args.air],
                     temp=args.temp, signs=signs)

    output = args.output or (os.path.splitext(args.image)[0] + ".cps")
    if not output.lower().endswith(".cps"):
        output += ".cps"
    with open(output, "wb") as handle:
        handle.write(blob)
    log("已写出 %s (%.1f KB)" % (output, len(blob) / 1024.0))

    if args.verify:
        log("校验: " + verify_cps(blob, plane, out_width, out_height))

    if args.preview:
        write_preview_png(args.preview, plane, out_width, out_height, table)
        log("已写出预览图 %s" % args.preview)

    log("把它拖进 The Powder Toy 窗口, 或者放进游戏的 saves 目录即可打开。")
    return 0


def _target_size(width, height, args):
    """根据原图比例和命令行参数算出沙盘尺寸(4 的倍数)"""
    if args.width and args.height:
        return (round_to_cell(args.width), round_to_cell(args.height))
    if args.width:
        target_width = round_to_cell(args.width)
        ratio = target_width / float(width)
        return (target_width, round_to_cell(height * ratio))
    if args.height:
        target_height = round_to_cell(args.height)
        ratio = target_height / float(height)
        return (round_to_cell(width * ratio), target_height)

    scale = min(MAX_W / float(width), MAX_H / float(height))
    if scale > 1.0 and not args.upscale:
        scale = 1.0
    scale *= args.scale
    return (round_to_cell(width * scale), round_to_cell(height * scale))


if __name__ == "__main__":
    sys.exit(main())
