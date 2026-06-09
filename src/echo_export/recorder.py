"""In-memory echo store with content de-duplication and atomic JSON output.

A few hundred echoes are tiny, so everything stays in memory; the JSON file is
rewritten atomically after each new echo for crash-safety. The output is a JSON
array in the optimizer's "Import echoes from text" format.
"""
from __future__ import annotations

import json
import os
import tempfile

from src.echo_export.parser import EchoRecord


class EchoRecorder:
    def __init__(self, out_path: str | None = None):
        self.out_path = out_path
        self._seen: set[tuple] = set()
        self._records: list[EchoRecord] = []

    def __len__(self) -> int:
        return len(self._records)

    @property
    def records(self) -> list[EchoRecord]:
        return list(self._records)

    def is_new(self, record: EchoRecord) -> bool:
        return record.signature() not in self._seen

    def add(self, record: EchoRecord) -> bool:
        """Add a record if unseen. Returns True if newly added."""
        sig = record.signature()
        if sig in self._seen:
            return False
        self._seen.add(sig)
        self._records.append(record)
        if self.out_path:
            self.save()
        return True

    def to_list(self) -> list[dict]:
        return [r.to_optimizer_dict() for r in self._records]

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
