# M0+M1 — deferred review findings and rulings

Carried forward from the subagent-driven build of plan `2026-10-14-calcview-migrator-m0-m1.md`. Input for the M4 audit plan and later milestones.

## Rulings
- Ruling: use /opt/homebrew/bin/python3.13 for the .venv instead of default python3 (3.14) — closer to the 3.11 floor and safer for lxml/pydantic-core wheels — cost if wrong: none, venv is recreatable.
- Ruling: implementer may write `root, _error, _line = x.load(data)` or keep names; unused locals are not a defect worth a fix round — cost if wrong: cosmetic.
- Ruling: network downloads in T2 approved by user ("dont worry about network access") — cost if wrong: none.
- Ruling: fix the warning with a narrowly scoped pytest filterwarnings entry rather than adding httpx2 or pinning — keeps the deps the plan lists, test output clean — cost if wrong: hides a deprecation we'll have to address when Starlette drops httpx support.
- Ruling: commit trailers name the model that wrote the commit (subagent's own attribution reminder), not a fixed 'Opus 5.5' — accurate attribution — cost if wrong: earlier T1-T4 commits say Opus; cosmetic.
- Ruling: (a) flatten consecutive same-operator left-associative chains (+,-,*,/,and,or) into one n-ary `binary` node whose args are left-folded (a-b-c → binary "-" [a,b,c]); (b) after parsing, compute tree depth iteratively and raise ExprParseError above MAX_DEPTH=64; keep RecursionError backstop — rejecting a realistic 100-column SUM as unparseable would be wrong for real views, flattening keeps it depth 2 — cost if wrong: generators (M6/M8) must treat binary with >2 args as a left fold; documented on ExprNode.
- Ruling: read `f.get("expressionLanguage") or cv.get("filterExpressionLanguage")`, add inline-XML test asserting SQL lang + SQL_EXPR_DEFERRED; add `calculationView@filterExpressionLanguage` to the plan's "Still unconfirmed" list at final — reviewer's domain knowledge matches mine, fixture can't show it — cost if wrong: one extra attribute read, harmless.
- Ruling: before golden freeze, (a) _check_children on each logicalModel attribute {descriptions,keyMapping}, base measure {descriptions,measureMapping}, calculated attribute/measure {descriptions,keyCalculation,formula}; (b) INFO warning HIDDEN_COLUMN when hidden="true"; (c) WARNING MEASURE_TYPE_DEFERRED + Semantics understood=False when measureType present and ≠ "simple". No IR model change. Same gap on viewAttribute (Task 7) deferred — fixture viewAttributes carry only id/aggregationType — cost if wrong: real files may emit extra UNKNOWN_ELEMENT noise until the audit tunes the known sets; that noise is the intended signal.
- Ruling: keep the parametrized garbage case; add a dedicated test that writes a sentinel file under tmp_path, loads `<!DOCTYPE x [<!ENTITY e SYSTEM "file:///…sentinel">]><x>&e;</x>` via app.parsers.xmlutil.load, and asserts the sentinel text is absent from etree.tostring(root) — directly pins resolve_entities=False/no_network — cost if wrong: none.
- Ruling: one fix wave per final-fix-brief.md incl. README + constraints.txt (pre-work-install minor, cheap) — cost if wrong: constraints pin to dev-Mac versions; IT may need to relax them.

## Deferred minor findings
- Task 1: minor (deferred): no upper bounds on deps; consider lock/constraints file before work install
- Task 1: minor (deferred): no test of the /static mount itself (T2's vendor tests cover it)
- Task 1: minor (deferred): filterwarnings entry lacks :DeprecationWarning category
- Task 2: minor (deferred): serve test asserts only 200, not body equality / content-type
- Task 2: minor (deferred): no test verifying SHA256SUMS
- Task 2: minor (deferred): remote-URL guard only scans .html templates
- Task 3: minor (deferred): ColumnMapItem allows contradictory source/constant/null states (plan-mandated)
- Task 3: minor (deferred): test name says "lowercase" but DataCategory values are uppercase
- Task 3: minor (deferred): round-trip test omits JoinSpec/Filter/Parameter/ParameterMapping/DataSource/IRWarning
- Task 3: minor (deferred): coverage_pct unbounded
- Task 4: minor (deferred): xmlutil.text() returns "" for whitespace-only (callers in T6-8 use truthiness, so behaviour identical; empty formula still warns EXPR_PARSE_FAILED)
- Task 4: minor (deferred): entity refs truncate text() silently (resolve_entities=False); consider DOCTYPE warning
- Task 4: minor (deferred): XSI_NS hardcoded vs docstring claim
- Task 4: minor (deferred): xmlutil tests thin (raw, descendants positive, error message, child namespaces)
- Task 4: minor (deferred): `from conftest import MAIN` relies on prepend import mode
- Task 5: minor (deferred): non-str input raises TypeError not ExprParseError (dispatch guard catches)
- Task 5: minor (deferred): `""` accepted as empty column name
- Task 5: minor (deferred): '...$$P$$...' embedded placeholders stay plain strings (param usage still recorded by regex over text in T7)
- Task 5: minor (deferred): tests missing for <>,!=,<=,>=, column "" escaping, nested calls, left-assoc
- Task 5: minor (deferred): alternating-operator chains >64 terms now rejected (clean ExprParseError) — revisit if audit shows them
- Task 6: minor (deferred): duplicate/missing DataSource or parameter ids overwrite silently (no DUPLICATE_ID/MISSING_ID warning)
- Task 6: minor (deferred): dispatch failure paths untested here — covered by Task 9 test_never_raises
- Task 6: minor (deferred): FAILED-with-no-warning case — T8 MISSING_LOGICAL_MODEL covers the empty-scenario path; verify at final review
- Task 7: minor (deferred): duplicate/empty calculationView ids overwrite nodes silently
- Task 7: minor (deferred): calculated columns always ATTRIBUTE even with aggregationType
- Task 7: minor (deferred): EXPR_PARSE_FAILED / SQL_EXPR_DEFERRED warnings lack el= line numbers
- Task 7: minor (deferred): _record_parameter_usage would duplicate warnings if called twice (T8 calls it once — verify)
- Task 7: minor (deferred): many warning paths untested (SCRIPTED_DEFERRED covered in T8; RANK_NODE, SPECIAL_JOIN, JOIN_INPUT_COUNT, UNRESOLVED_INPUT, UNKNOWN_MAPPING untested)
- Task 7: minor (deferred): unknown children of <input> dropped silently
- Task 8: minor (deferred): keyMapping/measureMapping@columnObjectName not checked against logicalModel@id
- Task 8: minor (deferred): attribute/measure with no mapping is silent (no lineage)
- Task 8: minor (deferred): calculationView named "Semantics" collides with output node
- Task 8: minor (deferred): MISSING_LOGICAL_MODEL leaves coverage 100%; test asserts neither status nor coverage
- Task 8: minor (deferred): logicalModel UNRESOLVED_INPUT, RESTRICTED_MEASURES_DEFERRED, LOCAL_DIMENSIONS_DEFERRED untested
- Task 8: minor (deferred): calculated containers walked twice; hidden/measureType tests cover attribute/base measure only
- Task 9: minor (deferred): golden fixes Aggregation_1/CC_2 kind=attribute with no hand-written test
- Task 9: minor (deferred): UPDATE_GOLDEN mode always passes (by design)
- Task 9: minor (deferred): golden test ids use stem — collide if two dirs share a stem
- Task 9: minor (deferred): XXE test passes vacuously if root is None — add `assert root is not None`
- Final: minor (deferred): DataSource/calculatedViewAttribute unknown-child tests don't assert understood False; constraints.txt not dry-run on Python 3.11; plan exit checklist install line lacks -c constraints.txt
