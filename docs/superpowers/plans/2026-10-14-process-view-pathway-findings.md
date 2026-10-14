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
- Ruling (T3): duplicate view ids get one `DUPLICATE_VIEW_ID` error; the estate keeps one definition per bare id (parsed before failed, then package/root first, then file hash); the package tie-break only decides internal vs leaf — cost if wrong: if real estates reuse names across packages, identity must include the package across IR, store and UI. Add to the M4 audit's "still unconfirmed" list.
- Ruling (T3): an ambiguous calc-view source becomes leaf `view:<key>` with only `AMBIGUOUS_DEPENDENCY`; Task 10 should mark such nodes visibly — cost if wrong: a separate `ambiguous:` prefix is a small model change.
- Ruling (T3): CDS sources become `unknown:` leaves until a parser produces them — cost if wrong: add `LeafKind.CDS`.
- Ruling (T3): `upstream`/`downstream` are transitive, internal views only; unknown id returns [] — cost if wrong: add a direct-neighbour helper.
- Ruling (T3): URI package = first non-empty segment when the URI has ≥3 segments; match key falls back from last URI segment to source name to DataSource id — confirm with the audit's resourceUri shapes.
- Ruling (T3): one `CYCLE` warning per cycle (view_id None), not one per member; per-view pages read `estate.cycles` — cost if wrong: duplicate counts if changed later.
- Ruling (T3): `Estate` fields carry default factories (same shape as specified) — cost if wrong: none.

## Deferred minor findings
- T3: `order_and_cycles(estate)` runs on a half-built Estate; consider taking views + dependencies directly.
- T3: `used_by` collected by append then de-duplicated; could use sets.
- T3: `test_warnings_are_deterministic` overlaps the input-order test.
