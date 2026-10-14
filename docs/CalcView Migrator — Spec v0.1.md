# CalcView Migrator — Spec v0.1

Oct 13, 2026 · @Jacob

## Overview

CalcView Migrator is a local Python web app that parses exported HANA calculation view XML into one dependency graph. From that graph it generates a business-logic spec, a lineage and process map, and target code for Databricks SQL or Datasphere. The first use case is the tax transparency reporting solution, about 50–60 views. The tool is built to be reused on later BW/HANA migrations.

### Goals

1. Parse graphical and scripted calculation views into a single intermediate representation (IR).
2. Resolve view-to-view dependencies into one estate-wide graph.
3. Generate a plain-English business-logic spec per view, written for SME sign-off.
4. Render lineage at three levels: estate (view to view), view (node to node) and column (output field back to its source fields).
5. Capture and apply source remapping from legacy objects and fields to S/4HANA or Datasphere equivalents.
6. Recommend a target platform (Datasphere or Databricks) per view; the user makes the final call.
7. Generate Databricks SQL views (or SQL table functions) and Datasphere SQL, in dependency order.

### Non-goals for v1

- No live connections to HANA, Datasphere or Databricks. The app reads files and writes files.
- No execution or deployment of generated code.
- No reconciliation test generation. Parallel-run reconciliation stays in the migration plan, outside the app.
- No multi-user features or authentication.

### Constraints

| Constraint | Consequence for the design |
| --- | --- |
| Runs locally on a work laptop with only Python installable | No Node and no frontend build step. JS libraries are vendored as static files in the repo. |
| Work data cannot leave the work boundary | Binds to 127.0.0.1 only. No CDN calls at runtime. No telemetry. The LLM is off by default. |
| Built by Claude Code outside work, on synthetic data | The parser is built against sanitised skeleton fixtures. A structure-only audit CLI closes the loop (see Build plan). |
| LLM approval is unknown | The LLM is an optional plug-in behind an interface. Every core output is deterministic without it. |
| Remapping doc is mixed: object-level in a sheet, field-level partial | The app imports object-level mappings and provides an editor to capture field-level mappings. |

### Decisions so far

| Decision | Choice |
| --- | --- |
| Reuse | Reusable tool; tax transparency is the first project |
| Hosting | Local, single user |
| Language | Python only |
| Outputs | Logic spec, lineage/process map, target code |
| Databricks code format | Databricks SQL views |
| Target platform per view | App recommends, user decides |
| Future architecture | S/4HANA → Datasphere / Databricks |

## Architecture

The app works like a compiler. Front ends parse each view type into one graph IR. Enrichment passes add remapping and classification. Back ends generate each output from the IR. No generator ever reads XML directly, so a new input type or output format touches one module.

&#91;embedded content: pipeline · 5 stages\]

The mapping sheet feeds enrichment, and the LLM is a dashed, optional input to generators only.

### Stack

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.11+ | Only runtime available at work. Version to confirm (Open questions). |
| Web | FastAPI + Jinja2 templates + htmx | Server-rendered; no JS build step |
| Graph rendering | Cytoscape.js + dagre layout, vendored into `static/vendor/` | Handles 50–500 nodes interactively; no npm needed |
| XML | lxml | Namespaces, XPath, line numbers for error reporting |
| SQL parsing | sqlglot, subject to a spike (M2) | Parses and transpiles SQL; its HANA SQLScript coverage is unverified |
| Graph algorithms | networkx | Topological sort, cycle detection, ancestor queries for lineage |
| IR models | Pydantic v2 | Typed IR with JSON round-trip for golden tests |
| Persistence | SQLite via the standard library `sqlite3` | One file per project; no server |
| Spreadsheet import | openpyxl | Reads the object-level mapping sheet |
| Tests | pytest | Golden-file tests against fixtures |

### Repo layout

