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

```
calcview serve
```

The server always binds to 127.0.0.1; there is no option to change the host.

## More

- Spec: `docs/` (see `CalcView Migrator — Spec v0.1.md`) and plans in `docs/superpowers/plans/`.
- Build rules and commands: `CLAUDE.md`.
