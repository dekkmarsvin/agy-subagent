# agy-subagent

Codex Skill that delegates scoped work to an existing authenticated agy CLI, checks the result, and retains local logs. This uses a CLI process bridge, not Codex's native `spawn_agent` registration.

## Install

Requires Windows, Python 3.10+, and an authenticated `agy` on PATH. The bridge uses only Python's standard library.

```powershell
git clone https://github.com/dekkmarsvin/agy-subagent.git
cd agy-subagent
./install.ps1
```

The installer writes six managed Skill files to `$CODEX_HOME/skills/agy-subagent` (default `~/.codex/skills/agy-subagent`). Existing local model selection is preserved. It does not edit agy's authentication, global model, or permission settings. Start a new Codex task to discover `$agy-subagent`.

## Choose a model

Default: **Gemini 3.8 Flash (High)**, `gemini-3.8-flash-high`.

```powershell
$agySkill = "$env:USERPROFILE/.codex/skills/agy-subagent"
python "$agySkill/scripts/agy_control.py" models
python "$agySkill/scripts/agy_control.py" select
# Or select directly:
python "$agySkill/scripts/agy_control.py" select gemini-3.8-flash-high
python "$agySkill/scripts/agy_control.py" quota
```

`select` provides a numbered terminal picker using the live agy catalog. A selection is saved in the installed Skill's `settings.local.json`; `--model MODEL_ID` on an invocation overrides it for that call only. If using a custom `CODEX_HOME`, adjust `$agySkill` accordingly. The repository and the installed Skill each have independent local selections; run the installed copy to change the model used by Codex.

## Delegate

Ask Codex: “Use $agy-subagent to review this change, then verify its findings.”

For a direct invocation, write a scoped UTF-8 prompt file, then:

```powershell
python "$agySkill/scripts/invoke_agy.py" `
  --cwd 'D:/Workspace/Github/example' `
  --prompt-file 'C:/task/work/prompt.txt' `
  --run-dir 'C:/task/work/agy-run-01' `
  --mode plan
```

Choose `--mode accept-edits` for authorized implementation. Resume with `--conversation ID` and the same workspace. Each call needs a new run directory. Context must be passed explicitly; agy does not inherit the Codex conversation.

## Five-hour quota guard

Before each task, the bridge refreshes the model catalog and queries structured `agy --print /usage --output-format json` data:

- Gemini models: `gemini-5h` bucket.
- Claude and GPT-OSS: `3p-5h` bucket.
- **Below 15% remaining: no task is started. Exactly 15% is allowed.**
- Missing, malformed, unavailable, or unmapped quota data stops delegation.
- No automatic switch to another quota group, no bypass option, and no dependence on rounded display percentages.

This applies to agy's quota, not Codex's. Weekly limits are separate and are not used for this requested five-hour threshold. The check runs before submission; it does not reserve quota or stop work already in progress, and other sessions may consume the shared quota after the check. New model families or changed backend bucket schemas require a verified mapping update.

## Results and limitations

`result.json` includes the resolved model and quota snapshot. Actual dispatches also retain `stdout.json` and `stderr.log`; blocked calls only write `result.json`. Exit codes:

| Code | Meaning |
|---|---|
| 0 | Nonempty successful agy result, no denied tools |
| 1 | Invalid input, metadata/quota failure, protocol error, or failed/denied task |
| 2 | Five-hour quota below 15%; no task dispatched |
| 124 | Local task timeout |

Keep logs and prompts local unless sharing is authorized. `plan` and `accept-edits` are agent modes, not OS sandboxes. Existing agy permission policy still applies; unattended shell commands may be refused. The bridge does not enable `--dangerously-skip-permissions`. Codex should independently verify files and run appropriate tests.

Timeouts terminate the local process tree on Windows, but remote work already submitted may persist. Inspect the conversation/workspace before retrying mutating tasks. Prompts are passed as a single process argument; very large prompts are subject to Windows command-line length limits. Scope prompts and reference workspace files for larger context.

## Tests

```powershell
python -m unittest discover -s scripts -p 'test_*.py' -v
```

Tests cover model selection, exact threshold boundaries, quota group matching, unknown quota rejection before process creation, fresh checks, literal Unicode arguments, denied actions, malformed responses, timeouts, and run directory preservation. They mock agy and do not consume model quota.

Live verification on Windows with agy 1.2.2 included catalog discovery, quota lookup, terminal selection, a guarded model response, and the previous version's read/write plus conversation continuation tests. Low quota is tested with controlled fixtures; it is not simulated by consuming the real account's allowance.

References: [agy headless mode](https://antigravity.google/docs/cli/headless/), [agy quota command](https://antigravity.google/docs/cli/commands/usage).
