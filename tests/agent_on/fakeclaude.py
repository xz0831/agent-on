#!/usr/bin/env python3
"""A stand-in for the `claude` binary, for the launcher's unit tests. It records what it received (its environment
and argv), runs the apiKeyHelper it was handed exactly as Claude Code would (a shell command), writes a transcript
shaped like Claude Code's into $CLAUDE_CONFIG_DIR/projects/<slug>/, honours --session-id / --resume / --continue /
--no-session-persistence, and exits with $FAKE_CLAUDE_EXIT (or, if $FAKE_CLAUDE_SIGNAL is set, kills itself with
that signal — e.g. FAKE_CLAUDE_SIGNAL=TERM — to fixture a Ctrl-C/SIGTERM death for the launcher's exit-code test)."""
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

args = sys.argv[1:]


def opt(flag):
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return None


out = os.environ.get("FAKE_CLAUDE_OUT")
if out:
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "env.json"), "w") as f:
        json.dump(dict(os.environ), f)
    with open(os.path.join(out, "argv.json"), "w") as f:
        json.dump(args, f)
    settings = opt("--settings")
    if settings and os.path.exists(settings):
        with open(settings) as f:
            doc = json.load(f)
        with open(os.path.join(out, "settings.json"), "w") as f:
            json.dump(doc, f)
        helper = doc.get("apiKeyHelper")
        if helper:
            key = subprocess.run(helper, shell=True, capture_output=True, text=True).stdout.strip()
            with open(os.path.join(out, "helper_key.txt"), "w") as f:
                f.write(key)

cfg = os.environ.get("CLAUDE_CONFIG_DIR")
if cfg and "--no-session-persistence" not in args:
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.getcwd())
    pdir = os.path.join(cfg, "projects", slug)
    os.makedirs(pdir, exist_ok=True)
    sid = opt("--session-id") or opt("--resume") or opt("-r")
    if sid is None:
        existing = sorted((os.path.join(pdir, f) for f in os.listdir(pdir) if f.endswith(".jsonl")), key=os.path.getmtime)
        if ("--continue" in args or "-c" in args) and existing:
            path = existing[-1]
        else:
            path = os.path.join(pdir, f"{uuid.uuid4()}.jsonl")
    else:
        path = os.path.join(pdir, f"{sid}.jsonl")
    session_id = os.path.basename(path)[:-6]
    model = os.environ.get("FAKE_CLAUDE_MODEL") or os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL", "unknown")
    turns = int(os.environ.get("FAKE_CLAUDE_TURNS", "2"))
    with open(path, "a") as f:
        if os.environ.get("FAKE_CLAUDE_SYNTHETIC_FIRST"):
            # Claude Code's only response was an API error (429, provider error, "prompt too long"): one assistant
            # line, message.model == "<synthetic>", an all-zero usage, and nothing else (final-fix item 1's fixture
            # for `qualify --baseline`, whose one-shot -p prompt gets exactly one response).
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            zero = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
            f.write(json.dumps({"type": "assistant", "timestamp": ts, "sessionId": session_id, "version": "0.0.0-fake", "effort": "high",
                                "permissionMode": "default", "message": {"id": f"msg_{uuid.uuid4().hex[:8]}", "model": "<synthetic>",
                                "role": "assistant", "usage": zero, "content": [{"type": "text", "text": "API Error: 429"}]}}) + "\n")
            turns = 0
        for i in range(turns):
            time.sleep(0.002)
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"      # real milliseconds, like Claude Code
            usage = {"input_tokens": 1000, "output_tokens": 50, "cache_read_input_tokens": 20000 if i else 0, "cache_creation_input_tokens": 0 if i else 20000}
            mid = f"msg_{uuid.uuid4().hex[:8]}"
            line = {"type": "assistant", "timestamp": ts, "sessionId": session_id, "version": "0.0.0-fake", "effort": "high", "permissionMode": "default",
                    "message": {"id": mid, "model": model, "role": "assistant", "usage": usage, "content": [], "total_cost_usd": 0.24}}
            f.write(json.dumps(line) + "\n")
            f.write(json.dumps({**line, "message": {**line["message"], "content": [{"type": "text", "text": "second block"}]}}) + "\n")

sig_name = os.environ.get("FAKE_CLAUDE_SIGNAL")
if sig_name:
    os.kill(os.getpid(), getattr(signal, f"SIG{sig_name}"))
    time.sleep(5)   # the process is dead once the signal's default disposition runs; this only guards a caught signal
sys.exit(int(os.environ.get("FAKE_CLAUDE_EXIT", "0")))