```
calcview-migrator/
  CLAUDE.md                 # build rules for Claude Code (see Build plan)
  pyproject.toml
  app/
    main.py                 # FastAPI app, binds 127.0.0.1
    cli.py                  # import, audit, export commands
    ingest/                 # folder scan, file hashing, re-import diff
    parsers/
      graphical.py          # Calculation:* node views
      scripted.py           # SqlScriptView wrapper
      sqlscript_split.py    # statement splitter for SQLScript
      expressions.py        # column-engine + SQL expression parsing
    ir/
      models.py             # Pydantic IR
      graph.py              # networkx build, lineage queries
      store.py              # SQLite persistence
    enrich/
      deps.py               # cross-view dependency resolution
      remap.py              # remapping application
      classify.py           # complexity signals
      recommend.py          # target platform rules
    generators/
      spec_md.py            # business-logic spec
      lineage.py            # graph JSON for Cytoscape
      sql_databricks.py
      sql_datasphere.py
      expr_translate.py     # function map, column-engine → SQL
    llm/
      provider.py           # interface + NullProvider
    web/
      templates/
      static/vendor/        # cytoscape, dagre, htmx
  config/
    recommend.yaml          # target rule weights
    naming.yaml             # catalog/schema naming conventions
  fixtures/synthetic/       # sanitised skeletons + golden IR JSON
  tests/
```

## Intermediate representation

The IR is the product; every output is a view of it. It must express both graphical and scripted views with the same entities, so generators never branch on view type.

### Entities

| Entity | Key fields | Notes |
| --- | --- | --- |
| Project | id, name, source\_label | One per migration (e.g. tax transparency) |
| View | id, name, package\_path, view\_type (graphical / scripted), data\_category (CUBE / DIMENSION / DEFAULT), file\_hash, parse\_status, coverage\_pct | coverage\_pct = share of nodes fully understood |
| Node | id, view\_id, node\_type, name, raw | Types: datasource, projection, join, aggregation, union, rank, script\_statement, opaque, output. `raw` keeps the original XML or SQL fragment. |
| Column | id, node\_id, name, datatype, length, scale, kind (attribute / measure), aggregation, expression, expression\_lang (column\_engine / sql) | Calculated columns carry `expression` |
| Edge | from\_node, to\_node, column\_map\[\] | Each column\_map item maps a source column (or a constant, for unions) to a target column |
| JoinSpec | node\_id, join\_type, cardinality, conditions\[\] | join\_type includes referential and text joins, flagged for special semantics |
| Filter | node\_id, expression, expression\_lang |  |
| Parameter | view\_id, name, kind (input\_parameter / variable), datatype, default, mandatory, used\_in\[\] | `used_in` records whether it only filters or also feeds calculations; this drives codegen |
| DataSource | id, kind (table / calc\_view / table\_function / cds / unknown), schema, name, resolved\_view\_id | Internal sources resolve to another View; the rest become leaf sources for remapping |
| ColumnLineage | output\_column\_id, source\_column\_ids\[\], path\_node\_ids\[\], transform\_summary | Derived, never parsed |
| Warning | view\_id, node\_id, code, message, severity | Unknown element, unparsed statement, unsupported function, cycle |
| Annotation | view\_id, purpose\_text, owner, signoff\_status (draft / reviewed / approved), notes | User-entered; survives re-import |
| TargetDecision | view\_id, recommended, chosen, reasons\[\], override\_rationale |  |

### Identity and re-import

- IDs are deterministic: `view_name/node_name/column_name`. The same file re-imported gives the same IDs, so annotations stay attached.
- On re-import, an unchanged file\_hash is skipped. A changed file is re-parsed, and any annotation or sign-off on a changed node is marked stale, not deleted.

### Expressions

Calculation views use two expression languages: the legacy column engine (`if()`, `leftstr()`, `isnull()`) and SQL. The IR stores the raw text plus the language tag. It also stores a parsed AST when parsing succeeds, and a warning when it fails. An expression that can't be parsed never blocks the rest of the view.

## Parser

The parser has one rule above all: never crash on a file, and always say what it didn't understand. Every view yields a ParseResult with nodes, warnings and a coverage percentage, even if most of it is opaque.

### Detection

Read the root and each `calculationView` element's `xsi:type`. `Calculation:SqlScriptView` routes to the scripted front end. `ProjectionView`, `JoinView`, `AggregationView`, `UnionView` and `RankView` route to the graphical front end. Any other type becomes an opaque node with a warning. These element names come from general HANA knowledge and must be confirmed against the skeleton fixtures before M1 is accepted.

### Front end A: graphical

1. Parse `dataSources` into DataSource entities.
2. Parse each `calculationView` into a Node, with its input edges, column mappings, filters, calculated columns and join specs.
3. Parse the output layer (`logicalModel` or the semantics node) into the output node: attributes, measures, calculated and restricted columns.
4. Parse input parameters and variables, and record where each is referenced.
5. Preserve the raw XML fragment on every node for display and debugging.

