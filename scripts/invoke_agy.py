"""Run agy without shell interpolation; retain results for inspection."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from agy_control import prepare_dispatch, QuotaError


def positive_int(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", required=True, type=Path)
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path, help="New directory for this invocation's logs")
    parser.add_argument("--mode", choices=["plan", "accept-edits"], default="plan")
    parser.add_argument("--conversation")
    parser.add_argument("--model", help="Override the bridge default for this invocation")
    parser.add_argument("--agent")
    parser.add_argument("--timeout", type=positive_int, default=300, help="Hard timeout in seconds")
    args = parser.parse_args()
    try:
        cwd = args.cwd.resolve(strict=True)
        if not cwd.is_dir():
            raise ValueError("cwd must be a directory")
        prompt = args.prompt_file.read_text(encoding="utf-8-sig")
        if not prompt.strip():
            raise ValueError("prompt file must not be empty")
        executable = shutil.which("agy")
        if not executable:
            raise ValueError("agy is not on PATH")
        run_dir = args.run_dir.resolve()
        run_dir.mkdir(parents=True, exist_ok=False)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "BRIDGE_ERROR", "error": str(exc)}, ensure_ascii=False))
        return 1

    command = [executable, "--add-dir", str(cwd), "--mode", args.mode, "--print", prompt,
               "--output-format", "json", "--print-timeout", f"{args.timeout}s"]
    for option in ("conversation", "agent"):
        value = getattr(args, option)
        if value:
            command.extend(["--" + option, value])

    exit_code = 1
    result = {"status": "BRIDGE_ERROR"}
    model = None
    quota = None
    try:
        model, quota = prepare_dispatch(args.model)
        if quota["status"] != "ALLOWED":
            result = {"status": "BLOCKED_QUOTA", "error": "agy five-hour remaining quota is below 15%; no task dispatched.", "quota": quota}
            exit_code = 2
        else:
            # Always pin the resolved selection, including resumed conversations.
            command.extend(["--model", model])
            result, exit_code = execute(command, cwd, run_dir, args.timeout)
    except QuotaError as exc:
        result = {"status": "QUOTA_UNAVAILABLE", "error": str(exc)}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result = {"status": "BRIDGE_ERROR", "error": str(exc)}

    result["bridge"] = {"cwd": str(cwd), "mode": args.mode, "model": model, "quota": quota,
                        "run_dir": str(run_dir), "exit_code": exit_code}
    serialized = json.dumps(result, ensure_ascii=False)
    (run_dir / "result.json").write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return exit_code


def execute(command, cwd, run_dir, timeout):
    exit_code = 1
    result = {"status": "BRIDGE_ERROR"}
    try:
        with (run_dir / "stdout.json").open("wb") as stdout, (run_dir / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    if os.name == "nt":
                        subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                                       capture_output=True, timeout=10,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
                result = {"status": "TIMEOUT", "error": "Local process stopped; backend work may persist."}
                exit_code = 124
        if exit_code != 124:
            payload = json.loads((run_dir / "stdout.json").read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("agy output must be a JSON object")
            result = payload
            valid = (process.returncode == 0 and payload.get("status") == "SUCCESS"
                     and isinstance(payload.get("response"), str)
                     and bool(payload["response"].strip())
                     and not payload.get("denied_actions")
                     and isinstance(payload.get("conversation_id"), str)
                     and bool(payload["conversation_id"]))
            exit_code = 0 if valid else 1
            if not valid:
                result = {"status": "BRIDGE_ERROR", "error": "agy failed, denied actions, or returned an incomplete result",
                          "process_exit_code": process.returncode, "agy_result": payload}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result = {"status": "BRIDGE_ERROR", "error": str(exc)}

    return result, exit_code


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
