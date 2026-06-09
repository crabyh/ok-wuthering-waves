# ExportEchoTask.py
import os
import re

import cv2
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
    screen, and whenever a new max-level echo panel is shown it parses and
    records it. Toggle it on/off from the control panel. The parsing logic
    lives in :mod:`src.echo_export` and is unit tested on its own.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Canonical English name/description; localized via i18n .po/.mo (tr()).
        self.name = "Export Echoes"
        self.description = (
            "Browse +25 echoes on the echo equipment page; new ones are "
            "auto-recorded to a JSON file importable by the optimizer."
        )
        self.icon = FluentIcon.SAVE
        # NOTE: do NOT gate on supported_languages — that filters by the OK-WW
        # *UI* language, but this feature only needs the *game* to be in
        # Simplified/Traditional Chinese (for OCR). Keep the task always visible.
        # minimum gap between ticks; OCR time dominates. content dedup makes
        # frequent ticks harmless, so keep it responsive.
        self.trigger_interval = 0.1
        self.default_config.update({
            "_enabled": False,
            "Output File": "echoes_export.json",
            "Save Screenshots": False,
        })
        self.config_description = {
            "Output File": "导出文件路径 / path of the exported JSON file",
            "Save Screenshots": "保存每个已识别声骸的截图(用于构建测试样本) / "
            "also save a screenshot of every recognized echo (for building test fixtures)",
        }
        self._recorder = None
        self._out_path = None
        self._last_sig = None   # content signature of the last seen echo
        self._tick = 0

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
            # screenshots of recognized echoes (only when "Save Screenshots" is
            # on) — useful for building (screenshot, expected-JSON) test fixtures.
            self._shot_dir = os.path.join(
                os.path.dirname(out), "echo_export_screenshots"
            )
            self._unknown_count = 0
            self._shot_count = 0
            self.info_set("Output", self._out_path)
            self.info_set("Recorded", 0)
            self.info_set("Unrecognized", 0)
            self.info_set("Status", "monitoring")
        return self._recorder

    @staticmethod
    def _safe(part) -> str:
        """Filename-safe fragment (strips illegal chars + whitespace; keeps CJK)."""
        return re.sub(r'[<>:"/\\|?*\s]+', "", str(part if part not in (None, "") else "_"))

    def _imwrite(self, path, frame) -> bool:
        """Write a PNG, supporting non-ASCII (Chinese) paths on Windows.

        cv2.imwrite silently fails on unicode paths on Windows; encode then write
        the bytes ourselves instead.
        """
        ok_, buf = cv2.imencode(".png", frame)
        if not ok_:
            return False
        with open(path, "wb") as f:
            f.write(buf.tobytes())
        return True

    def _save_screenshot(self, record):
        """Save the full frame of a recognized echo (for test fixtures)."""
        os.makedirs(self._shot_dir, exist_ok=True)
        self._shot_count += 1
        name = "_".join(self._safe(p) for p in (
            f"{self._shot_count:03d}", record.echo, record.name_zh,
            record.echo_set, f"cost{record.type}"))
        path = os.path.join(self._shot_dir, f"{name}.png")
        self._imwrite(path, self.frame)
        self.log_info(f"[export] saved screenshot {path}")

    def _save_unrecognized(self, record):
        """Save the full frame for an echo we couldn't fully map, for later.

        The name encodes what we *did* read (cleaned zh name, set, cost) so the
        echo is identifiable at a glance when filling in the mapping.
        """
        os.makedirs(self._unknown_dir, exist_ok=True)
        self._unknown_count += 1
        name = "_".join(self._safe(p) for p in (
            f"{self._unknown_count:03d}", record.name_zh or "unknown",
            record.echo_set or record.set_zh, f"cost{record.type}"))
        path = os.path.join(self._unknown_dir, f"{name}.png")
        self._imwrite(path, self.frame)
        self.info_set("Unrecognized", self._unknown_count)
        self.log_info(
            f"unrecognized echo saved for later mapping: {record.name_zh!r} "
            f"(echo={record.echo}, set={record.set_zh}->{record.echo_set}); "
            f"warnings={record.warnings}; saved {path}",
            notify=True,
        )

    # -- main monitor tick -------------------------------------------------
    def run(self):
        try:
            return self._run()
        except Exception as e:
            import traceback
            self.log_error(f"[export] run() error: {e}\n{traceback.format_exc()}")
            return  # swallow so the executor doesn't disable the task

    def _run(self):
        # No image-hash stability gate: the echo equipment page shows an
        # animated 3D model, so the panel pixels never settle. Instead OCR each
        # tick (the *text* is stable) and use the parsed content signature to
        # detect a newly-selected echo.
        self._tick += 1
        recorder = self._ensure_recorder()

        # Full-frame OCR (absolute coords). The parser isolates the right detail
        # panel itself, anchored on the COST label, so this is resolution-robust.
        boxes = self.ocr()
        items = from_ok_boxes(boxes, self.width, self.height)

        if not is_equipment_page(items):
            if self._tick % 20 == 0:  # ~10s heartbeat
                self.log_info(
                    f"[export] alive (tick {self._tick}); not on echo equipment "
                    f"page (ocr_items={len(items)}, frame={self.width}x{self.height})"
                )
            return

        record = parse_equipment_frame(items)
        if record is None:
            if self._tick % 20 == 0:
                self.log_info("[export] on equipment page but no +25 echo "
                              "(not max level, or stats not readable)")
            return

        sig = record.signature()
        if sig == self._last_sig:
            return  # same echo still displayed; nothing new
        self._last_sig = sig
        self.log_info(
            f"[export] parsed {record.name_zh!r} echo={record.echo} "
            f"set={record.echo_set} cost={record.type} warnings={record.warnings}"
        )

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
            elif self.config.get("Save Screenshots"):
                self._save_screenshot(record)
            return True
        else:
            self.info_set("Last", f"{record.name_zh} (already recorded)")