### Front end B: scripted

1. Extract the SQLScript text from the definition block.
2. Split it into statements with a tokenizer that respects string literals, comments, parentheses and `BEGIN … END` blocks. Do not split on a bare semicolon regex.
3. Classify each statement:
   - Table variable assignment (`lt_x = SELECT …`) becomes a node, with an edge from every `:var` it reads.
   - The final `var_out = …` assignment becomes the output node.
   - Scalar assignments and `DECLARE` become node attributes.
   - Control flow (`IF`, `FOR`, `WHILE`, cursors, dynamic SQL) becomes an opaque node flagged for manual review.
4. Parse each SELECT into joins, filters, projections, aggregations and source references, using sqlglot if the M2 spike passes.
5. Fallback when the SQL parser fails: extract FROM and JOIN targets by regex so the graph stays connected, keep the statement as an opaque node, and lower coverage.

### Dependency resolution

- A DataSource whose name matches an imported view becomes an internal edge to that view.
- The estate graph is topologically sorted. That order is the deploy order.
- Cycles are reported as errors with the views involved. Unresolved sources are listed as leaf sources and feed remapping.

### Fixture contract

Claude Code never sees real files, so fixtures carry the parser's accuracy. Jacob supplies one or two sanitised skeletons that keep real elements, attributes and nesting, with names, columns and logic replaced by dummies (`TABLE_A`, `COL_1`). From those, the build produces:

- At least one graphical fixture with a join, an aggregation, a union, a calculated column, a filter and an input parameter.
- At least one scripted fixture with two or more table variables, a join, an aggregation and one control-flow block.
- One fixture pair where a view consumes another view.
- Malformed variants: truncated file, unknown `xsi:type`, unparseable expression.
- A golden IR JSON file for each fixture, checked in and diffed by tests.

## Source remapping

Remapping is the semantic core of the migration: legacy sources won't exist after S/4HANA replaces them. Column lineage keeps the effort bounded. The app asks you to map only the legacy columns that actually reach an output, not every column of every legacy table.

### Inputs

- **Object-level import.** CSV or XLSX. A column-picker step lets you choose which sheet columns hold the legacy object, target object, target system and notes, so the sheet's layout doesn't have to change.
- **Field-level capture.** In-app editor, one leaf source at a time. It lists only the used columns, derived from lineage.

### Field mapping states

| State | Meaning | Effect on codegen |
| --- | --- | --- |
| Unmapped | Not yet reviewed | Placeholder comment `/* UNMAPPED: SRC.COL */`; the view is marked not ready |
| Mapped | Target column chosen | Substituted directly |
| Mapped with transform | Target differs in semantics (sign, unit, type) | The transform expression wraps the target column |
| No equivalent | Field doesn't exist in S/4 | Flagged as a blocking issue in the spec |
| Not needed | Used only by logic being retired | Logic using it is marked for removal in the spec |

### Target naming

Mapping targets reference the objects the generated code will actually read. For Databricks, that is the Datasphere tables mirrored into Databricks, under the catalog and schema set in `naming.yaml`. For Datasphere, it is the Datasphere object name.

### Round trip

The full mapping (object and field level) exports to CSV and re-imports. The sheet can then stay the system of record if the team prefers to maintain it outside the app.

## Generators

Every generator is deterministic and reads only the IR plus enrichment. Anything it can't translate is written out as a visible marker, never dropped silently.

### Business-logic spec

Output: one Markdown file per view, plus a roll-up per output view that walks its full upstream chain. Sections:

1. Purpose (user-entered annotation)
2. Inputs: sources with remapped names, plus parameters
3. Logic, step by step in plain English, rendered from templates per node type, e.g. "Left-joins General Ledger to Company Code on BUKRS", "Keeps rows where fiscal year equals the input parameter", "Sums AMOUNT by company code and period"
4. Calculated fields: name, plain-English rule, original expression
5. Outputs: columns with type and meaning
6. Open issues: parse warnings, unmapped fields, opaque blocks
7. Sign-off: owner, status, date

The templates are the readability lever. They are listed in `generators/spec_md.py` and tested against fixtures so the wording stays stable between runs.

