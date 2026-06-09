# ExportEchoTask.py
import os
import re

import cv2
import numpy as np
from qfluentwidgets import FluentIcon

from ok import Logger, TriggerTask
from src.echo_export.ocr_items import from_ok_boxes
from src.echo_export.parser import is_equipment_page, parse_equipment_frame
from src.echo_export.recorder import EchoRecorder
from src.task.BaseWWTask import BaseWWTask

logger = Logger.get_logger(__name__)


class ExportEchoTask(TriggerTask, BaseWWTask):
    """Passively records +25 echoes from the echo *equipment* page while you
    browse them with a controller, and exports a JSON file in the
    wuthering-waves-optimizer "Import echoes from text" format.

    This task never controls the game; you drive navigation. It monitors the
    screen, and whenever a new, stable, max-level echo panel is shown it parses
    and records it. Toggle it on/off from the control panel. The parsing logic
    lives in :mod:`src.echo_export` and is unit tested on its own.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "导出声骸到优化器(声骸装配界面/Export Echoes)"
        self.description = (
            "在声骸装配界面用手柄浏览+25声骸, 程序自动记录为优化器可导入的JSON. "
            "Open the echo equipment page and browse +25 echoes; new ones are "
            "auto-recorded to a JSON file importable by the optimizer."
        )
        self.icon = FluentIcon.SAVE
        self.supported_languages = ["zh_CN", "zh_TW"]
        self.trigger_interval = 0.2
        self.default_config.update({
            "_enabled": False,
            "Output File": "echoes_export.json",
        })
        self.config_description = {
            "Output File": "导出文件路径 / path of the exported JSON file",
        }
        self._recorder = None
        self._out_path = None
        self._last_hash = None
        self._last_hash_count = 0
        self._processed_hash = None

    # -- lifecycle ---------------------------------------------------------
    def _ensure_recorder(self):
        out = os.path.abspath(self.config.get("Output File") or "echoes_export.json")
        if self._recorder is None or out != self._out_path:
            self._out_path = out
            self._recorder = EchoRecorder(out_path=out)
            # screenshots of echoes whose zh name/set we can't map yet, so the
            # mapping can be filled in later from these images.
            self._unknown_dir = os.path.join(
                os.path.dirname(out), "echo_export_unrecognized"
            )
            self._unknown_count = 0
            self.info_set("Output", self._out_path)
            self.info_set("Recorded", 0)
            self.info_set("Unrecognized", 0)
            self.info_set("Status", "monitoring")
        return self._recorder

    def _save_unrecognized(self, record):
        """Save the full frame for an echo we couldn't fully map, for later."""
        os.makedirs(self._unknown_dir, exist_ok=True)
        self._unknown_count += 1
        safe = re.sub(r'[<>:"/\\|?*]', "", record.name_zh or "unknown") or "unknown"
        path = os.path.join(self._unknown_dir, f"{self._unknown_count:03d}_{safe}.png")
        cv2.imwrite(path, self.frame)
        self.info_set("Unrecognized", self._unknown_count)
        self.log_info(
            f"unrecognized echo saved for later mapping: {record.name_zh!r} "
            f"(echo={record.echo}, set={record.set_zh}->{record.echo_set}); "
            f"warnings={record.warnings}; saved {path}",
            notify=True,
        )

    # -- stable-frame detection (cheap, no OCR) ----------------------------
    def _panel_hash(self):
        """Downscaled hash of the right detail panel; stable between scrolls."""
        box = self.box_of_screen(0.55, 0.0, 1.0, 1.0)
        crop = box.crop_frame(self.frame)
        small = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (24, 24))
        return small.tobytes()

    def _is_stable(self):
        h = self._panel_hash()
        if h == self._last_hash:
            self._last_hash_count += 1
        else:
            self._last_hash = h
            self._last_hash_count = 0
        # one prior identical tick (~0.2s) is enough; never re-process same panel
        return self._last_hash_count >= 1 and h != self._processed_hash, h

    # -- main monitor tick -------------------------------------------------
    def run(self):
        recorder = self._ensure_recorder()
        stable, h = self._is_stable()
        if not stable:
            return

        boxes = self.ocr(box=self.box_of_screen(0.55, 0.0, 1.0, 1.0))
        items = from_ok_boxes(boxes, self.width, self.height)
        if not is_equipment_page(items):
            self._processed_hash = h  # don't re-OCR this non-echo panel
            return

        record = parse_equipment_frame(items)
        self._processed_hash = h
        if record is None:
            return  # not a usable +25 echo panel

        if recorder.add(record):
            self.info_set("Recorded", len(recorder))
            tag = "NEW" if record.is_recognized else "NEW (unrecognized)"
            self.info_set("Last", f"{record.name_zh} ({record.echo}) {tag}")
            self.log_info(
                f"recorded echo #{len(recorder)}: {record.name_zh} -> "
                f"{record.echo} {record.echo_set} cost{record.type}",
                notify=True,
            )
            # Save a screenshot of anything we couldn't fully map (unknown echo
            # name, unknown sonata set, or stat warnings) so we can resolve the
            # mapping later from the image.
            if not record.is_recognized:
                self._save_unrecognized(record)
            return True
        else:
            self.info_set("Last", f"{record.name_zh} (already recorded)")
