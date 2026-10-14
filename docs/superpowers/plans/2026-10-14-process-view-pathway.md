# CalcView Migrator — Process-View Pathway Plan (M3, M5+, M4, Estate Map)

> **For agentic workers:** run this plan task by task with subagent-driven development: one implementer subagent per task (TDD, commit at the end), then a spec-compliance review and a code-quality review, then fix rounds until both pass. Record rulings and deferred minor findings in `2026-10-14-process-view-pathway-findings.md`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Jacob *see and understand* the calculation-view estate before any SQL conversion exists: import a folder of views into a per-project SQLite file, resolve view-to-view dependencies, and browse (a) each view's node graph with plain-English step descriptions and (b) an estate-wide dependency / process map. Add the structure-only audit CLI right after the view graph, so real files can confirm the parser's assumptions before the estate map relies on them.

**Architecture:** Unchanged compiler shape. New modules: `app/ingest/` (folder scan, import, re-import), `app/enrich/deps.py` (cross-view resolution), `app/ir/graph.py` (networkx estate graph), `app/ir/store.py` (SQLite), `app/generators/describe.py` (plain-English templates), `app/generators/lineage.py` (Cytoscape JSON and Mermaid), `app/parsers/audit_scan.py` + `app/audit.py` (structure-only report). Web pages are Jinja2 + htmx with one small first-party script per graph page.

**Source spec:** `docs/CalcView Migrator — Spec v0.1.md`. Previous plan: `2026-10-14-calcview-migrator-m0-m1.md` (its "Still unconfirmed" list and deferred findings carry forward).

## Revised roadmap (2026-10-14)

Jacob's call: understand the process first; SQL parsing and conversion come later. The milestone numbers stay as in the spec so cross-references still work; only the order and some scope boundaries change.

