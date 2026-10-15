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
- Ruling (T4): the store keeps the IR as a `ParseResult` JSON blob plus summary `view`/`node` tables, not fully flattened columns/edges — revisit at M7 when field-level remapping needs per-column rows.
- Ruling (T4 review): an unchanged file hash still re-parses; if the fresh JSON differs from the stored text the row is rewritten and counted `reparsed`, with no stale marks except "node removed". This lets parser fixes from the audit loop reach stored views and repairs rows written by an older IR — cost if wrong: none; it costs one parse per file, which the scan does anyway.
- Ruling (T4): a file renamed within its package (identical JSON, new rel_path) rewrites the row and counts `unchanged` — cost if wrong: one line to count it as reparsed.
- Ruling (T4): duplicate view ids in one scan prefer a parsed file over a failed one, then sorted rel_path (matches T3).
- Ruling (T4): `DUPLICATE_NODE_ID` (parser warning) covers repeated calculationView/DataSource ids and a calculationView named `Semantics`; the last node still wins; such views now parse `partial`. Settles the M1 deferred duplicate-id findings.
- Ruling (T4): transactions use `BEGIN IMMEDIATE`, savepoints when nested, busy_timeout 5000; connections use `check_same_thread=False` because each request owns its Store.
- Ruling (T5): GET pages use `get_existing_store` (never creates a db); only POST /import creates one. `serve` fails fast on an unusable db; `import` and `serve` both honour `$CALCVIEW_DB`.
- Ruling (T5): the import report splits "Leaf sources" (tables, table functions) from "Unresolved" (external, unknown, ambiguous); counts are consumer→producer lines, not distinct sources.
- Ruling (T6): projection "Takes N columns" counts non-calculated columns; the output headline counts all columns including calculated ones (both pinned by the plan's fixture sentences).
- Ruling (T6): a calc-view source with no estate and no resolution gets no detail (neither "Defined in this project" nor "external") — Task 7 and M6 must not "fix" this.
- Ruling (T6): invented wording for gaps (CDS, opaque, script statement, unknown cardinality, no join columns, missing inputs, unknown aggregation) — each states the gap visibly; see the plan's Task 6 rules.
- Ruling (T7): the view graph uses dagre `rankDir: 'BT'` — output at the top, sources at the bottom, like the HANA modeller.
- Ruling (T7): POST bodies are parsed with `parse_qs` (no python-multipart); POST /import opens the Store only after the folder is validated, so a bad path never creates a db.
- Ruling (T7): duplicate edge pairs get `#n` id suffixes; an edge to an undefined step gets a visible "missing" placeholder node; a repeated node id is drawn once (last definition wins).
- Ruling (T7): list "Reads views"/"Used by" counts are direct internal links; the header adds transitive lists when longer.
- Ruling (T7): identity travels in query parameters (`/node?view=&node=<node id>`, `POST /notes?view=`, `POST /node/notes?view=&node=`, `GET /view.mmd?view=`) because view ids may contain `/`; the page itself is `/views/{id:path}`.
- Ruling (T7 review, security): unsafe methods require Sec-Fetch-Site absent/same-origin/none and a matching Origin, and a urlencoded body (else 403/415); TrustedHostMiddleware allows only 127.0.0.1 and localhost. Prevents a web page from triggering imports (which delete views) and DNS-rebinding reads.
- Ruling (T7): stored-data errors render a 409 page with a re-import action; store reads fetch all rows before validating so a failed validation cannot hold a read lock.
- Ruling (T9): SQL-language expressions are only counted, never mined for names (SQL can hold unquoted column names before `(`).
- Ruling (T9 review): namespace URIs print only for `http://www.sap.com/ndb/…` and `http://www.w3.org/…`; others and foreign-namespace prefixes print as `<other>`. Function names split into a known HANA catalogue (`KNOWN_FUNCTIONS`, grows from audit reports) and "unrecognised (review before sharing)".
- Ruling (T9): element/attribute names, xsi:type values and allow-listed enum values print as written (the M1 gate needs them); the README and the report intro tell the reader to review these before sharing.
- Ruling (T9): the audit counts UNKNOWN_ELEMENT through an optional collector on the parser's own `_check_children`, so the two cannot drift.
- Ruling (T9): duplicate-id counts exclude only files whose id fell back to the file stem.
- Resolved: T6 → T7 deferred items (failed-view message; escaped `(not parsed)` markup).
- Ruling (T8): a notes POST merges: a field the form does not send keeps its stored value (the node panel sends owner, status and notes only, so a step's purpose survives). A field over 20 000 characters or an unknown status is a 400 that re-renders the form with what was typed; nothing is saved — cost if wrong: none.
- Ruling (T8): POST /node/notes answers a validation error with 400, unlike GET /node's 200 error fragments; `viewgraph.js` swaps a 400 into `#node-panel` via `htmx:beforeSwap`. An unknown view or step stays a 200 fragment like GET /node — cost if wrong: one line in the route.
- Ruling (T8 review): notes routes live in `app/web/notes.py` (own router). `viewgraph.js` also listens for `htmx:responseError` on the panel and prepends "Not saved (HTTP n)" (POST) or "Could not load this step (HTTP n)" (GET), keeping what was typed. An emptied field clears the stored value; an absent field keeps it.
- Ruling (T8 review): annotation identity is (target_kind, target_id): `PRIMARY KEY (target_kind, target_id)`, `get_annotation(target_id, kind)` and `mark_stale(target_ids, reason, kind)` take the kind, so a view and a step sharing an id keep separate notes and staleness. `SCHEMA_VERSION = 2`; a version-1 db is refused with the existing "cannot use this database" message and no migration (no real data exists yet) — cost if wrong: a one-off migration copying the v1 annotation table.
- Ruling (T8 review): orphaned notes are never hidden. A step note whose step is gone belongs to the longest existing view id that prefixes it plus `/` and is listed on that view's Notes tab ("Notes on steps that no longer exist"). A step note with no such view, or stale with reason "view removed", is listed on /views under "Notes on views that no longer exist", with view notes of removed views. The "view removed" reason is what tells view `A/B` removed (its `A/B/X` goes to the removed list) from a step of view `A` (the prefix alone cannot) — cost if wrong: a step note already stale "node removed" before its view `A/B` was removed still lands on view `A`; fixing that needs the owning view id stored on the annotation.
- Ruling (T8): the views list "Sign-off" column sorts no note first, then draft, reviewed, approved.

## Deferred minor findings
- T9: each file is parsed twice by the audit (parser + structure scan); fine at estate scale.
- T7: view ids `.` or `..` would be normalised away by browsers.
- T7: every node click recomputes the estate; fine at a few hundred views.
- T6 → T7: a failed view yields no steps; the Steps tab must show a "could not be parsed" message with the view warnings.
- T6 → T7: `` `raw` (not parsed) `` text must be styled/escaped in HTML, not rendered as Markdown.
- T4: a failed import that created a db removes the .db but not a stray -journal file.
- T3: `order_and_cycles(estate)` runs on a half-built Estate; consider taking views + dependencies directly.
- T3: `used_by` collected by append then de-duplicated; could use sets.
- T3: `test_warnings_are_deterministic` overlaps the input-order test.
