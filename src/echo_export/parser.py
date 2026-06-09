"""Parse the in-game echo *equipment* page into an optimizer-ready record.

The equipment page right panel shows everything for the selected echo in one
view (no scrolling): name, level, COST, two main stats, five sub stats, and the
sonata set as text. This module turns the OCR of that frame into an
:class:`EchoRecord` matching the wuthering-waves-optimizer "Import echoes from
text" schema.

Pure Python: no ok-script / Qt imports, so it is unit-testable on Linux.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.echo_export import mappings
from src.echo_export.ocr_items import OcrItem

MAX_LEVEL = 25

# A numeric stat value, e.g. "30.0%", "100", "1,234", "9.3%".
_NUMBER_RE = re.compile(r"^[+\-]?[\d][\d.,]*\s*[%％]?$")
_LEVEL_RE = re.compile(r"\+\s*(\d+)")
_COST_RE = re.compile(r"COST\s*(\d+)", re.IGNORECASE)
# Keep only CJK + middle-dot separators; drops OCR junk (emoji/icons 🌌🎯, '@',
# '（1/1)', '：', the level '+25', ASCII) from displayed names/sets.
_CLEAN_RE = re.compile(r"[㐀-鿿·・]")


def _clean_text(s: str) -> str:
    return "".join(_CLEAN_RE.findall(s or ""))

# Page / section anchors (simplified Chinese).
ANCHOR_PAGE = "简述"          # only present on the equipment page
ANCHOR_COST = "COST"
ANCHOR_SKILL = "声骸技能"      # echo skill section: marks the end of the stat list
ANCHOR_SONATA = "合鸣效果"     # sonata effect section: set name follows it

# Words that may sit in the stat region but are not stats.
_HEADER_WORDS = {ANCHOR_SKILL, ANCHOR_SONATA, "声骸推荐", "简述", "声骸管理方案"}


@dataclass
class EchoRecord:
    """One parsed echo, serializable to the optimizer import format."""

    name_zh: str
    echo: str | None
    type: int | None              # COST (1/3/4)
    stat: str | None              # main (variable) stat key
    echo_set: str | None
    substats: list[tuple[str, float]] = field(default_factory=list)
    rank: int = 5
    level: int = MAX_LEVEL
    set_zh: str | None = None     # raw OCR'd sonata name (diagnostic)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_recognized(self) -> bool:
        """True if the echo parsed cleanly (mapped echo + set, no warnings)."""
        return not self.warnings

    def to_optimizer_dict(self) -> dict:
        d: dict = {
            "echo": self.echo,
            "type": self.type,
            "rank": self.rank,
            "stat": self.stat,
            "echoSet": self.echo_set,
        }
        for i in range(5):
            t, v = (self.substats[i] if i < len(self.substats) else (None, None))
            d[f"echoSubStatsType{i + 1}"] = t
            d[f"echoSubStatsValue{i + 1}"] = v
        return d

    def signature(self) -> tuple:
        """Content key for de-duplication (no identical echoes exist in game).

        Computed from the optimizer dict only (no name_zh) so it can be
        reconstructed from a saved echoes_export.json on the next run.
        """
        return signature_from_dict(self.to_optimizer_dict())


def signature_from_dict(d: dict) -> tuple:
    """De-dup signature from an optimizer echo dict (for loading existing JSON)."""
    subs = tuple(sorted(
        (d.get(f"echoSubStatsType{i}"), d.get(f"echoSubStatsValue{i}"))
        for i in range(1, 6)
        if d.get(f"echoSubStatsType{i}") is not None
    ))
    return (d.get("echo"), d.get("type"), d.get("stat"), d.get("echoSet"), subs)


def parse_value(value_str: str) -> float:
    # substat values are positive; OCR sometimes prefixes a stray '-'/'+' (the
    # substat bullet read as a sign), so strip leading signs.
    s = value_str.replace("％", "%").replace("%", "").replace(",", "").strip()
    s = s.lstrip("+-").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _find(items: list[OcrItem], needle: str) -> OcrItem | None:
    for it in items:
        if needle in it.clean:
            return it
    return None


def _find_cost(items: list[OcrItem]) -> OcrItem | None:
    """The panel COST anchor (``COST <n>``), not the left-side cost filter chip.

    Prefer an item that actually carries a cost number; fall back to the
    right-most bare ``COST``.
    """
    with_num = [it for it in items if _COST_RE.search(it.clean)]
    if with_num:
        return max(with_num, key=lambda it: it.nx)
    bare = [it for it in items if ANCHOR_COST in it.clean]
    if bare:
        return max(bare, key=lambda it: it.nx)
    return None


def is_equipment_page(items: list[OcrItem]) -> bool:
    """True when the frame is the echo equipment page with a populated panel."""
    return _find(items, ANCHOR_PAGE) is not None and _find_cost(items) is not None


def _is_number(text: str) -> bool:
    return bool(_NUMBER_RE.match(text.strip()))


def parse_equipment_frame(items: list[OcrItem]) -> EchoRecord | None:
    """Parse one equipment-page frame. Returns None if it is not a usable,
    max-level echo panel."""
    if not is_equipment_page(items):
        return None

    cost_item = _find_cost(items)
    if cost_item is None:
        return None

    # Restrict to the right detail panel, anchored on COST's x position.
    panel_min_nx = cost_item.nx - 0.12
    panel = [it for it in items if it.nx >= panel_min_nx]

    skill_item = _find(panel, ANCHOR_SKILL)
    sonata_item = _find(panel, ANCHOR_SONATA)

    # Readiness gate: 声骸技能 and 合鸣效果 sit BELOW the stat block, so their
    # presence means the panel finished rendering and the stat rows above them
    # are loaded. If either is missing the frame was captured mid-load — skip it
    # and let the next tick catch the fully-rendered panel.
    if skill_item is None or sonata_item is None:
        return None

    warnings: list[str] = []

    # ---- level (gate on max) ---------------------------------------------
    level = _parse_level(panel, cost_item)
    if level is None:
        return None
    if level != MAX_LEVEL:
        return None  # only record +25 echoes

    # ---- cost ------------------------------------------------------------
    cost = _parse_cost(items, cost_item)

    # ---- name ------------------------------------------------------------
    name_zh = _parse_name(panel, cost_item)

    # ---- stats (2 mains + 5 subs) ----------------------------------------
    y_top = cost_item.ny
    y_bot = skill_item.ny if skill_item else (sonata_item.ny if sonata_item else 1.0)
    pairs = _stat_pairs(panel, cost_item, y_top, y_bot)

    main_stat_key, substats, stat_warns = _split_stats(pairs)
    warnings.extend(stat_warns)

    # ---- sonata set ------------------------------------------------------
    set_zh, set_key = _parse_set(panel, cost_item, sonata_item)
    if set_key is None:
        warnings.append(f"set not mapped: {set_zh!r}" if set_zh else "set not found")

    # ---- identity via mapping (echo key + cost cross-check) ---------------
    echo_key = None
    info = mappings.lookup_echo(name_zh)
    if info is not None:
        echo_key = info["key"]
        if cost is None:
            cost = info["cost"]
        elif cost != info["cost"]:
            warnings.append(f"cost mismatch: ocr={cost} map={info['cost']}")
        if set_key and info["sets"] and set_key not in info["sets"]:
            warnings.append(f"set {set_key} not in possible sets {info['sets']}")
    else:
        warnings.append(f"echo name not mapped: {name_zh!r}")

    return EchoRecord(
        name_zh=name_zh,
        echo=echo_key,
        type=cost,
        stat=main_stat_key,
        echo_set=set_key,
        substats=substats,
        level=level,
        set_zh=set_zh,
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _parse_level(panel: list[OcrItem], cost_item: OcrItem) -> int | None:
    """The +NN token in the panel header (above/at the COST row)."""
    best = None
    for it in panel:
        if it.ny > cost_item.ny + 0.02:
            continue
        m = _LEVEL_RE.search(it.clean.replace(" ", ""))
        if m:
            val = int(m.group(1))
            # prefer the highest level token in the header (the echo's level)
            if best is None or val > best:
                best = val
    return best


def _parse_cost(items: list[OcrItem], cost_item: OcrItem) -> int | None:
    m = _COST_RE.search(cost_item.clean)
    if m:
        return int(m.group(1))
    # number may be a separate box just right of "COST" on the same row
    cands = [
        it for it in items
        if abs(it.ny - cost_item.ny) < 0.02 and it.nx > cost_item.nx and _is_number(it.clean)
    ]
    cands.sort(key=lambda it: it.nx)
    if cands:
        return int(parse_value(cands[0].clean))
    return None


def _parse_name(panel: list[OcrItem], cost_item: OcrItem) -> str:
    """CJK text between the top bar and the COST row, in the name column."""
    cands = [
        it for it in panel
        if it.has_cjk()
        and 0.07 < it.ny < cost_item.ny - 0.005
        and abs(it.nx - cost_item.nx) < 0.10
        and it.clean not in _HEADER_WORDS
    ]
    cands.sort(key=lambda it: it.nx)
    raw = "".join(it.clean for it in cands)
    # Keep CJK + separators only: drops the merged level (+25), UI-icon emoji,
    # '@', progress markers, etc. that OCR appends at narrower resolutions.
    return _clean_text(raw)


def _stat_pairs(panel, cost_item, y_top, y_bot):
    """Return (name, value_str, ny) tuples for stat rows, ordered top→bottom."""
    band = [it for it in panel if y_top + 0.005 < it.ny < y_bot - 0.002]
    names = [
        it for it in band
        if it.has_cjk() and it.clean not in _HEADER_WORDS
        and it.nx < cost_item.nx + 0.06
    ]
    names.sort(key=lambda it: it.ny)  # pair top→bottom for stable greedy matching
    values = [it for it in band if _is_number(it.clean)]

    pairs = []
    used = set()
    for nm in names:
        best, best_dy = None, 1e9
        for i, val in enumerate(values):
            if i in used or val.nx <= nm.nx:
                continue
            dy = abs(val.ny - nm.ny)
            if dy < best_dy:
                best, best_dy, best_i = val, dy, i
        if best is not None and best_dy < 0.03:
            used.add(best_i)
            pairs.append((nm.clean, best.clean, nm.ny))
    pairs.sort(key=lambda p: p[2])
    return pairs


def _split_stats(pairs):
    """First two rows are main stats; the remaining (≤5) are sub stats.

    The exported main ``stat`` is the *variable* main — the one whose value is a
    percentage (the other main is a flat HP/ATK base, which the optimizer
    ignores). Sub stats keep their value and %/flat distinction.
    """
    warnings = []
    if len(pairs) < 2:
        warnings.append(f"expected >=2 main stats, got {len(pairs)}")
    mains = pairs[:2]
    subs = pairs[2:7]

    main_key = None
    pct_mains = [p for p in mains if "%" in p[1] or "％" in p[1]]
    chosen = pct_mains[0] if pct_mains else (mains[0] if mains else None)
    if chosen is not None:
        main_key = mappings.map_stat(chosen[0], chosen[1])
        if main_key is None:
            warnings.append(f"main stat not mapped: {chosen[0]!r}")

    substats = []
    for name, value_str, _ in subs:
        key = mappings.map_stat(name, value_str)
        if key is None:
            warnings.append(f"substat not mapped: {name!r}")
            continue
        substats.append((key, parse_value(value_str)))
    if len(substats) != 5:
        warnings.append(f"expected 5 substats, got {len(substats)}")
    return main_key, substats, warnings


def _parse_set(panel, cost_item, sonata_item):
    """First CJK line after the 合鸣效果 anchor is the sonata set name."""
    if sonata_item is None:
        return None, None
    cands = [
        it for it in panel
        if it.ny > sonata_item.ny + 0.005
        and it.has_cjk()
        and it.clean not in _HEADER_WORDS
        and abs(it.nx - cost_item.nx) < 0.10
    ]
    cands.sort(key=lambda it: it.ny)
    for it in cands:
        key = mappings.lookup_set(it.clean)
        if key:
            return _clean_text(it.clean), key
    set_zh = _clean_text(cands[0].clean) if cands else None
    return set_zh, None
