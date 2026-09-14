"""List/select agy models and check their live five-hour quota before delegation."""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

DEFAULT_MODEL = "gemini-3.8-flash-high"
MIN_REMAINING_PERCENT = 15
SETTINGS = Path(__file__).resolve().parents[1] / "settings.local.json"


class QuotaError(ValueError):
    pass


def run_cli(arguments):
    executable = shutil.which("agy")
    if not executable:
        raise ValueError("agy is not on PATH")
    result = subprocess.run([executable, *arguments], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, encoding="utf-8-sig", timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode != 0:
        raise ValueError(f"agy metadata query failed (exit {result.returncode}): {result.stderr.strip()[:500]}")
    return result.stdout


def list_models():
    models = []
    for line in run_cli(["models"]).splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            models.append({"id": parts[0].strip(), "label": parts[1].strip()})
    if not models or len({m["id"] for m in models}) != len(models):
        raise ValueError("agy returned an empty or ambiguous model catalog")
    return models


def selected_model():
    if not SETTINGS.exists():
        return DEFAULT_MODEL
    value = json.loads(SETTINGS.read_text(encoding="utf-8"))
    model = value.get("default_model") if isinstance(value, dict) else None
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Invalid local default_model setting")
    return model


def validate_model(model, models):
    if model not in {entry["id"] for entry in models}:
        raise ValueError(f"Model is not in the live agy catalog: {model}")


def quota_bucket_id(model):
    if model.startswith("gemini-"):
        return "gemini-5h"
    if model.startswith(("claude-", "gpt-oss-")):
        return "3p-5h"
    raise QuotaError(f"No verified quota-group mapping for model: {model}")


def evaluate_quota(payload, model):
    try:
        if not isinstance(payload, dict) or payload.get("status") != "SUCCESS":
            raise QuotaError("agy quota response was unsuccessful")
        command = payload["command"]
        if command["name"] not in ("usage", "quota"):
            raise QuotaError("Expected an agy usage command result")
        bucket_id = quota_bucket_id(model)
        matches = [(group, bucket) for group in command["data"]["groups"]
                   for bucket in group["buckets"] if bucket.get("id") == bucket_id]
        if len(matches) != 1:
            raise QuotaError("Missing or ambiguous five-hour quota bucket")
        group, bucket = matches[0]
        value = bucket["remaining_fraction"]
        if (bucket.get("window") != "5h" or isinstance(value, bool)
                or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1):
            raise QuotaError("Invalid five-hour remaining_fraction")
        percent = value * 100
        return {"status": "ALLOWED" if percent >= MIN_REMAINING_PERCENT else "BLOCKED_QUOTA",
                "model": model, "group": group["name"], "bucket_id": bucket_id,
                "remaining_percent": percent, "minimum_remaining_percent": MIN_REMAINING_PERCENT,
                "reset_time": bucket.get("reset_time")}
    except (KeyError, TypeError, AttributeError) as exc:
        raise QuotaError("Unrecognized agy quota schema") from exc


def check_quota(model):
    try:
        payload = json.loads(run_cli(["--print", "/usage", "--output-format", "json"]))
        return evaluate_quota(payload, model)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        raise QuotaError(f"Live quota unavailable; delegation stopped: {exc}") from exc


def prepare_dispatch(override=None):
    model = override or selected_model()
    validate_model(model, list_models())
    return model, check_quota(model)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("models", help="List live choices and current bridge default")
    listing.add_argument("--json", action="store_true")
    selection = commands.add_parser("select", help="Choose a bridge default without changing agy global settings")
    selection.add_argument("model", nargs="?", help="Omit for numbered interactive selection")
    quota = commands.add_parser("quota", help="Check live quota; exit 2 when blocked")
    quota.add_argument("--model")
    args = parser.parse_args()
    try:
        current = selected_model()
        if args.command == "quota":
            _, result = prepare_dispatch(args.model)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["status"] == "ALLOWED" else 2
        models = list_models()
        if args.command == "models" and args.json:
            print(json.dumps({"default_model": current, "models": models}, ensure_ascii=False))
            return 0
        if args.command == "models" or not args.model:
            for index, entry in enumerate(models, 1):
                marker = "*" if entry["id"] == current else " "
                print(f"{index:2}. {marker} {entry['label']}  [{entry['id']}]")
            if args.command == "models":
                return 0
            if not sys.stdin.isatty():
                raise ValueError("Interactive selection requires a terminal; use select MODEL_ID")
            choice = input("Model number (Enter keeps current): ").strip()
            if not choice:
                return 0
            if not choice.isdigit() or not 1 <= int(choice) <= len(models):
                raise ValueError("Invalid model number")
            model = models[int(choice) - 1]["id"]
        else:
            model = args.model
        validate_model(model, models)
        # A choice may be saved while quota is low, but cannot bypass the dispatch gate.
        quota_bucket_id(model)
        SETTINGS.write_text(json.dumps({"default_model": model}, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"default_model": model, "settings": str(SETTINGS)}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "CONTROL_ERROR", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
