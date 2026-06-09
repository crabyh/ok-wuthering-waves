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
        """ASCII-only filename fragment.

        Chinese/■ characters in filenames cause trouble (downstream tooling,
        cross-platform, OCR pipelines), so filenames stay pure ASCII; the full
        Chinese names are preserved in the sidecar index.jsonl instead.
        """
        return re.sub(r"[^A-Za-z0-9]+", "", str(part)) if part not in (None, "") else ""

    def _append_index(self, folder, fname, record):
        """Append the parsed details (incl. CJK names) for a saved screenshot."""
        import json as _json
        with open(os.path.join(folder, "index.jsonl"), "a", encoding="utf-8") as f:
            f.write(_json.dumps({
                "file": fname,
                "name_zh": record.name_zh,
                "set_zh": record.set_zh,
                "echo": record.echo,
                "echoSet": record.echo_set,
                "type": record.type,
                "stat": record.stat,
                "warnings": record.warnings,
            }, ensure_ascii=False) + "\n")

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
        """Save the full frame of a recognized echo (for test fixtures).

        Filename is ASCII-only (echo key/set are English); the Chinese names go
        into index.jsonl.
        """
        os.makedirs(self._shot_dir, exist_ok=True)
        self._shot_count += 1
        fname = "_".join(filter(None, (
            f"{self._shot_count:03d}", self._safe(record.echo),
            self._safe(record.echo_set), f"cost{record.type}"))) + ".png"
        path = os.path.join(self._shot_dir, fname)
        self._imwrite(path, self.frame)
        self._append_index(self._shot_dir, fname, record)
        self.log_info(f"[export] saved screenshot {path}")

    def _save_unrecognized(self, record):
        """Save the full frame for an echo we couldn't fully map, for later.

        Filename stays ASCII (counter + any recognized set + cost); the Chinese
        name/set we *did* read are written to index.jsonl so the echo is
        identifiable when filling in the mapping.
        """
        os.makedirs(self._unknown_dir, exist_ok=True)
        self._unknown_count += 1
        fname = "_".join(filter(None, (
            f"{self._unknown_count:03d}", self._safe(record.echo_set),
            f"cost{record.type}"))) + ".png"
        path = os.path.join(self._unknown_dir, fname)
        self._imwrite(path, self.frame)
        self._append_index(self._unknown_dir, fname, record)
        self.info_set("Unrecognized", self._unknown_count)
        self.log_info(
            f"unrecognized echo #{self._unknown_count} saved {path}: "
            f"name={record.name_zh!r} set={record.set_zh!r}->{record.echo_set}; "
            f"warnings={record.warnings}",
            notify=True,
        )

    # number of immediate re-OCR attempts when a read is incomplete (the
    # animated 3D model can transiently obscure the stat rows).
    RETRY_ON_INCOMPLETE = 5

    def _ocr_parse(self):
        """One full-frame OCR + parse. Returns (on_equipment_page, record, n)."""
        items = from_ok_boxes(self.ocr(), self.width, self.height)
        if not is_equipment_page(items):
            return False, None, len(items)
        return True, parse_equipment_frame(items), len(items)

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

        on_page, record, n_items = self._ocr_parse()
        if not on_page:
            if self._tick % 20 == 0:  # ~heartbeat
                self.log_info(
                    f"[export] alive (tick {self._tick}); not on echo equipment "
                    f"page (ocr_items={n_items}, frame={self.width}x{self.height})"
                )
            return

        if record is None:
            if self._tick % 20 == 0:
                self.log_info("[export] on equipment page but no +25 echo "
                              "(not max level, or mid-load)")
            return

        # Incomplete read (e.g. the 3D model is covering the main-stat rows):
        # skip this frame and immediately re-OCR a few fresh frames — the model
        # animates, so the stats usually become readable within a moment.
        if not record.is_recognized:
            for _ in range(self.RETRY_ON_INCOMPLETE):
                self.next_frame()
                self.sleep(0.06)
                _, retry_rec, _ = self._ocr_parse()
                if retry_rec is not None and retry_rec.is_recognized:
                    record = retry_rec
                    break

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
