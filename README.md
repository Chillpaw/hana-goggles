# CalcView Migrator

A local tool that maps out bulk SAP HANA calculation view XML files. It parses each view into a typed intermediate representation (IR) of nodes, columns, expressions, parameters and warnings, so the views can be inspected and migrated. It runs entirely on your machine and makes no network calls at runtime.

## Install

Needs Python 3.11 or newer. macOS / Linux:

```
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]" -c constraints.txt
```

Windows (PowerShell or cmd, with the `py` launcher):

```
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]" -c constraints.txt
```

If PowerShell refuses to run `activate`, use `.venv\Scripts\Activate.ps1` after `Set-ExecutionPolicy -Scope Process RemoteSigned`, or run the commands from cmd.

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

`--db` defaults to the `CALCVIEW_DB` environment variable when it is set, else `./calcview.db`. `serve` refuses to start (exit 2) if the file exists but is not a CalcView project. Running `import` again on the same folder re-imports it: unchanged files keep their notes (and are counted as reparsed if this build parses them differently), changed views replace the stored ones, and notes on changed views or nodes are marked stale. `import --name NAME` sets the project name (default: the existing name, else the folder name). The import report lists counts (added, changed, unchanged, reparsed, removed, failed, not stored, stale annotations), internal dependencies, leaf sources (tables and table functions), unresolved sources (views outside the folder, ambiguous or unknown sources), cycles, deploy order and warnings. The database holds work data and stays on your machine; `*.db` files are git-ignored.

The server always binds to 127.0.0.1; there is no option to change the host.

If part of the folder cannot be read during a re-import (`SCAN_DIR_UNREADABLE`, e.g. a permissions problem or a network drive dropping out), views that were not seen are kept rather than removed, and the report says how many (`REMOVALS_SKIPPED`). Re-import once the folder is readable. Every warning code added on this pathway is listed, with its severity and when it is raised, in the "Warning codes added on this pathway" table of `docs/superpowers/plans/2026-10-14-process-view-pathway.md`.

## Using the app

1. **Import.** Either run `calcview import path/to/views --db project.db` and then `calcview serve --db project.db`, or start `calcview serve --db project.db` first and type the folder path into the form at `/`. Re-import at any time with the **Re-import** button on the Views page or the same command; notes are kept.
2. **Open** `http://127.0.0.1:8765` in a browser (`serve --port N` changes the port).
3. **Views list** (`/views`). The **Last import** box at the top shows the counts from the most recent import (click to expand) and lists its warnings, such as `DUPLICATE_VIEW_ID` for a skipped file or `SCAN_DIR_UNREADABLE`; warnings stay visible without expanding anything. Below it: cycles, estate warnings (dependencies between views), a filter box, and one row per view with type, category, node count, coverage, parse status, warning count, how many views it reads and is used by, and its sign-off. Click a column heading to sort.
4. **A view's page** has tabs:
   - **Graph**: the view's steps, output at the top and sources at the bottom. Click a step for its plain-English description, warnings and step note; a source that is another view in the project links to it. "Mermaid (.mmd)" in the header downloads the graph as text.
   - **Steps**: one plain-English sentence block per step, in order. Expressions the parser could not read are shown verbatim, marked "(not parsed)".
   - **Columns**: every step's columns with types, aggregation and calculations.
   - **Warnings**: what the parser could not fully understand, by step and line.
   - **Raw XML**: each step's original XML.
   - **Notes**: purpose, owner, sign-off (draft, reviewed, approved) and free notes for the view, plus the step notes, and notes on steps that no longer exist.
5. **Stale badges.** A note shows **Stale: <reason>** when what it describes changed after it was saved: "view file changed", "node changed", "node removed" or "view removed". Read the change, then save the note again to clear the badge. Notes on views that were removed are listed at the bottom of the Views page, never hidden.
6. **Estate map** (`/estate`, linked from every page): every view and its leaf sources (tables, table functions, views outside the folder). **Colour by** parse status, view type, data category or sign-off; toggle leaf sources; search by name. Click a view to highlight everything upstream and downstream of it (click the background to clear); double-click to open its page. **Export PNG** saves the current map as an image; the **Mermaid** links download it as text, with or without leaf sources. The deploy order and any cycles are listed beside the map.
7. **Audit at work.** Run `calcview audit path/to/views --output audit.txt` (or `--format json --output audit.json`), review the file as described below, and bring it back.

## Running the audit at work

The audit tells us what the parser meets in the real folder without carrying any business content out:

```
calcview audit path/to/views --output audit.txt
calcview audit path/to/views --format json --output audit.json
```

It reads the folder directly (no database is opened or created) and writes the same report in either format. `--output FILE` writes UTF-8 on every platform; without it the report is printed, and `> audit.txt` also works, except that Windows PowerShell 5.1 redirection writes UTF-16, so prefer `--output` there.

**What it prints:** file counts by suffix, parse status and view type; warning codes and their counts; coverage percentages (sorted, plus a histogram); how many view ids are shared by more than one file (counts only); how many root ids are `plain` (letters, digits, underscores), `<namespace>::<name>`, `<other>` or `<missing>` (counts only, never the ids); SAP and W3C namespace URIs (any other URI shows as `<other>`, and attributes in such a namespace as `<other>:name`); every XML element and attribute name, with counts and parent > child pairs; `xsi:type` values; the values of a fixed list of schema-enum attributes (such as `dataCategory`, `DataSource@type`, `joinType`, `aggregationType`, datatypes), with anything that does not look like an enum token shown as `<other>`; the shape of each `resourceUri` with every name replaced by its role (e.g. `/<package>/calculationviews/<name>`); counts of expressions by language; column-engine function names, split into known catalogue functions and unrecognised names; and unknown elements by parent > child.

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
