"""Echo export: parse the in-game echo equipment page into the
wuthering-waves-optimizer "Import echoes from text" JSON format.

The modules in this package are intentionally free of any ``ok``/``ok-script``
or Qt imports so the whole image -> JSON pipeline can be unit tested on Linux
with plain ``pytest`` (only the OCR engine, onnxocr, is needed). The live-game
glue lives in ``src/task/ExportEchoTask.py`` and is the only part that depends
on ok-script.
"""
from src.echo_export.ocr_items import OcrItem, from_onnxocr, from_ok_boxes
from src.echo_export.parser import (
    EchoRecord,
    is_equipment_page,
    parse_equipment_frame,
)
from src.echo_export.recorder import EchoRecorder

__all__ = [
    "OcrItem",
    "from_onnxocr",
    "from_ok_boxes",
    "EchoRecord",
    "is_equipment_page",
    "parse_equipment_frame",
    "EchoRecorder",
]
