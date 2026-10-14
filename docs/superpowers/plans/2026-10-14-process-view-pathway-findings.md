# Process-view pathway — rulings and deferred review findings

Carried forward from the subagent-driven build of plan `2026-10-14-process-view-pathway.md`.

## Rulings
- Ruling: pin `networkx==3.6.1` — 3.7 requires Python 3.12, which breaks the 3.11 floor — cost if wrong: none; bump when the floor moves.

- Ruling (T1): new fixtures carry `outputViewType="Projection"` (their top node is a projection); the parser ignores the attribute — cost if wrong: one attribute edit and golden regeneration.
- Ruling (T1): cycle fixtures stay minimal (no parameters, no filter) — cost if wrong: extend them if parameter wiring across a cycle needs testing.
- Ruling (T2): symlinked files are included; only symlinked directories are skipped (a file cannot loop) — cost if wrong: a view could be imported twice; one `is_symlink()` check.
- Ruling (T2): the scan root is resolved, so a root symlink is followed and every path is canonical — cost if wrong: paths show the real location rather than the link.
- Ruling (T2): views are sorted by plain codepoint order of the relative posix path (`a-b/…` sorts before `a/…`); later tasks must not assume per-component order — cost if wrong: cosmetic ordering.
- Ruling (T2 review): unreadable directories and non-UTF-8 file names become scan warnings (`SCAN_DIR_UNREADABLE`, `SCAN_BAD_FILENAME`) via an optional `warnings` list, keeping `scan_folder`'s return type; hidden files are skipped like hidden dirs — cost if wrong: none.

## Deferred minor findings
