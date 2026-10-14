# CalcView Migrator

A local tool that maps out bulk SAP HANA calculation view XML files. It parses each view into a typed intermediate representation (IR) of nodes, columns, expressions, parameters and warnings, so the views can be inspected and migrated. It runs entirely on your machine and makes no network calls at runtime.

## Install

```
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]" -c constraints.txt
```

## Test

```
pytest -q
```

## Run

Import a folder of calculation views into a project database, then browse it:

```
calcview import path/to/views --db project.db
calcview serve --db project.db
```

`--db` defaults to the `CALCVIEW_DB` environment variable when it is set, else `./calcview.db`. `serve` refuses to start (exit 2) if the file exists but is not a CalcView project. Running `import` again on the same folder re-imports it: unchanged files keep their notes (and are counted as reparsed if this build parses them differently), changed views replace the stored ones, and notes on changed views or nodes are marked stale. `import --name NAME` sets the project name (default: the existing name, else the folder name). The import report lists counts (added, changed, unchanged, reparsed, removed, failed, stale annotations), internal dependencies, leaf sources (tables and table functions), unresolved sources (views outside the folder, ambiguous or unknown sources), cycles, deploy order and warnings. The database holds work data and stays on your machine; `*.db` files are git-ignored.

The server always binds to 127.0.0.1; there is no option to change the host.

## Running the audit at work

The audit tells us what the parser meets in the real folder without carrying any business content out:

```
calcview audit path/to/views > audit.txt
calcview audit path/to/views --format json > audit.json
```

It reads the folder directly (no database is opened or created) and prints the same report in either format.

**What it prints:** file counts by suffix, parse status and view type; warning codes and their counts; coverage percentages (sorted, plus a histogram); how many view ids are shared by more than one file (counts only); SAP and W3C namespace URIs (any other URI shows as `<other>`, and attributes in such a namespace as `<other>:name`); every XML element and attribute name, with counts and parent > child pairs; `xsi:type` values; the values of a fixed list of schema-enum attributes (such as `dataCategory`, `DataSource@type`, `joinType`, `aggregationType`, datatypes), with anything that does not look like an enum token shown as `<other>`; the shape of each `resourceUri` with every name replaced by its role (e.g. `/<package>/calculationviews/<name>`); counts of expressions by language; column-engine function names, split into known catalogue functions and unrecognised names; and unknown elements by parent > child.

**What it never prints:** file names, folder paths, view, node, column or parameter ids and names, schema and table names, descriptions, literals, formulas and filter text, parameter defaults, or warning messages. SQL-language expressions are only counted. Nothing from a project database is printed.

**Before bringing it back:** read it, and check that everything below is a schema word (not a company, project, table or column name):

- element and attribute names outside SAP namespaces (for example attributes shown as `<other>:name`),
- `xsi:type` values,
- enum attribute values,
- the two "Unrecognised function names (review before sharing)" sections. The unparsed-text one is mined from formulas that did not parse, after removing quoted strings, quoted column names and `$$…$$` placeholders.

Delete any line that is not a schema word and mention that you did. Then copy the file out (JSON is easier to diff here) and add it to the conversation.

## More

- Spec: `docs/` (see `CalcView Migrator — Spec v0.1.md`) and plans in `docs/superpowers/plans/`.
- Build rules and commands: `CLAUDE.md`.
