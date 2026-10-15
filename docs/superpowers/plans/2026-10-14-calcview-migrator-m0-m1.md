# CalcView Migrator — M0 + M1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the CalcView Migrator skeleton (M0) and a graphical calculation-view parser that turns `Calculation:scenario` XML into a typed, golden-tested IR without ever raising on an input file (M1).

**Architecture:** A compiler-style pipeline. M1 builds only the front end: `app/parsers/dispatch.py` loads XML safely and routes the file to `app/parsers/graphical.py`. That module walks the scenario element by element and emits Pydantic IR (`app/ir/models.py`). Column-engine expressions get a small recursive-descent parser (`app/parsers/expressions.py`) that fails cleanly. Every failure becomes an `IRWarning` with a code, never an exception.

**Tech Stack:** Python ≥ 3.11, FastAPI + Jinja2 + uvicorn, lxml, Pydantic v2, pytest + httpx (TestClient). Vendored JS: htmx 1.9.12, cytoscape 3.30.2, dagre 0.8.5, cytoscape-dagre 2.5.0.

**Source spec:** `docs/CalcView Migrator — Spec v0.1.md`

## Global Constraints

- Python floor is 3.11 (`requires-python = ">=3.11"`). Do not use syntax or stdlib APIs newer than 3.11. The dev Mac has 3.13/3.14, and the work laptop's version is still unconfirmed.
- Server binds `127.0.0.1` only, with no `--host` option. There are no CDN calls at runtime and no telemetry.
- JS libraries are vendored into `app/web/static/vendor/`. No Node, no npm, no build step.
- Parsers never raise on input files. Every failure becomes a warning with a code.
- Generators read only the IR. XML is never accessed outside `app/parsers/`.
- Every IR change updates the golden files in the same commit, with a note on why.
- Untranslatable or unrecognised content produces a visible marker or warning, never silent omission.
- IDs are deterministic: `view_name/node_name/column_name`.
- Keep runtime dependencies minimal for M0/M1: `fastapi`, `uvicorn`, `jinja2`, `lxml`, `pydantic`. Dev dependencies: `pytest`, `httpx`.

---

## Roadmap (M0–M10)

> **Superseded on 2026-10-14** by the revised order in `2026-10-14-process-view-pathway.md` (process view first: M3 → M5+ → M4 → estate map, then M2 and the SQL work). The table below is kept as the original record.

This document gives full detail for **M0 and M1** only. Each later milestone gets its own plan, written once its blockers clear. The scripted parser in particular needs a scripted skeleton before it can be planned properly.

| # | Milestone | Plan status | Blocked by |
|---|---|---|---|
| M0 | Skeleton | **This plan, Tasks 1–2** | Python version and PyPI/mirror access at work (the plan assumes 3.11 and PyPI; see Task 1 note) |
| M1 | Graphical parser + IR | **This plan, Tasks 3–9** | Partly unblocked by the graphical skeleton (below). Still open: the full `xsi:type` mix from a grep across the real folder |
| M2 | Scripted parser + sqlglot spike | Next plan | Scripted (`SqlScriptView`) sanitised skeleton |
| M3 | Dependencies + SQLite persistence + re-import | Later plan | M1. Needs a second fixture (`SOURCE_VIEW_01` itself) to build the consumer/producer pair |
| M4 | Audit CLI + leak test | Later plan. **Pull forward to right after M1 if possible**: it is how the M1 assumptions below get confirmed against real files | M1 |
| M5 | Views list + view graph UI | Later plan | M3 |
| M6 | Spec Markdown generator | Later plan | M3 |
| M7 | Remapping (sheet import, field editor, CSV round-trip) | Later plan | M3. Adds openpyxl |
| M8 | Databricks + Datasphere SQL generators | Later plan | M6 and M7. Also needs naming conventions, the output consumer (Power BI or SAC), and the Datasphere parameter behaviour |
| M9 | Column lineage + estate map + recommender | Later plan | M3 and M8. Adds networkx and PyYAML |
| M10 | LLM plug-in (NullProvider) | Later plan | LLM approval route |

**Recommended order:** M0 → M1 → M4 (audit) → M2 → M3 → M5 → M6 → M7 → M8 → M9 → M10. Running the audit right after M1 lets the real folder confirm or correct the assumptions this plan makes (see "Assumptions: confirmed and open") before more code is built on top of them.

---

## Input: the graphical skeleton (2026-10-14)

Jacob described the real file structure as follows (element order preserved):

```
<Calculation:scenario xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                      xmlns:Calculation="http://www.sap.com/ndb/BiModelCalculation.ecore"
                      xmlns:Variable="sap.com/ndb/BiModelVariable.ecore"      ← as typed
                      schemaVersion="2.3" id="GENERIC_TAX_REPORTING_CUBE">
  <origin>
  <localVariables>
  <variableMappings>
  <dataSources>
  <calculationView …>              (repeated)
    <viewAttributes>
    <calculatedViewAtrributes>     ← as typed
    <input node="#SOURCE_VIEW_01">
    <filter>
  <logicalModel>
    <attributes>
    <privateDataFoundation>
    <baseMeasures>
    <calculatedMeasures>
  <layout>
```

The synthetic fixture in Task 4 follows this structure. It uses dummy names only (`TABLE_A`, `COL_1`, `SOURCE_VIEW_01`).

### Assumptions: confirmed and open

Jacob checked a real file on 2026-10-14.

**Confirmed**
1. **`<calculationViews>` wrapper** is present. The parser also accepts unwrapped `calculationView` elements; this costs nothing, and the Task 8 test for it stays.
2. **`calculatedViewAttributes`** is the real spelling; `calculatedViewAtrributes` was a typo. An unrecognised child of `calculationView` still raises `UNKNOWN_ELEMENT`.
3. **Namespaces** carry the full `http://www.sap.com/...` URIs. The parser still never compares URIs: it matches by local name.
4. **JoinView** carries `cardinality` (e.g. `CN_1`), `joinOrder="OUTSIDE_IN"` and `joinType="leftOuter"` as attributes, followed by `<descriptions/>` and `<viewAttributes>`. `joinOrder` is not modelled in M1.
5. **`<input node=…>` refs appear both with and without `#`.** The skeleton showed `#SOURCE_VIEW_01`, while a real JoinView input showed `SOME_CUBE`. `_ref()` strips an optional `#`, and the fixture uses both forms (`Aggregation_1` reads `Union_1` without `#`).
6. **Input mappings** use `mapping xsi:type="Calculation:AttributeMapping" target=… source=…`.
7. **logicalModel attributes**: `attribute@id/@order/@attributeHierarchyActive/@displayAttribute`, a `descriptions@defaultDescription` child and `keyMapping@columnObjectName/@columnName`. `logicalModel` also has a `<descriptions/>` child.
8. **baseMeasures**: `measure@id/@order/@aggregationType/@engineAggregation/@measureType`, plus `descriptions` and `measureMapping@columnObjectName/@columnName`. `engineAggregation` is not modelled in M1. `aggregationType` is the one used.
9. **localVariables**: `variable@id/@parameter="true"` and `variableProperties@datatype/@defaultValue/@length/@mandatory`, with `valueDomain@type` and `selection@multiline/@type` children. Note the lowercase `multiline`.

**Still unconfirmed**. Check these with the audit (M4) or another snippet:
- `ConstantAttributeMapping` with `@value`/`@null` (union constants)
- `DataSource@type` values (`DATA_BASE_TABLE`, `CALCULATION_VIEW`), `columnObject@schemaName/@columnObjectName`, `resourceUri`
- `joinAttribute@name` for the join keys
- `viewAttribute@aggregationType` inside AggregationView
- `calculatedViewAttribute@datatype/@length/@scale/@expressionLanguage` and the `<formula>` child
- The `<filter>` element's text and the language attribute
- `calculatedMeasures` structure
- `variableMappings` structure (`mapping@dataSource`, `targetVariable@name`, `localVariable`)
- `calculationView@filterExpressionLanguage` as the filter-language carrier (parser also accepts `filter@expressionLanguage`)
- children of `viewAttribute` (e.g. attribute-level `filter` elements) and node-level children such as `restrictedViewAttributes` — currently UNKNOWN_ELEMENT + node not understood
- how non-parameter variables (`parameter="false"`) bind to attributes — `V_COMPANY` ends with `used_in: []` today; codegen needs this
- other root children real files may carry (e.g. `informationModelLayout`) — currently UNKNOWN_ELEMENT

### Spec deltas from the skeleton

The skeleton exposes things the spec's IR table doesn't cover. This plan implements them as listed below. Fold them into spec v0.2 when convenient. This plan does not edit the spec.

| Delta | Implementation |
|---|---|
| `<variableMappings>` maps local parameters to an upstream view's parameters | New IR entity `ParameterMapping(view_id, data_source_id, target_parameter, local_parameter, constant)`. M3 needs it to wire parameters across views. |
| `<localVariables>` holds both input parameters and variables | `Parameter.kind` comes from `variable/@parameter` (`"true"` means `input_parameter`; anything else means `variable`). |
| `<input node="#X">` references | The `#` is stripped, and the ref resolves against data sources and calculation views together. An unresolved ref raises `UNRESOLVED_INPUT` and marks the node not understood. |
| `<logicalModel>` is the output layer | It becomes a node named `Semantics` (`node_type=output`). `attributes` become attribute columns, `baseMeasures` become measure columns, and `calculatedAttributes` / `calculatedMeasures` become columns with an `expression`. The edge from the node named in `logicalModel/@id` carries the key and measure mappings. |
| `<privateDataFoundation>`, `<restrictedMeasures>`, `<localDimensions>` | When these contain only empty containers (`tableProxies`, `joins`, `layout`, `shapes`), they are silently fine. With real content, they raise a `*_DEFERRED` warning and mark the Semantics node not understood. |
| `<origin>`, `<descriptions>`, `<layout>`, `<metadata>` at the root | Known and ignored, with no warning and no effect on coverage. |
| Root attributes | `View.schema_version` is a new field taken from `@schemaVersion`. `View.data_category` comes from `@dataCategory`. |
| Data source nodes | Each `DataSource` is also a `Node(node_type=datasource)` with the same id, so edges are uniform. |
| Columns, filters and joins nest in their `Node` | The spec lists these as flat entities, which suits SQLite. The IR nests them for readability, and M3's store flattens them. Column ids still embed the node id. |
| Parameter ids | `view/@param/NAME`, so they can't collide with node names. |
| `IRWarning` | This is the spec's `Warning` entity, renamed to avoid shadowing the builtin. It adds `line` (source line number). |
| `DataSource.schema_name` | This is the spec's `schema`, renamed because `schema` shadows a Pydantic `BaseModel` attribute. |
| SQL-language expressions in graphical views | They are kept as text with an INFO `SQL_EXPR_DEFERRED` warning until the M2 sqlglot spike. |

### Warning codes introduced in M1

| Code | Severity | Raised when |
|---|---|---|
| `XML_SYNTAX` | error | File is not well-formed XML (truncated, binary, empty) |
| `NOT_A_SCENARIO` | error | Root element is not `scenario` |
| `PARSER_CRASH` | error | An internal parser bug; caught by the dispatch guard |
| `READ_ERROR` | error | File could not be read |
| `UNKNOWN_ELEMENT` | warning | Unmodelled child of the root, a `calculationView` or `logicalModel` |
| `UNKNOWN_NODE_TYPE` | warning | `calculationView` `xsi:type` not in the known set (kept as an opaque node) |
| `SCRIPTED_DEFERRED` | warning | `SqlScriptView` met before M2 (kept as an opaque node) |
| `UNKNOWN_DATASOURCE_TYPE` | warning | `DataSource/@type` not recognised |
| `UNKNOWN_MAPPING` | warning | An `input/mapping` with neither a source nor a constant |
| `UNRESOLVED_INPUT` | warning | `#ref` names nothing in the view |
| `UNRESOLVED_VARIABLE_MAPPING` | warning | A variable mapping names an unknown data source |
| `UNKNOWN_PARAMETER_REF` | warning | `$$NAME$$` or `#NAME` names no local parameter |
| `EXPR_PARSE_FAILED` | warning | A column-engine expression failed to parse |
| `JOIN_INPUT_COUNT` | warning | A join doesn't have exactly two inputs |
| `SPECIAL_JOIN` | info | Referential or text join (needs special semantics) |
| `RANK_NODE` | info | Rank node (partition logic flagged for codegen) |
| `SQL_EXPR_DEFERRED` | info | SQL-language expression stored as text |
| `MISSING_LOGICAL_MODEL` | error | No `<logicalModel>` |
| `PRIVATE_DATA_FOUNDATION_DEFERRED`, `RESTRICTED_MEASURES_DEFERRED`, `LOCAL_DIMENSIONS_DEFERRED` | warning | These blocks have real content |

`parse_status` is `failed` if no nodes were produced, `partial` if any warning or error was raised, and `ok` otherwise. `coverage_pct` is `round(100 × understood_nodes / total_nodes, 1)`.

---

## File structure (M0 + M1)

```
pyproject.toml                      # package, deps, `calcview` entry point, pytest config
CLAUDE.md                           # build rules for Claude Code
.gitattributes                      # + keep fixture bytes exact (hashes, golden raw XML)
app/
  __init__.py
  main.py                           # FastAPI app factory; HOST = "127.0.0.1"
  cli.py                            # `calcview serve` (import/audit/export come later)
  ir/
    __init__.py
    models.py                       # Pydantic IR + make_id
  parsers/
    __init__.py
    xmlutil.py                      # safe load, local-name helpers, xsi:type resolution
    expressions.py                  # column-engine tokenizer + recursive-descent parser
    graphical.py                    # Calculation:scenario → ParseResult
    dispatch.py                     # parse_bytes/parse_file: never raise, route, finalize
  web/
    templates/index.html
    static/vendor/                  # htmx, cytoscape, dagre, cytoscape-dagre + VENDOR.md
fixtures/synthetic/
  graphical/GENERIC_TAX_REPORTING_CUBE.calculationview (+ .ir.json golden)
  malformed/truncated.calculationview        (+ .ir.json)
  malformed/unknown_type.calculationview     (+ .ir.json)
  malformed/bad_expression.calculationview   (+ .ir.json)
tests/                              # flat; no __init__.py, so `from helpers import …` works
  conftest.py  helpers.py
  test_app.py  test_vendor.py  test_models.py  test_xmlutil.py  test_expressions.py
  test_graphical_metadata.py  test_graphical_nodes.py  test_graphical_output.py
  test_never_raises.py  test_golden_ir.py
```

