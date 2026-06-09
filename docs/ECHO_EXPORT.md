# Echo Export (to wuthering-waves-optimizer)

Export your in-game echoes to a JSON file that the
[wuthering-waves-optimizer](https://github.com/ryanbenson/wuthering-waves-optimizer)
can import via **"Import echoes from text"**.

The program is a **passive screen monitor** — it never controls the game. You
browse your echoes (e.g. with a controller); whenever a new **+25** echo is
shown on the **echo equipment page**, it is parsed and recorded.

---

## 0. One-time prerequisites

- **Python 3.12** (required — see `pyappify.yml`). Install from python.org and
  tick **"Add Python to PATH"**.
- **Git** (git-scm.com).

Verify in a new PowerShell window:

```powershell
python --version      # should print 3.12.x
git --version
```

## 1. Get the code

```powershell
cd $HOME\Documents
git clone https://github.com/crabyh/ok-wuthering-waves.git
cd ok-wuthering-waves
```

If you already have a clone: `cd ok-wuthering-waves; git pull origin master`.

## 2. Create the virtual environment and install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 3. (Optional) Sanity-check the export tests

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest tests\test_echo_export.py -v
```

All tests should pass before you touch the game.

## 4. Run the app

1. **Start Wuthering Waves first** (the tool attaches to the running game).
2. Launch ok-wuwa from source:

   ```powershell
   .\.venv\Scripts\python.exe main.py
   ```

## 5. Capture your echoes

1. In game, open the **echo equipment page** — the one whose right panel shows
   the selected echo's stats **and** the 合鸣效果 / sonata set, and which has
   `简述` at the top-right. (Not the 强化/enhancement page or the
   inventory-management page.)
2. In the ok-wuwa control panel, enable **"导出声骸到优化器 (Export Echoes)"**.
3. Browse through your **+25** echoes one at a time. The panel shows:
   - `Recorded` — unique echoes captured so far
   - `Unrecognized` — echoes that could not be fully mapped (screenshots saved)
   - `Last` — most recent echo + NEW / already-recorded
4. **Stop** the task when finished.

## 6. Output

- `echoes_export.json` — paste its contents into the optimizer's
  **Import echoes from text**.
- `echo_export_unrecognized\` — full-frame screenshots of any echo whose Chinese
  name or sonata set is not yet in the mapping. Keep these so the mapping can be
  filled in later.

## 7. Notes / troubleshooting

- Only **+25 (max level)** echoes are recorded; others are skipped on purpose.
- Duplicate detection is by content (name + cost + main stat + set + sub stats),
  so re-viewing an echo does not create a duplicate.
- If echoes record with empty/None stats, the OCR region may need adjustment —
  share a screenshot from `echo_export_unrecognized\` and the `logs\` output.
- The parsing/mapping core lives in `src/echo_export/`; the live-game glue is
  `src/task/ExportEchoTask.py`. The core is covered by `tests/test_echo_export.py`.
