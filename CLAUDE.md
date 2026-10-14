# CalcView Migrator — build rules

Spec: `docs/CalcView Migrator — Spec v0.1.md`. Plans: `docs/superpowers/plans/`.

## Commands
- Install: `python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]" -c constraints.txt`
- Test: `pytest -q`
- Regenerate golden IR (then review the diff by hand): `UPDATE_GOLDEN=1 pytest tests/test_golden_ir.py`
- Import: `calcview import <folder> --db <file>` (default db `$CALCVIEW_DB`, else `./calcview.db`)
- Serve: `calcview serve --db <file>` (always 127.0.0.1)

## Rules
- Never read from or write to the network at runtime. Vendor every JS dependency into `app/web/static/vendor/`.
- Python floor is 3.11: no newer syntax or stdlib APIs.
- Parsers never raise on input files. Every failure becomes an `IRWarning` with a code.
- Generators read only the IR. No XML access outside `app/parsers/`.
- Every IR change updates the golden files in the same commit, with a note on why.
- Untranslatable logic produces a visible marker, never silent omission.
- Keep the audit CLI free of business content. Its leak test must pass.
- Fixtures are synthetic only: dummy names like `TABLE_A`, `COL_1`. Never commit real view XML.