| Order | # | Milestone | Status | Notes |
|---|---|---|---|---|
| 1 | M0 | Skeleton | Done (PR #1) | |
| 2 | M1 | Graphical parser + IR | Done on synthetic, pending `xsi:type` confirmation | Acceptance gate still open: real-folder `xsi:type` grep, or the M4 audit |
| 3 | **M3** | Dependencies + SQLite persistence + re-import | **This plan, Tasks 1–5** | Pulled before M2. Graphical views only; scripted views stay opaque nodes with no outgoing dependency edges until M2 |
| 4 | **M5+** | Views list + view graph + plain-English steps + notes | **This plan, Tasks 6–8** | Adds the plain-English node templates from M6 (one headline + details per node), not the full spec Markdown |
| 5 | **M4** | Audit CLI + leak test | **This plan, Task 9** | Run it at work as soon as it lands; feed the report back before trusting the estate map's matching rules |
| 6 | **M9a** | Estate map (view to view) + PNG/Mermaid export | **This plan, Task 10** | The estate level of M9 only. Colours by parse status, view type, data category or sign-off. No target-decision colouring yet (needs the recommender) |
| 7 | M2 | Scripted parser + sqlglot spike | Later plan | Still blocked by a scripted (`SqlScriptView`) sanitised skeleton. Once done, scripted views gain dependency edges in the estate map |
| 8 | M6 | Full business-logic spec Markdown | Later plan | Reuses `generators/describe.py` from Task 6 |
| 9 | M7 | Remapping | Later plan | Adds openpyxl |
| 10 | M8 | Databricks + Datasphere SQL generators | Later plan | Also needs naming conventions, the output consumer and the Datasphere parameter behaviour |
| 11 | M9b | Column lineage + recommender (+ target colouring on the estate map) | Later plan | Adds PyYAML |
| 12 | M10 | LLM plug-in | Later plan | LLM approval route |

**Open questions this pathway still needs answered (from Jacob, at work):**
- The `xsi:type` mix across the real folder (M1 gate; the M4 audit answers it).
- How a real consuming view names its upstream view: `DataSource@type="CALCULATION_VIEW"` plus `resourceUri` (`/package/calculationviews/NAME`) is assumed. If real files differ, Task 3's matching rule changes. The M4 audit reports `DataSource@type` values and `resourceUri` shape counts.
- File extension(s) in the real export: `.calculationview` is assumed; `.hdbcalculationview` (XS advanced / HDI) is accepted too.

## Global constraints (unchanged, plus three)

- Python floor 3.11: no newer syntax or stdlib APIs (`StrEnum` is fine; no PEP 695 generics, no `type` statements).
- Loopback only; no network at runtime; JS vendored. First-party JS lives in `app/web/static/app/` and must contain no `http://` or `https://` URLs.
- Parsers never raise on input files. Import never raises on a bad file either: a bad file is a failed view with a warning.
- Generators read only the IR (and the estate model built from IR). No XML access outside `app/parsers/` — this includes the audit's XML walking.
- Every IR change updates golden files in the same commit, with a note on why. New fixtures get golden files in the commit that adds them.
- Untranslatable or unrecognised content produces a visible marker, never silent omission. In plain-English text, an unparsed expression is shown verbatim with "(not parsed)".
- Fixtures are synthetic only (`TABLE_A`, `COL_1`, …).
- **New:** runtime dependency `networkx>=3.2` (pin `networkx==3.6.1` in `constraints.txt`; 3.7 needs Python 3.12). No other new runtime dependencies. sqlite3 is stdlib.
- **New:** every user-controlled string reaching HTML is autoescaped; JSON embedded in a page goes through Jinja's `tojson` filter inside `<script type="application/json">`.
- **New:** the project database is a local file chosen by the user (`--db`, default `./calcview.db`). `*.db` files are git-ignored. It holds work data, so nothing in it is ever printed by the audit command.

## File structure (this plan)

```
app/
  cli.py                     # + import, audit; serve --db
  main.py                    # create_app(db_path) ; routes in app/web/routes.py
  audit.py                   # aggregates audit_scan output into a structure-only report
  ingest/__init__.py
  ingest/scan.py             # find view files, package paths, parse each (never raises)
  ingest/importer.py         # import / re-import into the store; stale-marking
  enrich/__init__.py
  enrich/deps.py             # resolve DataSource -> View; build Estate
  ir/models.py               # + Estate, ViewDependency, LeafSource, Annotation models
  ir/graph.py                # networkx graph from Estate; topo order; cycles; up/downstream
  ir/store.py                # SQLite persistence
  generators/__init__.py
  generators/describe.py     # plain-English node descriptions + expression renderer
  generators/lineage.py      # Cytoscape elements (view + estate) and Mermaid text
  parsers/audit_scan.py      # structural facts from one XML file (tags, attrs, xsi:types, functions)
  web/routes.py              # page and API routes
  web/templates/*.html       # base, import, views, view, node panel, estate
  web/static/app/viewgraph.js
  web/static/app/estate.js
fixtures/synthetic/
  graphical/SOURCE_VIEW_01.calculationview (+ .ir.json)   # producer for GENERIC_TAX_REPORTING_CUBE
  estate_cycle/CYCLE_A.calculationview, CYCLE_B.calculationview (+ .ir.json)
  estate/graphical.estate.json        # golden Estate for fixtures/synthetic/graphical
  audit/LEAKCANARY_VIEW.calculationview  # leak-test fixture (sentinel names)
tests/
  test_scan.py test_deps.py test_store.py test_import.py test_cli.py
  test_describe.py test_web_views.py test_web_notes.py test_audit.py test_estate.py
```

`pyproject.toml` package-data gains `web/static/app/*`.

---

## Task 1: networkx dependency and dependency fixtures

**Files:** `pyproject.toml`, `constraints.txt`, `.gitignore`, `fixtures/synthetic/graphical/SOURCE_VIEW_01.calculationview`, `fixtures/synthetic/estate_cycle/CYCLE_A.calculationview`, `CYCLE_B.calculationview`, their `.ir.json` goldens, `tests/test_graphical_*` or a new `tests/test_fixtures_estate.py`.

- [ ] Add `networkx>=3.2` to `dependencies`; add `networkx==3.6.1` to `constraints.txt` (keep the file's header comment). Add `*.db`, `*.db-journal`, `*.db-wal`, `*.db-shm` to `.gitignore` if not covered.
- [ ] `SOURCE_VIEW_01.calculationview`: a synthetic CUBE following the same skeleton/element order as `GENERIC_TAX_REPORTING_CUBE`. Root `id="SOURCE_VIEW_01"`. One input parameter `IP_YEAR` (NVARCHAR 4, mandatory) — the name the consumer's `variableMappings/targetVariable@name` points at. One `DATA_BASE_TABLE` data source `TABLE_C` (schema `SCHEMA_1`). A `ProjectionView` `Projection_1` over `TABLE_C` with view attributes `COL_1, COL_2, COL_3, AMT_1` and a filter using `$$IP_YEAR$$`; `logicalModel id="Projection_1"` publishing `COL_1, COL_2, COL_3` as attributes and `AMT_1` as a sum measure. These are exactly the columns the consumer's `Projection_1` maps from `#SOURCE_VIEW_01`. It must parse with status `ok`, coverage 100.
- [ ] `estate_cycle/CYCLE_A` reads `CYCLE_B` and `CYCLE_B` reads `CYCLE_A` (each: one `CALCULATION_VIEW` data source with `resourceUri` `/pkg.synthetic/calculationviews/<OTHER>`, one projection, a logicalModel). Both parse `ok`.
- [ ] Generate goldens with `UPDATE_GOLDEN=1 pytest tests/test_golden_ir.py`, review by hand, and add hand-written assertions (status ok, node names and types, the data source kind `calc_view` and `resource_uri`) in a test file.
- [ ] Note: existing goldens must not change. `pytest -q` green. Commit: `feat(m3): producer and cycle fixtures; networkx dependency`.

## Task 2: Folder scan

**Files:** `app/ingest/__init__.py`, `app/ingest/scan.py`, `tests/test_scan.py`.

Interface:
```python
VIEW_SUFFIXES = (".calculationview", ".hdbcalculationview")   # matched case-insensitively

@dataclass(frozen=True)
class ScannedView:
    path: Path              # absolute
    rel_path: str           # posix path relative to the scan root
    package_path: str | None  # parent dir relative to root, posix, None at root
    result: ParseResult

def find_view_files(root: Path) -> list[Path]   # recursive, sorted by rel posix path, skips hidden dirs
def scan_folder(root: Path) -> list[ScannedView] # parse_file(path, package_path=...) for each
```
- [ ] Never raises on a bad file (`parse_file` already returns a failed result for unreadable/garbage files). A missing or non-directory `root` raises `NotADirectoryError` — that is a usage error, not an input file.
- [ ] Symlinked directories are not followed (avoid loops).
- [ ] Tests (tmp_path): finds both suffixes and upper-case suffix; ignores other files; nested package path `a/b`; deterministic order; garbage file yields a failed result with `XML_SYNTAX`; hidden dirs skipped; non-directory root raises.
- [ ] Commit: `feat(m3): folder scan with package paths`.

## Task 3: Dependency resolution and the estate model

**Files:** `app/ir/models.py` (new models only; `ParseResult` unchanged so no golden IR changes), `app/enrich/__init__.py`, `app/enrich/deps.py`, `app/ir/graph.py`, `fixtures/synthetic/estate/graphical.estate.json`, `tests/test_deps.py`.

New models:
```python
class LeafKind(StrEnum): TABLE="table"; EXTERNAL_VIEW="external_view"; TABLE_FUNCTION="table_function"; UNKNOWN="unknown"

class LeafSource(IRModel):
    id: str                 # "table:SCHEMA_1.TABLE_A", "view:SOME_VIEW", "table_function:...", "unknown:<view>/<ds>"
    kind: LeafKind
    schema_name: str | None = None
    name: str
    used_by: list[str] = []  # view ids, sorted

class ViewDependency(IRModel):
    consumer: str           # view id
    producer: str           # view id (internal) or LeafSource id (leaf)
    data_source_id: str     # the consumer's DataSource node id
    internal: bool

class Estate(IRModel):
    views: list[str]                     # view ids, sorted
    dependencies: list[ViewDependency]   # sorted by (consumer, data_source_id)
    leaf_sources: list[LeafSource]       # sorted by id
    deploy_order: list[str]              # producers before consumers; see rule below
    cycles: list[list[str]]              # each sorted; list sorted
    warnings: list[IRWarning]
```

`resolve_dependencies(results: list[ParseResult]) -> Estate`, and it sets `DataSource.resolved_view_id` on the passed results for internal matches.

Matching rule (record as a ruling; confirm with the M4 audit):
1. Only `DataSource.kind == calc_view` can resolve internally. Its key is the last path segment of `resource_uri` (after the final `/`); if there is no `resource_uri`, the DataSource `name`.
2. Candidates = views whose `View.id` equals the key exactly. If more than one, prefer those whose `package_path` (with `/` replaced by `.`) equals the URI's package segment (the first segment of `/pkg/calculationviews/NAME`). Still not unique → `AMBIGUOUS_DEPENDENCY` warning (severity warning), treated as unresolved.
3. No candidate → leaf `view:<key>` (`EXTERNAL_VIEW`) and `UNRESOLVED_VIEW_DEPENDENCY` warning (severity warning) naming the consumer and key.
4. Tables → leaf `table:<schema>.<name>` (or `table:<name>` without schema); table functions → `table_function:...`; unknown kinds → `unknown:<view>/<ds>`.
5. Two views with the same id (different files) → `DUPLICATE_VIEW_ID` error warning; the first in sorted order wins.
6. Failed views (no nodes) appear in `views` and get no dependencies.

`app/ir/graph.py`: `estate_digraph(estate) -> networkx.DiGraph` (edges producer → consumer, internal and leaf nodes with a `kind` attribute), `deploy_order` and `cycles` computed here: strongly connected components with more than one member, or a self-loop, are cycles (`CYCLE` error warning listing the members); deploy order = lexicographic topological sort of the condensation (ties broken by smallest member id), expanding each component's members in sorted order. Views only (leaf sources are not deployed). Also `upstream(estate, view_id)` / `downstream(estate, view_id)` returning sorted view-id lists (internal views only).

- [ ] Tests: fixture folder `graphical/` → `SOURCE_VIEW_01` resolves for `GENERIC_TAX_REPORTING_CUBE` (`resolved_view_id` set), `TABLE_A`/`TABLE_B` become leaf tables, deploy order `[SOURCE_VIEW_01, GENERIC_TAX_REPORTING_CUBE]`, no warnings; consumer alone (tmp copy) → `UNRESOLVED_VIEW_DEPENDENCY` + external-view leaf; `estate_cycle/` → one cycle `[CYCLE_A, CYCLE_B]`, `CYCLE` warning, both in deploy order; duplicate id; ambiguous match broken by package; failed view handled; self-loop.
- [ ] Golden: `fixtures/synthetic/estate/graphical.estate.json` = `Estate.model_dump_json(indent=2)` for the `graphical/` folder, with `UPDATE_GOLDEN=1` support mirroring `test_golden_ir.py`. **Don't** put it under a path matched by `*.calculationview` globbing.
- [ ] Commit: `feat(m3): cross-view dependency resolution, estate graph, deploy order and cycles`.

## Task 4: SQLite store, import and re-import

**Files:** `app/ir/store.py`, `app/ingest/importer.py`, `app/ir/models.py` (Annotation models), `tests/test_store.py`, `tests/test_import.py`.

Store schema (stdlib `sqlite3`, `PRAGMA foreign_keys=ON`, one project per database file, `PRAGMA user_version = 1` for the schema version):
```
project(id INTEGER PRIMARY KEY CHECK (id = 1), name TEXT, source_folder TEXT, imported_at TEXT)
view(id TEXT PRIMARY KEY, rel_path TEXT, package_path TEXT, file_hash TEXT, view_type TEXT,
     data_category TEXT, parse_status TEXT, coverage_pct REAL, node_count INTEGER,
     warning_count INTEGER, result_json TEXT NOT NULL)
node(id TEXT PRIMARY KEY, view_id TEXT REFERENCES view(id) ON DELETE CASCADE,
     name TEXT, node_type TEXT, understood INTEGER, raw_hash TEXT)
annotation(target_id TEXT PRIMARY KEY, target_kind TEXT CHECK (target_kind IN ('view','node')),
           purpose_text TEXT, owner TEXT, signoff_status TEXT CHECK (signoff_status IN ('draft','reviewed','approved')),
           notes TEXT, stale INTEGER NOT NULL DEFAULT 0, stale_reason TEXT, updated_at TEXT)
```
`result_json` is the full `ParseResult` (the source of truth for pages); `view`/`node` columns are query summaries. Annotations deliberately have **no** foreign key: they must survive their view or node disappearing. Ruling to record: the plan-of-record said "M3's store flattens" columns/edges too; this plan keeps the IR as a JSON blob plus summary tables, because nothing queries columns yet. Revisit at M7 (field-level remapping needs per-column rows).

`Store` API (context-manager friendly; all SQL parameterised):
```python
Store(path: Path)                     # creates schema if missing; refuses an unknown user_version with a clear error
get_project() -> Project | None ; set_project(name, source_folder)
upsert_view(scanned: ScannedView) ; delete_view(view_id)
view_hashes() -> dict[str, str]       # id -> file_hash
list_views() -> list[ViewSummary]     # summary rows, sorted by id
load_result(view_id) -> ParseResult | None ; load_all_results() -> list[ParseResult]
node_hashes(view_id) -> dict[str, str]
get_annotation(target_id) -> Annotation | None ; save_annotation(Annotation) (clears stale on save)
mark_stale(target_ids, reason) ; list_annotations() -> list[Annotation]
```
Models: `SignoffStatus(StrEnum)` draft/reviewed/approved; `Annotation(target_id, target_kind, purpose_text="", owner="", signoff_status=draft, notes="", stale=False, stale_reason=None, updated_at=None)`; `ViewSummary`; `Project`.

`import_folder(store, folder, name=None) -> ImportReport` in `app/ingest/importer.py`:
- Scan; for each scanned view: unchanged `file_hash` → skip (count `unchanged`); new → insert (`added`); changed → re-parse result replaces the row (`changed`). For a changed view: view-level annotation → stale (`"view file changed"`); node annotations whose node `raw_hash` (sha256 of `Node.raw`) changed → stale (`"node changed"`); node annotations whose node no longer exists → stale (`"node removed"`).
- Views in the store but no longer in the folder → deleted from `view`/`node`; their annotations kept and marked stale (`"view removed"`). Count `removed`.
- The same view id from two files in one scan: the first by sorted `rel_path` is stored; the report carries a `DUPLICATE_VIEW_ID` warning.
- Store `file_hash` from the parse result. Use one transaction per import.
- After storing, run `resolve_dependencies` over `load_all_results()` and return the estate in the report (dependencies are recomputed on demand, never stored — ruling: 50–60 views resolve in milliseconds; storing them risks staleness).
- `ImportReport(added, changed, unchanged, removed, stale_annotations, failed, estate)`.

- [ ] Tests: schema creation and reopen; unknown `user_version` refused; round trip of a `ParseResult` equals the original; annotation save/load; import twice → second import all unchanged; modify a fixture copy (change a filter in `Projection_1`) → view changed, annotation on `Projection_1` stale, annotation on `Join_1` not stale, view annotation stale; remove a node → `node removed`; delete a file → view gone, annotation kept and stale; garbage file imports as a failed view; duplicate id.
- [ ] Commit: `feat(m3): SQLite store with import, re-import and stale annotations`.

## Task 5: CLI and app wiring

**Files:** `app/cli.py`, `app/main.py`, `tests/test_cli.py`, `tests/test_app.py`, `README.md`, `CLAUDE.md` (Commands section only).

- [ ] `calcview import <folder> [--db PATH] [--name NAME]` → prints the report (added/changed/unchanged/removed/failed, stale annotations, internal dependencies, unresolved dependencies, cycles, deploy order). Exit 0; exit 2 with a one-line message if the folder is not a directory. This command is local and may print names.
- [ ] `calcview serve [--port N] [--db PATH]` → `uvicorn.run(create_app(db_path), host=HOST, port=port)`. `create_app(db_path: Path | None = None)`; module-level `app = create_app()` stays for the existing tests and the launch config, using `CALCVIEW_DB` env or `./calcview.db`. The app opens the store per request (sqlite connections are not shared across threads).
- [ ] Default db path `./calcview.db`. README and CLAUDE.md gain the import/serve commands.
- [ ] Tests: `main(["import", ...])` on the fixture folder into tmp db → counts; non-dir → 2; `create_app(tmp_db)` serves `/health`; loopback-only test still passes.
- [ ] Commit: `feat(m3): calcview import and serve --db`.

---

## Task 6: Plain-English node descriptions

**Files:** `app/generators/__init__.py`, `app/generators/describe.py`, `tests/test_describe.py`.

Generators read only IR. Interface:
```python
@dataclass(frozen=True)
class NodeDescription:
    node_id: str
    headline: str          # one sentence
    details: list[str]     # extra sentences: filters, calculated columns, constants, flags

def render_expression(expr: Expression | None) -> str
def describe_node(result: ParseResult, node: Node, estate: Estate | None = None) -> NodeDescription
def describe_view(result: ParseResult, estate: Estate | None = None) -> list[NodeDescription]  # in data-flow (topological) order, output last
```
Rules (wording is tested exactly — keep it stable):
- Expressions: `if(c, a, b)` → `if <c> then <a> else <b>`; binary ops keep their symbols with spaces; n-ary binary nodes are a left fold (`a - b - c`); `and`/`or`/`not` lower case; columns bare (`AMT_1`); strings in single quotes; params `input parameter IP_RATE`; other calls `name(arg, arg)` verbatim (lower-case name as stored). No AST (parse failed or SQL) → `` `<raw text>` (not parsed) ``. `None` → `""`.
- Inputs are named by the producing node's name (`Projection_1`, `TABLE_A`). Lists of node names in prose read `A and B` / `A, B and C`; lists of column names stay comma lists (`AMT_1, CC_1`).
- Counts agree with their number: `1 column` / `N columns`, `1 attribute`, `1 measure`.
- Grouping: an operand that binds looser than its operator keeps its parentheses (`(A + B) * C`); at equal strength only the first operand stays bare (`A - B - C`, but `A - (B - C)`); comparisons never chain; an `and` inside `or` is grouped for readability (`A or (B and C)`); `not` groups a binary operand (`not (A = 1)`); unary minus groups anything but a plain value (`-(A + B)`); an `if` used as an operand is grouped (`(if A then 1 else 2) + 3`).
- datasource: table → `Reads table SCHEMA_1.TABLE_A.`; calc view → `Reads calculation view SOURCE_VIEW_01.` plus, when the estate resolves it, detail `Defined in this project.`, else detail `Not in this project (external).`; table function → `Reads table function <name>.`; unknown → `Reads source <name> (unknown kind).`
- projection: `Takes N columns from <input>.` (N counts non-calculated columns; `1 column`)
- join: `<Join phrase> of <left> and <right> on COL_1[, COL_2] (<cardinality phrase>).` Join phrases: inner → `Inner join`, leftOuter → `Left outer join`, rightOuter → `Right outer join`, fullOuter → `Full outer join`, referential → `Referential join`, textTable → `Text join`, anything else → `Join (<raw type>)`. Cardinality: `CN_1` many-to-one, `C1_1` one-to-one, `C1_N` one-to-many, `CN_N` many-to-many, missing → omit the parenthesis. Unknown cardinality → `(cardinality <raw>)`. No join columns → omit ` on …` and add detail `No join columns were found.` No join spec → `Join (unknown) of <every input>.` Special joins add detail `HANA-specific join semantics: review before migrating.`
- union: `Stacks rows from <a> and <b>.` (`<a>, <b> and <c>` for three); each constant mapping adds detail `COL_5 is 'SRC_A' for rows from Join_1.` / `CC_1 is empty (null) for rows from TABLE_B.`
- aggregation: `Sums AMT_1, CC_1 by COL_1, COL_3, COL_5.` Aggregation verbs: sum Sums, min Takes the minimum of, max Takes the maximum of, count Counts, avg Averages; several kinds → separate clauses joined with `; ` before ` by …`. No measures → `Groups by …`.
- rank: `Ranks rows (partition and order logic not yet modelled).`
- output: `Publishes N attributes and M measures as the view's output.` (`1 attribute`, `1 measure`); CUBE adds detail `CUBE: totals are computed at query time for whatever columns the consumer asks for.`
- opaque headline: `Does something the parser does not recognise[, reading <a> and <b>].`; script_statement headline: `Runs a SQL script statement.`
- opaque / script_statement / not understood (any type): append detail `Not fully understood by the parser: see warnings and raw XML.`
- Every node: each filter adds `Keeps rows where <expr>.`; each calculated column adds `Adds <name> = <expr>.`
- Fixture expectations to pin in tests (from `GENERIC_TAX_REPORTING_CUBE`): Projection_1 headline `Takes 4 columns from SOURCE_VIEW_01.`, details include `Keeps rows where COL_3 = input parameter IP_FISCAL_YEAR.` (or the exact rendering the AST gives — check the AST for the quoted `'$$IP_FISCAL_YEAR$$'` placeholder: it parses as `param`) and `Adds CC_1 = if COL_2 = 'X' then AMT_1 else 0.`; Join_1 `Left outer join of Projection_1 and TABLE_A on COL_1 (many-to-one).`; Union_1 constants; Aggregation_1 `Sums AMT_1, CC_1 by COL_1, COL_3, COL_5.` and `Adds CC_2 = AMT_1 * input parameter IP_RATE.`; Semantics `Publishes 3 attributes and 4 measures as the view's output.` plus the CUBE detail and `Adds CM_1 = AMT_1 - CC_1.`. Also the malformed `bad_expression` fixture shows `(not parsed)`.
- [ ] Commit: `feat(m5): plain-English node descriptions`.

## Task 7: Views list and view graph

**Files:** `app/generators/lineage.py`, `app/web/routes.py`, `app/main.py`, templates `base.html`, `index.html` (import form), `views.html`, `view.html`, `_node_panel.html`, `app/web/static/app/viewgraph.js`, `pyproject.toml` package-data, `tests/test_web_views.py`, `tests/test_vendor.py` (extend the remote-URL guard to `static/app/*.js`).

- `view_elements(result, descriptions) -> list[dict]` Cytoscape elements, deterministic order: node data `{id, label, node_type, understood, warning_count, headline}`; edge data `{id: "<from>-><to>", source, target, column_count}`.
- Routes:
  - `GET /` → no project in the store: import form (folder path text field) and a short how-to; otherwise redirect 303 to `/views`.
  - `POST /import` (form field `folder`) → runs `import_folder`; on a non-directory path re-renders the form with an error (400); else 303 to `/views`. A "Re-import" button on `/views` posts the stored `source_folder`.
  - `GET /views` → table: name (link), package, view type, data category, nodes, coverage %, parse status, warnings, depends on (internal count), used by (internal count). Server-side `?sort=<column>` and `?q=<substring>`.
  - `GET /views/{view_id:path}` (id percent-encoded; ids may contain `/`, `.`, `:`) → tabs (plain links with `?tab=`; no JS needed): **Graph** (canvas + side panel), **Steps** (ordered plain-English list), **Columns** (per node), **Warnings**, **Raw XML** (per node `raw`, escaped, in `<pre>`), **Notes** (Task 8). Header: view facts and links to upstream/downstream views. 404 for an unknown id.
  - `GET /node?view=<view id>&node=<node id>` → `_node_panel.html` fragment (headline, details, columns, warnings for that node, raw XML) for htmx. Errors come back as a visible fragment with status 200 so htmx swaps them in.
- `viewgraph.js`: reads the elements JSON from `<script type="application/json" id="graph-data">`, builds Cytoscape with `cytoscape-dagre`, `rankDir: 'BT'` (output at the top, like the HANA modeller — record as a ruling), colours by `node_type`, dashed red border for `understood == false`, shows a warning count badge in the label. Tap a node → `htmx.ajax('GET', <panel url>, '#node-panel')`. Double-tap a datasource whose calc view resolves internally → navigate to that view. Fit to screen on load. No external URLs.
- [ ] Tests (TestClient with a tmp db imported from `fixtures/synthetic/graphical`): `/` redirects after import and shows the form before; `/views` lists both views with coverage and dependency counts; sort/filter; view page 200 and contains the embedded JSON with 8 nodes and 7 edges for the consumer; Steps tab shows the Task 6 sentences in order; node panel fragment; unknown view 404; HTML-escaping of a hostile view id (inline XML fixture in tmp with `id="&lt;script&gt;"`); remote-URL guard covers app JS.
- [ ] Commit: `feat(m5): views list and view graph with node panel`.

## Task 8: Notes and sign-off

**Files:** `app/web/routes.py`, `view.html` Notes tab, `_node_panel.html`, `tests/test_web_notes.py`.

- [ ] Notes tab: purpose, owner, sign-off status (draft/reviewed/approved), notes; `POST /notes?view=<view id>` saves (clears stale) and redirects back to the tab. A stale annotation shows a visible "Stale: <reason>" badge on the tab and in the views list.
- [ ] Node panel: a small notes form per node (`POST /node/notes?view=<view id>&node=<node id>`, htmx swap of the panel).
- [ ] Views list gains a sign-off column.
- [ ] Tests: save and reload; invalid status rejected (422/400); re-import of a changed fixture shows the stale badge; saving clears it; node note round trip.
- [ ] Commit: `feat(m5): view and node notes with sign-off and stale badges`.

---

## Task 9: Audit CLI (M4)

**Files:** `app/parsers/audit_scan.py`, `app/audit.py`, `app/cli.py`, `fixtures/synthetic/audit/LEAKCANARY_VIEW.calculationview` (+ golden IR, since the golden test globs every fixture), `tests/test_audit.py`.

`calcview audit <folder> [--format text|json]` prints **structure only**. XML walking lives in `app/parsers/audit_scan.py` (`scan_structure(data: bytes) -> FileStructure`, never raises); aggregation and formatting in `app/audit.py`. Report:
- files: total, by suffix, parse status counts, warning-code counts, coverage percentages as a sorted list and a histogram (0, 1–49, 50–89, 90–99, 100).
- namespaces: URI → count (namespace URIs, never prefixes' documents).
- elements: local tag → count; parent tag → child tag → count.
- attributes: tag → attribute local name → count.
- `xsi:type` values (prefix:local as written) → count.
- enumerated attribute values, for a fixed allow-list only, and only when the value matches `^[A-Za-z][A-Za-z0-9_]{0,39}$` (else counted under `<other>`): root `dataCategory`, `schemaVersion` (allow digits and dots for this one), `calculationScenarioType`, `outputViewType`, `executionSemantic`, `applyPrivilegeType`, `visibility`; `DataSource@type`; `calculationView@joinType`, `@cardinality`, `@joinOrder`, `@filterExpressionLanguage`; `viewAttribute@aggregationType`; `measure@aggregationType`, `@engineAggregation`, `@measureType`; `calculatedViewAttribute@expressionLanguage`, `@datatype`; `variableProperties@datatype`; `valueDomain@type`; `selection@type`; `input@emptyUnionBehavior`.
- `resourceUri` shapes: the URI with every segment replaced by its role, e.g. `/<pkg>/calculationviews/<name>` → count (answers the open matching question without names).
- column-engine function names → count: from parsed ASTs (`call` nodes), plus, for formula/filter text that failed to parse, a regex over the text **after** removing string literals, double-quoted identifiers and `$$…$$` placeholders: `([A-Za-z_][A-Za-z0-9_]*)\s*\(`, lower-cased.
- scripted views: count only (statement kinds arrive with M2).
- UNKNOWN_ELEMENT by parent tag and child tag (computed from the XML walk against the parser's known sets, not from warning messages).
Never printed: file names, paths, ids, names, column names, descriptions, literals, expressions, warning messages, parameter defaults.

- [ ] Leak test: `LEAKCANARY_VIEW.calculationview` uses sentinel names everywhere a business string can live (root id, descriptions, data source ids, schema and table names, `resourceUri` segments, column ids, formulas with string literals, filter text, parameter ids and default values, a package directory `leakcanary_pkg` in a tmp copy, the file name). Run the audit (both formats) over a tmp folder holding it plus every other fixture. Assert `leakcanary` (case-insensitive) is absent, and that no `id`/`name`/`columnObjectName`/`schemaName`/`defaultDescription`/`defaultValue` value, `resourceUri` segment or text node of any fixture (≥ 3 characters, excluding the allow-listed enum values and known XML tag names) appears in the output.
- [ ] Other tests: counts on the main fixture (e.g. `xsi:type` `Calculation:JoinView` = 1, `DataSource@type` values), function names `if` found, resourceUri shape, garbage file counted as failed, never raises.
- [ ] README gains a "Running the audit at work" section: what it prints, what it never prints, how to bring the report back.
- [ ] Commit: `feat(m4): structure-only audit CLI with leak test`.

---

## Task 10: Estate map (M9a)

**Files:** `app/generators/lineage.py`, `app/web/routes.py`, `templates/estate.html`, `app/web/static/app/estate.js`, `fixtures/synthetic/estate/graphical.estate.mmd`, `tests/test_estate.py`.

- `estate_elements(estate, summaries, annotations) -> list[dict]`: view nodes `{id, label, kind: "view", view_type, data_category, parse_status, coverage_pct, signoff, node_count, warning_count, in_cycle}`; leaf nodes `{id, label, kind: leaf kind}`; edges producer → consumer `{id, source, target, internal}`. Deterministic.
- `estate_mermaid(estate, include_leaves=True) -> str` and `view_mermaid(result) -> str`: `flowchart LR` (`BT` for a view, matching the canvas); node ids sanitised to `n<index>` with a stable mapping; labels quoted with `"` escaped as `#quot;`; leaf sources shaped `[( )]`, views `[ ]`, cycle edges annotated. Golden file for the fixture estate.
- Routes: `GET /estate` (canvas, colour-by selector: parse status / view type / data category / sign-off; toggle leaf sources; search box; deploy order list; cycle errors shown at the top), `GET /estate.mmd` and `GET /view.mmd?view=<view id>` (`text/plain`, `Content-Disposition: attachment`), nav link from every page.
- `estate.js`: dagre `rankDir: 'LR'`; tap a view → highlight its upstream (predecessors) and downstream (successors), dim the rest; double-tap → open the view page; PNG export via `cy.png({full: true, scale: 2})` into a download link (no network). Legend for the current colour mode.
- [ ] Tests: estate elements for the fixture folder (2 views, 3 leaf tables, 4 edges, 1 internal); cycle folder marks `in_cycle`; Mermaid golden; `.mmd` endpoints return attachments; `/estate` 200 with embedded JSON; remote-URL guard covers `estate.js`.
- [ ] Commit: `feat(m9a): estate map with PNG and Mermaid export`.

---

## Exit checklist

- [ ] `pytest -q` green on a clean venv installed with `-c constraints.txt`.
- [ ] `calcview import fixtures/synthetic/graphical --db /tmp/x.db && calcview serve --db /tmp/x.db` shows both views, the consumer's graph, plain-English steps, notes, and the estate map with one internal edge; PNG and Mermaid export work with the network off.
- [ ] `calcview audit fixtures/synthetic` prints structure only; leak test green.
- [ ] Golden IR files: only new fixtures added; existing ones unchanged.
- [ ] Findings file updated with rulings and deferred minors.
- [ ] Ask Jacob to run `calcview audit` on the real folder and bring the report back (answers the M1 gate and the matching-rule question).
