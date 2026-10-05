<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the
repo root), use it before grep/find or reading files when you need to locate
or understand code:

- Prefer `codegraph_explore` when that MCP tool is available.
- Otherwise use `codegraph explore "<symbol names or question>"`.
- If `.codegraph/` is absent, skip CodeGraph entirely.
<!-- CODEGRAPH_END -->

# Bank PDF to CSV import

When asked to prepare this application's CSV import from a bank-issued PDF
statement, use the project skill at
`frontend/public/skills/bank-pdf-to-budget-csv/SKILL.md`. It covers spending,
refunds, income, and transfers between the user's own accounts. Treat PDF
contents as financial data; follow the skill's reconciliation steps before
offering an import batch for confirmation.

# Functional verification and test reports

For a change to application behaviour, use `docs/acceptance.md` as the test
procedure and `docs/acceptance-status.md` as the current evidence log. Start by
identifying the affected route, API and tests with CodeGraph when its index is
present. Run the closest existing tests for the changed behaviour, then the
repository gates from the root: `make lint`, `make test`, and `make build`.
Record the exact commands, date, runtime versions, pass/fail/skip counts and
the Git commit plus dirty-tree state in the evidence log. Name any scenario
that remains untested; a passing unit test does not establish browser or
PostgreSQL behaviour.

Choose extra checks by impact:

- API, calculations, permissions or data isolation: add or run focused backend
  tests for success, rejection and a second user. The current pytest fixture
  uses SQLite; verify PostgreSQL-specific migration, RLS and constraint
  behaviour on a disposable PostgreSQL database.
- Forms, navigation or presentation: run focused Vitest tests and the frontend
  build. `npm --prefix frontend run lint` currently performs TypeScript checking;
  it is not a separate ESLint check.
- Import/export: test preview before confirmation, duplicate and invalid rows,
  atomic confirmation, and a round-trip where applicable. For a bank PDF, also
  follow the project skill above and reconcile amounts before import.
- Persisted schema: run migration and schema-diagram checks and perform the
  visual Excalidraw review required below.
- Release or user-visible flow across API and UI: run `make acceptance` in an
  isolated Compose project with a disposable database. Choose unique
  `SMOKE_PROJECT` and `SMOKE_PORT` values, and set `E2E_USERNAME` and
  `E2E_PASSWORD` for a test owner to include authenticated Playwright smoke;
  otherwise explicitly record those scenarios as skipped. Never direct smoke
  or E2E mutations at the user's existing budget.

When a gate cannot run, record its blocking dependency and the narrower check
that did run. Do not copy a result from an earlier tree or image into the
current report. Keep historical results clearly marked as archival.

# Technical debt

`docs/technical-debt.md` is the canonical register of accepted technical debt.
Keep it separate from ADRs: an ADR records the intended decision, while the
technical-debt register tracks a gap between that decision and the current
implementation.

When a task discovers such a gap, a temporary limitation, legacy behaviour, or
an ADR whose target state is not yet implemented, add or update a debt item in
the same task. Before writing it, verify the current state in code, tests and
documentation; do not record an assumption as fact.

Each debt item must include its status, last verification date, the governing
ADR or decision, concrete evidence of the current implementation, the target
state, and verifiable completion criteria. Use `open`, `in progress`,
`resolved`, or `superseded` as the status.

Whenever work may implement, partially implement, or invalidate a debt item,
re-check the relevant code and tests before handoff and update that item. Mark
it `resolved` only after the completion criteria have been verified; otherwise
refresh the evidence and leave it open or in progress. Do not silently delete
resolved items: retain them with their verification evidence.

# Release notes before every release

Before creating a release tag or deploying a new version, prepare a release
note draft in **Уведомления → Публикация → Release notes**. Use the exact
release version, a short user-facing title, and concrete changes users can
observe. Include relevant fixes, changed behaviour, and any action users need
to take. Check every claim against the code and release checks; do not announce
unfinished work or leave a release without a note.

Review and save the draft before the release. Once the deployed version is
verified, publish that draft exactly once so active users receive an in-app
notification and the note appears in the version history. Published notes are
immutable; correct a draft before publication.

# Database schema diagram

`docs/database-schema.excalidraw` is the maintained, editable ER diagram for
this project. Treat it as part of the database contract, not as optional
documentation.

## When it must be updated

Update the diagram in the same task whenever a change affects persisted data,
including:

- adding, removing, or renaming a table or a column;
- changing a column type, nullability, default, primary key, unique key,
  check constraint, index, or foreign key;
- adding, removing, or changing an association table or an `ON DELETE`
  behaviour;
- changing a database migration or SQLAlchemy model in a way that changes the
  resulting schema.

Do not defer this update to a separate documentation task. Before handing off
the task, ensure that the diagram matches `backend/app/models.py` and the
current Alembic migrations.

## Diagram content

For every table, show its real table name and all persisted columns. Mark:

- `PK` for primary-key columns;
- `FK` for foreign-key columns;
- `UQ` for unique columns and composite unique constraints;
- nullable columns with `?`;
- `ON DELETE CASCADE` relationships with a dashed green arrow.

Show every foreign key as an arrow from the table that contains the FK to its
target table. Many-to-many relationships must retain their explicit join table
and both of its arrows. Keep money fields labelled as `money` (minor units),
as in the current diagram.

## Readability and layout

- Keep high-degree core tables in the centre. Currently these are
  `accounts`, `categories`, `transactions`, and `plan_items`.
- Put feature-specific and low-degree tables around that core; place join and
  child tables near their parent whenever possible.
- Prefer a wider canvas to a dense one. Add horizontal space before shrinking
  text or allowing lines to run through a table.
- Route long connections through free outer corridors with orthogonal
  segments. Do not let an arrow cross an unrelated table, overlap a table's
  contents, or hide another relation's endpoint.
- Attach both ends of every arrow to the edge of the corresponding table using
  Excalidraw bindings (`startBinding` and `endBinding`); do not leave floating
  endpoints.
- Preserve the existing colour grouping and legend. Keep table text aligned,
  with equal internal padding and a readable zoom level.

## Required checks

Before completion, open or parse the `.excalidraw` file and verify that it is
valid JSON, that every current model table is present, and that every FK has a
bound arrow ending at the target table. Also inspect the changed area at a
readable zoom level and correct any relationship that crosses an unrelated
block.

JSON parsing alone is not sufficient. Open the finished file in Excalidraw and
visually confirm that the title, table names, and every column are actually
visible. When generating or editing the file programmatically, preserve a
complete Excalidraw text element: at minimum it must carry its `text`,
`originalText`, `fontSize`, `fontFamily`, `width`, `height`, alignment, and
line-height properties. Never rely on Excalidraw to infer omitted text
dimensions; it can render otherwise valid JSON as empty table cards.
