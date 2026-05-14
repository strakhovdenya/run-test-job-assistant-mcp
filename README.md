# run-test-job-assistant-mcp

MCP server for safely running checks in the [`strakhovdenya/job-assistant`](https://github.com/strakhovdenya/job-assistant) project.

This server exposes a small allowlisted set of test commands that can be invoked by an AI assistant through MCP. Its goal is to make project validation repeatable, explicit, and safe.

---

## Purpose

`run-test-job-assistant-mcp` is a helper MCP server for the **AI Job Assistant** project.

It allows an AI assistant to:

- start the test PostgreSQL dependency
- run backend tests
- run frontend tests
- run the full project test suite

The server is intentionally narrow in scope. It is not a general shell runner and should not expose arbitrary command execution.

---

## Target project

Main project repository:

```text
strakhovdenya/job-assistant
```

The target project is a Python monorepo with:

- FastAPI backend
- Streamlit frontend
- PostgreSQL database
- `uv` workspace dependency management
- `pytest` test suite

---

## Configuration

The MCP server needs to know where the local `job-assistant` repository is located.

Set this environment variable before running the server:

```text
JOB_ASSISTANT_PROJECT_ROOT=
```

You can use `.env.example` as a reference for the required variable names.

Do not commit your real `.env` file or local machine paths to the repository.

---

## Available tools

### `run_tests`

Runs one allowlisted test/check command.

Supported commands:

| Command | Description |
| --- | --- |
| `test_db_up` | Starts PostgreSQL with Docker Compose |
| `test_backend` | Runs backend tests |
| `test_frontend` | Runs frontend tests |

Expected command behavior:

```bash
# test_db_up
docker compose up -d postgres

# test_backend
uv run --project apps/backend --no-sync pytest tests/backend

# test_frontend
uv run --project apps/frontend --no-sync pytest tests/frontend
```

---

### `run_full_test_suite`

Runs the complete project test suite in order:

1. Start PostgreSQL
2. Run backend tests
3. Run frontend tests

The suite stops after the first failing step.

Expected command sequence:

```bash
docker compose up -d postgres
uv run --project apps/backend --no-sync pytest tests/backend
uv run --project apps/frontend --no-sync pytest tests/frontend
```

---

## Safety model

This MCP server should follow a strict allowlist model:

- no arbitrary shell access
- no user-provided command strings
- no destructive commands
- no access to secrets beyond what the test environment requires
- commands should be explicit and auditable
- local project paths should be provided through environment variables, not committed to the repository

The server should only expose commands that are safe to run repeatedly during development and review.

---

## Typical usage

An AI assistant can use this MCP server while helping with the `job-assistant` project, for example:

- after changing backend code, run backend tests
- after changing frontend code, run frontend tests
- before opening or reviewing a pull request, run the full suite
- when debugging CI failures, reproduce the failing test command locally

Example assistant workflow:

```text
1. Inspect the code change
2. Decide which tests are relevant
3. Run one of the allowlisted MCP commands
4. Read the test output
5. Suggest or apply fixes
6. Re-run the relevant command
```

---

## Requirements

The target `job-assistant` project should have:

- Docker / Docker Compose
- Python and `uv`
- project dependencies installed or resolvable through `uv`
- test folders available at:
  - `tests/backend`
  - `tests/frontend`

---

## Relationship to CI

This MCP server does not replace GitHub Actions.

It is meant to complement CI by giving an AI assistant a safe way to run the same checks earlier in the development loop.

Recommended flow:

```text
Local / MCP checks → Pull Request → GitHub Actions
```

---

## Documentation in the main project

The main `job-assistant` repository can reference this MCP server from its developer documentation, for example:

```text
Docs/mcp-test-server.md
```

That document should explain how the MCP server fits into the development workflow of the main project.

---

## Notes

- Keep the command surface small.
- Prefer explicit tools over flexible shell commands.
- Add new commands only when they are useful, repeatable, and safe.
- Treat this repository as developer automation infrastructure for `job-assistant`.
