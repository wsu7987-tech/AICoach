# TASK-101 Independent Review — Final Incremental Review

## Final decision

**TASK-101 independent review: PASS. Allow TASK-102: Yes.**

Reviewed fix commit `65ed64f41857b107b8e6c121c5f602e63cb37e27` on top of the
original TASK-101 implementation `e21ede82948913861c926b8db9c812e0bca271e0`.
The prior P0-1 and P1-2/P1-3/P1-4 findings are independently verified as fixed.
No open P0, P1, or P2 finding remains in TASK-101 scope.

This review made no business-code changes. The pre-existing staged
`UV_MIGRATION_REVIEW.md` remains excluded and untouched.

## Baseline and reviewed evidence

| Check | Result |
|---|---|
| Branch / reviewed HEAD | `main` / `65ed64f41857b107b8e6c121c5f602e63cb37e27` |
| Original implementation | `e21ede8` |
| Fix scope | Contract, PromptBuilder, focused tests, reports, and project status |
| Worktree baseline | staged review report and unrelated `UV_MIGRATION_REVIEW.md`; no unstaged code diff |
| `git diff --check` | clean |

Reviewed `AGENTS.md`, TASK-101 instructions, Contract docs 03/06/07/09,
Bootstrap, execution/fix reports, implementation, and all TASK-101 tests.

## Contract gate

| Requirement | Result | Evidence |
|---|---|---|
| Required Pydantic types; reject unknown fields | PASS | `ContractModel(extra="forbid")` and specified models |
| Fixed seven primary Route keys | PASS | Fixed `RouteKey` `Literal` and Snapshot validator |
| Snapshot rejects missing, extra, duplicate, or disabled fixed Route | PASS | Snapshot validator plus regression tests |
| Secondary Intent/Slot/Enum/Alias driven by Snapshot | PASS | Dynamic output validation; no router hard-coding |
| Confidence bounded to 0..1 | PASS | Constraints reject negative, >1, NaN, and infinity |
| Runtime `risk` present and nullable | PASS | Default `model_dump()` emits `risk: null` |
| Clarification invariants | PASS | False requires null; true requires nonblank; training forces false/null |
| Route-only `training_business` | PASS | `intent.py:121-125,134,152` permits empty list only for training |
| Non-training route requires Intent | PASS | Shared validator rejects empty lists otherwise |
| Secondary Intent route/enabled validation | PASS | Dynamic business validation rejects mismatch/disabled intent |
| Runtime/debug separation | PASS | Runtime excludes trace-only fields; LLM model retains them separately |

Independent focused probe:

```text
route_only_training=[]
empty_non_training=REJECTED
intents_required=True
intents_min_items=None
```

The field remains required in structured output, while a zero-length list is
permitted only for `training_business`; the generated schema no longer imposes
`minItems: 1`.

## UTF-16 Slot-span gate

**PASS.** UTF-16 code-unit `[start,end)` validation, unique-value/alias repair,
and non-fatal `SLOT_SPAN_INVALID` drops are correct. Coverage includes emoji
plus Chinese repair (`😄练胸`: `胸` is UTF-16 `[3,4)`, not Python `[2,3)`), valid
enum-alias retention, repeated-value ambiguity, and absent-value drops. The
issue retains the original Slot for TASK-103 Trace `validation_json`.

## Snapshot and PromptBuilder gate

**PASS.** Bootstrap conforms to the strict Business Snapshot shape; Model Config
remains separate. PromptBuilder is pure Python, filters disabled secondary
configuration, and deterministically emits canonical messages, final prompt,
SHA-256 hash, and metadata without database/model I/O.

The former mutable-instance bypass is fixed. Public Snapshot validation rebuilds
an instance from `model_dump(mode="json")`; PromptBuilder and output validation
consume that validated copy. After disabling a fixed Route, independent probes
returned:

```text
snapshot REJECTED_INVALID_MUTATION: all fixed Route Contract routes must be enabled
builder  REJECTED_INVALID_MUTATION: all fixed Route Contract routes must be enabled
```

Prompt determinism remains verified with reordered context and a changed hash
when enabled business configuration changes. Canonical JSON keeps Chinese,
emoji, quotes, newlines, and JSON-special input as data. Preview only calls the
pure builder.

## Cross-task compatibility

| Next task | Status | Available Contract |
|---|---|---|
| TASK-102 Provider / IntentService | Ready | Consume `PromptBuildResult.messages`, use LLM schema, and validate with `validate_llm_output`. |
| TASK-201 Config / Release | Ready | Strict Draft/Snapshot validation, immutable-by-boundary copy, canonical hash, and pure Preview. |
| TASK-103 Trace / Runtime API | Ready | Runtime Contract, UTF-16 repair/drop output, and Trace-ready validation issues. |

TASK-103 must serialize Runtime output without `exclude_none=True` and persist
`SLOT_SPAN_INVALID`. No premature Provider, Release publishing, Runtime API, or
TraceStore implementation was added.

## Automated verification

Executed from `backend` using the locked environment:

| Command | Result |
|---|---|
| `uv run --locked --extra dev ruff check .` | PASS |
| `uv run --locked --extra dev ruff format --check .` | PASS — 37 files already formatted |
| `uv run --locked --extra dev pytest -q -rs` | PASS — **38 passed, 2 skipped** |

Both skips are MySQL integration tests: `MYSQL_TEST_DATABASE_URL` is not
configured. Only `MYSQL_HOME` is present and no isolated MySQL 8/Docker target
is available, so no destructive database test was attempted. TASK-101 did not
alter database code; this does not block closure.

## Previous finding disposition

| Finding | Disposition |
|---|---|
| P0-1: route-only training result rejected | Fixed and regression-tested |
| P1-2: mutated Snapshot bypassed validation | Fixed and regression-tested in validator, builder, and output validation |
| P1-3: absent slot-value drop lacked a test | Fixed with a non-fatal drop/issue test |
| P1-4: Ruff format check failed | Fixed; locked format check passes |

## Handoff

TASK-101 may close. TASK-102 may begin using this Contract boundary. TASK-102
must preserve the Provider constraints: async client in async paths, SDK retry
disabled, Provider-owned bounded retries, explicit timeout/concurrency, and no
`max_tokens` for structured JSON output.
