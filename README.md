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

`--db` defaults to `./calcview.db`; `serve` without `--db` uses the `CALCVIEW_DB` environment variable when it is set. Running `import` again on the same folder re-imports it: unchanged files are skipped, changed views replace the stored ones, and notes on changed views or nodes are marked stale. `import --name NAME` sets the project name (default: the folder name). The import report lists counts, internal and unresolved dependencies, cycles, deploy order and warnings. The database holds work data and stays on your machine; `*.db` files are git-ignored.

The server always binds to 127.0.0.1; there is no option to change the host.

## More

- Spec: `docs/` (see `CalcView Migrator — Spec v0.1.md`) and plans in `docs/superpowers/plans/`.
- Build rules and commands: `CLAUDE.md`.