Folders for later milestones (`ingest/`, `enrich/`, `generators/`, `llm/`, `config/`) are created by those milestones, not here.

---

### Task 1: Project skeleton, app factory and `calcview serve`

**Files:**
- Create: `pyproject.toml`, `CLAUDE.md`, `app/__init__.py`, `app/main.py`, `app/cli.py`, `app/web/templates/index.html`, `app/web/static/vendor/.gitkeep`, `tests/test_app.py`

**Interfaces:**
- Produces: `app.main.HOST: str` (`"127.0.0.1"`), `app.main.WEB_DIR: Path`, `app.main.create_app() -> FastAPI`, `app.main.app`, `app.cli.main(argv: list[str] | None = None) -> int`

> **Note (M0 blocker):** this plan assumes pip can reach PyPI. If the work laptop only has an internal mirror, `pip install -e .` works unchanged once `PIP_INDEX_URL` points at it. Confirm this before the work-side install.

- [ ] **Step 1: Create the virtualenv and package config**

```bash
python3 -m venv .venv && source .venv/bin/activate
```

`pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "calcview-migrator"
version = "0.1.0"
description = "Parse HANA calculation view XML into one IR; generate specs, lineage and target SQL."
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.110",
  "uvicorn>=0.29",
  "jinja2>=3.1",
  "lxml>=5.2",
  "pydantic>=2.6",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]

[project.scripts]
calcview = "app.cli:main"

[tool.setuptools.packages.find]
include = ["app*"]

[tool.setuptools.package-data]
app = ["web/templates/*.html", "web/static/vendor/*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`CLAUDE.md`:

```markdown
# CalcView Migrator — build rules

Spec: `docs/CalcView Migrator — Spec v0.1.md`. Plans: `docs/superpowers/plans/`.

## Commands
- Install: `python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
- Test: `pytest -q`
- Regenerate golden IR (then review the diff by hand): `UPDATE_GOLDEN=1 pytest tests/test_golden_ir.py`
- Serve: `calcview serve` (always 127.0.0.1)

## Rules
- Never read from or write to the network at runtime. Vendor every JS dependency into `app/web/static/vendor/`.
- Python floor is 3.11: no newer syntax or stdlib APIs.
- Parsers never raise on input files. Every failure becomes an `IRWarning` with a code.
- Generators read only the IR. No XML access outside `app/parsers/`.
- Every IR change updates the golden files in the same commit, with a note on why.
- Untranslatable logic produces a visible marker, never silent omission.
- Keep the audit CLI free of business content. Its leak test must pass.
- Fixtures are synthetic only: dummy names like `TABLE_A`, `COL_1`. Never commit real view XML.
```

`app/__init__.py`: empty file.

`app/web/static/vendor/.gitkeep`: empty file. `StaticFiles` refuses to mount a directory that doesn't exist.

- [ ] **Step 2: Write the failing tests**

`tests/test_app.py`:

```python
import pytest
from fastapi.testclient import TestClient

import app.cli as cli
from app.main import HOST, create_app


def test_health_endpoint():
    client = TestClient(create_app())
    assert client.get("/health").json() == {"status": "ok"}


def test_index_renders():
    response = TestClient(create_app()).get("/")
    assert response.status_code == 200
    assert "CalcView Migrator" in response.text


def test_host_is_loopback():
    assert HOST == "127.0.0.1"


def test_serve_binds_loopback_only(monkeypatch):
    calls = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: calls.update(app=app, **kw))
    assert cli.main(["serve", "--port", "9001"]) == 0
    assert calls == {"app": "app.main:app", "host": "127.0.0.1", "port": 9001}


def test_serve_has_no_host_option():
    with pytest.raises(SystemExit):
        cli.main(["serve", "--host", "0.0.0.0"])
```

- [ ] **Step 3: Install and run the tests to verify they fail**

Run: `pip install -e ".[dev]" && pytest tests/test_app.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 4: Implement the app and CLI**

`app/main.py`:

```python
"""FastAPI app. Binds to loopback only; there is deliberately no way to change the host."""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

HOST = "127.0.0.1"
WEB_DIR = Path(__file__).parent / "web"


def create_app() -> FastAPI:
    app = FastAPI(title="CalcView Migrator")
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=WEB_DIR / "templates")

    @app.get("/")
    def index(request: Request):
        return templates.TemplateResponse(request, "index.html", {})

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
```

`app/cli.py`:

```python
"""`calcview` command line. Import, audit and export commands arrive in M3/M4."""
import argparse

import uvicorn

from app.main import HOST


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="calcview")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="start the web app on 127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    if args.command == "serve":
        uvicorn.run("app.main:app", host=HOST, port=args.port)
    return 0
```

`app/web/templates/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>CalcView Migrator</title>
  <script src="/static/vendor/htmx.min.js"></script>
  <script src="/static/vendor/cytoscape.min.js"></script>
  <script src="/static/vendor/dagre.min.js"></script>
  <script src="/static/vendor/cytoscape-dagre.js"></script>
</head>
<body>
  <h1>CalcView Migrator</h1>
  <p>No projects yet. Folder import arrives in M3.</p>
</body>
</html>
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_app.py -q`
Expected: 5 passed

- [ ] **Step 6: Smoke-test the server by hand**

Run: `calcview serve --port 8765`, then open `http://127.0.0.1:8765/health` and confirm it returns `{"status":"ok"}`. Stop the server with Ctrl-C.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml CLAUDE.md app tests/test_app.py
git commit -m "feat(m0): app skeleton, loopback-only serve command"
```

---

### Task 2: Vendor the JS libraries and prove they load offline

**Files:**
- Create: `app/web/static/vendor/{htmx.min.js,cytoscape.min.js,dagre.min.js,cytoscape-dagre.js,SHA256SUMS,VENDOR.md}`, `tests/test_vendor.py`
- Delete: `app/web/static/vendor/.gitkeep`

**Interfaces:**
- Consumes: `app.main.WEB_DIR`, `app.main.create_app()` (Task 1)

> **Permission needed:** Step 3 downloads four files from cdn.jsdelivr.net. Confirm this with Jacob before running it. This is the only network access in the whole build. The app makes none at runtime.

- [ ] **Step 1: Write the failing tests**

`tests/test_vendor.py`:

```python
import re

import pytest
from fastapi.testclient import TestClient

from app.main import WEB_DIR, create_app

