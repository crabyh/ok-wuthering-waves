"""A tiny OCR-engine-agnostic representation of a recognized text box.

Both the onnxocr result format (used in Linux tests) and the ok-script ``Box``
format (used live in the game) are adapted into a list of :class:`OcrItem`, so
the parser never needs to know which OCR engine produced the data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Matches Chinese (CJK) characters.
_CJK = re.compile(r"[一-鿿]")


@dataclass(frozen=True)
class OcrItem:
    """One recognized text box, with pixel coordinates and the frame size.

    ``nx``/``ny`` give the resolution-independent (0..1) center of the box so
    the parser can reason about layout regardless of capture resolution.
    """

    text: str
    x1: int
    y1: int
    x2: int
    y2: int
    frame_w: int
    frame_h: int

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0

    @property
    def nx(self) -> float:
        return self.cx / self.frame_w if self.frame_w else 0.0

    @property
    def ny(self) -> float:
        return self.cy / self.frame_h if self.frame_h else 0.0

    @property
    def clean(self) -> str:
        """Text with surrounding whitespace and stray spaces removed."""
        return self.text.strip()

    def has_cjk(self) -> bool:
        return bool(_CJK.search(self.text))


def from_onnxocr(result, frame_w: int, frame_h: int) -> list[OcrItem]:
    """Adapt an onnxocr/PaddleOCR result to OcrItems.

    A "line" is ``[box_pts, (text, conf)]`` where ``box_pts`` is a list of 4
    ``[x, y]`` corner points. ``onnxocr.ocr(img)`` returns ``[lines]`` (a list
    per image); this accepts either the lines list or that ``[lines]`` wrapper.
    """
    if not result:
        return []
    lines = result
    # If wrapped one extra level ([lines]), result[0][0][0][0] is a coord list
    # rather than a number; unwrap once.
    try:
        if isinstance(result[0][0][0][0], (list, tuple)):
            lines = result[0]
    except (IndexError, TypeError):
        pass
    items: list[OcrItem] = []
    for line in lines:
        try:
            pts, rec = line[0], line[1]
            text = rec[0] if isinstance(rec, (list, tuple)) else rec
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            items.append(
                OcrItem(
                    text=str(text),
                    x1=int(min(xs)),
                    y1=int(min(ys)),
                    x2=int(max(xs)),
                    y2=int(max(ys)),
                    frame_w=frame_w,
                    frame_h=frame_h,
                )
            )
        except (IndexError, TypeError, ValueError):
            continue
    return items


def from_ok_boxes(boxes, frame_w: int, frame_h: int) -> list[OcrItem]:
    """Adapt ok-script ``Box`` objects (``.x .y .width .height .name``)."""
    items: list[OcrItem] = []
    for b in boxes:
        text = getattr(b, "name", None)
        if text is None:
            continue
        x, y = int(b.x), int(b.y)
        items.append(
            OcrItem(
                text=str(text),
                x1=x,
                y1=y,
                x2=x + int(b.width),
                y2=y + int(b.height),
                frame_w=frame_w,
                frame_h=frame_h,
            )
        )
    return items