### Lineage and process map

| Level | Shows | Use |
| --- | --- | --- |
| Estate | Views and leaf sources, with dependency edges | The process map for business stakeholders; nodes coloured by target decision and sign-off status |
| View | Nodes inside one view | Debugging and walkthroughs |
| Column | Selecting an output column highlights its path back to its source fields | Answering "where does this number come from" |

Rendered with Cytoscape.js. Exports: PNG from the canvas, and Mermaid text for pasting into other documents.

### Target code: Databricks SQL

- Each view becomes `CREATE OR REPLACE VIEW <catalog>.<schema>.<name> AS WITH … SELECT …`. Each IR node is one CTE, in topological order, named after the original node so the spec and the code line up.
- Files are numbered by deploy order, with a `manifest.json` listing the order.
- Every generated file is syntax-checked with sqlglot's Databricks dialect in tests.

Three semantic traps need explicit rules:

1. **Dynamic aggregation.** A CUBE calculation view aggregates at query time, by whatever columns the consumer asks for. A SQL view with `GROUP BY` fixes the grain. Rule: emit the final output at the grain of all its attributes, with measures summed. Then document in the spec that roll-up moves to the consumer (Power BI or a semantic layer). If a measure isn't additive (ratios, distinct counts, exception aggregation), flag it as blocking. Its rollup must be redesigned.
2. **Input parameters.** Databricks views take no parameters. If a parameter only filters, drop it and document that consumers filter. If it feeds a calculation, generate a SQL table function (`CREATE FUNCTION … RETURNS TABLE`) instead of a view.
3. **Column-engine functions.** `expr_translate.py` holds a function map, for example `if` → `CASE WHEN`, `isnull` → `IS NULL`, `leftstr` → `LEFT`, `midstr` → `SUBSTRING`, `daysbetween` → `DATEDIFF`. An unmapped function emits `/* TODO: <original expression> */` and marks the view not ready. The map grows as the audit finds functions.

Special HANA semantics are flagged rather than translated: currency and unit conversion, hierarchies, referential and text joins, and rank nodes with partition logic.

### Target code: Datasphere SQL

Datasphere SQL views use HANA SQL, so this generator is closer to the source. It emits SQL view text for the Datasphere SQL view editor, with remapped sources, and keeps HANA functions as they are. Whether Datasphere views support input parameters in the same way needs checking before this generator's parameter handling is fixed.

### Target recommendation

A rules engine scores each view. Weights live in `recommend.yaml` and are expected to be tuned. The default rules below are a starting heuristic, not an established standard.

| Signal | Leans |
| --- | --- |
| Scripted, procedural, or many opaque nodes | Databricks |
| Non-SAP sources, or feeds ML or classification work | Databricks |
| Deep dependency chain or high node count | Databricks |
| Simple projection, join or aggregation over S/4 data only | Datasphere |
| Needs SAP semantics (currency conversion, hierarchies) | Datasphere |
| SME-maintained, or consumed in SAC | Datasphere |

The UI shows the recommendation, its reasons and the score. Your choice and override rationale are stored in TargetDecision.

One cross-platform rule: if a Databricks view depends on a Datasphere view, the generator must reference the mirrored object and flag the cross-platform dependency.

## UI

The UI is a working console, not a showcase: dense tables, a graph canvas and plain forms. It is server-rendered with htmx for partial updates. Every page works without an LLM.

| Page | Contents | Key actions |
| --- | --- | --- |
| Projects | Project list | Create project; pick an XML folder; re-import |
| Views | Table: name, type, node count, coverage %, unmapped fields, recommended and chosen target, sign-off status, readiness | Sort and filter; click through to a view |
| View detail | Tabs: Graph · Logic spec · Columns and lineage · Code (Databricks or Datasphere) · Warnings · Raw XML · Notes | Edit purpose and notes; set sign-off status; choose target with rationale |
| Estate map | Whole dependency graph, coloured by target or status | Click a node to open the view; export PNG or Mermaid |
| Remapping | Leaf sources with mapped-field counts; per-source field editor | Import sheet; edit field mappings; export CSV |
| Export | Choose views and outputs | Download a zip of spec Markdown, SQL files, manifest and mapping CSV |

Readiness is a computed badge per view: Ready, Blocked (with a reason) or Needs review. A view is Ready only when it has no unmapped fields, no TODO markers, a chosen target and an approved spec.

