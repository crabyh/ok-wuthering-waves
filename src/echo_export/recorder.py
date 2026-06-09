"""In-memory echo store with content de-duplication and atomic JSON output.

A few hundred echoes are tiny, so everything stays in memory; the JSON file is
rewritten atomically after each new echo for crash-safety. The output is a JSON
array in the optimizer's "Import echoes from text" format.
"""
from __future__ import annotations

import json
import os
import tempfile

from src.echo_export.parser import EchoRecord, signature_from_dict


class EchoRecorder:
    """De-duplicating echo store. Records are kept as optimizer dicts.

    On init it LOADS any existing ``out_path`` JSON and seeds the de-dup set, so
    re-browsing the echo list (within a run or across restarts) never produces
    duplicates and never overwrites previously-collected echoes.
    """

    def __init__(self, out_path: str | None = None):
        self.out_path = out_path
        self._seen: set[tuple] = set()
        self._records: list[dict] = []
        if out_path and os.path.exists(out_path):
            self._load()

    def _load(self) -> None:
        try:
            with open(self.out_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, list):
            return
        for d in data:
            if not isinstance(d, dict):
                continue
            sig = signature_from_dict(d)
            if sig not in self._seen:
                self._seen.add(sig)
                self._records.append(d)

    def __len__(self) -> int:
        return len(self._records)

    @property
    def records(self) -> list[dict]:
        return list(self._records)

    def is_new(self, record: EchoRecord) -> bool:
        return record.signature() not in self._seen

    def add(self, record: EchoRecord, screenshot: str | None = None) -> bool:
        """Add a record if unseen. Returns True if newly added.

        ``screenshot`` is the path of this echo's screenshot (relative to the
        output dir); stored on the entry so each echo JSON maps 1:1 to its image.
        """
        sig = record.signature()
        if sig in self._seen:
            return False
        self._seen.add(sig)
        d = record.to_optimizer_dict()
        if screenshot:
            d["screenshot"] = screenshot
        self._records.append(d)
        if self.out_path:
            self.save()
        return True

    def to_list(self) -> list[dict]:
        return list(self._records)

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_list(), ensure_ascii=False, indent=indent)

    def save(self, path: str | None = None) -> str:
        """Atomically write the JSON array to ``path`` (or ``self.out_path``)."""
        target = path or self.out_path
        if not target:
            raise ValueError("no output path configured")
        directory = os.path.dirname(os.path.abspath(target))
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(self.to_json())
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return target
