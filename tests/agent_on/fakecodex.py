#!/usr/bin/env python3
"""A stand-in for the `codex` binary, for the harness_codex unit tests. It records what it received (its environment
and argv), reads the profile the launcher wrote under $CODEX_HOME (via --profile <name>) and dumps it as JSON,
records what every CODEX_SHARED symlink in $CODEX_HOME points at, writes a rollout shaped like Codex's own under
$CODEX_HOME/sessions/…, honours `-o <file>` (writes "OK"), and exits with $FAKE_CODEX_EXIT (default 0)."""
from __future__ import annotations

import json
import os
import sys
import tomllib
import uuid
from pathlib import Path
from datetime import datetime, timezone

args = sys.argv[1:]

if args == ["--version"]:
    # codex_version() runs `<binary> --version` and regex-matches a leading x.y.z; this must answer for the
    # *binary the launch used*, not whatever real `codex` is on PATH.
    print("codex-cli 0.0.0 (fake)")
    sys.exit(0)


def opt(flag):
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return None


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


out = os.environ.get("FAKE_CODEX_OUT")
codex_home = os.environ.get("CODEX_HOME")

if out:
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "env.json"), "w") as f:
        json.dump(dict(os.environ), f)
    with open(os.path.join(out, "argv.json"), "w") as f:
        json.dump(args, f)
    cwd_path = os.path.join(out, "cwd.txt")
    if not os.path.exists(cwd_path):
        with open(cwd_path, "w") as f:
            f.write(os.getcwd())
    if codex_home and os.path.isdir(codex_home):
        links = {}
        for item in os.listdir(codex_home):
            p = os.path.join(codex_home, item)
            if os.path.islink(p):
                links[item] = os.readlink(p)
        with open(os.path.join(out, "home_links.json"), "w") as f:
            json.dump(links, f)

profile_name = opt("--profile") or opt("-p")
profile = None
if out and codex_home and profile_name:
    profile_path = os.path.join(codex_home, f"{profile_name}.config.toml")
    if os.path.exists(profile_path):
        with open(profile_path, "rb") as f:
            profile = tomllib.load(f)
        with open(os.path.join(out, "profile.json"), "w") as f:
            json.dump(profile, f)

out_file = opt("-o")
if out_file:
    with open(out_file, "w") as f:
        f.write("OK")

if codex_home:
    model_provider = (profile or {}).get("model_provider")
    model = (profile or {}).get("model")
    session_dir = os.path.join(codex_home, "sessions", "2026", "09", "09")
    os.makedirs(session_dir, exist_ok=True)
    resumed = "resume" in args
    session_id = args[args.index("resume") + 1] if resumed else str(uuid.uuid4())
    rollout_path = os.path.join(session_dir, f"rollout-2026-09-09T00-00-00-{session_id}.jsonl")
    if resumed and not os.path.isfile(rollout_path):
        sys.exit(42)
    turns = int(os.environ.get("FAKE_CODEX_TURNS", "1"))
    running = {"input_tokens": 0, "cached_input_tokens": 0, "cache_write_input_tokens": 0,
               "output_tokens": 0, "reasoning_output_tokens": 0, "total_tokens": 0}
    if resumed:
        for line in Path(rollout_path).read_text().splitlines():
            event = json.loads(line)
            total = event.get("payload", {}).get("info", {}).get("total_token_usage")
            if total:
                running = total
    with open(rollout_path, "a" if resumed else "w") as f:
        if not resumed:
            f.write(json.dumps({"timestamp": ts(), "type": "session_meta",
                            "payload": {"id": session_id, "cli_version": "0.0.0", "model_provider": model_provider,
                                        "cwd": os.getcwd()}}) + "\n")
        f.write(json.dumps({"timestamp": ts(), "type": "turn_context", "payload": {"model": model}}) + "\n")
        last = None
        for _ in range(turns):
            last = {"input_tokens": 7000, "cached_input_tokens": 6000, "cache_write_input_tokens": 0,
                    "output_tokens": 20, "reasoning_output_tokens": 5, "total_tokens": 7020}
            for k, v in last.items():
                running[k] += v
            f.write(json.dumps({"timestamp": ts(), "type": "event_msg",
                                "payload": {"type": "token_count",
                                            "info": {"last_token_usage": last, "total_token_usage": dict(running)}}}) + "\n")
        # real Codex re-emits the last token_count event with no new model call (info.total_token_usage
        # unchanged): a zero-delta re-emit that read_rollout must drop, not count as a phantom turn.
        if last is not None:
            f.write(json.dumps({"timestamp": ts(), "type": "event_msg",
                                "payload": {"type": "token_count",
                                            "info": {"last_token_usage": last, "total_token_usage": dict(running)}}}) + "\n")

sys.exit(int(os.environ.get("FAKE_CODEX_EXIT", "0")))