## LLM plug-in

The LLM is optional, off by default, and never the source of truth. It drafts; you accept.

- **Interface:** `LLMProvider.complete(prompt, context) -> str`. Implementations are `NullProvider` (the default, which hides LLM buttons), plus stubs for Azure OpenAI or Foundry and Databricks model serving. All are configured by environment variables.
- **Uses:**
  - a narrative summary of a view's logic
  - a first-draft translation of opaque procedural blocks
  - suggested translations for column-engine functions missing from the function map
- **Governance:** before any call, the UI shows the exact payload that will be sent. Only IR-derived text is sent, never whole files.
- **Labelling:** LLM output is stored separately, labelled "AI draft", and never overwrites deterministic output. Accepting a draft copies it into the user's notes, or into a manual override for that node's code, with attribution.

## Build plan

Build the parser and IR first and the UI last. Everything depends on the IR, and an IR proven by golden tests is what makes the rest cheap.

| # | Milestone | Acceptance criteria |
| --- | --- | --- |
| M0 | Skeleton | Repo layout as specified; `pip install -e .` and `calcview serve` start the app on 127.0.0.1; vendored JS loads offline; pytest runs |
| M1 | Graphical parser + IR | All graphical fixtures match golden IR JSON; malformed fixtures produce warnings, not exceptions |
| M2 | Scripted parser | sqlglot spike written up in `docs/decisions/` (keep, patch or replace); scripted fixtures match golden IR; control flow becomes opaque nodes |
| M3 | Dependencies + persistence | Cross-view fixture resolves; topological order correct; cycle fixture reports an error; re-import keeps annotations |
| M4 | Audit CLI | `calcview audit <folder>` emits a structure-only report (see below); a test proves no names or values leak |
| M5 | Views list + view graph | Views page and view-level graph render from the store |
| M6 | Spec generator | Spec Markdown for each fixture matches golden output |
| M7 | Remapping | Sheet import with column picker; field editor; CSV round-trip is lossless |
| M8 | Code generators | Databricks and Datasphere SQL match golden files; every Databricks file passes sqlglot syntax validation; TODO and UNMAPPED markers appear where expected |
| M9 | Lineage + estate map + recommender | Column lineage correct on fixtures; estate map exports PNG and Mermaid; recommendations reproducible from `recommend.yaml` |
| M10 | LLM plug-in | NullProvider default; payload preview shown; drafts stored separately |

### The audit loop

The build happens outside the work boundary, so the app needs a safe way to report back what it met at work. `calcview audit <folder>` prints only structural facts:

- counts of each element tag, attribute name and `xsi:type` value
- names of column-engine functions
- SQLScript statement kinds
- parse failure codes and coverage percentages

It prints no object names, column names, literals or expressions. You review the report, bring it back here, and new fixtures and function mappings are added. This is the main way the parser hardens against real files.

### CLAUDE.md rules for the build

- Never read from or write to the network at runtime. Vendor every JS dependency.
- Parsers never raise on input files. Every failure becomes a warning with a code.
- Generators read only the IR. No XML access outside `parsers/`.
- Every IR change updates the golden files in the same commit, with a note on why.
- Untranslatable logic produces a visible marker, never silent omission.
- Keep the audit CLI free of business content. Its leak test must pass.

## Open questions

Items marked "blocks" must be answered before the named milestone starts.

- [ ] Sanitised skeletons: one graphical and one scripted file, structure only (blocks M1)
- [ ] View type mix: result of the `xsi:type` grep across the folder (blocks M1)
- [ ] Python version on the work laptop, and whether pip reaches PyPI or an internal mirror (blocks M0)
- [ ] Do the views use table functions, procedures, hierarchies, currency conversion, restricted columns or rank nodes? (blocks M2 scope)
- [ ] Who consumes the outputs today, Power BI via Fabric or SAC? This decides where dynamic aggregation moves to (blocks M8).
- [ ] Databricks catalog and schema naming conventions, and the names of the mirrored Datasphere tables (blocks M8)
- [ ] Do Datasphere views support input parameters the way calculation views do? (blocks the Datasphere generator)
- [ ] Who signs off each business-logic spec: a tax SME, the BW report owner, or you? (shapes sign-off states)
- [ ] LLM approval route and endpoint, if any (blocks M10 only)
