---
name: agent-chapter-python-migrator
description: Migrate a chapter of the learn-agent TypeScript tutorial into a readable, Java-oriented Python project with equivalent behavior, tests, configuration, README, and a matching Chinese tutorial article. Use when the user asks to convert, port, translate, or continue another tutorial chapter into Python, especially when they want the same workflow as the first chapter.
---

# Agent Chapter Python Migrator

Use this skill to continue the repository's chapter-by-chapter Python migration. Treat the existing TypeScript chapter as the behavioral specification and produce an independently runnable Python snapshot for the requested chapter.

## Required Inputs

Infer the chapter number from the user request. If it is not stated, ask for it. Preserve the repository root and use the existing layout:

```text
code/chapters/chNN/src/       # TypeScript source of truth
code/chapters/chNN/tests/     # behavioral contract
python/chNN_agent/            # Python output
<root article for the Python version>.md
```

Do not overwrite the TypeScript chapter. Do not copy a later chapter's capabilities into an earlier snapshot.

## Workflow

### 1. Build the contract before coding

Read the repository `AGENTS.md`, the requested chapter article, every file under `code/chapters/chNN/src/`, and every test under `code/chapters/chNN/tests/`. Search for imports and public symbols when output is truncated. Record:

- public data objects and message formats;
- interfaces/protocol boundaries and injected fakes;
- success, validation, timeout, cancellation, and failure behavior;
- CLI arguments, `.env` fields, default limits, and exit codes;
- chapter profile/capability restrictions;
- filesystem, process, network, and authorization boundaries.

Use tests as acceptance criteria. Do not simplify behavior merely because a smaller demo would be easier.

### 2. Design the Python snapshot using Java-oriented layers

Create chapter code at `python/chNN_agent/`, but share the Python runtime at `python/.venv` and model configuration at `python/.env`. Do not create a chapter-local `.venv` or `.env`. Use this shape unless the chapter requires an additional module:

```text
python/
├─ .venv/             # shared; create once
├─ .env               # shared; configure once
├─ .env.example       # shared template
├─ chNN_agent/
├─ pyproject.toml
├─ README.md
├─ .env.example
├─ .gitignore
├─ agent_chNN/
│  ├─ core/          # dataclasses, Protocol interfaces, domain/application services
│  ├─ adapters/      # OpenAI-compatible SDK, OS, filesystem, or other external adapters
│  ├─ features/      # chapter-specific tools/features
│  ├─ bootstrap.py   # composition root / Spring @Configuration analogue
│  ├─ config.py
│  └─ cli.py
└─ chNN_agent/tests/
```

Use `dataclass(frozen=True, slots=True)` for value objects, `Protocol` for injectable interfaces, explicit type hints, and specific exception classes. Treat the reader as a Python beginner who knows Java backend development. Add plain Simplified Chinese comments/docstrings to every module, core class, public method, and non-obvious branch. Explain unfamiliar Python syntax at first use with a Java comparison, including `self`, dataclass, Protocol, tuple, `T | None`, `*items`, `**mapping`, context managers, comprehensions, decorators, and async syntax when present. Comments must explain what happens, why it is necessary, what the Java equivalent is, and which layer owns the responsibility. Avoid terse expert-only narration.

Prefer standard library plus the smallest compatible dependencies. For OpenAI-compatible chapters use `openai` and `python-dotenv` only when the source chapter needs them. Keep tests offline by injecting fake model, command, filesystem, scheduler, or MCP boundaries.

### 2.1 中文日志与错误

面向学习者、终端用户和模型的日志、提示、异常说明、工具执行结果，能用自然中文表达的必须使用简体中文；这样用户不需要先翻译英文才能定位问题。机器要读取的错误码、配置键、协议字段、JSON 字段、模型的 `finish_reason` 值、Python/HTTP/SDK 类型名保留原文，中文说明放在它们旁边。例如使用 `工具执行错误 [shell_timeout]: 命令超时`，不要把机器可读的 `shell_timeout` 改成中文。测试断言应优先锁定稳定的错误码；若断言可见说明，则使用中文说明。

### 3. Port behavior, not syntax

Map TypeScript concepts as follows:

| TypeScript tutorial concept | Python/Java-oriented form |
| --- | --- |
| `interface` | `typing.Protocol` with an explanatory docstring |
| immutable object | frozen slots dataclass |
| union message type | typed dataclass variants plus explicit role checks |
| Zod/schema validation | explicit validation function or a small local schema helper |
| `AgentRunner` | application service that orchestrates interfaces |
| adapter | infrastructure implementation of a core Protocol |
| composition root | `bootstrap.py` |
| Vitest fake | pytest fake/stub with recorded calls |
| `.env` parser | `python-dotenv` or a small deterministic parser |

Preserve error codes and externally visible text whenever tests or the source chapter depend on them. Keep tool call IDs paired with exactly one tool result. Convert malformed external responses and handler failures at the adapter/registry boundary instead of leaking untrusted values into the core loop.

### 4. Write the matching documentation

Create a new root-level Markdown article named with the chapter sequence and a clear Python label, without editing the original TypeScript article. Treat the original chapter article as the documentation source of truth. Perform a complete migration, not a summary or a newly invented shortened tutorial. Preserve every substantive section, argument, comparison, warning, table, production-design discussion, limitation, experiment, and conclusion from the original article. Preserve the original heading order unless a language-specific heading must be renamed. Replace only language-dependent code, file paths, commands, dependency instructions, test counts, and implementation descriptions with the generated Python project's actual behavior.

Before finishing, compare the original and Python article heading lists and account for every original heading. The Python article may add a Java/Python beginner section, but must not silently remove original content.

The article must:

- state that it is paired with `python/chNN_agent`;
- explain the chapter's one main capability before advanced features;
- show the Python project tree;
- provide a Java/Spring concept mapping table;
- provide a Python-syntax-to-Java mapping table and a beginner reading path starting from one focused test;
- use Python snippets that match the generated files;
- use PowerShell commands only;
- explain the recommended test-first archaeology order;
- document `.env`, offline tests, real-run prerequisites, and authorization/safety boundaries;
- distinguish an adapter, core service, registry, and composition root.
- explain every shown Python class field and important method in plain language when the surrounding text introduces it;
- add Java equivalents for unfamiliar Python structures rather than assuming Python fluency.

Use fenced code blocks with language tags. Keep paths and names synchronized with the Python output. Read the complete new article back before finishing; check that fences are paired and tables are valid.

### 5. Validate in gates

Create the shared environment only if `python/.venv` does not exist. Configure `python/.env` only if it does not exist. Then install and test the requested chapter using the existing environment:

```powershell
Set-Location 'python'
if (-not (Test-Path '.venv')) { python -m venv .venv }
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
& .\.venv\Scripts\python.exe -m pip install -e '.\chNN_agent[dev]'
```

Run gates from `python/chNN_agent/` with the shared interpreter:

```powershell
& ..\.venv\Scripts\python.exe -m pytest tests
& ..\.venv\Scripts\python.exe -m compileall -q agent_chNN
& ..\.venv\Scripts\python.exe -m ruff check agent_chNN tests
& ..\.venv\Scripts\python.exe -m mypy agent_chNN
```

If a tool is unavailable, report it and still run the available gates. Never claim real-model verification unless credentials and network access were available; offline tests are the required gate. For a Windows process test, normalize paths before comparing them because 8.3 short paths and long paths can refer to the same directory.

After each failure, identify whether it is a porting defect, a test-environment assumption, or an unavailable external dependency. Fix porting defects; do not weaken the behavioral contract merely to make a test green.

## Output Expectations

Finish only after creating:

1. a runnable `python/chNN_agent` project;
2. focused offline tests covering the chapter's public behavior and failure branches;
3. shared `python/.env.example`, appropriate `.gitignore`, `pyproject.toml`, and a Java-oriented README;
4. a synchronized root-level Python chapter article;
5. a concise verification report with exact commands and results.

When the user asks for another chapter later, repeat this workflow using that chapter's source and tests, and keep the previous Python snapshots untouched.

## Version Control

After implementation, documentation, and all available validation gates pass, inspect `git status` and the final diff. Stage only files created or changed for the current chapter migration; never include unrelated user changes, caches, virtual environments, `.env`, secrets, or generated temporary files. Create one focused Git commit before reporting completion. Write the commit subject in Simplified Chinese using a concise imperative description, for example:

```text
迁移第二章 Python 工具系统
```

If the directory is not a Git repository, report that the commit is blocked instead of inventing commit metadata.