VENDOR_DIR = WEB_DIR / "static" / "vendor"
VENDORED = ["htmx.min.js", "cytoscape.min.js", "dagre.min.js", "cytoscape-dagre.js"]
REMOTE_REF = re.compile(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//""", re.IGNORECASE)


@pytest.mark.parametrize("name", VENDORED)
def test_vendored_file_is_present_and_served_locally(name):
    assert (VENDOR_DIR / name).stat().st_size > 1000
    response = TestClient(create_app()).get(f"/static/vendor/{name}")
    assert response.status_code == 200


def test_templates_reference_no_remote_urls():
    for template in (WEB_DIR / "templates").rglob("*.html"):
        assert not REMOTE_REF.search(template.read_text(encoding="utf-8")), template.name


def test_every_script_in_index_is_vendored():
    html = (WEB_DIR / "templates" / "index.html").read_text(encoding="utf-8")
    for src in re.findall(r'<script src="/static/vendor/([^"]+)"', html):
        assert (VENDOR_DIR / src).is_file(), src
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_vendor.py -q`
Expected: 4 FAILED with `FileNotFoundError` (vendored files missing), plus 1 FAILED from the index-script check.

- [ ] **Step 3: Download the pinned versions (after Jacob approves)**

```bash
cd app/web/static/vendor
curl -fsSLo htmx.min.js       https://cdn.jsdelivr.net/npm/htmx.org@1.9.12/dist/htmx.min.js
curl -fsSLo cytoscape.min.js  https://cdn.jsdelivr.net/npm/cytoscape@3.30.2/dist/cytoscape.min.js
curl -fsSLo dagre.min.js      https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js
curl -fsSLo cytoscape-dagre.js https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.js
shasum -a 256 *.js > SHA256SUMS
rm -f .gitkeep
cd -
```

`app/web/static/vendor/VENDOR.md`:

```markdown
# Vendored JavaScript

Served from `/static/vendor/`. Never loaded from a CDN at runtime. Checksums are in `SHA256SUMS`.

| File | Package | Version | License | Source |
|---|---|---|---|---|
| htmx.min.js | htmx.org | 1.9.12 | 0BSD | https://cdn.jsdelivr.net/npm/htmx.org@1.9.12/dist/htmx.min.js |
| cytoscape.min.js | cytoscape | 3.30.2 | MIT | https://cdn.jsdelivr.net/npm/cytoscape@3.30.2/dist/cytoscape.min.js |
| dagre.min.js | dagre | 0.8.5 | MIT | https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js |
| cytoscape-dagre.js | cytoscape-dagre | 2.5.0 | MIT | https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.js |

To upgrade: download the new pinned version, regenerate `SHA256SUMS`, and update this table.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest -q`
Expected: all of `test_app.py` and `test_vendor.py` pass (11 passed)

- [ ] **Step 5: Offline check by hand**

Turn Wi-Fi off, run `calcview serve`, and open `http://127.0.0.1:8765/`. In the browser dev tools, confirm that `typeof htmx`, `typeof cytoscape` and `typeof dagre` are all `"object"` or `"function"`, and that the Network tab shows no failed requests.

- [ ] **Step 6: Commit**

```bash
git add app/web/static/vendor tests/test_vendor.py
git commit -m "feat(m0): vendor htmx, cytoscape, dagre; offline-load tests"
```

---

### Task 3: IR models

**Files:**
- Create: `app/ir/__init__.py` (empty), `app/ir/models.py`, `tests/test_models.py`

**Interfaces:**
- Produces (used by every later task):
  - `make_id(*parts: str) -> str`: joins the parts with `/`
  - Enums (all `StrEnum`): `ViewType{GRAPHICAL,SCRIPTED,UNKNOWN}`, `DataCategory{CUBE,DIMENSION,DEFAULT,UNKNOWN}`, `NodeType{DATASOURCE,PROJECTION,JOIN,AGGREGATION,UNION,RANK,SCRIPT_STATEMENT,OPAQUE,OUTPUT}`, `ColumnKind{ATTRIBUTE,MEASURE}`, `ExpressionLang{COLUMN_ENGINE,SQL}`, `ParameterKind{INPUT_PARAMETER,VARIABLE}`, `ParamUsage{FILTER,CALCULATION}`, `DataSourceKind{TABLE,CALC_VIEW,TABLE_FUNCTION,CDS,UNKNOWN}`, `Severity{INFO,WARNING,ERROR}`, `ParseStatus{OK,PARTIAL,FAILED}`
  - Models: `ExprNode`, `Expression`, `Column`, `ColumnMapItem`, `Edge`, `JoinCondition`, `JoinSpec`, `Filter`, `Node`, `ParameterUse`, `Parameter`, `ParameterMapping`, `DataSource`, `IRWarning`, `View`, `ParseResult` (fields as in the code below)

- [ ] **Step 1: Write the failing tests**

`tests/test_models.py`:

```python
import pytest
from pydantic import ValidationError

from app.ir.models import (
    Column, ColumnKind, ColumnMapItem, DataCategory, Edge, Expression, ExpressionLang,
    ExprNode, Node, NodeType, ParseResult, ParseStatus, View, ViewType, make_id,
)


def test_make_id_joins_parts_with_slash():
    assert make_id("V", "N", "C") == "V/N/C"


def test_parse_result_round_trips_through_json():
    view = View(id="V", name="V", view_type=ViewType.GRAPHICAL, data_category=DataCategory.CUBE,
                schema_version="2.3", file_hash="abc", parse_status=ParseStatus.OK, coverage_pct=100.0)
    expr = Expression(
        text='"A" * 2', lang=ExpressionLang.COLUMN_ENGINE,
        ast=ExprNode(kind="binary", value="*",
                     args=[ExprNode(kind="column", value="A"), ExprNode(kind="number", value="2")]),
    )
    node = Node(id="V/P", view_id="V", node_type=NodeType.PROJECTION, name="P", raw="<x/>",
                columns=[Column(id="V/P/C", name="C", kind=ColumnKind.ATTRIBUTE, expression=expr)])
    edge = Edge(from_node="V/T", to_node="V/P",
                column_map=[ColumnMapItem(target="C", source="A"), ColumnMapItem(target="K", constant="X")])
    result = ParseResult(view=view, nodes=[node], edges=[edge])

    assert ParseResult.model_validate_json(result.model_dump_json()) == result


def test_ir_models_reject_unknown_fields():
    with pytest.raises(ValidationError):
        Column(id="a", name="a", bogus=1)


def test_enums_serialise_as_lowercase_values():
    node = Node(id="V/P", view_id="V", node_type=NodeType.OPAQUE, name="P", raw="")
    assert '"node_type":"opaque"' in node.model_dump_json()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_models.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ir'`

- [ ] **Step 3: Implement the models**

`app/ir/models.py`:

```python
"""Intermediate representation. Every output is a view of these models.

Graphical and scripted views share the same entities, so generators never branch on
view type. Ids are deterministic (view/node/column) so annotations survive re-import.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def make_id(*parts: str) -> str:
    return "/".join(parts)


class IRModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ViewType(StrEnum):
    GRAPHICAL = "graphical"
    SCRIPTED = "scripted"
    UNKNOWN = "unknown"


class DataCategory(StrEnum):
    CUBE = "CUBE"
    DIMENSION = "DIMENSION"
    DEFAULT = "DEFAULT"
    UNKNOWN = "UNKNOWN"


class NodeType(StrEnum):
    DATASOURCE = "datasource"
    PROJECTION = "projection"
    JOIN = "join"
    AGGREGATION = "aggregation"
    UNION = "union"
    RANK = "rank"
    SCRIPT_STATEMENT = "script_statement"
    OPAQUE = "opaque"
    OUTPUT = "output"


class ColumnKind(StrEnum):
    ATTRIBUTE = "attribute"
    MEASURE = "measure"


class ExpressionLang(StrEnum):
    COLUMN_ENGINE = "column_engine"
    SQL = "sql"


class ParameterKind(StrEnum):
    INPUT_PARAMETER = "input_parameter"
    VARIABLE = "variable"


class ParamUsage(StrEnum):
    FILTER = "filter"
    CALCULATION = "calculation"


class DataSourceKind(StrEnum):
    TABLE = "table"
    CALC_VIEW = "calc_view"
    TABLE_FUNCTION = "table_function"
    CDS = "cds"
    UNKNOWN = "unknown"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ParseStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


class ExprNode(IRModel):
    """Expression AST. `value` holds the literal text, column name, parameter name,
    function name (lowercased) or operator, depending on `kind`."""

    kind: Literal["string", "number", "column", "param", "call", "binary", "unary"]
    value: str | None = None
    args: list[ExprNode] = Field(default_factory=list)


class Expression(IRModel):
    text: str
    lang: ExpressionLang
    ast: ExprNode | None = None


class Column(IRModel):
    id: str
    name: str
    datatype: str | None = None
    length: int | None = None
    scale: int | None = None
    kind: ColumnKind = ColumnKind.ATTRIBUTE
    aggregation: str | None = None
    expression: Expression | None = None


class ColumnMapItem(IRModel):
    """Maps a source column, or a constant (unions), to a target column."""

    target: str
    source: str | None = None
    constant: str | None = None
    null: bool = False


class Edge(IRModel):
    from_node: str
    to_node: str
    column_map: list[ColumnMapItem] = Field(default_factory=list)


class JoinCondition(IRModel):
    column: str


class JoinSpec(IRModel):
    join_type: str
    cardinality: str | None = None
    left_node: str | None = None
    right_node: str | None = None
    conditions: list[JoinCondition] = Field(default_factory=list)
    special: bool = False  # referential / text joins need special semantics


class Filter(IRModel):
    expression: Expression


class Node(IRModel):
    id: str
    view_id: str
    node_type: NodeType
    name: str
    raw: str
    columns: list[Column] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list)
    join: JoinSpec | None = None
    understood: bool = True  # feeds View.coverage_pct


class ParameterUse(IRModel):
    node_id: str
    usage: ParamUsage


class Parameter(IRModel):
    id: str
    view_id: str
    name: str
    kind: ParameterKind
    datatype: str | None = None
    length: int | None = None
    scale: int | None = None
    default: str | None = None
    mandatory: bool = False
    used_in: list[ParameterUse] = Field(default_factory=list)


class ParameterMapping(IRModel):
    """A local parameter (or constant) passed to a parameter of an upstream view."""

    view_id: str
    data_source_id: str
    target_parameter: str
    local_parameter: str | None = None
    constant: str | None = None


class DataSource(IRModel):
    id: str
    kind: DataSourceKind
    schema_name: str | None = None
    name: str
    resource_uri: str | None = None
    resolved_view_id: str | None = None  # set by dependency resolution (M3)


class IRWarning(IRModel):
    view_id: str | None = None
    node_id: str | None = None
    code: str
    message: str
    severity: Severity = Severity.WARNING
    line: int | None = None


class View(IRModel):
    id: str
    name: str
    package_path: str | None = None
    view_type: ViewType
    data_category: DataCategory
    schema_version: str | None = None
    file_hash: str
    parse_status: ParseStatus
    coverage_pct: float


class ParseResult(IRModel):
    view: View
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    parameters: list[Parameter] = Field(default_factory=list)
    parameter_mappings: list[ParameterMapping] = Field(default_factory=list)
    data_sources: list[DataSource] = Field(default_factory=list)
    warnings: list[IRWarning] = Field(default_factory=list)


ExprNode.model_rebuild()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_models.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/ir tests/test_models.py
git commit -m "feat(m1): Pydantic IR models"
```

---

### Task 4: Synthetic fixtures and XML helpers

**Files:**
- Modify: `.gitattributes` (append one line)
- Create: `fixtures/synthetic/graphical/GENERIC_TAX_REPORTING_CUBE.calculationview`, `fixtures/synthetic/malformed/truncated.calculationview`, `fixtures/synthetic/malformed/unknown_type.calculationview`, `fixtures/synthetic/malformed/bad_expression.calculationview`, `app/parsers/__init__.py` (empty), `app/parsers/xmlutil.py`, `tests/conftest.py`, `tests/test_xmlutil.py`

**Interfaces:**
- Produces, in `app.parsers.xmlutil`:
  - `XSI_NS: str`
  - `load(data: bytes) -> tuple[etree._Element | None, str | None, int | None]`, returning `(root, error_message, error_line)`
  - `local(el) -> str`
  - `children(el | None, name: str | None = None) -> list[etree._Element]`: element children only, filtered by local name
  - `child(el | None, name: str) -> etree._Element | None`
  - `descendants(el | None, name: str) -> list`, `first_descendant(el | None, name: str) -> etree._Element | None`
  - `text(el | None) -> str | None`: stripped text, or `None`
  - `xsi_type_name(el) -> str | None`: local part of `xsi:type` (`"Calculation:JoinView"` → `"JoinView"`)
  - `raw(el) -> str`: serialised XML fragment, without its tail
- Produces, in `tests/conftest.py`: the `FIXTURES: Path` constant, and the `fixture_bytes(rel: str) -> bytes` and `parse_fixture(rel: str) -> ParseResult` fixtures. `parse_fixture` imports `parse_bytes` lazily, so it works from Task 6 on.

- [ ] **Step 1: Keep fixture bytes exact across platforms**

Append this line to `.gitattributes`. The file hash and raw XML go into the golden files, so CRLF conversion on a Windows checkout would break them.

```
fixtures/** -text
```

- [ ] **Step 2: Write the main graphical fixture**

This fixture follows the skeleton's element order and covers the spec's fixture contract: a join, an aggregation, a union, calculated columns, a filter, input parameters, plus a variable and a variable mapping. All names are dummies.

`fixtures/synthetic/graphical/GENERIC_TAX_REPORTING_CUBE.calculationview`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!-- Synthetic fixture built from the structural skeleton supplied on 2026-10-14.
     Element order and nesting follow that skeleton; every name is a dummy. -->
<Calculation:scenario xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:Calculation="http://www.sap.com/ndb/BiModelCalculation.ecore" xmlns:Variable="http://www.sap.com/ndb/BiModelVariable.ecore" schemaVersion="2.3" id="GENERIC_TAX_REPORTING_CUBE" applyPrivilegeType="ANALYTIC_PRIVILEGE" checkAnalyticPrivileges="true" defaultClient="$$client$$" defaultLanguage="$$language$$" visibility="internal" calculationScenarioType="TREE_BASED" dataCategory="CUBE" enforceSqlExecution="false" executionSemantic="UNDEFINED" outputViewType="Aggregation">
  <origin/>
  <descriptions defaultDescription="GENERIC_TAX_REPORTING_CUBE"/>
  <localVariables>
    <variable id="IP_FISCAL_YEAR" parameter="true">
      <descriptions defaultDescription="IP_FISCAL_YEAR"/>
      <variableProperties datatype="NVARCHAR" length="4" mandatory="true">
        <valueDomain type="empty"/>
        <selection multiline="false" type="SingleValue"/>
      </variableProperties>
    </variable>
    <variable id="IP_RATE" parameter="true">
      <descriptions defaultDescription="IP_RATE"/>
      <variableProperties datatype="DECIMAL" length="5" scale="2" mandatory="false" defaultValue="1">
        <valueDomain type="empty"/>
        <selection multiline="false" type="SingleValue"/>
      </variableProperties>
    </variable>
    <variable id="V_COMPANY" parameter="false">
      <descriptions defaultDescription="V_COMPANY"/>
      <variableProperties datatype="NVARCHAR" length="4" mandatory="false">
        <valueDomain type="AttributeValue"/>
        <selection multiline="true" type="SingleValue"/>
      </variableProperties>
    </variable>
  </localVariables>
  <variableMappings>
    <mapping xsi:type="Variable:VariableMapping" dataSource="#SOURCE_VIEW_01">
      <targetVariable name="IP_YEAR" resourceUri="/pkg.synthetic/calculationviews/SOURCE_VIEW_01"/>
      <localVariable>#IP_FISCAL_YEAR</localVariable>
    </mapping>
  </variableMappings>
  <dataSources>
    <DataSource id="SOURCE_VIEW_01" type="CALCULATION_VIEW">
      <viewAttributes allViewAttributes="true"/>
      <resourceUri>/pkg.synthetic/calculationviews/SOURCE_VIEW_01</resourceUri>
    </DataSource>
    <DataSource id="TABLE_A" type="DATA_BASE_TABLE">
      <viewAttributes allViewAttributes="true"/>
      <columnObject schemaName="SCHEMA_1" columnObjectName="TABLE_A"/>
    </DataSource>
    <DataSource id="TABLE_B" type="DATA_BASE_TABLE">
      <viewAttributes allViewAttributes="true"/>
      <columnObject schemaName="SCHEMA_1" columnObjectName="TABLE_B"/>
    </DataSource>
  </dataSources>
  <calculationViews>
    <calculationView xsi:type="Calculation:ProjectionView" id="Projection_1">
      <descriptions/>
      <viewAttributes>
        <viewAttribute id="COL_1"/>
        <viewAttribute id="COL_2"/>
        <viewAttribute id="COL_3"/>
        <viewAttribute id="AMT_1"/>
      </viewAttributes>
      <calculatedViewAttributes>
        <calculatedViewAttribute datatype="DECIMAL" id="CC_1" length="15" scale="2" expressionLanguage="COLUMN_ENGINE">
          <formula>if(&quot;COL_2&quot; = 'X', &quot;AMT_1&quot;, 0)</formula>
        </calculatedViewAttribute>
      </calculatedViewAttributes>
      <input node="#SOURCE_VIEW_01">
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_1" source="COL_1"/>
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_2" source="COL_2"/>
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_3" source="COL_3"/>
        <mapping xsi:type="Calculation:AttributeMapping" target="AMT_1" source="AMT_1"/>
      </input>
      <filter>(&quot;COL_3&quot; = '$$IP_FISCAL_YEAR$$')</filter>
    </calculationView>
    <calculationView xsi:type="Calculation:JoinView" id="Join_1" cardinality="CN_1" joinOrder="OUTSIDE_IN" joinType="leftOuter">
      <descriptions/>
      <viewAttributes>
        <viewAttribute id="COL_1"/>
        <viewAttribute id="COL_2"/>
        <viewAttribute id="COL_3"/>
        <viewAttribute id="COL_4"/>
        <viewAttribute id="AMT_1"/>
        <viewAttribute id="CC_1"/>
      </viewAttributes>
      <calculatedViewAttributes/>
      <input node="#Projection_1">
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_1" source="COL_1"/>
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_2" source="COL_2"/>
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_3" source="COL_3"/>
        <mapping xsi:type="Calculation:AttributeMapping" target="AMT_1" source="AMT_1"/>
        <mapping xsi:type="Calculation:AttributeMapping" target="CC_1" source="CC_1"/>
      </input>
      <input node="#TABLE_A">
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_1" source="COL_1"/>
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_4" source="COL_4"/>
      </input>
      <joinAttribute name="COL_1"/>
    </calculationView>
    <calculationView xsi:type="Calculation:UnionView" id="Union_1">
      <descriptions/>
      <viewAttributes>
        <viewAttribute id="COL_1"/>
        <viewAttribute id="COL_3"/>
        <viewAttribute id="COL_5"/>
        <viewAttribute id="AMT_1"/>
        <viewAttribute id="CC_1"/>
      </viewAttributes>
      <calculatedViewAttributes/>
      <input emptyUnionBehavior="NO_ROW" node="#Join_1">
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_1" source="COL_1"/>
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_3" source="COL_3"/>
        <mapping xsi:type="Calculation:AttributeMapping" target="AMT_1" source="AMT_1"/>
        <mapping xsi:type="Calculation:AttributeMapping" target="CC_1" source="CC_1"/>
        <mapping xsi:type="Calculation:ConstantAttributeMapping" target="COL_5" null="false" value="SRC_A"/>
      </input>
      <input emptyUnionBehavior="NO_ROW" node="#TABLE_B">
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_1" source="COL_1"/>
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_3" source="COL_3"/>
        <mapping xsi:type="Calculation:AttributeMapping" target="AMT_1" source="AMT_1"/>
        <mapping xsi:type="Calculation:ConstantAttributeMapping" target="CC_1" null="true"/>
        <mapping xsi:type="Calculation:ConstantAttributeMapping" target="COL_5" null="false" value="SRC_B"/>
      </input>
    </calculationView>
    <calculationView xsi:type="Calculation:AggregationView" id="Aggregation_1">
      <descriptions/>
      <viewAttributes>
        <viewAttribute id="COL_1"/>
        <viewAttribute id="COL_3"/>
        <viewAttribute id="COL_5"/>
        <viewAttribute id="AMT_1" aggregationType="sum"/>
        <viewAttribute id="CC_1" aggregationType="sum"/>
      </viewAttributes>
      <calculatedViewAttributes>
        <calculatedViewAttribute datatype="DECIMAL" id="CC_2" length="17" scale="2" expressionLanguage="COLUMN_ENGINE">
          <formula>&quot;AMT_1&quot; * $$IP_RATE$$</formula>
        </calculatedViewAttribute>
      </calculatedViewAttributes>
      <input node="Union_1">
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_1" source="COL_1"/>
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_3" source="COL_3"/>
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_5" source="COL_5"/>
        <mapping xsi:type="Calculation:AttributeMapping" target="AMT_1" source="AMT_1"/>
        <mapping xsi:type="Calculation:AttributeMapping" target="CC_1" source="CC_1"/>
      </input>
    </calculationView>
  </calculationViews>
  <logicalModel id="Aggregation_1">
    <attributes>
      <attribute id="COL_1" order="1" attributeHierarchyActive="false" displayAttribute="false">
        <descriptions defaultDescription="COL_1"/>
        <keyMapping columnObjectName="Aggregation_1" columnName="COL_1"/>
      </attribute>
      <attribute id="COL_3" order="2" attributeHierarchyActive="false" displayAttribute="false">
        <descriptions defaultDescription="COL_3"/>
        <keyMapping columnObjectName="Aggregation_1" columnName="COL_3"/>
      </attribute>
      <attribute id="COL_5" order="3" attributeHierarchyActive="false" displayAttribute="false">
        <descriptions defaultDescription="COL_5"/>
        <keyMapping columnObjectName="Aggregation_1" columnName="COL_5"/>
      </attribute>
    </attributes>
    <calculatedAttributes/>
    <privateDataFoundation>
      <tableProxies/>
      <joins/>
      <layout>
        <shapes/>
      </layout>
    </privateDataFoundation>
    <baseMeasures>
      <measure id="AMT_1" order="4" aggregationType="sum" engineAggregation="sum" measureType="simple">
        <descriptions defaultDescription="AMT_1"/>
        <measureMapping columnObjectName="Aggregation_1" columnName="AMT_1"/>
      </measure>
      <measure id="CC_1" order="5" aggregationType="sum" engineAggregation="sum" measureType="simple">
        <descriptions defaultDescription="CC_1"/>
        <measureMapping columnObjectName="Aggregation_1" columnName="CC_1"/>
      </measure>
      <measure id="CC_2" order="6" aggregationType="sum" engineAggregation="sum" measureType="simple">
        <descriptions defaultDescription="CC_2"/>
        <measureMapping columnObjectName="Aggregation_1" columnName="CC_2"/>
      </measure>
    </baseMeasures>
    <calculatedMeasures>
      <measure id="CM_1" order="7" aggregationType="sum" measureType="simple" datatype="DECIMAL" length="17" scale="2" expressionLanguage="COLUMN_ENGINE">
        <descriptions defaultDescription="CM_1"/>
        <formula>&quot;AMT_1&quot; - &quot;CC_1&quot;</formula>
      </measure>
    </calculatedMeasures>
    <restrictedMeasures/>
    <localDimensions/>
  </logicalModel>
  <layout>
    <shapes>
      <shape expanded="true" modelObjectName="Output" modelObjectNameSpace="MeasureGroup">
        <upperLeftCorner x="40" y="85"/>
      </shape>
    </shapes>
  </layout>
</Calculation:scenario>
```

- [ ] **Step 3: Write the malformed fixtures**

`fixtures/synthetic/malformed/truncated.calculationview` (cut off mid-element on purpose):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Calculation:scenario xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:Calculation="http://www.sap.com/ndb/BiModelCalculation.ecore" schemaVersion="2.3" id="TRUNCATED_VIEW" dataCategory="CUBE">
  <origin/>
  <dataSources>
    <DataSource id="TABLE_A" type="DATA_BASE_TABLE">
      <viewAttri
```

`fixtures/synthetic/malformed/unknown_type.calculationview`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!-- Malformed variant: a calculationView xsi:type the parser does not know. -->
<Calculation:scenario xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:Calculation="http://www.sap.com/ndb/BiModelCalculation.ecore" schemaVersion="2.3" id="UNKNOWN_TYPE_VIEW" dataCategory="DEFAULT">
  <origin/>
  <localVariables/>
  <variableMappings/>
  <dataSources>
    <DataSource id="TABLE_A" type="DATA_BASE_TABLE">
      <viewAttributes allViewAttributes="true"/>
      <columnObject schemaName="SCHEMA_1" columnObjectName="TABLE_A"/>
    </DataSource>
  </dataSources>
  <calculationViews>
    <calculationView xsi:type="Calculation:ProjectionView" id="Projection_1">
      <viewAttributes>
        <viewAttribute id="COL_1"/>
      </viewAttributes>
      <calculatedViewAttributes/>
      <input node="#TABLE_A">
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_1" source="COL_1"/>
      </input>
    </calculationView>
    <calculationView xsi:type="Calculation:FancyNewView" id="Fancy_1">
      <viewAttributes>
        <viewAttribute id="COL_1"/>
      </viewAttributes>
      <input node="#Projection_1">
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_1" source="COL_1"/>
      </input>
    </calculationView>
  </calculationViews>
  <logicalModel id="Fancy_1">
    <attributes>
      <attribute id="COL_1" order="1">
        <keyMapping columnObjectName="Fancy_1" columnName="COL_1"/>
      </attribute>
    </attributes>
  </logicalModel>
  <layout>
    <shapes/>
  </layout>
</Calculation:scenario>
```

`fixtures/synthetic/malformed/bad_expression.calculationview`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!-- Malformed variant: a calculated column whose formula is missing its closing paren. -->
<Calculation:scenario xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:Calculation="http://www.sap.com/ndb/BiModelCalculation.ecore" schemaVersion="2.3" id="BAD_EXPRESSION_VIEW" dataCategory="DEFAULT">
  <origin/>
  <dataSources>
    <DataSource id="TABLE_A" type="DATA_BASE_TABLE">
      <viewAttributes allViewAttributes="true"/>
      <columnObject schemaName="SCHEMA_1" columnObjectName="TABLE_A"/>
    </DataSource>
  </dataSources>
  <calculationViews>
    <calculationView xsi:type="Calculation:ProjectionView" id="Projection_1">
      <viewAttributes>
        <viewAttribute id="COL_1"/>
      </viewAttributes>
      <calculatedViewAttributes>
        <calculatedViewAttribute datatype="INTEGER" id="CC_1" expressionLanguage="COLUMN_ENGINE">
          <formula>if(&quot;COL_1&quot; = 'X', 1</formula>
        </calculatedViewAttribute>
      </calculatedViewAttributes>
      <input node="#TABLE_A">
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_1" source="COL_1"/>
      </input>
    </calculationView>
  </calculationViews>
  <logicalModel id="Projection_1">
    <attributes>
      <attribute id="COL_1" order="1">
        <keyMapping columnObjectName="Projection_1" columnName="COL_1"/>
      </attribute>
      <attribute id="CC_1" order="2">
        <keyMapping columnObjectName="Projection_1" columnName="CC_1"/>
      </attribute>
    </attributes>
  </logicalModel>
</Calculation:scenario>
```

- [ ] **Step 4: Write the shared test fixtures**

`tests/conftest.py`:

```python
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic"
MAIN = "graphical/GENERIC_TAX_REPORTING_CUBE.calculationview"


@pytest.fixture
def fixture_bytes():
    def load(rel: str) -> bytes:
        return (FIXTURES / rel).read_bytes()

    return load


@pytest.fixture
def parse_fixture():
    from app.parsers.dispatch import parse_bytes

    def parse(rel: str):
        path = FIXTURES / rel
        return parse_bytes(path.read_bytes(), file_name=path.name)

    return parse
```

- [ ] **Step 5: Write the failing XML helper tests**

`tests/test_xmlutil.py`:

```python
from conftest import MAIN

from app.parsers import xmlutil as x

TWO_PREFIXES = b"""<?xml version="1.0"?>
<calc:scenario xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:calc="http://www.sap.com/ndb/BiModelCalculation.ecore">
  <!-- a comment -->
  <calculationViews>
    <calculationView xsi:type="calc:ProjectionView" id="P"/>
    <calculationView xsi:type="JoinView" id="J"/>
  </calculationViews>
</calc:scenario>"""


def test_load_returns_root_for_well_formed_xml(fixture_bytes):
    root, error, line = x.load(fixture_bytes(MAIN))
    assert error is None and line is None
    assert x.local(root) == "scenario"


def test_load_reports_syntax_error_with_line(fixture_bytes):
    root, error, line = x.load(fixture_bytes("malformed/truncated.calculationview"))
    assert root is None
    assert error
    assert isinstance(line, int)


def test_load_rejects_empty_and_binary_input():
    assert x.load(b"")[0] is None
    assert x.load(b"\xff\xfe\x00\x01")[0] is None


def test_children_skip_comments_and_match_local_names():
    root, _, _ = x.load(TWO_PREFIXES)
    assert [x.local(c) for c in x.children(root)] == ["calculationViews"]
    views = x.children(x.child(root, "calculationViews"), "calculationView")
    assert [v.get("id") for v in views] == ["P", "J"]


def test_xsi_type_name_ignores_prefix():
    root, _, _ = x.load(TWO_PREFIXES)
    views = x.descendants(root, "calculationView")
    assert [x.xsi_type_name(v) for v in views] == ["ProjectionView", "JoinView"]


def test_helpers_are_none_safe():
    assert x.children(None, "a") == []
    assert x.child(None, "a") is None
    assert x.text(None) is None
    assert x.first_descendant(None, "a") is None


def test_text_strips_whitespace():
    root, _, _ = x.load(b"<a>  hello  </a>")
    assert x.text(root) == "hello"
```

- [ ] **Step 6: Run the tests to verify they fail**

Run: `pytest tests/test_xmlutil.py -q`
Expected: FAIL with `ImportError: cannot import name 'xmlutil' from 'app.parsers'`

- [ ] **Step 7: Implement the XML helpers**

`app/parsers/__init__.py`: empty file.

`app/parsers/xmlutil.py`:

```python
"""lxml helpers. Elements are matched by local name so namespace URIs and prefixes,
which may differ between HANA versions, never affect parsing."""
from __future__ import annotations

from lxml import etree

XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

_PARSER_OPTIONS = dict(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)


def load(data: bytes) -> tuple[etree._Element | None, str | None, int | None]:
    """Parse bytes. Returns (root, None, None) or (None, message, line)."""
    try:
        return etree.fromstring(data, etree.XMLParser(**_PARSER_OPTIONS)), None, None
    except etree.XMLSyntaxError as exc:
        return None, str(exc), exc.lineno
    except ValueError as exc:  # e.g. unicode strings with an encoding declaration
        return None, str(exc), None


def local(el: etree._Element) -> str:
    return etree.QName(el).localname


def _is_element(node) -> bool:
    return isinstance(node.tag, str)  # comments and processing instructions are not


def children(el: etree._Element | None, name: str | None = None) -> list[etree._Element]:
    if el is None:
        return []
    return [c for c in el if _is_element(c) and (name is None or local(c) == name)]


def child(el: etree._Element | None, name: str) -> etree._Element | None:
    found = children(el, name)
    return found[0] if found else None


def descendants(el: etree._Element | None, name: str) -> list[etree._Element]:
    if el is None:
        return []
    return [d for d in el.iterdescendants() if _is_element(d) and local(d) == name]


def first_descendant(el: etree._Element | None, name: str) -> etree._Element | None:
    found = descendants(el, name)
    return found[0] if found else None


def text(el: etree._Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    return el.text.strip()


def xsi_type_name(el: etree._Element) -> str | None:
    """Local part of xsi:type, e.g. "Calculation:JoinView" -> "JoinView"."""
    value = el.get(f"{{{XSI_NS}}}type")
    if value is None:
        return None
    return value.rpartition(":")[2]


def raw(el: etree._Element) -> str:
    return etree.tostring(el, encoding="unicode", with_tail=False)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `pytest tests/test_xmlutil.py -q`
Expected: 7 passed

- [ ] **Step 9: Commit**

```bash
git add .gitattributes fixtures app/parsers tests/conftest.py tests/test_xmlutil.py
git commit -m "feat(m1): synthetic fixtures from skeleton; namespace-agnostic XML helpers"
```

---

### Task 5: Column-engine expression parser

**Files:**
- Create: `app/parsers/expressions.py`, `tests/test_expressions.py`

**Interfaces:**
- Consumes: `ExprNode` (Task 3)
- Produces: `parse_expression(text: str) -> ExprNode`, which raises `ExprParseError(ValueError)` on any failure. This includes deep nesting, which would otherwise surface as `RecursionError`.

Grammar (lowest to highest precedence): `or` → `and` → `not` → comparison (`= != <> < > <= >=`) → `+ -` → `* /` → unary `-` → primary. A primary is a number, a `'string'` (with `''` as an escaped quote), a `"column"`, `$$PARAM$$` (bare or inside quotes), a `func(args…)` call (name lowercased), or a parenthesised expression. Bare identifiers are rejected, because the column engine double-quotes column names.

- [ ] **Step 1: Write the failing tests**

`tests/test_expressions.py`:

```python
import pytest

from app.ir.models import ExprNode
from app.parsers.expressions import ExprParseError, parse_expression


def col(name): return ExprNode(kind="column", value=name)
def num(v): return ExprNode(kind="number", value=v)
def s(v): return ExprNode(kind="string", value=v)
def param(name): return ExprNode(kind="param", value=name)
def bin_(op, a, b): return ExprNode(kind="binary", value=op, args=[a, b])
def call(name, *args): return ExprNode(kind="call", value=name, args=list(args))


def test_if_call_with_comparison():
    assert parse_expression("if(\"COL_2\" = 'X', \"AMT_1\", 0)") == call(
        "if", bin_("=", col("COL_2"), s("X")), col("AMT_1"), num("0"))


def test_bare_parameter_placeholder():
    assert parse_expression('"AMT_1" * $$IP_RATE$$') == bin_("*", col("AMT_1"), param("IP_RATE"))


def test_quoted_parameter_placeholder_is_a_param():
    assert parse_expression("(\"COL_3\" = '$$IP_FISCAL_YEAR$$')") == bin_(
        "=", col("COL_3"), param("IP_FISCAL_YEAR"))


def test_arithmetic_precedence():
    assert parse_expression("1 + 2 * 3") == bin_("+", num("1"), bin_("*", num("2"), num("3")))


def test_boolean_precedence_and_not():
    expected = bin_(
        "or",
        bin_("and", bin_("=", col("A"), s("x")),
             ExprNode(kind="unary", value="not", args=[bin_("=", col("B"), s("y"))])),
        bin_(">", col("C"), num("1")),
    )
    assert parse_expression("\"A\" = 'x' and not \"B\" = 'y' OR \"C\" > 1") == expected


def test_escaped_quote_in_string():
    assert parse_expression("'it''s'") == s("it's")


def test_function_names_are_lowercased_and_zero_arg_calls_work():
    assert parse_expression('LEFTSTR("COL_1", 2)') == call("leftstr", col("COL_1"), num("2"))
    assert parse_expression("now()") == call("now")


def test_unary_minus_and_decimal():
    assert parse_expression("-1.5") == ExprNode(kind="unary", value="-", args=[num("1.5")])


@pytest.mark.parametrize("text", [
    "if(\"COL_1\" = 'X', 1",   # missing close paren
    '"COL_1" = ',              # dangling operator
    "COL_1 = 1",               # bare identifier
    "'unterminated",           # unterminated string
    "",                        # empty
    "   ",                     # whitespace only
    "1 2",                     # trailing token
    '"A" # 1',                 # unknown character
])
def test_invalid_expressions_raise_expr_parse_error(text):
    with pytest.raises(ExprParseError):
        parse_expression(text)


def test_deep_nesting_raises_expr_parse_error_not_recursion_error():
    with pytest.raises(ExprParseError):
        parse_expression("(" * 5000 + "1" + ")" * 5000)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_expressions.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.parsers.expressions'`

- [ ] **Step 3: Implement the parser**

`app/parsers/expressions.py`:

```python
"""Column-engine expression parser: tokenizer plus recursive descent into ExprNode.

Scope for M1: literals, double-quoted columns, $$PARAM$$ placeholders, function calls,
arithmetic, comparison and boolean operators. Anything else raises ExprParseError; the
caller turns that into a warning so the rest of the view still parses.
"""
from __future__ import annotations

import re

from app.ir.models import ExprNode


class ExprParseError(ValueError):
    pass


_TOKEN_RE = re.compile(
    r"""
     (?P<ws>\s+)
    |(?P<param>\$\$\w+\$\$)
    |(?P<number>\d+(?:\.\d+)?)
    |(?P<string>'(?:[^']|'')*')
    |(?P<column>"(?:[^"]|"")*")
    |(?P<op><=|>=|<>|!=|=|<|>|\+|-|\*|/)
    |(?P<lparen>\()
    |(?P<rparen>\))
    |(?P<comma>,)
    |(?P<ident>[A-Za-z_][A-Za-z0-9_]*)
    """,
    re.VERBOSE,
)
_PARAM_RE = re.compile(r"\$\$(\w+)\$\$")
_CMP_OPS = {"=", "!=", "<>", "<", ">", "<=", ">="}

Token = tuple[str, str]


def parse_expression(text: str) -> ExprNode:
    tokens = _tokenize(text)
    if not tokens:
        raise ExprParseError("empty expression")
    parser = _Parser(tokens)
    try:
        node = parser.parse_or()
    except RecursionError:
        raise ExprParseError("expression nested too deeply") from None
    if parser.peek() is not None:
        raise ExprParseError(f"unexpected token {parser.peek()[1]!r}")
    return node


def _tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if match is None:
            raise ExprParseError(f"unexpected character {text[pos]!r} at position {pos}")
        if match.lastgroup != "ws":
            tokens.append((match.lastgroup, match.group()))
        pos = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.i = 0

    def peek(self) -> Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self) -> Token:
        tok = self.peek()
        if tok is None:
            raise ExprParseError("unexpected end of expression")
        self.i += 1
        return tok

    def expect(self, kind: str) -> Token:
        tok = self.take()
        if tok[0] != kind:
            raise ExprParseError(f"expected {kind}, got {tok[1]!r}")
        return tok

    def accept_keyword(self, word: str) -> bool:
        tok = self.peek()
        if tok is not None and tok[0] == "ident" and tok[1].lower() == word:
            self.i += 1
            return True
        return False

    def accept_op(self, ops: set[str]) -> str | None:
        tok = self.peek()
        if tok is not None and tok[0] == "op" and tok[1] in ops:
            self.i += 1
            return tok[1]
        return None

    def parse_or(self) -> ExprNode:
        left = self.parse_and()
        while self.accept_keyword("or"):
            left = ExprNode(kind="binary", value="or", args=[left, self.parse_and()])
        return left

    def parse_and(self) -> ExprNode:
        left = self.parse_not()
        while self.accept_keyword("and"):
            left = ExprNode(kind="binary", value="and", args=[left, self.parse_not()])
        return left

    def parse_not(self) -> ExprNode:
        if self.accept_keyword("not"):
            return ExprNode(kind="unary", value="not", args=[self.parse_not()])
        return self.parse_comparison()

    def parse_comparison(self) -> ExprNode:
        left = self.parse_additive()
        op = self.accept_op(_CMP_OPS)
        if op is None:
            return left
        return ExprNode(kind="binary", value=op, args=[left, self.parse_additive()])

    def parse_additive(self) -> ExprNode:
        left = self.parse_multiplicative()
        while (op := self.accept_op({"+", "-"})) is not None:
            left = ExprNode(kind="binary", value=op, args=[left, self.parse_multiplicative()])
        return left

    def parse_multiplicative(self) -> ExprNode:
        left = self.parse_unary()
        while (op := self.accept_op({"*", "/"})) is not None:
            left = ExprNode(kind="binary", value=op, args=[left, self.parse_unary()])
        return left

    def parse_unary(self) -> ExprNode:
        if self.accept_op({"-"}):
            return ExprNode(kind="unary", value="-", args=[self.parse_unary()])
        return self.parse_primary()

    def parse_primary(self) -> ExprNode:
        kind, text = self.take()
        if kind == "number":
            return ExprNode(kind="number", value=text)
        if kind == "string":
            inner = text[1:-1].replace("''", "'")
            placeholder = _PARAM_RE.fullmatch(inner)
            if placeholder:
                return ExprNode(kind="param", value=placeholder.group(1))
            return ExprNode(kind="string", value=inner)
        if kind == "param":
            return ExprNode(kind="param", value=text[2:-2])
        if kind == "column":
            return ExprNode(kind="column", value=text[1:-1].replace('""', '"'))
        if kind == "lparen":
            inner_node = self.parse_or()
            self.expect("rparen")
            return inner_node
        if kind == "ident":
            if self.peek() is not None and self.peek()[0] == "lparen":
                self.i += 1
                return ExprNode(kind="call", value=text.lower(), args=self.parse_args())
            raise ExprParseError(f"bare identifier {text!r}; column references must be double-quoted")
        raise ExprParseError(f"unexpected token {text!r}")

    def parse_args(self) -> list[ExprNode]:
        args: list[ExprNode] = []
        if self.peek() is not None and self.peek()[0] == "rparen":
            self.i += 1
            return args
        args.append(self.parse_or())
        while self.peek() is not None and self.peek()[0] == "comma":
            self.i += 1
            args.append(self.parse_or())
        self.expect("rparen")
        return args
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_expressions.py -q`
Expected: 17 passed

- [ ] **Step 5: Commit**

```bash
git add app/parsers/expressions.py tests/test_expressions.py
git commit -m "feat(m1): column-engine expression parser with clean failure"
```

---

### Task 6: Dispatch plus graphical metadata (view, data sources, parameters, variable mappings)

**Files:**
- Create: `app/parsers/dispatch.py`, `app/parsers/graphical.py`, `tests/helpers.py`, `tests/test_graphical_metadata.py`

**Interfaces:**
- Consumes: the IR models (Task 3) and `xmlutil` (Task 4)
- Produces:
  - `app.parsers.dispatch.parse_bytes(data: bytes, *, file_name: str, package_path: str | None = None) -> ParseResult`: never raises
  - `app.parsers.dispatch.parse_file(path: Path, *, package_path: str | None = None) -> ParseResult`: never raises
  - `app.parsers.dispatch.finalize(result: ParseResult) -> ParseResult`: sets `coverage_pct` and `parse_status`. M2's scripted front end reuses it.
  - `app.parsers.graphical.parse_graphical(root, view: View) -> ParseResult`
  - `tests/helpers.py`: `node(result, name) -> Node`, `column(node, name) -> Column`, `codes(result) -> list[str]`

- [ ] **Step 1: Write the test helpers and failing tests**

`tests/helpers.py`:

```python
from app.ir.models import Column, Node, ParseResult


def node(result: ParseResult, name: str) -> Node:
    matches = [n for n in result.nodes if n.name == name]
    assert matches, f"no node named {name!r}; have {[n.name for n in result.nodes]}"
    return matches[0]


def column(n: Node, name: str) -> Column:
    matches = [c for c in n.columns if c.name == name]
    assert matches, f"no column {name!r} on {n.name}; have {[c.name for c in n.columns]}"
    return matches[0]


def codes(result: ParseResult) -> list[str]:
    return [w.code for w in result.warnings]
```

`tests/test_graphical_metadata.py`:

```python
import hashlib

from conftest import FIXTURES, MAIN

from app.ir.models import (
    DataCategory, DataSourceKind, NodeType, ParameterKind, ParameterMapping, ViewType,
)

V = "GENERIC_TAX_REPORTING_CUBE"


def test_view_metadata_comes_from_root(parse_fixture):
    view = parse_fixture(MAIN).view
    assert view.id == V and view.name == V
    assert view.view_type is ViewType.GRAPHICAL
    assert view.data_category is DataCategory.CUBE
    assert view.schema_version == "2.3"
    assert view.file_hash == hashlib.sha256((FIXTURES / MAIN).read_bytes()).hexdigest()


def test_data_sources_are_parsed_and_become_nodes(parse_fixture):
    result = parse_fixture(MAIN)
    by_id = {d.id: d for d in result.data_sources}
    assert set(by_id) == {f"{V}/SOURCE_VIEW_01", f"{V}/TABLE_A", f"{V}/TABLE_B"}

    table_a = by_id[f"{V}/TABLE_A"]
    assert (table_a.kind, table_a.schema_name, table_a.name) == (DataSourceKind.TABLE, "SCHEMA_1", "TABLE_A")

    upstream = by_id[f"{V}/SOURCE_VIEW_01"]
    assert upstream.kind is DataSourceKind.CALC_VIEW
    assert upstream.name == "SOURCE_VIEW_01"
    assert upstream.resource_uri == "/pkg.synthetic/calculationviews/SOURCE_VIEW_01"

    ds_nodes = {n.id for n in result.nodes if n.node_type is NodeType.DATASOURCE}
    assert ds_nodes == set(by_id)


def test_parameters_and_variables(parse_fixture):
    params = {p.name: p for p in parse_fixture(MAIN).parameters}
    assert set(params) == {"IP_FISCAL_YEAR", "IP_RATE", "V_COMPANY"}

    year = params["IP_FISCAL_YEAR"]
    assert year.id == f"{V}/@param/IP_FISCAL_YEAR"
    assert (year.kind, year.datatype, year.length, year.mandatory) == (
        ParameterKind.INPUT_PARAMETER, "NVARCHAR", 4, True)

    rate = params["IP_RATE"]
    assert (rate.datatype, rate.length, rate.scale, rate.default, rate.mandatory) == (
        "DECIMAL", 5, 2, "1", False)

    assert params["V_COMPANY"].kind is ParameterKind.VARIABLE


def test_variable_mapping_links_local_parameter_to_upstream_view(parse_fixture):
    assert parse_fixture(MAIN).parameter_mappings == [
        ParameterMapping(view_id=V, data_source_id=f"{V}/SOURCE_VIEW_01",
                         target_parameter="IP_YEAR", local_parameter="IP_FISCAL_YEAR")
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_graphical_metadata.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.parsers.dispatch'`

- [ ] **Step 3: Implement dispatch**

`app/parsers/dispatch.py`:

```python
"""Parser entry point. Loads XML safely, routes by view type, never raises on input."""
from __future__ import annotations

import hashlib
from pathlib import Path

from app.ir.models import (
    DataCategory, IRWarning, ParseResult, ParseStatus, Severity, View, ViewType,
)
from app.parsers import xmlutil as x
from app.parsers.graphical import parse_graphical


def parse_file(path: Path, *, package_path: str | None = None) -> ParseResult:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return _failed(_stem(path.name), "", package_path, "READ_ERROR", str(exc))
    return parse_bytes(data, file_name=path.name, package_path=package_path)


def parse_bytes(data: bytes, *, file_name: str, package_path: str | None = None) -> ParseResult:
    stem = _stem(file_name)
    file_hash = hashlib.sha256(data).hexdigest()
    try:
        return _parse(data, stem, file_hash, package_path)
    except Exception as exc:  # the parser must never raise on an input file
        return _failed(stem, file_hash, package_path, "PARSER_CRASH", f"{type(exc).__name__}: {exc}")


def finalize(result: ParseResult) -> ParseResult:
    nodes = result.nodes
    understood = sum(1 for n in nodes if n.understood)
    result.view.coverage_pct = round(100 * understood / len(nodes), 1) if nodes else 0.0
    severities = {w.severity for w in result.warnings}
    if not nodes:
        result.view.parse_status = ParseStatus.FAILED
    elif severities & {Severity.WARNING, Severity.ERROR}:
        result.view.parse_status = ParseStatus.PARTIAL
    else:
        result.view.parse_status = ParseStatus.OK
    return result


def _parse(data: bytes, stem: str, file_hash: str, package_path: str | None) -> ParseResult:
    root, error, line = x.load(data)
    if root is None:
        # Fixed message: libxml2's wording and line numbers vary between lxml builds,
        # which would make golden files machine-dependent. The detail is still useful
        # interactively, so M5's UI can re-run x.load() to show it.
        return _failed(stem, file_hash, package_path, "XML_SYNTAX", "file is not well-formed XML")
    if x.local(root) != "scenario":
        return _failed(stem, file_hash, package_path, "NOT_A_SCENARIO",
                       f"root element is <{x.local(root)}>, expected <scenario>")

    view_id = root.get("id") or stem
    types = {x.xsi_type_name(cv) for cv in x.descendants(root, "calculationView")}
    view = View(
        id=view_id,
        name=view_id,
        package_path=package_path,
        view_type=ViewType.SCRIPTED if "SqlScriptView" in types else ViewType.GRAPHICAL,
        data_category=_category(root.get("dataCategory")),
        schema_version=root.get("schemaVersion"),
        file_hash=file_hash,
        parse_status=ParseStatus.OK,
        coverage_pct=0.0,
    )
    # M2 routes scripted views to app.parsers.scripted; until then SqlScriptView nodes
    # become opaque inside the graphical front end.
    return finalize(parse_graphical(root, view))


def _failed(stem: str, file_hash: str, package_path: str | None, code: str, message: str,
            line: int | None = None) -> ParseResult:
    view = View(id=stem, name=stem, package_path=package_path, view_type=ViewType.UNKNOWN,
                data_category=DataCategory.UNKNOWN, file_hash=file_hash,
                parse_status=ParseStatus.FAILED, coverage_pct=0.0)
    warning = IRWarning(view_id=stem, code=code, message=message, severity=Severity.ERROR, line=line)
    return ParseResult(view=view, warnings=[warning])


def _category(value: str | None) -> DataCategory:
    try:
        return DataCategory(value or "")
    except ValueError:
        return DataCategory.UNKNOWN


def _stem(file_name: str) -> str:
    return Path(file_name).name.split(".")[0]
```

- [ ] **Step 4: Implement the metadata half of the graphical front end**

`app/parsers/graphical.py`:

```python
"""Front end A: graphical calculation views (Calculation:scenario XML).

Elements are matched by local name and xsi:type by its local part, so the parser does
not depend on namespace prefixes or URIs. Anything not modelled raises a warning.
"""
from __future__ import annotations

from lxml import etree

from app.ir.models import (
    DataSource, DataSourceKind, Edge, IRWarning, Node, NodeType, Parameter, ParameterKind,
    ParameterMapping, ParseResult, Severity, View, make_id,
)
from app.parsers import xmlutil as x

DATASOURCE_KINDS = {
    "DATA_BASE_TABLE": DataSourceKind.TABLE,
    "CALCULATION_VIEW": DataSourceKind.CALC_VIEW,
    "TABLE_FUNCTION": DataSourceKind.TABLE_FUNCTION,
}


def parse_graphical(root: etree._Element, view: View) -> ParseResult:
    return _Builder(root, view).build()


class _Builder:
    def __init__(self, root: etree._Element, view: View):
        self.root = root
        self.view = view
        self.vid = view.id
        self.nodes: dict[str, Node] = {}  # keyed by the id used in "#ref" attributes
        self.edges: list[Edge] = []
        self.params: dict[str, Parameter] = {}
        self.param_maps: list[ParameterMapping] = []
        self.sources: list[DataSource] = []
        self.warnings: list[IRWarning] = []

    def build(self) -> ParseResult:
        self._parse_parameters()
        self._parse_data_sources()
        self._parse_variable_mappings()
        return self._result()

    def _result(self) -> ParseResult:
        return ParseResult(
            view=self.view,
            nodes=list(self.nodes.values()),
            edges=self.edges,
            parameters=list(self.params.values()),
            parameter_mappings=self.param_maps,
            data_sources=self.sources,
            warnings=self.warnings,
        )

    def warn(self, code: str, message: str, *, el: etree._Element | None = None,
             node_id: str | None = None, severity: Severity = Severity.WARNING) -> None:
        self.warnings.append(IRWarning(
            view_id=self.vid, node_id=node_id, code=code, message=message, severity=severity,
            line=el.sourceline if el is not None else None,
        ))

    def _parse_parameters(self) -> None:
        for var in x.children(x.child(self.root, "localVariables"), "variable"):
            name = var.get("id") or ""
            props = x.child(var, "variableProperties")
            attrs = props.attrib if props is not None else {}
            default = attrs.get("defaultValue")
            if default is None:
                default_range = x.child(props, "defaultRange")
                default = default_range.get("lowValue") if default_range is not None else None
            self.params[name] = Parameter(
                id=make_id(self.vid, "@param", name),
                view_id=self.vid,
                name=name,
                kind=ParameterKind.INPUT_PARAMETER if var.get("parameter") == "true" else ParameterKind.VARIABLE,
                datatype=attrs.get("datatype"),
                length=_int(attrs.get("length")),
                scale=_int(attrs.get("scale")),
                default=default,
                mandatory=attrs.get("mandatory") == "true",
            )

    def _parse_data_sources(self) -> None:
        for ds in x.children(x.child(self.root, "dataSources"), "DataSource"):
            ds_id = ds.get("id") or ""
            node_id = make_id(self.vid, ds_id)
            kind = DATASOURCE_KINDS.get(ds.get("type") or "", DataSourceKind.UNKNOWN)
            if kind is DataSourceKind.UNKNOWN:
                self.warn("UNKNOWN_DATASOURCE_TYPE", f"data source {ds_id!r} has type {ds.get('type')!r}",
                          el=ds, node_id=node_id)
            column_object = x.child(ds, "columnObject")
            uri = x.text(x.child(ds, "resourceUri"))
            if column_object is not None:
                schema_name, name = column_object.get("schemaName"), column_object.get("columnObjectName") or ds_id
            else:
                schema_name, name = None, uri.rpartition("/")[2] if uri else ds_id
            self.sources.append(DataSource(id=node_id, kind=kind, schema_name=schema_name, name=name,
                                           resource_uri=uri))
            self.nodes[ds_id] = Node(id=node_id, view_id=self.vid, node_type=NodeType.DATASOURCE,
                                     name=ds_id, raw=x.raw(ds), understood=kind is not DataSourceKind.UNKNOWN)

    def _parse_variable_mappings(self) -> None:
        for m in x.children(x.child(self.root, "variableMappings"), "mapping"):
            ds_ref = _ref(m.get("dataSource"))
            target = x.child(m, "targetVariable")
            local_ref = x.text(x.child(m, "localVariable"))
            local_name = _ref(local_ref) if local_ref else None
            if ds_ref not in self.nodes:
                self.warn("UNRESOLVED_VARIABLE_MAPPING", f"variable mapping names unknown data source #{ds_ref}", el=m)
            if local_name is not None and local_name not in self.params:
                self.warn("UNKNOWN_PARAMETER_REF", f"variable mapping names unknown parameter #{local_name}", el=m)
            self.param_maps.append(ParameterMapping(
                view_id=self.vid,
                data_source_id=make_id(self.vid, ds_ref),
                target_parameter=(target.get("name") or "") if target is not None else "",
                local_parameter=local_name,
                constant=m.get("value"),
            ))


def _ref(value: str | None) -> str:
    return (value or "").removeprefix("#")


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_graphical_metadata.py -q`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add app/parsers/dispatch.py app/parsers/graphical.py tests/helpers.py tests/test_graphical_metadata.py
git commit -m "feat(m1): dispatch with never-raise guard; parse data sources, parameters, variable mappings"
```

---

### Task 7: Calculation-view nodes, edges, joins, unions, calculated columns, filters

**Files:**
- Modify: `app/parsers/graphical.py` (imports, constants, `_Builder.__init__`, `_Builder.build`, plus new methods)
- Create: `tests/test_graphical_nodes.py`

**Interfaces:**
- Consumes: `parse_expression`, `ExprParseError` (Task 5) and the `_Builder` from Task 6
- Produces: nodes for every `calculationView`, `Edge`s from every `<input>`, `Node.join`, `Node.filters`, calculated columns with `Expression`s, and `Parameter.used_in`. Task 8 calls the new `_Builder._calculated_columns(container, tag, node, kind)`, `_Builder._check_children(el, known, node_id)` and `_Builder._record_parameter_usage()` again.

- [ ] **Step 1: Write the failing tests**

`tests/test_graphical_nodes.py`:

```python
from conftest import MAIN
from helpers import codes, column, node

from app.ir.models import (
    ColumnKind, ColumnMapItem, ExpressionLang, JoinCondition, NodeType, ParamUsage,
)

V = "GENERIC_TAX_REPORTING_CUBE"


def test_calculation_views_become_typed_nodes(parse_fixture):
    result = parse_fixture(MAIN)
    types = {n.name: n.node_type for n in result.nodes if n.node_type is not NodeType.DATASOURCE}
    expected = {
        "Projection_1": NodeType.PROJECTION,
        "Join_1": NodeType.JOIN,
        "Union_1": NodeType.UNION,
        "Aggregation_1": NodeType.AGGREGATION,
    }
    assert expected.items() <= types.items()  # Task 8 tightens this to an exact match


def test_inputs_become_edges(parse_fixture):
    pairs = {(e.from_node.split("/")[1], e.to_node.split("/")[1]) for e in parse_fixture(MAIN).edges}
    assert {
        ("SOURCE_VIEW_01", "Projection_1"),
        ("Projection_1", "Join_1"),
        ("TABLE_A", "Join_1"),
        ("Join_1", "Union_1"),
        ("TABLE_B", "Union_1"),
        ("Union_1", "Aggregation_1"),
    } <= pairs


def test_edge_carries_column_mappings_and_union_constants(parse_fixture):
    edges = {(e.from_node, e.to_node): e for e in parse_fixture(MAIN).edges}
    from_b = edges[(f"{V}/TABLE_B", f"{V}/Union_1")].column_map
    assert ColumnMapItem(target="COL_1", source="COL_1") in from_b
    assert ColumnMapItem(target="COL_5", constant="SRC_B") in from_b
    assert ColumnMapItem(target="CC_1", null=True) in from_b


def test_join_spec(parse_fixture):
    join = node(parse_fixture(MAIN), "Join_1").join
    assert join.join_type == "leftOuter"
    assert join.cardinality == "CN_1"
    assert join.left_node == f"{V}/Projection_1"
    assert join.right_node == f"{V}/TABLE_A"
    assert join.conditions == [JoinCondition(column="COL_1")]
    assert join.special is False


def test_view_attributes_and_aggregation(parse_fixture):
    agg = node(parse_fixture(MAIN), "Aggregation_1")
    assert column(agg, "AMT_1").kind is ColumnKind.MEASURE
    assert column(agg, "AMT_1").aggregation == "sum"
    assert column(agg, "COL_1").kind is ColumnKind.ATTRIBUTE
    assert column(agg, "COL_1").id == f"{V}/Aggregation_1/COL_1"


def test_calculated_column_keeps_text_and_ast(parse_fixture):
    cc = column(node(parse_fixture(MAIN), "Projection_1"), "CC_1")
    assert (cc.datatype, cc.length, cc.scale) == ("DECIMAL", 15, 2)
    assert cc.expression.text == "if(\"COL_2\" = 'X', \"AMT_1\", 0)"
    assert cc.expression.lang is ExpressionLang.COLUMN_ENGINE
    assert cc.expression.ast.kind == "call" and cc.expression.ast.value == "if"


def test_filter_is_parsed(parse_fixture):
    filters = node(parse_fixture(MAIN), "Projection_1").filters
    assert len(filters) == 1
    assert filters[0].expression.ast.args[1].kind == "param"


def test_parameter_usage_distinguishes_filter_from_calculation(parse_fixture):
    params = {p.name: p for p in parse_fixture(MAIN).parameters}
    assert [(u.node_id, u.usage) for u in params["IP_FISCAL_YEAR"].used_in] == [
        (f"{V}/Projection_1", ParamUsage.FILTER)]
    assert [(u.node_id, u.usage) for u in params["IP_RATE"].used_in] == [
        (f"{V}/Aggregation_1", ParamUsage.CALCULATION)]
    assert params["V_COMPANY"].used_in == []


def test_unknown_node_type_is_opaque_but_stays_connected(parse_fixture):
    result = parse_fixture("malformed/unknown_type.calculationview")
    fancy = node(result, "Fancy_1")
    assert fancy.node_type is NodeType.OPAQUE
    assert fancy.understood is False
    assert "FancyNewView" in fancy.raw
    assert codes(result) == ["UNKNOWN_NODE_TYPE"]
    assert any(e.from_node.endswith("/Projection_1") and e.to_node.endswith("/Fancy_1") for e in result.edges)


def test_unparseable_expression_is_kept_and_flagged(parse_fixture):
    result = parse_fixture("malformed/bad_expression.calculationview")
    projection = node(result, "Projection_1")
    cc = column(projection, "CC_1")
    assert cc.expression.text == "if(\"COL_1\" = 'X', 1"
    assert cc.expression.ast is None
    assert projection.understood is False
    assert codes(result) == ["EXPR_PARSE_FAILED"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_graphical_nodes.py -q`
Expected: FAIL. `test_calculation_views_become_typed_nodes` fails because only datasource nodes exist, and the others fail with `AssertionError: no node named 'Join_1'` and similar.

- [ ] **Step 3: Extend the imports and constants in `app/parsers/graphical.py`**

Replace the import block and the constants with:

```python
import re

from lxml import etree

from app.ir.models import (
    Column, ColumnKind, ColumnMapItem, DataSource, DataSourceKind, Edge, Expression,
    ExpressionLang, Filter, IRWarning, JoinCondition, JoinSpec, Node, NodeType, Parameter,
    ParameterKind, ParameterMapping, ParameterUse, ParamUsage, ParseResult, Severity, View,
    make_id,
)
from app.parsers import xmlutil as x
from app.parsers.expressions import ExprParseError, parse_expression

DATASOURCE_KINDS = {
    "DATA_BASE_TABLE": DataSourceKind.TABLE,
    "CALCULATION_VIEW": DataSourceKind.CALC_VIEW,
    "TABLE_FUNCTION": DataSourceKind.TABLE_FUNCTION,
}
NODE_TYPES = {
    "ProjectionView": NodeType.PROJECTION,
    "JoinView": NodeType.JOIN,
    "AggregationView": NodeType.AGGREGATION,
    "UnionView": NodeType.UNION,
    "RankView": NodeType.RANK,
}
KNOWN_CALCVIEW_CHILDREN = {
    "descriptions", "viewAttributes", "calculatedViewAttributes", "input", "filter", "joinAttribute",
}
SPECIAL_JOIN_TYPES = {"referential", "textTable"}
PARAM_RE = re.compile(r"\$\$(\w+)\$\$")
```

- [ ] **Step 4: Extend `_Builder.__init__` and `build`**

Add this as the last line of `__init__`:

```python
        self._pending_inputs: list[tuple[Node, etree._Element]] = []
```

Replace `build` with:

```python
    def build(self) -> ParseResult:
        self._parse_parameters()
        self._parse_data_sources()
        self._parse_calculation_views()
        self._resolve_inputs()
        self._parse_variable_mappings()
        self._record_parameter_usage()
        return self._result()
```

- [ ] **Step 5: Add the calculation-view methods to `_Builder`**

```python
    def _calculation_view_elements(self) -> list[etree._Element]:
        wrapper = x.child(self.root, "calculationViews")
        return x.children(wrapper if wrapper is not None else self.root, "calculationView")

    def _parse_calculation_views(self) -> None:
        for cv in self._calculation_view_elements():
            name = cv.get("id") or ""
            node_id = make_id(self.vid, name)
            type_name = x.xsi_type_name(cv)
            node_type = NODE_TYPES.get(type_name or "")
            if node_type is None:
                code = "SCRIPTED_DEFERRED" if type_name == "SqlScriptView" else "UNKNOWN_NODE_TYPE"
                self.warn(code, f"calculationView {name!r} has type {type_name!r}; kept as an opaque node",
                          el=cv, node_id=node_id)
                node = Node(id=node_id, view_id=self.vid, node_type=NodeType.OPAQUE, name=name,
                            raw=x.raw(cv), understood=False)
            else:
                node = self._parse_node(cv, node_id, name, node_type)
            self.nodes[name] = node
            self._pending_inputs.extend((node, inp) for inp in x.children(cv, "input"))

    def _parse_node(self, cv: etree._Element, node_id: str, name: str, node_type: NodeType) -> Node:
        node = Node(id=node_id, view_id=self.vid, node_type=node_type, name=name, raw=x.raw(cv))
        self._check_children(cv, KNOWN_CALCVIEW_CHILDREN, node_id)
        node.columns.extend(self._view_attributes(cv, node_id))
        node.columns.extend(self._calculated_columns(
            x.child(cv, "calculatedViewAttributes"), "calculatedViewAttribute", node, ColumnKind.ATTRIBUTE))
        for f in x.children(cv, "filter"):
            text = x.text(f)
            if text:
                node.filters.append(Filter(expression=self._expression(text, f.get("expressionLanguage"), node, "filter")))
        if node_type is NodeType.JOIN:
            node.join = self._join_spec(cv, node_id)
        if node_type is NodeType.RANK:
            self.warn("RANK_NODE", f"{name} is a rank node; partition logic needs review in codegen",
                      el=cv, node_id=node_id, severity=Severity.INFO)
        return node

    def _view_attributes(self, cv: etree._Element, node_id: str) -> list[Column]:
        columns = []
        for va in x.children(x.child(cv, "viewAttributes"), "viewAttribute"):
            name = va.get("id") or ""
            aggregation = va.get("aggregationType")
            columns.append(Column(
                id=make_id(node_id, name), name=name, datatype=va.get("datatype"),
                length=_int(va.get("length")), scale=_int(va.get("scale")),
                kind=ColumnKind.MEASURE if aggregation else ColumnKind.ATTRIBUTE, aggregation=aggregation,
            ))
        return columns

    def _calculated_columns(self, container: etree._Element | None, tag: str, node: Node,
                            kind: ColumnKind) -> list[Column]:
        columns = []
        for ca in x.children(container, tag):
            name = ca.get("id") or ""
            formula = x.first_descendant(ca, "formula")
            # Datatype sits on the element itself, or on the formula's parent (e.g. keyCalculation).
            spec = ca if ca.get("datatype") is not None or formula is None else formula.getparent()
            columns.append(Column(
                id=make_id(node.id, name), name=name, datatype=spec.get("datatype"),
                length=_int(spec.get("length")), scale=_int(spec.get("scale")),
                kind=kind, aggregation=ca.get("aggregationType"),
                expression=self._expression(x.text(formula) or "", spec.get("expressionLanguage"),
                                            node, f"column {name}"),
            ))
        return columns

    def _expression(self, text: str, lang_attr: str | None, node: Node, where: str) -> Expression:
        lang = ExpressionLang.SQL if (lang_attr or "").upper() == "SQL" else ExpressionLang.COLUMN_ENGINE
        expr = Expression(text=text, lang=lang)
        if lang is ExpressionLang.SQL:
            self.warn("SQL_EXPR_DEFERRED", f"{node.name} {where}: SQL expression kept as text until M2",
                      node_id=node.id, severity=Severity.INFO)
            return expr
        try:
            expr.ast = parse_expression(text)
        except ExprParseError as exc:
            node.understood = False
            self.warn("EXPR_PARSE_FAILED", f"{node.name} {where}: {exc}", node_id=node.id)
        return expr

    def _join_spec(self, cv: etree._Element, node_id: str) -> JoinSpec:
        refs = [_ref(i.get("node")) for i in x.children(cv, "input")]
        if len(refs) != 2:
            self.warn("JOIN_INPUT_COUNT", f"join has {len(refs)} inputs, expected 2", el=cv, node_id=node_id)
        join_type = cv.get("joinType") or "inner"
        spec = JoinSpec(
            join_type=join_type,
            cardinality=cv.get("cardinality"),
            left_node=make_id(self.vid, refs[0]) if len(refs) > 0 else None,
            right_node=make_id(self.vid, refs[1]) if len(refs) > 1 else None,
            conditions=[JoinCondition(column=j.get("name") or "") for j in x.children(cv, "joinAttribute")],
            special=join_type in SPECIAL_JOIN_TYPES,
        )
        if spec.special:
            self.warn("SPECIAL_JOIN", f"{join_type} join needs special semantics in codegen",
                      el=cv, node_id=node_id, severity=Severity.INFO)
        return spec

    def _resolve_inputs(self) -> None:
        for node, inp in self._pending_inputs:
            ref = _ref(inp.get("node"))
            source = self.nodes.get(ref)
            if source is None:
                node.understood = False
                self.warn("UNRESOLVED_INPUT", f"{node.name} reads #{ref}, which is not in this view",
                          el=inp, node_id=node.id)
                continue
            self.edges.append(Edge(from_node=source.id, to_node=node.id, column_map=self._mappings(inp, node.id)))

    def _mappings(self, inp: etree._Element, node_id: str) -> list[ColumnMapItem]:
        items = []
        for m in x.children(inp, "mapping"):
            target = m.get("target") or ""
            if x.xsi_type_name(m) == "ConstantAttributeMapping":
                is_null = m.get("null") == "true"
                items.append(ColumnMapItem(target=target, constant=None if is_null else m.get("value"), null=is_null))
            elif m.get("source") is not None:
                items.append(ColumnMapItem(target=target, source=m.get("source")))
            else:
                self.warn("UNKNOWN_MAPPING", f"mapping to {target!r} has no source or constant",
                          el=m, node_id=node_id)
        return items

    def _record_parameter_usage(self) -> None:
        for node in self.nodes.values():
            uses = [(f.expression.text, ParamUsage.FILTER) for f in node.filters]
            uses += [(c.expression.text, ParamUsage.CALCULATION) for c in node.columns if c.expression]
            for text, usage in uses:
                for name in PARAM_RE.findall(text):
                    param = self.params.get(name)
                    if param is None:
                        self.warn("UNKNOWN_PARAMETER_REF", f"{node.name} references $${name}$$", node_id=node.id)
                        continue
                    use = ParameterUse(node_id=node.id, usage=usage)
                    if use not in param.used_in:
                        param.used_in.append(use)

    def _check_children(self, el: etree._Element, known: set[str], node_id: str | None) -> None:
        for c in x.children(el):
            if x.local(c) not in known:
                self.warn("UNKNOWN_ELEMENT", f"<{x.local(c)}> inside <{x.local(el)}> is not modelled",
                          el=c, node_id=node_id)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_graphical_nodes.py tests/test_graphical_metadata.py -q`
Expected: all passed (10 + 4)

- [ ] **Step 7: Commit**

```bash
git add app/parsers/graphical.py tests/test_graphical_nodes.py
git commit -m "feat(m1): parse calculation-view nodes, edges, joins, unions, expressions, parameter usage"
```

---

### Task 8: Output layer (`logicalModel`), root-level checks, coverage and status

**Files:**
- Modify: `app/parsers/graphical.py` (constants, `build`, new methods and helpers), `tests/test_graphical_nodes.py` (simplify the first test)
- Create: `tests/test_graphical_output.py`

**Interfaces:**
- Consumes: `_calculated_columns`, `_check_children`, `_record_parameter_usage` (Task 7) and `finalize` (Task 6)
- Produces: the `Semantics` output node and its incoming edge. After this task, `parse_status` and `coverage_pct` are meaningful for every fixture.

- [ ] **Step 1: Tighten the node-type test and write the failing tests**

In `tests/test_graphical_nodes.py`, replace `test_calculation_views_become_typed_nodes` with this exact-match version:

```python
def test_calculation_views_become_typed_nodes(parse_fixture):
    result = parse_fixture(MAIN)
    types = {n.name: n.node_type for n in result.nodes if n.node_type is not NodeType.DATASOURCE}
    assert types == {
        "Projection_1": NodeType.PROJECTION,
        "Join_1": NodeType.JOIN,
        "Union_1": NodeType.UNION,
        "Aggregation_1": NodeType.AGGREGATION,
        "Semantics": NodeType.OUTPUT,
    }
```

`tests/test_graphical_output.py`:

```python
import pytest
from conftest import MAIN
from helpers import codes, column, node

from app.ir.models import ColumnKind, ColumnMapItem, NodeType, ParamUsage, ParseStatus, ViewType
from app.parsers.dispatch import parse_bytes

V = "GENERIC_TAX_REPORTING_CUBE"
NS = ('xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
      'xmlns:Calculation="http://www.sap.com/ndb/BiModelCalculation.ecore"')
NO_WRAPPER = f"""<?xml version="1.0" encoding="UTF-8"?>
<Calculation:scenario {NS} schemaVersion="2.3" id="NO_WRAPPER" dataCategory="DIMENSION">
  <dataSources>
    <DataSource id="TABLE_A" type="DATA_BASE_TABLE">
      <columnObject schemaName="SCHEMA_1" columnObjectName="TABLE_A"/>
    </DataSource>
  </dataSources>
  <calculationView xsi:type="Calculation:ProjectionView" id="Projection_1">
    <viewAttributes><viewAttribute id="COL_1"/></viewAttributes>
    <input node="#TABLE_A"><mapping xsi:type="Calculation:AttributeMapping" target="COL_1" source="COL_1"/></input>
  </calculationView>
  <logicalModel id="Projection_1">
    <attributes><attribute id="COL_1"><keyMapping columnObjectName="Projection_1" columnName="COL_1"/></attribute></attributes>
  </logicalModel>
  EXTRA
</Calculation:scenario>"""
SCRIPTED_STUB = f"""<?xml version="1.0" encoding="UTF-8"?>
<Calculation:scenario {NS} schemaVersion="2.3" id="SCRIPTED_STUB" dataCategory="CUBE">
  <calculationViews>
    <calculationView xsi:type="Calculation:SqlScriptView" id="Script_View">
      <viewAttributes><viewAttribute id="COL_1"/></viewAttributes>
      <definition>BEGIN var_out = SELECT "COL_1" FROM "SCHEMA_1"."TABLE_A"; END</definition>
    </calculationView>
  </calculationViews>
  <logicalModel id="Script_View">
    <attributes><attribute id="COL_1"><keyMapping columnObjectName="Script_View" columnName="COL_1"/></attribute></attributes>
  </logicalModel>
</Calculation:scenario>"""


def parse_text(text: str):
    return parse_bytes(text.encode(), file_name="inline.calculationview")


def test_logical_model_becomes_semantics_node(parse_fixture):
    semantics = node(parse_fixture(MAIN), "Semantics")
    assert semantics.node_type is NodeType.OUTPUT
    assert semantics.id == f"{V}/Semantics"
    assert [c.name for c in semantics.columns] == ["COL_1", "COL_3", "COL_5", "AMT_1", "CC_1", "CC_2", "CM_1"]
    assert column(semantics, "COL_1").kind is ColumnKind.ATTRIBUTE
    assert column(semantics, "AMT_1").kind is ColumnKind.MEASURE
    assert column(semantics, "AMT_1").aggregation == "sum"


def test_calculated_measure_has_expression(parse_fixture):
    cm = column(node(parse_fixture(MAIN), "Semantics"), "CM_1")
    assert cm.kind is ColumnKind.MEASURE
    assert cm.expression.text == '"AMT_1" - "CC_1"'
    assert cm.expression.ast.value == "-"


def test_semantics_edge_carries_key_and_measure_mappings(parse_fixture):
    edges = [e for e in parse_fixture(MAIN).edges if e.to_node == f"{V}/Semantics"]
    assert len(edges) == 1
    assert edges[0].from_node == f"{V}/Aggregation_1"
    assert [m.target for m in edges[0].column_map] == ["COL_1", "COL_3", "COL_5", "AMT_1", "CC_1", "CC_2"]
    assert ColumnMapItem(target="CC_2", source="CC_2") in edges[0].column_map


def test_main_fixture_is_fully_understood(parse_fixture):
    result = parse_fixture(MAIN)
    assert codes(result) == []
    assert result.view.parse_status is ParseStatus.OK
    assert result.view.coverage_pct == 100.0
    assert len(result.nodes) == 8
    assert len(result.edges) == 7


@pytest.mark.parametrize("rel, status, coverage, expected_codes", [
    ("malformed/truncated.calculationview", ParseStatus.FAILED, 0.0, ["XML_SYNTAX"]),
    ("malformed/unknown_type.calculationview", ParseStatus.PARTIAL, 75.0, ["UNKNOWN_NODE_TYPE"]),
    ("malformed/bad_expression.calculationview", ParseStatus.PARTIAL, 66.7, ["EXPR_PARSE_FAILED"]),
])
def test_malformed_fixtures_degrade_gracefully(parse_fixture, rel, status, coverage, expected_codes):
    result = parse_fixture(rel)
    assert result.view.parse_status is status
    assert result.view.coverage_pct == coverage
    assert codes(result) == expected_codes


def test_calculation_views_without_wrapper_are_parsed():
    result = parse_text(NO_WRAPPER.replace("EXTRA", ""))
    assert codes(result) == []
    assert node(result, "Projection_1").node_type is NodeType.PROJECTION
    assert {(e.from_node, e.to_node) for e in result.edges} == {
        ("NO_WRAPPER/TABLE_A", "NO_WRAPPER/Projection_1"),
        ("NO_WRAPPER/Projection_1", "NO_WRAPPER/Semantics"),
    }


def test_unknown_root_element_is_reported_not_dropped():
    result = parse_text(NO_WRAPPER.replace("EXTRA", "<executionHints/>"))
    assert codes(result) == ["UNKNOWN_ELEMENT"]
    assert "executionHints" in result.warnings[0].message
    assert result.view.parse_status is ParseStatus.PARTIAL


def test_non_empty_private_data_foundation_is_flagged():
    text = NO_WRAPPER.replace("EXTRA", "").replace(
        "</attributes>",
        "</attributes><privateDataFoundation><tableProxies><tableProxy/></tableProxies></privateDataFoundation>",
    )
    result = parse_text(text)
    assert codes(result) == ["PRIVATE_DATA_FOUNDATION_DEFERRED"]
    assert node(result, "Semantics").understood is False


def test_missing_logical_model_is_an_error():
    text = NO_WRAPPER.replace("EXTRA", "")
    text = text[: text.index("<logicalModel")] + text[text.index("</logicalModel>") + len("</logicalModel>"):]
    result = parse_text(text)
    assert codes(result) == ["MISSING_LOGICAL_MODEL"]


def test_scripted_view_is_detected_and_kept_opaque_until_m2():
    result = parse_text(SCRIPTED_STUB)
    assert result.view.view_type is ViewType.SCRIPTED
    assert node(result, "Script_View").node_type is NodeType.OPAQUE
    assert codes(result) == ["SCRIPTED_DEFERRED"]
    assert ("SCRIPTED_STUB/Script_View", "SCRIPTED_STUB/Semantics") in {(e.from_node, e.to_node) for e in result.edges}


def test_calculated_measure_parameter_usage_is_recorded():
    text = NO_WRAPPER.replace("EXTRA", "").replace(
        '<dataSources>',
        '<localVariables><variable id="IP_X" parameter="true"><variableProperties datatype="INTEGER"/></variable></localVariables><dataSources>',
    ).replace(
        "</attributes>",
        '</attributes><calculatedMeasures><measure id="CM_1" aggregationType="sum" datatype="INTEGER">'
        '<formula>$$IP_X$$ * 2</formula></measure></calculatedMeasures>',
    )
    params = parse_text(text).parameters
    assert [(u.node_id, u.usage) for u in params[0].used_in] == [("NO_WRAPPER/Semantics", ParamUsage.CALCULATION)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_graphical_output.py tests/test_graphical_nodes.py -q`
Expected: FAIL. There is no node named `'Semantics'`. Coverage is wrong for the unknown_type fixture (66.7, not 75.0) and the bad_expression fixture (50.0, not 66.7), and `UNKNOWN_ELEMENT` and `MISSING_LOGICAL_MODEL` aren't raised yet.

- [ ] **Step 3: Add the constants to `app/parsers/graphical.py`**

Add these below `PARAM_RE`:

```python
OUTPUT_NODE_NAME = "Semantics"
HANDLED_ROOT_CHILDREN = {
    "localVariables", "variableMappings", "dataSources", "calculationViews", "calculationView", "logicalModel",
}
# Root children that carry no logic: editor metadata and diagram positions.
IGNORED_ROOT_CHILDREN = {"origin", "descriptions", "metadata", "layout"}
KNOWN_LOGICAL_MODEL_CHILDREN = {
    "descriptions", "attributes", "calculatedAttributes", "privateDataFoundation",
    "baseMeasures", "calculatedMeasures", "restrictedMeasures", "localDimensions",
}
# Containers that may appear empty inside deferred blocks without meaning anything.
EMPTY_CONTAINER_PARTS = {"tableProxies", "joins", "layout", "shapes", "shape", "upperLeftCorner", "rectangleSize"}
DEFERRED_LOGICAL_MODEL_BLOCKS = {
    "privateDataFoundation": "PRIVATE_DATA_FOUNDATION_DEFERRED",
    "restrictedMeasures": "RESTRICTED_MEASURES_DEFERRED",
    "localDimensions": "LOCAL_DIMENSIONS_DEFERRED",
}
```

- [ ] **Step 4: Update `build` and add the output-layer methods**

Replace `build` with:

```python
    def build(self) -> ParseResult:
        self._check_children(self.root, HANDLED_ROOT_CHILDREN | IGNORED_ROOT_CHILDREN, None)
        self._parse_parameters()
        self._parse_data_sources()
        self._parse_calculation_views()
        self._resolve_inputs()
        self._parse_logical_model()
        self._parse_variable_mappings()
        self._record_parameter_usage()
        return self._result()
```

Add these methods to `_Builder`:

```python
    def _parse_logical_model(self) -> None:
        lm = x.child(self.root, "logicalModel")
        if lm is None:
            self.warn("MISSING_LOGICAL_MODEL", "no <logicalModel>; the view has no output layer",
                      severity=Severity.ERROR)
            return
        node = Node(id=make_id(self.vid, OUTPUT_NODE_NAME), view_id=self.vid, node_type=NodeType.OUTPUT,
                    name=OUTPUT_NODE_NAME, raw=x.raw(lm))
        self._check_children(lm, KNOWN_LOGICAL_MODEL_CHILDREN, node.id)

        column_map: list[ColumnMapItem] = []
        for attr in x.children(x.child(lm, "attributes"), "attribute"):
            name = attr.get("id") or ""
            node.columns.append(Column(id=make_id(node.id, name), name=name, kind=ColumnKind.ATTRIBUTE))
            column_map.extend(_output_mapping(x.child(attr, "keyMapping"), name))
        for measure in x.children(x.child(lm, "baseMeasures"), "measure"):
            name = measure.get("id") or ""
            node.columns.append(Column(id=make_id(node.id, name), name=name, kind=ColumnKind.MEASURE,
                                       aggregation=measure.get("aggregationType")))
            column_map.extend(_output_mapping(x.child(measure, "measureMapping"), name))
        node.columns.extend(self._calculated_columns(
            x.child(lm, "calculatedAttributes"), "calculatedAttribute", node, ColumnKind.ATTRIBUTE))
        node.columns.extend(self._calculated_columns(
            x.child(lm, "calculatedMeasures"), "measure", node, ColumnKind.MEASURE))

        for tag, code in DEFERRED_LOGICAL_MODEL_BLOCKS.items():
            block = x.child(lm, tag)
            if block is not None and _has_content(block):
                node.understood = False
                self.warn(code, f"<{tag}> has content that is not modelled yet", el=block, node_id=node.id)

        top_ref = lm.get("id") or ""
        top = self.nodes.get(top_ref)
        self.nodes[OUTPUT_NODE_NAME] = node
        if top is None:
            node.understood = False
            self.warn("UNRESOLVED_INPUT", f"logicalModel reads #{top_ref}, which is not in this view",
                      el=lm, node_id=node.id)
            return
        self.edges.append(Edge(from_node=top.id, to_node=node.id, column_map=column_map))
```

Add these module-level helpers next to `_ref` and `_int`:

```python
def _output_mapping(mapping: etree._Element | None, target: str) -> list[ColumnMapItem]:
    if mapping is None:
        return []
    return [ColumnMapItem(target=target, source=mapping.get("columnName"))]


def _has_content(el: etree._Element) -> bool:
    return any(x.local(d) not in EMPTY_CONTAINER_PARTS
               for d in el.iterdescendants() if isinstance(d.tag, str))
```

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add app/parsers/graphical.py tests/test_graphical_nodes.py tests/test_graphical_output.py
git commit -m "feat(m1): parse logicalModel into Semantics node; root checks; coverage and status"
```

---

### Task 9: Never-raise hardening and golden IR snapshots

**Files:**
- Create: `tests/test_never_raises.py`, `tests/test_golden_ir.py`, and four `fixtures/synthetic/**/<stem>.ir.json` golden files (generated, then reviewed by hand)

**Interfaces:**
- Consumes: `app.parsers.dispatch` (Tasks 6–8)
- Produces: the golden regression guard that the CLAUDE.md "update golden files in the same commit" rule refers to

- [ ] **Step 1: Write the never-raise tests**

`tests/test_never_raises.py`:

```python
import pytest
from conftest import FIXTURES, MAIN

import app.parsers.dispatch as dispatch
from app.ir.models import ParseResult, ParseStatus, Severity


@pytest.mark.parametrize("data", [
    b"",
    b"not xml at all",
    b"<a>",
    b"\xff\xfe\x00\x01",
    b"<?xml version='1.0'?><other/>",
    b"<?xml version='1.0'?><!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><x>&e;</x>",
])
def test_garbage_yields_a_failed_result(data):
    result = dispatch.parse_bytes(data, file_name="junk.calculationview")
    assert result.view.parse_status is ParseStatus.FAILED
    assert result.warnings and result.warnings[0].severity is Severity.ERROR


def test_every_truncation_of_the_main_fixture_returns_a_result():
    data = (FIXTURES / MAIN).read_bytes()
    for cut in range(0, len(data), 53):
        assert isinstance(dispatch.parse_bytes(data[:cut], file_name="cut.calculationview"), ParseResult)


def test_internal_bug_becomes_a_parser_crash_warning(monkeypatch):
    def boom(root, view):
        raise RuntimeError("simulated bug")

    monkeypatch.setattr(dispatch, "parse_graphical", boom)
    result = dispatch.parse_bytes((FIXTURES / MAIN).read_bytes(), file_name="x.calculationview")
    assert result.view.parse_status is ParseStatus.FAILED
    assert result.warnings[-1].code == "PARSER_CRASH"
    assert "simulated bug" in result.warnings[-1].message


def test_unreadable_file_becomes_a_read_error(tmp_path):
    result = dispatch.parse_file(tmp_path / "missing.calculationview")
    assert result.warnings[0].code == "READ_ERROR"
```

The DOCTYPE case checks that external entities are never resolved. `resolve_entities=False` leaves the root as `<x>`, so the result is `NOT_A_SCENARIO`, which is also `FAILED`.

- [ ] **Step 2: Run them**

Run: `pytest tests/test_never_raises.py -q`
Expected: 9 passed. These should pass straight away, because the guard was built in Task 6. If any fails, debug it with superpowers:systematic-debugging before continuing.

- [ ] **Step 3: Write the golden test**

`tests/test_golden_ir.py`:

```python
"""Golden IR snapshots. A regression guard, not the primary check: the hand-written
assertions in test_graphical_*.py define correctness. Regenerate with
UPDATE_GOLDEN=1 pytest tests/test_golden_ir.py, then review the diff by hand."""
import os

import pytest
from conftest import FIXTURES

from app.parsers.dispatch import parse_bytes

CASES = sorted(FIXTURES.rglob("*.calculationview"))


def test_fixture_set_is_not_empty():
    assert len(CASES) >= 4


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_ir_matches_golden(path):
    actual = parse_bytes(path.read_bytes(), file_name=path.name).model_dump_json(indent=2) + "\n"
    golden = path.with_name(f"{path.stem}.ir.json")
    if os.environ.get("UPDATE_GOLDEN") == "1":
        golden.write_bytes(actual.encode("utf-8"))
    assert golden.exists(), f"missing {golden.name}; run UPDATE_GOLDEN=1 pytest tests/test_golden_ir.py and review it"
    assert actual == golden.read_text(encoding="utf-8")
```

- [ ] **Step 4: Run it to verify it fails**

Run: `pytest tests/test_golden_ir.py -q`
Expected: 4 FAILED with `missing GENERIC_TAX_REPORTING_CUBE.ir.json …`

- [ ] **Step 5: Generate the golden files**

Run: `UPDATE_GOLDEN=1 pytest tests/test_golden_ir.py -q`
Expected: 5 passed. The run writes four `.ir.json` files.

- [ ] **Step 6: Review the golden files by hand. Do not skip this step.**

Open `fixtures/synthetic/graphical/GENERIC_TAX_REPORTING_CUBE.ir.json` and check:
- `view.parse_status` is `"ok"`, `coverage_pct` is `100.0`, and `warnings` is `[]`
- There are 8 nodes: 3 `datasource`, then `projection`, `join`, `union`, `aggregation`, `output`
- There are 7 edges, and the `TABLE_B → Union_1` edge has `"constant": "SRC_B"` and a `"null": true` item for `CC_1`
- `Join_1.join` is `leftOuter` / `CN_1` with left `Projection_1` and right `TABLE_A`
- `IP_FISCAL_YEAR.used_in` is filter on `Projection_1`, `IP_RATE.used_in` is calculation on `Aggregation_1`, and `V_COMPANY` is a `variable` with `used_in` empty
- No real names appear anywhere: only `TABLE_*`, `COL_*`, `AMT_*`, `CC_*`, `CM_*`, `SOURCE_VIEW_01`, `SCHEMA_1`, `pkg.synthetic`

Open the three malformed goldens and confirm that each has exactly the warning codes listed in Task 8's parametrized test. If anything looks wrong, fix the parser and its hand-written test first, then regenerate.

- [ ] **Step 7: Run the full suite**

Run: `pytest -q`
Expected: all passed

- [ ] **Step 8: Commit**

```bash
git add tests/test_never_raises.py tests/test_golden_ir.py fixtures/synthetic
git commit -m "test(m1): never-raise hardening and reviewed golden IR snapshots

Golden files are new: first snapshot of the M1 IR for all four synthetic fixtures."
```

---

## M0 / M1 exit checklist

- [ ] `pip install -e ".[dev]"` and `calcview serve` start on 127.0.0.1 (M0)
- [ ] Vendored JS loads with the network off (M0, Task 2 Step 5)
- [ ] `pytest -q` is green
- [ ] All graphical fixtures match their golden IR JSON (M1)
- [ ] The malformed fixtures produce warnings, not exceptions (M1)
- [ ] The `xsi:type` element names used by the parser are confirmed against the real files. **This is the spec's M1 acceptance gate.** Confirm the names from Jacob's `xsi:type` grep of the real folder, or wait for M4. Until then M1 counts as "done on synthetic, pending confirmation".
- [ ] The "Still unconfirmed" list is carried forward into the M4 plan. The audit must report namespace URIs, root attribute names (`schemaVersion`, `dataCategory`, …), every element tag (this catches `calculatedViewAtrributes` versus `calculatedViewAttributes`), every `xsi:type` value, and the counts of each warning code.
- [ ] The M4 audit must report UNKNOWN_ELEMENT counts by parent tag and child tag.
