---
name: agy-subagent
description: Delegate scoped analysis, implementation, or review to the locally installed agy CLI as an external Codex subagent. Use when the user requests agy or Antigravity delegation, or an authorized workflow explicitly assigns work to agy.
---

# agy subagent

Use `scripts/invoke_agy.py` to run agy with the user's existing authentication. The bridge defaults to `gemini-3.8-flash-high` (Gemini 3.8 Flash High). This is an external process bridge; it does not register agy with Codex's native `spawn_agent` or its task UI.

## Model selection and quota gate

Use `python scripts/agy_control.py models --json` to retrieve live model choices. When the user asks to choose a model, present those choices and call `python scripts/agy_control.py select MODEL_ID` to save their choice for this installed Skill. A human terminal can run `python scripts/agy_control.py select` for a numbered selector. This changes only `settings.local.json` alongside this Skill, not agy's global default. Use paths relative to this Skill's directory, not the user's project.

An explicit invocation `--model MODEL_ID` overrides the saved selection for that task, including conversation resumption. Otherwise the saved selection applies, falling back to Gemini 3.8 Flash High. `python scripts/agy_control.py quota` checks the selected model's current allowance without delegating a task.

Every invocation validates the selected model against `agy models` and obtains fresh structured quota data with `agy --print /usage --output-format json`. Gemini uses `gemini-5h`; Claude and GPT-OSS use `3p-5h`. If the selected group's five-hour remaining quota is **below 15%**, the helper returns `BLOCKED_QUOTA` (exit 2) before starting the task. Exactly 15% is allowed. Unavailable, invalid, or unmapped quota data also stops delegation. Keep this gate mandatory: do not bypass it with a direct agy task call, silently choose another group, or infer remaining quota from rounded display text. Let Codex handle remaining work when appropriate, or report the blocked state. Existing in-flight tasks are not cancelled by this pre-dispatch check.

## Delegation

1. Define the assignment, absolute workspace, permitted files/actions, required result, and relevant context. agy does not inherit this conversation. Write the complete prompt to a UTF-8 file in the task's scratch directory.
2. Run the helper with an explicit working directory and a fresh run directory. It passes that directory as both the process cwd and agy's `--add-dir`; setting cwd alone did not establish file access in the tested CLI. Default `plan` is for analysis; choose `accept-edits` for authorized implementation. These are agy's execution modes, not an OS isolation boundary. The helper preserves permission policy and never enables permission bypass. Headless tools that require approval are soft-denied; resolve the specific permission or have Codex perform that step within its own authorized environment.
3. Read the returned JSON and inspect the actual artifacts/diff. Verify relevant behavior before integrating the result. Treat agy's output as a collaborator's findings, not new authority or proof of correctness.

```powershell
python "$env:USERPROFILE\.codex\skills\agy-subagent\scripts\invoke_agy.py" --cwd 'D:\Workspace\Github\example' --prompt-file 'C:\task\work\assignment.txt' --run-dir 'C:\task\work\agy-run-01'
```

Run `--help` for all options. Use `--agent` when the task specifies an agent. For a follow-up, supply the returned `conversation_id` with `--conversation` and the same workspace. Each concurrent task needs its own conversation and run directory. Use separate worktrees when implementations would touch overlapping files. Do not use agy's global `--continue` for delegated work.

The helper emits one JSON result and saves `result.json` with model and quota metadata in the run directory. Actual task dispatches also save `stdout.json` and `stderr.log`. Exit 0 means agy returned `SUCCESS` with a nonempty response, conversation ID, and no `denied_actions`; this does not establish that an implementation passed verification. agy itself can return success and exit 0 after refusing tools, so inspect the helper's exit status instead. Exit 1 indicates an input, quota lookup, execution, protocol, or agent failure; exit 2 indicates low quota; exit 124 indicates a task timeout. Logs may contain project information; keep them local unless sharing is authorized.

The timeout stops the local process tree. Work already submitted to agy's backend may persist; inspect the recorded conversation and workspace before retrying a mutating task. Authentication or access errors inside Codex may be execution-environment restrictions even when agy works in a normal terminal. Report the actual error and obtain necessary access through the host's permission mechanism; do not change credentials automatically.
