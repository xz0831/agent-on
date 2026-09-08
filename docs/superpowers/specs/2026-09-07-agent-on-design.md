# agent-on — an agent-operated model-source layer for agent harnesses, Claude Code first

Status: DRAFT rev 8 · 2026-09-08 · reinstates the conclusion
of the 2026-08-20 verdict "Does claude-litellm Need LiteLLM?" (no), and on
landing replaces `docs/ARCHITECTURE.md`.

Rev 3 incorporated an adversarial review (4 refutations, 7 claim
verifications, 1 completeness critique; workflow `wf_05884356-4c8`). Every
decision the review refuted *as written* is marked ⟲ with what changed.
Three of its findings were measurements that overturned claims in rev 2;
they are stated plainly in §1.1.

Rev 4 incorporates the owner's review of rev 3 (seven findings, three quick
fixes; the owner verified TOML parsing, the installed CLI's options, and
environment inheritance with synthetic keys). Two were P1: the helper-based
credential binding could not see a key supplied only by environment
variable, because the helper inherits the *scrubbed* child environment
(D2 ⟲⟲, §11); and Plan B deleted callbacks the still-running old path
references (§14 — Plans A–C are now purely additive). Five were the same
finding in different places — rev 3 was still treating a configured or
declared value as an applied one: settings-file limits (§7 `configured` /
`advertised` / `verified`), `status --check` writing the gate record
(`last_check` / `last_gate_run`), a two-file "atomic" write (§6, §7.1),
the first request's `input_tokens` as the harness baseline (§7, §12), and
qualification currency by HEAD (§8 fingerprint).

Rev 5 applies the owner's second review (four P2s on the rev-4 diff): the
context formula let a `verified` probe *lift* a declared operator cap
(§7 — now `min(declared, verified)`); the qualification fingerprint hashed
the route entry alone and so missed a changed source URL or inherited limit
(§8 — now the effective, source-merged configuration); concurrent `add`s
could lose an addition invisibly (§7.1 — now a checkout-keyed lock with
re-read); and the session read-back had lost whole-session totals in the
baseline fix (§11 — `first_request`, `this_run`, `session_total`). D9 is
confirmed.

Rev 6 carries the owner's two P2s on the rev-5 diff into Plan A's contract
(the owner asked that they not wait for another review round): the `add`
lock lived under `$STATE`, so two runs with different `CLAUDE_ON_STATE` did
not share it (§7.1 — now `<checkout>/.routes.lock`, keyed by the resource,
not the state root); and the session read-back priced every turn in the
transcript at the *current* route's price, so a paid session resumed on a
free route cost 0 (§11 — now a per-run ledger with the price snapshot taken
at launch, and `unknown` wherever a turn's price cannot be restored). Three
consistency edits found while planning are marked ⟲⟲⟲: source limits are
inherited by any route of the source that declares none (§6);
`harness.env.clean` fails on `model` only when its value is a literal model
id rather than a tier name (§8); and `spend.openrouter` was exercised on
2026-09-07 (§7).

Rev 7 records two shapes Plan A's review found the examples got wrong
(⟲⟲⟲⟲): a `reasoning` table may carry `supported` alone, because a catalog
such as OpenRouter's names parameters and never effort levels (§6, §9); and
`last_gate_run.verifiers` is `{declared, ran}`, not a count, because only the
object lets `gate.no_silent_skip` fail on a verifier declared but never run
(§7, §10; F6). A measurement the same day (§12 `concurrency`) corrected a
belief this document had carried since 2026-09-06: oMLX does not serialise
concurrent requests as such — batching gain is a property of the model (MTP
models barely gain; a plain 4-bit model gains ~3× at 8 in flight), which is
why `concurrency` is measured per route by `qualify` and must never be
inherited from the source.

Rev 8 (owner, 2026-09-08) names the thing for what it turns on: the repository,
the package and the tower CLI are **`agent-on`** (`agent_on/`, `~/.local/state/agent-on/`,
`AGENT_ON_STATE`, `skills/agent-on/`). The harness-specific launchers are thin
shims — **`claude-on <route>`** now, **`codex-on <route>`** when a second L6
lands (Plan F, after D; spikes S6 codex-over-oMLX `/v1/responses` with tools,
S7 credential path without an apiKeyHelper equivalent). Every tower verb
(`status`, `sync`, `add`, `qualify`, `learn`, `gate`, `install`) is
`agent-on <verb>`; a launch is `<harness>-on <route>`, equal to
`agent-on launch --harness <harness> <route>`. The tower (L0–L5) never learns
which harness is asking; L6 is one file per harness. Measured the same day:
oMLX serves the Anthropic, chat, completions and responses wires at once from
one engine with no penalty for mixing them in flight (§12).

## 0. One paragraph

`agent-on` runs an agent harness — Claude Code today, Codex next — on any model from any source —
OpenRouter, oMLX on this machine or any tailnet machine, the two-node
tensor-parallel oMLX endpoint, and exo when it exists — through one route
table, one command, and one queryable statement of what is true right now. It
is operated by agents, not people: every surface is JSON-first, every action
is idempotent and says which invariants it checked, and everything an agent
learns while operating it is written back into the repository where the next
agent can read it. Nothing runs between Claude Code and the model: every
surviving source speaks the Anthropic wire natively, which was measured, not
assumed. There is one copy of the system — the checkout — and no runtime
dependency beyond Python's standard library. LiteLLM leaves entirely, and the
name changes to say so.

## 1. Why this redesign, in evidence

On 2026-09-06 one session operated `claude-litellm` for six hours and hit
fourteen failures. Every one was found sideways while doing something else;
none was found by a check aimed at it. A fourteen-agent mapping pass then read
all tracked lines and a critic verified its main claims against the code.

Baseline, measured as `git ls-files | xargs wc -l` at `1eeb9ed`: **27,806
lines including `config/python-requirements.lock` (2,512); 25,294 without
it.** That count includes docs (1,330), tests (695), config (894) and CI (159);
the targets in §13 use the same measure.

| measure | value |
|---|---|
| public commands | 83 — an operating agent needs 9 (§9 reconciles 9 → 7) |
| non-obvious facts an agent must know to operate safely ("traps") | 232 |
| lines in the invariants layer | 6,794 — the largest layer, and it reports `ok` for checks it did not run |
| lines identified as vestigial with evidence | ~6,150 |
| embedded languages in `lib.zsh` (8,575 lines) | zsh + 42 Ruby blocks + 32 Node blocks + 39 jq calls |
| homes for the fact "LiteLLM is 1.92.0" | 14 |
| homes for concrete route names | 11 |
| homes for "the managed Python version" | 7 |

Five root causes explain all fourteen failures; each was confirmed by the
critic with file:line evidence.

| # | root cause | mechanism | explains failures |
|---|---|---|---|
| R1 | **Declared state stands in for served state.** | `--list`, `status`, `doctor`, the proxy's `/v1/models` all read config and print declarations as if measured. Liveness, limits and policy application are measured only by opt-in, billable or hand-run probes whose results are not kept. | 1 2 10 11 12 13 |
| R2 | **Two copies of the system with a silent selector.** | Checkout and installed prefix share file names; `lib.zsh` force-points 30 path exports (31 export statements with the mode flag) at the installed prefix whenever a manifest exists at the default prefix, and nothing prints which copy was chosen. The installer never runs the verifier the next launch will. | 4 6 7 8 9 |
| R3 | **One fact, N homes, no designated source.** | The same fact is copied across zsh, Ruby, Node, Python, YAML, JSON and Markdown and kept equal by "keep in sync" comments. Checks compare copies to each other, never to an origin. | 2 5 7 12 14 |
| R4 | **Verification is shell text, not predicates, and reports `ok` for not-having-checked.** | The gate is one 1,352-line single-quoted `zsh -fc` string under `set -e` only: an apostrophe truncates it silently; twelve bare `! cmd` assertions cannot fail (zsh exempts negated pipelines from ERR_EXIT); skips print `ok:`; three of eight verifiers are only `py_compile`d. | 1 3 5 6 9 |
| R5 | **No knowledge layer.** | Contracts, remedies and traps live in validator error strings, `lib.zsh` comments, one agent's out-of-repo memory, or nowhere. Three evidence ledgers are name-keyed, write-only, or never written. The same failures recur (F1 three times, F4 twice). A peer agent has no queryable surface and answered 3 of 10 questions wrongly from config. | 1 4 10 13 14 |

The fourteen failures (full text in the mapping transcript `wf_1ffee4a8-b7e`):

1. packaged local routes named oMLX ids the runtime no longer served (3rd time); still listed everywhere; only a completion errored
2. runtime policy globs matched 0 of 17 live models
3. a gate guard false-passed: an apostrophe closed the single-quoted battery
4. promotion deadlock: install refuses a discovered route promoted to packaged (2nd time)
5. semantic merge conflict: a test hardcoded the haiku alias target
6. `verify_litellm_token_clamp.py` could not run; gate only compiled it
7. manifest Python version vs `pyvenv.cfg` drifted; install bricked
8. `lib.zsh` silently measured the installed copy when sourced from a checkout
9. gate needs port 4000 free; fails with the advice "run sync"
10. a peer agent answered from config and was wrong on 3 of 10 points
11. Claude Code reports `total_cost_usd 0.24` on a free local model; 48,312 input tokens before task content
12. two overlapping globs with unresolved precedence
13. the token-observation log was used for non-token facts
14. declaring `x_provider_reasoning_efforts` silently requires two other fields

### 1.1 Three things rev 2 got wrong, corrected by measurement

**(a) Thinking on local models.** Rev 2 claimed the proxy *caused* the
two-week "thinking must be off" policy. Wrong. A two-arm test on
`root4k--Huihui-Qwen3.8-27B-abliterated-oQ4e-mtp` with thinking ON passes all
six fidelity gates **both** direct on oMLX and through LiteLLM 1.92.0 launched
the packaged way. The recorded breakage (`PROVIDERS.md:44`,
`MODEL-RUNBOOK.md:180`) was on Qwen3.5/3.6 models no longer served, and the
2026-08-23 "never answers" leak was measured on the *direct* wire — it was
budget exhaustion, not translation. What stands: on Huihui-Qwen3.8, thinking
on does not break tool calls on either wire. What also stands, and rev 2
missed: **on the direct wire there is no per-request thinking-off switch** —
oMLX honours `thinking: {type: disabled}` or `chat_template_kwargs`, and Claude
Code sends neither for a non-Anthropic model. See D12 ⟲.

**(b) Gateway model discovery.** Rev 2 said (and the owner preferred, from
OpenRouter's page) that `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` lists
the bound source's catalog in Claude Code's picker. Measured on 2.1.263: the
binary fetches `/v1/models?limit=1000` and then **keeps only ids matching
`/(claude|anthropic)/i`**, returning "0 usable models after filter" otherwise.
OpenRouter's 430 models → 27 kept, all `anthropic/claude-*` (paid Anthropic
models through OpenRouter); oMLX → 0. On local sources it is a wasted 3-second
GET per launch; on OpenRouter it adds exactly the escape hatch the tier pin
exists to close. See D8 ⟲.

**(c) Credential exposure on the direct wire.** Rev 2's binding exported the
source's real key as `ANTHROPIC_AUTH_TOKEN`. Measured on 2.1.263: that variable
is inherited by every Bash-tool child, the model can `printenv` it, and it
was echoed into the on-disk transcript. Today only the worthless local
LiteLLM master key reaches the child; the OpenRouter key is scrubbed. The fix
is also measured: `apiKeyHelper` in a per-launch 0600 settings file puts the
key on the wire (`authorization: Bearer …`, `x-api-key: …` observed on a local
listener) while `env | grep` in the child finds nothing. That measurement used the
rev-3 helper form; the owner's rev-4 review found its environment-only case
broken (the helper inherits the scrubbed environment), so the wire path is
the same but the key now travels through a parent-written file. See D2 ⟲⟲,
§11.

Ten questions an agent in the driver's seat cannot answer today. They are
the acceptance test for §7 — each must be answerable from `status`:

| # | question | why unanswerable today |
|---|---|---|
| Q1 | What did the last session consume and cost, under which effort / permission mode / Claude Code version? | Claude Code already writes this to `<config-dir>/projects/<slug>/<session>.jsonl`; nothing reads or points there |
| Q2 | Is the process on :4000 running the code I see in the checkout? | status proves pid/health/config hash only |
| Q3 | Which backend id does route X hit right now, and is it served? | requires hand-joining config against the runtime catalog |
| Q4 | When did the gate last pass, on which port, with which skips? | nothing persisted |
| Q5 | How do I run the checkout against a scratch prefix? | the answer exists (`AI_LITELLM_HOME=<checkout>`) but no surface says so |
| Q6 | How much OpenRouter money have probes and sessions spent? | no ledger |
| Q7 | Does anything phone home? | `LITELLM_TELEMETRY` is set only inside one verifier |
| Q8 | Which shared `~/.claude` items account for the 48K pre-task tokens? | shared links are all-or-nothing; no attribution |
| Q9 | When does the OAuth token expire? | computed in `oauth.py`, surfaced nowhere |
| Q10 | What must change together to delete X? | no dependency map in the repo |

## 2. The three properties, defined operationally

**Agent-intuitive.** An agent can know the true state of the system from one
command without reading source. Every fact is shown as *declared* next to
*observed*, with a timestamp on the observation. Nothing prints `ok` unless
it checked.

**Agent-ergonomic.** The commonest action is the shortest. There are seven
commands; each is idempotent, each accepts `--json`, each evaluates the
relevant invariants before acting and names them in its output. There are no
hidden preconditions: if a command cannot run, it says which invariant failed
and how to fix it.

**Agent-accretive.** Every learning an agent makes while operating the system
— a measurement, a decision, a trap — has exactly one typed, schema-checked,
git-tracked home, keyed by a stable id. A peer agent in another session finds
it by reading a file. The system's own actions write to the same files.

A fourth, implied property: **resource-optimal control.** An agent can only
minimise resource use if it knows the costs before it acts. Every route
carries a cost model (§12) and the launcher prints it.

### 2.1 Why a program at all, and not a skill

A public observation (2026-09-07) argues that with Tailscale making every AI
machine on the network reachable, one should "install Tailscale, then ask the
model in your harness to wire the tailnet-served model APIs into the
harness" — no separate program. The argument is right about reachability and
right that a skill is the ergonomic surface for an agent already inside Claude
Code. It is wrong about one thing and silent about two:

- The *launch* cannot be a skill. Binding Claude Code to a source means
  setting that process's environment before it starts; no code running inside
  the process can do it. That is the one irreducible reason `claude-on` is a
  command.
- A skill improvises; it does not accumulate. The route table with its limit
  tiers, the observed liveness and cost, and the knowledge files are what let
  the *next* session start from what the last one learned instead of
  re-deriving it. That is the accretive property, and a per-session skill
  cannot carry it.
- Reachability is not liveness. Tailscale answers "can I connect"; `sync`
  answers "is the model served, at what limit, at what cost".

So: `agent-on` is a command for the durable state and `claude-on` for the launch, **and** it
ships a skill (`skills/agent-on/SKILL.md`) that exposes `status`, `sync`,
`qualify` and `learn` to an agent already in a session. Tailscale is not a
feature of `agent-on`; it is a property of a source's `base_url` (§5).

## 3. Decisions

All thirteen are settled with the owner (2026-09-06/07); D9 was the one
default and was confirmed on 2026-09-07. ⟲ marks a decision amended by the
rev-3 adversarial review; ⟲⟲ one amended again by the owner's rev-4 review.

| # | decision | rationale |
|---|---|---|
| D1 | **Rename to `agent-on`** (⟲⟲⟲⟲⟲ rev 8; was `claude-on`). Repo, package, tower binary, config dir, state dir; `claude-on` survives as the Claude Code launcher shim beside it. No compatibility shim beyond a one-time `mv` note. | The current name encodes an implementation. The previous rename's compatibility code is 1,100 vestigial lines; do it once, cleanly. `claude-on kimi` reads as English and the commonest action is the shortest. |
| D2 ⟲⟲ | **No proxy. Nothing runs between Claude Code and the source**, and **no source credential is ever placed in the child environment.** The *launcher* resolves the key (environment, else `$STATE/env`), writes it to a per-launch 0600 file under `$STATE/run/<launch-id>/`, and the `apiKeyHelper` in the per-launch settings file reads that file; every source's `auth_env` — including the active one — is scrubbed from the child. §11 has the full flow and cleanup. | Every surviving source speaks `/v1/messages` natively (§5). Routing through LiteLLM cost prompt caching on every route, put 13 monkeypatches in every path and pinned a version across 14 files. Rev 2's binding leaked the real key to the model (§1.1c). Rev 3's helper read the key from the environment — but the helper runs as a child of Claude Code and inherits the *scrubbed* environment, so a key supplied only by environment variable never reached it, and "environment wins over file" could not hold. The parent must choose and hand over the key. |
| D3 | **The ChatGPT OAuth lane is dropped.** The four `GPT-*-chatgpt-oauth` routes packaged on 2026-09-06 are deleted in Plan D. | Owner, 2026-09-07: "gpt는 안하면 그만 … 실제로 굳이 필요없었는데 litellm으로 붙일 수 있다고 하니까 했던거." It was the only source needing a translator. GPT is used through Codex. This reverses 2026-09-06, which reversed 2026-08-20; all three turns and their reasons go into `decisions.jsonl`. |
| D4 ⟲ | **One implementation language, zero dependencies.** One package, `agent_on/`, Python ≥ 3.11 from `PATH`, standard library only. Declarations are TOML (`tomllib`). zsh survives as a ≤20-line shim. | An agent modifying the system should hold one language. `python3` on this machine is 3.14.7 and `import yaml` fails there today — a dependency is F7's territory. TOML removes it. |
| D5 | **One home per fact.** Versions are read from the runtime. Route names live only in `routes.toml`; tests and docs derive from it. Constants live once. | R3. The "replication as drift guard" pattern existed only because there were four implementations. |
| D6 | **Inform, don't gate.** Qualification results, cost models and liveness are shown; they do not block a launch. | Owner: operated by competent agents. The current launch gates produced false confidence without preventing any observed failure. |
| D7 ⟲ | **Tier aliases are not user configuration.** The launcher binds Claude Code's four tier slots and the subagent slot to the launch route. `--sonnet <route>` / `--haiku <route>` override one slot with a route **on the same source**; `--sonnet` matters only under `--permission-mode auto`, where the classifier resolves through it. | Owner: agents invoke `claude-on <route>` directly. The slots must still be *set* — subagents and the classifier resolve through them. History for `decisions.jsonl`: the per-tier map was added 2026-06-07 so `haiku` could be a free local model for background calls (only possible behind a proxy), and pinned off on 2026-07-13 (`38ce3f0`). Residual: the auto-mode classifier consults a server-supplied feature config before the SONNET slot; not verifiable offline. |
| D8 ⟲ | **Gateway model discovery is OFF by default**; `--discover` opts in. | §1.1b: the binary filters discovery to `/(claude\|anthropic)/i`; on local sources it lists nothing, on OpenRouter only paid Anthropic models. Rev 2 and the owner's preference rested on the doc's description, which the measurement contradicts. The filter is seeded into `traps.jsonl` so it is not rediscovered. |
| D9 ⟲ | **No installed copy.** The checkout is the installation: `install` links `~/.local/bin/agent-on` and `~/.local/bin/claude-on` to `<checkout>/bin/`, creates the state directory, and checks the interpreter. Drift detection is `git status --porcelain` plus "does the shim point here". The fingerprint chain, shim digest pin and symlink walks are deleted — **confirmed by the owner 2026-09-07** as the sole owner-choice item, default kept. | This kills R2 at the root instead of detecting it: there is nothing to drift between. `ARCHITECTURE.md` says the chain "is not a security boundary against the owner of the Unix account"; `git log` shows it never caught anything; it bricked the install (F7). Its main object, the venv, disappears with D4. |
| D10 | **Route names are `<source>/<model>`.** Optional short aliases live in `routes.toml`. | The source is then visible in the name (half of Q3 by convention); retires the `-openrouter`/`-omlx` suffix idiom. |
| D11 | **Strangler migration**, decomposed into five plans (§14). | `55e17e3` deleted direct mode *and its rationale* in one commit; irreversible big steps have failed here twice. |
| D12 ⟲ | **Thinking on a local model is whatever the source's template does; `agent-on` measures and reports its cost and does not pretend to control it.** There is no `thinking:` field in `routes.toml`. `qualify` records whether a `thinking` block appeared and whether the answer completed. The controls that exist are the source's own server/template default and `CLAUDE_CODE_MAX_OUTPUT_TOKENS`. | §1.1a. Rev 2's "cost hint passed through by the launcher" was unimplementable: no per-request field reaches a non-Anthropic model. The cost is real (1.9–3.3K thinking tokens on a five-sentence task; >6,000 on the 2026-08-23 run) and is what the cost model shows. |
| D13 | **Machine-written state lives in one place, outside git.** `$XDG_STATE_HOME/agent-on/` (default `~/.local/state/agent-on/`) holds `routes.discovered.toml`, `observed.json`, `locks/observed.lock` (§7.1 — the `add` lock is `<checkout>/.routes.lock`, keyed by the resource it protects), `sessions/<session-id>.jsonl` (the per-run cost ledger — §11), `run/<launch-id>/` (per-launch files under a launcher-minted id, removed on exit — §7.1), the isolated Claude config dir, and the 0600 `env` file. `knowledge/` and `routes.toml` live in the checkout and are git-tracked. `AGENT_ON_STATE` overrides the state root for scratch runs. Storage rules: §7.1. | The review's day-one gap: rev 2 never said where the three machine-written files live or which copy owns them. With D9 there is one copy; with this rule there is one state root. `sync` never dirties a tracked file; `learn` and `add` produce diffs the agent can commit. |

## 4. The tower

Each layer has one artifact, one interface, and depends only on the layers
below it. `X` in the current system — 3,969 lines that cut across every layer
— has no place here.

```
L5  KNOWLEDGE   knowledge/*.jsonl              typed, git-tracked, stable ids       read by: status, peers, skill
L4  ACTIONS     agent-on <verb> · <harness>-on <route>   7 commands, idempotent, --json   read: L1-L3  write: L2, L5
L3  INVARIANTS  agent_on/invariants.py        named predicates over a context       read: L1, L2, tree, home
L2  TRUTH       $STATE/observed.json           per-route measurements, timestamped   written by: sync, launch, qualify, status --check, the gate
L1  ROUTES      routes.toml + $STATE/routes.discovered.toml   the only declarations
L0  SOURCES     openrouter · omlx · omlx@<tailnet-host> · omlx-tp2 · exo
────────────────────────────────────────────────────────────────────────────────────
L6  HARNESS     agent_on/harness.py           how Claude Code is bound to a route   read: L1, L2
```

L6 sits beside the tower, not on top of it: it is the Claude-Code-specific
binding and it is what makes "identical harness, different model" true.

## 5. L0 — Sources

A source is something that serves models over the Anthropic wire, reachable
by URL. There is one binding: Claude Code is pointed at it. A source that
does not speak `/v1/messages` is not a source of this system (D2, D3).

| source | endpoint | auth | catalog | discovery | measured |
|---|---|---|---|---|---|
| `openrouter` | `https://openrouter.ai/api` | `OPENROUTER_API_KEY` via `apiKeyHelper` | `GET /api/v1/models` (limits, `supported_parameters`, pricing) | on request (`add`) | 30/30 gates direct 2026-08-20; real 2-turn session 2026-09-07 with `cache_read_input_tokens` 21,440 — but two standalone identical requests cached 0, so caching is measured per route, not assumed |
| `omlx` | `http://127.0.0.1:8000` — `/v1/messages`, `/v1/messages/count_tokens` (200, `{"input_tokens":53}`) | none | `GET /v1/models` (ids, `max_model_len`); configured caps (settings file, `confidence = "configured"`) in `~/.omlx/settings.json` `sampling.max_context_window` 131072 / `max_tokens` 32768 | automatic on `sync` | 6/6 gates direct, thinking on, 2026-09-07; real session `cache_read` 20,480 |
| `omlx@<host>` | `http://<tailnet-host>:8000` — the same oMLX on another tailnet machine (today: `mortys-mac-studio`, 100.77.98.96, MagicDNS) | none | same | automatic on `sync` when reachable | **not yet** — morty has an oMLX install per the cluster docs; S5 |
| `omlx-tp2` | `http://127.0.0.1:8003` — oMLX serving one model tensor-parallel across rick↔morty over Thunderbolt-5 RDMA | none | `GET /v1/models` | automatic on `sync` | **not reachable on 2026-09-07** from any rick address; the cluster orchestrator's report of a live TP2 endpoint was stale at review time. S4 |
| `exo` | `http://127.0.0.1:52415` — `/v1/messages` per README | none | `GET /v1/models` | automatic on `sync` when reachable | **not yet** — S3; §5.1 |

A source's `base_url` may be any host. Tailscale is the reason the third row
exists and costs no code: `tailscale status` on rick lists `mortys-mac-studio`
active, so `omlx@morty` is a URL, and `sync` treats it like any other.
`omlx` and `omlx-tp2` are separate sources because they are separate
endpoints with separate catalogs and a very different cost model (one node vs
two over RDMA: 1.21× decode, 1.51× prefill measured on Kimi-K2.7).

oMLX carries its own `claude_code` section (`mode`, `opus_model`,
`sonnet_model`, `haiku_model`). `agent-on` does not use it: tier slots are
set by the launcher (D7) so one rule holds across every source.

OpenRouter's official page, quoted in full because rev 2 quoted one sentence:
"Claude Code with OpenRouter is only guaranteed to work with the Anthropic
first-party provider. For maximum compatibility, we recommend setting
Anthropic 1P as top priority provider when using Claude Code." · "Claude Code
is optimized for Anthropic models and may not work correctly with other
providers." · "Fast mode is only served by the Anthropic first-party
provider." · "When you set `ANTHROPIC_BASE_URL` to `https://openrouter.ai/api`,
Claude Code speaks its native protocol directly to OpenRouter. No local proxy
server is required." No enforcement observed: a Claude-Code-shaped request
(adaptive thinking, `output_config.effort`, betas) on `z-ai/glm-5.2` returned
200 with `[thinking, text]`.

### 5.1 exo and the cluster — state on 2026-09-07 (orchestrator report, measured)

- **rick:** no `EXO.app`, no process, nothing on :52415; `mac-cluster/services-rick.conf:14` still lists exo (stale). macOS 26.6.2 meets exo's RDMA floor (26.2).
- **morty:** `~/.local/bin/exo` present; no app, no process, :52415 closed.
- **History:** exo's launchd daemon was disabled on 2026-08-26 — it took over the Thunderbolt service and reverted static TB IPs to DHCP mid-benchmark, breaking rank 1 of the oMLX tensor-parallel pair. On 2026-09-02 a two-node bench found exo peer discovery failing; the pair was declared unneeded. No open task. Only trace: `mac-cluster/docs/CLUSTER_OPERATIONS.md:301` (exo claims 1.8× on two devices; the cluster measured 1.21× under oMLX).
- **RDMA works** — one Thunderbolt-5 link, 80 Gb/s, static `10.0.1.1/2`, jaccl ring 13.86 GB/s. When it is in use, it is used by oMLX tensor-parallel, not exo.
- **Constraint if exo returns:** it must not manage Thunderbolt networking.

exo is a source with `discover = true` that `sync` reports `unreachable`
until it exists. No plan is blocked on it.

## 6. L1 — Routes: `routes.toml` and `$STATE/routes.discovered.toml`

Two files, one schema, loaded together. `routes.toml` is git-tracked and
hand- or `add`-edited. `routes.discovered.toml` is machine-written by `sync`
into the state root (D13) and never committed. A route outside the
discovered file is *packaged* by definition — there is no `packaged` flag.

```toml
version = 1

[sources.openrouter]
base_url = "https://openrouter.ai/api"
auth_env = "OPENROUTER_API_KEY"
catalog  = "https://openrouter.ai/api/v1/models"        # absolute: used verbatim

[sources.omlx]
base_url = "http://127.0.0.1:8000"
catalog  = "/v1/models"                                  # relative: urljoin(base_url, catalog)
discover = true

[sources.omlx.limits]                                    # applies to every discovered omlx route
input      = 131072
output     = 32768
confidence = "configured"                                # what the settings file says, not what the server applied
source     = "~/.omlx/settings.json sampling.max_context_window / sampling.max_tokens"

[sources."omlx@morty"]
base_url = "http://mortys-mac-studio:8000"
catalog  = "/v1/models"
discover = true

[sources.omlx-tp2]
base_url = "http://127.0.0.1:8003"
catalog  = "/v1/models"
discover = true

[sources.exo]
base_url = "http://127.0.0.1:52415"
catalog  = "/v1/models"
discover = true

[routes."openrouter/z-ai/glm-5.2"]
wire_model = "z-ai/glm-5.2"
aliases    = ["glm"]

[routes."openrouter/z-ai/glm-5.2".limits]
input = 1048576
output = 32768
confidence = "provider"
source = "openrouter.top_provider"

[routes."openrouter/z-ai/glm-5.2".reasoning]
efforts = ["low", "medium", "high"]
provider_efforts = ["xhigh", "high"]
confidence = "provider"
source = "openrouter.supported_parameters"

[routes."openrouter/z-ai/glm-5.2".price]
input_usd_per_mtok = 0.60
output_usd_per_mtok = 2.20
cache_read_usd_per_mtok = 0.06
cache_write_usd_per_mtok = 0.75
source = "openrouter.pricing"

[routes."omlx/root4k--Huihui-Qwen3.8-27B-abliterated-oQ4e-mtp"]
wire_model = "root4k--Huihui-Qwen3.8-27B-abliterated-oQ4e-mtp"
aliases = ["huihui"]
```

Rules the schema enforces — and the schema (`agent_on/schemas/routes.py`)
is the only place they are stated:

- Route name = `<source>/<model>`; the source must exist; `wire_model` defaults to the part after the first `/`.
- Every numeric limit carries a `confidence` and a `source`. In L1 the allowed confidences are `provider` (the provider's published figure), `owned-policy` (a cap we chose), and `configured` (read from a source's settings file — what the file says, not what the server applied). `advertised` and `verified` are L2 tiers written only by `sync`/`qualify` (§7); `add` may copy an `advertised` value into L1 as `provider`, never as `verified`.
- `reasoning.provider_efforts` may be present without `efforts` (advertised but not selectable). No ceiling field: with no translator there is no transport ceiling. `supported` (bool) with a `source` may stand alone (⟲⟲⟲⟲ rev 7): OpenRouter's `supported_parameters` lists `reasoning` / `reasoning_effort` — parameter names, never levels — so `add` writes `supported` and `confidence = "provider"` and invents no effort list; `efforts` is written only when a catalog publishes levels.
- Duplicates between the two files are resolved **at read time, packaged wins**, keyed by `(source, wire_model)`. `add omlx/<id>` therefore writes only `routes.toml` (one file, one atomic temp+rename); the discovered twin is shadowed immediately and dropped from `routes.discovered.toml` at the next `sync`. No write ever spans the two files — they may sit on different filesystems, and a two-file "atomic" update is not one (the F4 path, done honestly). A packaged route whose `wire_model` the source no longer serves is reported `orphaned`, never deleted.
- Source-level `limits` apply to every route of that source that declares no `limits` of its own — discovered or packaged (⟲⟲⟲ rev 6: the packaged `omlx/…Huihui…` route above carries none and must not end up uncapped). No globs.
- A relative `catalog` is `urljoin(base_url, catalog)`; an absolute one is used verbatim.

## 7. L2 — Truth: `$STATE/observed.json`

What has been measured, by what, when. Written only by actions; validated
against `agent_on/schemas/observed.py`; every `checked` is RFC 3339 UTC.
Never-measured is always explicit, never implied by absence: a numeric or
boolean field that has not been measured is `null`; `caching` is the string
`"unknown"` because it is three-valued (`true` / `false` / `unknown`). The
schema rejects a missing key. `status` prints it beside L1.

```json
{
  "copy":    { "checkout": "/Users/rick/Projects/agent-on", "commit": "1eeb9ed", "dirty": false,
               "shim": "~/.local/bin/agent-on -> /Users/rick/Projects/agent-on/bin/agent-on",
               "python": "/opt/homebrew/bin/python3 3.14.7", "state": "~/.local/state/agent-on" },
  "sources": {
    "openrouter": { "reachable": true, "checked": "2026-09-07T00:12:03Z", "catalog_count": 430,
                    "catalog": { "z-ai/glm-5.2": { "context_length": 1048576, "pricing": { "prompt": 0.0000006 } } } },
    "omlx":       { "reachable": true, "checked": "2026-09-07T00:12:03Z", "catalog": ["root4k--Huihui-Qwen3.8-27B-abliterated-oQ4e-mtp"],
                    "configured_limits": { "input": 131072, "output": 32768, "source": "~/.omlx/settings.json", "read_at": "2026-09-07T00:12:03Z" } },
    "omlx@morty": { "reachable": false, "checked": "2026-09-07T00:12:04Z", "error": "connect refused mortys-mac-studio:8000" },
    "omlx-tp2":   { "reachable": false, "checked": "2026-09-07T00:12:04Z", "error": "connect refused 127.0.0.1:8003" },
    "exo":        { "reachable": false, "checked": "2026-09-07T00:12:04Z", "error": "connect refused 127.0.0.1:52415" }
  },
  "routes": {
    "omlx/root4k--Huihui-Qwen3.8-27B-abliterated-oQ4e-mtp": {
      "served": true, "checked": "2026-09-07T00:12:03Z",
      "limits": {
        "input":  { "configured": 131072, "advertised": 262144, "verified": null, "checked": "2026-09-07T00:12:03Z" },
        "output": { "configured": 32768,  "advertised": null,   "verified": null, "checked": "2026-09-07T00:12:03Z" }
      },
      "cost_model": { "context": 131072, "context_basis": "declared",
                      "harness_baseline_tokens": { "value": 48312, "measured_by": "qualify --baseline", "claude_code": "2.1.263", "at": "2026-09-07T00:41:10Z" },
                      "tok_s": 63, "usd_per_mtok": { "input": 0, "output": 0, "cache_read": 0, "cache_write": 0 },
                      "caching": true, "concurrency": 1,
                      "thinking": { "observed": true, "tokens_on_probe": 2600 }, "checked": "2026-09-07T00:40:00Z" },
      "last_qualification": { "pass": true, "gates": 6, "thinking_block_seen": true, "completed": true, "at": "2026-09-07T00:40:00Z",
                              "fingerprint": { "effective_route_sha": "3f9a1c2e", "wire_model": "root4k--Huihui-Qwen3.8-27B-abliterated-oQ4e-mtp",
                                               "source_identity": "omlx 0.6.4 / owned_by=omlx", "claude_code": "2.1.263" } },
      "last_session": { "id": "b41e7c02-5d3a-4f9e-9c1b-2a6f8e0d7a55", "at": "2026-09-07T01:05:12Z",
                        "first_request": { "input_tokens_total": 51880,
                                           "usage": { "input_tokens": 3568, "cache_read_input_tokens": 48312, "cache_creation_input_tokens": 0, "output_tokens": 412 } },
                        "this_run":      { "turns": 3, "usage": { "input_tokens": 9714, "cache_read_input_tokens": 144936, "cache_creation_input_tokens": 0, "output_tokens": 1204 },
                                           "cost_usd": 0.0, "models_seen": ["root4k--Huihui-Qwen3.8-27B-abliterated-oQ4e-mtp"] },
                        "session_total": { "turns": 3, "usage": { "input_tokens": 9714, "cache_read_input_tokens": 144936, "cache_creation_input_tokens": 0, "output_tokens": 1204 },
                                           "cost_usd": 0.0, "covered_turns": 3, "uncovered_turns": 0 },
                        "scope_note": "fresh session; this_run == session_total",
                        "duration_ms": 41200, "effort": "xhigh", "permission_mode": null, "claude_code": "2.1.263" }
    }
  },
  "last_check":    { "at": "2026-09-07T01:02:00Z", "commit": "1eeb9ed", "result": "pass", "skipped": ["source.reachable:omlx-tp2"] },
  "last_gate_run": { "at": "2026-09-07T00:50:00Z", "commit": "1eeb9ed", "result": "pass", "tests": 31, "verifiers": { "declared": ["fidelity"], "ran": ["fidelity"] },
                     "skipped": ["source.reachable:omlx@morty", "source.reachable:omlx-tp2", "source.reachable:exo"], "mock_port": 51873 },
  "spend": { "openrouter": { "usd_used": 77.85, "usd_limit": 100, "limit_reset": "daily", "usd_remaining": 99.96, "usd_used_daily": 0.04,
                             "source": "openrouter GET /api/v1/auth/key", "checked": "2026-09-07T00:12:03Z" } }
}
```

How each field is measured:

| field | measured by | cost |
|---|---|---|
| `sources.*.reachable`, `catalog` | `sync`: `GET catalog`. For OpenRouter only entries for declared routes plus `catalog_count` are kept | free |
| `sources.omlx*.configured_limits` | `sync`: read the source host's `~/.omlx/settings.json` when local — what the file says, not what the server applied; the same numbers appear per route as `limits.*.configured` | free |
| `routes.*.served` | `sync`: `wire_model ∈ catalog` — the check that would have caught F1 the day it happened | free |
| `routes.*.limits.*.configured` | `sync`: the source's settings file (local only) | free |
| `routes.*.limits.*.advertised` | `sync`: catalog `max_model_len` / `context_length` — what the running server *says* | free |
| `routes.*.limits.*.verified` | `qualify --limits`: a request sized just under and just over the smaller of configured/advertised; the boundary the server actually enforces. Absent until run. **Configured and advertised are not applied limits** — a settings edit the server has not reloaded, or a second endpoint started with other settings, differ from what a request meets; recording either as "measured" is R1 again | local free; cloud ~ one long prompt |
| `cost_model.context`, `context_basis` | **`min(L1 declared, verified)`** when `verified` is present, else `min(L1 declared, configured, advertised)`. The L1 declared cap participates in *both* branches — a 32K `owned-policy` cap on a route whose probe finds 128K yields 32K, because the operator set it; `verified` only ever lowers, never lifts. `context_basis` names which bound won; on a tie it names `declared`, because the operator's cap is the reason the number is what it is | — |
| `cost_model.tok_s`, `concurrency` | `qualify`: short timed completion, then two concurrent | local free; cloud ~$0.001 |
| `cost_model.caching` | `qualify`: two-turn probe reading `cache_read_input_tokens` → `true` / `false`; **`unknown` until the probe has run** — a missing price is not a measurement | as above |
| `cost_model.thinking` | `qualify`: `thinking` block present? `stop_reason == end_turn` and answer non-truncated? thinking tokens counted | as above |
| `cost_model.harness_baseline_tokens` | `qualify --baseline`: a fixed minimal prompt (`-p 'Reply with exactly: OK'`) on this route, first request's `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`, with the Claude Code version. **Not** taken from ordinary sessions — their first request carries the task, and `input_tokens` excludes cache tokens, so a well-cached session would report a *smaller* baseline | free locally; ~48K input tokens on cloud |
| `routes.*.last_session` | the launch: read from Claude Code's session `.jsonl` after exit (§11) — `first_request` (all three input fields summed, plus raw usage), `this_run` and `session_total` (turn counts, summed usage, `cost_usd` — a number, or the string `"unknown"` when any turn's price cannot be restored, §11); recorded on every launch that persisted a session, latest wins | free |
| `routes.*.last_qualification` | `qualify`: the six fidelity gates against the route's real endpoint, plus the **fingerprint** it was valid for (§8 `qualification.current`) | cloud ~$0.01 |
| `last_check` | `status --check`: invariants only | — |
| `last_gate_run` | the gate runner only: unit tests + verifiers + invariants. `status --check` never writes it, so a failed gate is never masked by a later invariant-only pass (Q4) | — |
| `spend.openrouter` | `sync`: `GET /api/v1/auth/key` — exercised 2026-09-07 with the Keychain key (⟲⟲⟲): `data.usage` is lifetime USD, `data.limit` + `limit_reset` the cap and its period (here 100, daily), `limit_remaining` and `usage_daily` what is left and spent today; recorded as `usd_used`, `usd_limit`, `limit_reset`, `usd_remaining`, `usd_used_daily` | free |
| `copy.*` | every command: `__file__`, `git status --porcelain`, the shim's target, `sys.executable` | free |

### 7.1 Storage rules

Several processes write state: `sync`, `qualify`, `status --check`, the gate,
and every launch's read-back — and two launches can end at the same moment.

- **`observed.json`**: read-modify-write under an exclusive `fcntl.flock` on
  `$STATE/locks/observed.lock`, held for the whole update; the writer merges its
  fields into the *freshly re-read* document (never a copy loaded earlier),
  writes `observed.json.tmp.<pid>`, `fsync`, `rename`. A reader ignores `.tmp.*`
  files. The lock is advisory and dies with the process, so a crash leaves at
  worst a stale `.tmp.*`, which the next writer deletes.
- **`routes.discovered.toml`**: written only by `sync`, same temp+rename, under
  the same lock (it is state, and `sync` also writes `observed.json`).
- **`routes.toml`**: written only by `add`, under an exclusive `flock` on
  `<checkout>/.routes.lock` (git-ignored; ⟲⟲⟲ rev 6 — the lock is keyed by
  the resource it protects, so a default run and a `CLAUDE_ON_STATE` scratch
  run editing the same checkout take the *same* lock; the rev-5 state-rooted
  lock measurably let two exclusive locks be held at once); `add` re-reads `routes.toml` *after* taking the
  lock, applies its change to that fresh content, writes a temp file in the
  checkout, `fsync`, `rename`. Two concurrent `add`s therefore serialise and
  both survive. Without the lock the second rename would silently discard the
  first addition and the final `git diff` would show only the survivor — a
  loss the diff cannot reveal, which is why "the diff makes it visible" was
  wrong.
- **`knowledge/*.jsonl`**: append with `O_APPEND` of one complete line; the
  POSIX guarantee for small appends is enough, and each record carries its
  own `id`.
- **`$STATE/run/<launch-id>/`**: created by a launch under a **launcher-chosen
  `launch-id`** (a ULID minted before spawn — the session id is *not* used
  as the name because under `--resume`/`--continue` the launcher does not
  know it until Claude Code exits; the session id, once known, is recorded
  inside the directory), removed when its child exits; a launch first sweeps
  any `run/*` directory whose recorded pid is dead (crash recovery, and the
  credential file goes with it).

Claude Code's own transcript is the single most valuable truth source the
current system ignores (Q1). Verified fields per assistant turn:
`message.model`, `message.usage.{input_tokens,output_tokens,cache_read_input_tokens,cache_creation_input_tokens}`,
a per-line `timestamp` (RFC 3339 — what the `this_run` split in §11 rests on);
session-level `version`; `effort` and `permissionMode` exist as top-level keys
and are populated when Claude Code sets them (both were null in a `-p` run,
so they are recorded *when present*). `total_cost_usd` is **never** copied:
it is computed from Anthropic's price table and is meaningless on any other
model (F11; measured `costUSD 0.183` on a free local model). Cost is
`usage × price` from L1.

## 8. L3 — Invariants

A registry of named predicates over a context `(routes, observed, tree,
home)` — the two declaration files, the observed state, the checkout tree
(for lints) and `~/.claude` (for the harness lint). Each has a stable id, a
one-line statement, a fix hint, and returns `pass | fail | skip` with a
reason. `status --check` evaluates all of them; every action evaluates the
ones it depends on and names them. **A skip is never printed as a pass.**

```python
@invariant("route.served",
           fix="run `agent-on sync`; if still orphaned, the source renamed the model — update wire_model")
def route_served(ctx, route):
    src = ctx.observed.sources.get(route.source)
    if src is None or not src.reachable:
        return skip(f"{route.source} unreachable")
    return ok() if route.wire_model in src.catalog else fail(f"{route.wire_model} not in {route.source} catalog")
```

| id | statement | catches |
|---|---|---|
| `route.served` | every route's `wire_model` is in its source's live catalog | F1 |
| `route.unique` | no two routes share a name; discovered routes dedup against packaged by `(source, wire_model)` at read time | F4 |
| `source.limits.propagated` | every discovered route of a source carries the source limits — checked by reading the route (propagation only; whether the server applies them is the `verified` tier) | F2, F12 |
| `limits.declared_vs_observed` | declared input ≤ `verified` when present, else ≤ min(configured, advertised) and the result is reported `unverified`; declared > the bound fails | R1 |
| `copy.single` | the shim resolves to this checkout and the tree is clean (`dirty` is reported, not failed) | F7, F8, R2 |
| `credential.not_in_child_env` | a launched child's environment contains no source `auth_env` value (asserted by a unit test that spawns `printenv`) | §1.1c |
| `harness.env.clean` | `~/.claude/settings.json` sets none of the routing denylist — the **current broad list** (`ANTHROPIC_*`, `CLAUDE_CODE_SUBAGENT_MODEL`, `CLAUDE_CODE_MAX_*`, `*_PROXY`, `apiKeyHelper`, `model` — where `model` fails only for a literal model id; a tier name such as `fable` resolves through the slots the launcher pins (D7) and passes with a note, ⟲⟲⟲ rev 6, because this machine's shared settings carry `model: fable`), because a shared `env` block measurably overrides the launcher's process env | (kept; rev 2 had narrowed it to three keys) |
| `gate.no_silent_skip` | the last gate run's `skipped` list is printed with the result, and every verifier it declared ran | F6 |
| `gate.mock.ephemeral` | the gate's mock source binds an ephemeral port, never a configured one | F9 |
| `test.names.derived` | no test or doc contains a route name literal not in `routes.toml` (lint over `tree`) | F5 |
| `knowledge.typed` | every knowledge record validates against its kind's schema | F13 |
| `schema.complete` | every field contract lives in the schema; no validator emits a rule the schema lacks (lint) | F14 |
| `cost.not_copied` | no L2 field is ever sourced from Claude Code's `total_cost_usd` (unit test over the read-back) | F11 |
| `qualification.current` | the route's last qualification **fingerprint** still matches: `effective_route_sha` — the hash of the route's entry **merged with its source's entry** (`base_url`, `auth_env`, `catalog`, inherited `limits`), i.e. the resolved configuration a request actually uses, not HEAD (a docs commit must not expire it) and not the route entry alone (a changed `sources.omlx.base_url` or an inherited limit must) — plus `wire_model`, `source_identity` (server version / `owned_by` from the catalog when published), and the Claude Code version; any mismatch → `stale` naming the field (warn, D6) | F10 |

F3 (the truncated quoted battery) has no predicate: its element is D4 —
there is no quoted shell string to truncate. F15 is spike S1.

Invariants replace: `check.zsh`'s battery, the seven `doctor` sub-batteries,
the Ruby YAML validator, and the three "is the string present in the YAML"
checks. The gate becomes: unit tests (including an in-process mock
`/v1/messages` source on an ephemeral port for harness and sync tests), each
verifier as a process, every invariant, then `last_gate_run` to L2 and a
record to `knowledge/gate-runs.jsonl`.

## 9. L4 — Actions

Seven commands. Six are tower verbs, `agent-on <verb>`; the launch is the
harness shim `claude-on <route>` (referred to below as "the launch"; there is
no `use` verb; ⟲⟲⟲⟲⟲ rev 8). Every command accepts `--json`; every
command prints `copy.*`.

| command | does | reads | writes | invariants first |
|---|---|---|---|---|
| `claude-on <route\|alias> [claude args…]` | bind Claude Code to the route and **spawn** it as a child (inherited stdio, SIGINT/SIGTERM forwarded, exit status propagated); after exit, read the session transcript when one exists and record the session summary. Session rules: the launcher passes `--session-id <uuid>` unless the user passed `--session-id` (theirs is used) or `--resume`/`--continue` (the resumed session's file is read); if the user passed `--no-session-persistence` there is no transcript and `last_session` is recorded as `{ "skipped": "no-session-persistence" }` — read-back is best-effort, never a reason to refuse arguments | L1 L2 | L2 | `route.served` (re-probed with one ≤2 s GET; unreachable → skip + warning, launch proceeds — D6), `harness.env.clean`, `credential.not_in_child_env` |
| `agent-on status [--check]` | print L1 beside L2 and the last N observations and applicable traps for the selected route; with `--check`, evaluate every invariant and write **`last_check`** — never `last_gate_run`, which only the gate runner writes | L1 L2 L5 | L2 (`last_check` if `--check`) | all |
| `agent-on sync` | probe every source; refresh catalogs, served flags, `configured` and `advertised` limits (never `verified` — that is `qualify --limits`), spend; rewrite `routes.discovered.toml`; report orphans | L0 L1 | `$STATE/routes.discovered.toml`, L2 | `route.unique` after write |
| `agent-on add <source>/<model> [--alias a]` | declare a packaged route in `routes.toml`; for OpenRouter fill limits, reasoning (`supported`; `efforts` only when a catalog publishes levels — ⟲⟲⟲⟲ rev 7) and price from the catalog with `confidence = "provider"`; a discovered twin is shadowed at read time (packaged wins, §6) and dropped by the next `sync` | L0 L1 | `routes.toml` | `route.served`, `route.unique` |
| `agent-on qualify <route> [--baseline] [--limits]` | six fidelity gates + throughput / concurrency / caching / thinking probes, recorded with the fingerprint (§8); `--baseline` measures `harness_baseline_tokens` with the fixed minimal prompt; `--limits` finds the enforced input boundary (`verified`) | L1 L2 | L2 L5 (`qualifications.jsonl`) | `route.served` |
| `agent-on learn <kind> --json '<record>'` (or stdin) | validate and append to `knowledge/<kind>.jsonl`; assigns `id = <kind>-<ULID>` and `ts`; validates `supersedes` | — | L5 | `knowledge.typed` |
| `agent-on install` | link the shim, create the state root, check `python3 ≥ 3.11`, record `copy.*` | checkout | shim, state | `copy.single` |

9 → 7: the mapping said an agent needs nine — the seven above plus `task
create/handoff` (now `learn task …`, §10.1) and `proxy status` (moot).

Removed (83 → 7): `proxy *`, `auth *`, `model *`, `context *`, `reasoning *`,
`harness *`, `key set/status` (secrets: an environment variable, else
`$STATE/env` — `KEY=value` lines, 0600, loaded before the scrub; the
environment wins), `permissions set/get` (`--permission-mode` passes
through), `doctor` (= `status --check`), `task *` (§10.1), `uninstall`
(`rm` the shim and the state root; documented).

## 10. L5 — Knowledge: `knowledge/`

Git-tracked, append-only JSONL in the checkout, one file per kind, each line
validated against that kind's schema, **every record with `id` and `ts`**.
Written by `learn` and by actions; read by `status`, the skill, and any
agent with a file reader.

| file | record | written by |
|---|---|---|
| `observations.jsonl` | `{id, ts, route, kind: tokens\|throughput\|quality\|liveness\|cost, values{}, evidence, session}` | `learn`, `qualify`, the launch |
| `decisions.jsonl` | `{id, ts, decision, rationale, supersedes?, by}` | `learn` |
| `traps.jsonl` | `{id, ts, trap, mechanism, avoid, evidence, found_by, applies_to[]}` | `learn` |
| `qualifications.jsonl` | `{id, ts, route, fingerprint{effective_route_sha, wire_model, source_identity, claude_code}, gates{name: pass\|fail}, thinking_block_seen, completed, tok_s, concurrency, caching, commit}` — `commit` is provenance only; currency is judged by `fingerprint` (§8) | `qualify` |
| `gate-runs.jsonl` | `{id, ts, commit, result, tests, verifiers{declared[], ran[]}, invariants{id: pass\|fail\|skip}, skipped_reasons[], mock_port}` — the durable twin of `last_gate_run`; `verifiers` is the object, not a count, so a verifier declared but never run is visible (⟲⟲⟲⟲ rev 7, F6) | the gate |
| `tasks.jsonl` | event-sourced: `{id, ts, task_id, event: created\|handoff\|launched\|completed, …}`; current state is the fold | `learn task …` |

Seed content on landing: the tokenizer-vs-template observation, the
Huihui-outranks-Instruct quality observation, the serialisation measurement,
the 48K baseline, the two-arm thinking result (§1.1a), the direct-wire
cache measurements; decisions D1–D13 with rationale, D3 recording all three
turns of the OAuth lane, D7 recording the haiku-alias history; traps: the
single-quoted battery, the installed-copy selector, the promotion deadlock,
the budget-formula-in-code rule, the port-4000 collision, the fabricated cost
field, the discovery filter (§1.1b), the child-env credential exposure
(§1.1c), the exo Thunderbolt hijack.

### 10.1 The task ledger

`task create/handoff/launch/complete` (PR #12) stays as a kind of knowledge,
event-sourced into `tasks.jsonl`, and `claude-on <route> --task <id>` injects
the handoff prompt exactly as `task launch` does. Its local-route pre-probe
becomes `route.served` at launch. The Orca/dispatcher paragraph in
`ARCHITECTURE.md` is dropped: nothing consumes it.

## 11. L6 — Harness binding: `agent_on/harness.py`

1. **Config-dir isolation.** `CLAUDE_CONFIG_DIR=$STATE/claude-config` with the
   same symlink farm as today (settings, plugins, skills, keybindings,
   `CLAUDE.md` → `~/.claude`), and `.claude.json` carrying project trust
   (required by `apiKeyHelper`; measured to work in `-p`).
2. **Env injection**, computed from the route:
   - `ANTHROPIC_BASE_URL` — the source's `base_url`
   - `ANTHROPIC_API_KEY=""`; `ANTHROPIC_AUTH_TOKEN` is **never** the source key. For a keyless source `ANTHROPIC_AUTH_TOKEN=claude-on` (a fixed non-empty placeholder — Claude Code prompts for login on an empty one). For a source with `auth_env`, the **credential flow** is:
     1. The launcher (the parent, running in the *unscrubbed* environment) resolves the key: `$<auth_env>` from its own environment if set, else the line for it in `$STATE/env`. The environment wins — decided here, once, where both are visible.
     2. It writes the key to `$STATE/run/<launch-id>/key`, mode 0600, and a per-launch settings file `$STATE/run/<launch-id>/settings.json` containing `{"apiKeyHelper": "cat $STATE/run/<launch-id>/key"}`, passed as `--settings` (merged before any user `--settings`).
     3. It scrubs every source's `auth_env` from the child environment, including the active one. The helper runs as a child of Claude Code and inherits that scrubbed environment — which is why it must read a file the parent wrote, not an environment variable the parent removed (rev 3's defect).
     4. When the child exits — normally or by signal — the launcher removes `$STATE/run/<launch-id>/`. On start, every launch sweeps `run/*` directories whose recorded pid is dead (§7.1), so a crash never leaves a key behind for longer than the next launch.

     Threat model, stated plainly: the key is in a file the same Unix user can read, so a model that *deliberately* runs `cat` on that path gets it — exactly as it could run `security find-generic-password` today. What this flow prevents is what rev 2 measured: *accidental* propagation into every Bash child, hook, MCP server and the transcript. Adversarial containment is a separate OS account, as `ARCHITECTURE.md` already says.
   - `ANTHROPIC_DEFAULT_{FABLE,OPUS,SONNET,HAIKU}_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL` — the route's `wire_model` (D7), with `--sonnet` / `--haiku` overrides
   - `CLAUDE_CODE_MAX_CONTEXT_TOKENS` — `cost_model.context` (§7: `min(L1 declared, verified)` when verified, else `min(L1 declared, configured, advertised)`; the declared cap is never exceeded; `context_basis` names which)
   - `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` only with `--discover` (D8)
   - `CLAUDE_CODE_ATTRIBUTION_HEADER=0` — meaningful with no proxy, where the cache prefix it protects is reachable
   - scrub: **every** source's `auth_env` — including the active one — is removed from the child environment; the launch's own unit test spawns `printenv` and asserts it (`credential.not_in_child_env`)
3. **The shared-settings routing lint** (`harness.env.clean`) with the current broad denylist.
4. **Session read-back.** After the child exits, if a session was persisted (§9 session rules), read `$STATE/claude-config/projects/<slug>/<session-id>.jsonl` and record `last_session` with three keys:
   - `first_request`: the raw first-turn `usage` and `input_tokens_total` = `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`. This is **not** the harness baseline — the first request carries the user's task, and Anthropic's `input_tokens` excludes cached tokens, so a well-cached session would understate it. The baseline is measured separately by `qualify --baseline` (§7).
   - `this_run` and `session_total`, same shape: `turns`, `usage` summed over every assistant turn (four fields), and `cost_usd` (never Claude Code's own cost figure — F11). These answer Q1. **Cost is attributed per run, at the price of that run** (⟲⟲⟲ rev 6): at spawn the launcher snapshots the route's L1 `price`; at exit it appends one line to `$STATE/sessions/<session-id>.jsonl` — `{launch_id, route, source, wire_model, started, ended, turns, usage, price, cost_usd, models_seen}` — covering the turns whose per-line `timestamp` (a verified transcript field, §7) falls inside `[started, ended]`. A turn whose `message.model` is not the run's `wire_model` (`--model`, `/model`, `--fallback-model`) is priced only if a route on the same source declares that `wire_model` with a price; otherwise the run's `cost_usd` is the string `"unknown"` and `models_seen` names the model. A usage field that is non-zero with no price for it (e.g. `cache_creation_input_tokens` on a route whose catalog publishes no cache-write price) is `unknown` too — a price that is absent is not 0. `this_run` is that line. `session_total` is the fold of every line for the session: `turns` and `usage` come from the whole transcript; `cost_usd` is the sum of the lines when every transcript turn is covered by exactly one line and no line is `unknown`, else `"unknown"` with `covered_turns` / `uncovered_turns` — a session begun under the old launcher, or resumed from a paid route onto a free one before this rule existed, therefore reports `unknown`, never a fabricated 0. For a fresh session `this_run == session_total`; `scope_note` says which turns the launch added; `status` shows both.
   - When no session was persisted, `last_session` is `{ "skipped": "<reason>" }` — the observed schema admits this shape alongside the full one.
5. **Pass-through.** Claude arguments pass unchanged. `--model`, `--settings` and `--fallback-model` are no longer refused (D6); a user `--settings` is merged after the helper file.

Deleted from the binding: the four budget derivations and their
differential test; the permission-mode subsystem; the effort validator (the
provider is the truth); the tier alias map; every OAuth env manipulation. Kept
from the old overlay: only the ~10 lines that write the helper settings file.

## 12. The cost model

Every route's `observed.cost_model`:

| field | meaning | origin |
|---|---|---|
| `context` | usable input tokens = the L1 declared cap bounded by the best observed tier (§7); `context_basis` = `declared` \| `verified` \| `configured` \| `advertised` names which bound won | §7 limits tiers |
| `harness_baseline_tokens` | tokens Claude Code sends before task content on this route, measured with a fixed minimal prompt and tagged with the Claude Code version (48,312 on `omlx/…Huihui…` at 2.1.263; 37% of 131,072) | `qualify --baseline` |
| `tok_s` | output tokens per second at short context | `qualify` |
| `usd_per_mtok` | `{input, output, cache_read, cache_write}`; 0 for local. Cache write is priced separately by every provider that caches (Anthropic: 1.25× input for 5-minute, 2× for 1-hour; OpenRouter passes the provider's rates), so a session's cost is `Σ usage_field × its price` over all four fields | L1 `price` |
| `caching` | `true` / `false` from the two-turn probe; `unknown` until run | `qualify` |
| `concurrency` | parallel requests before serialisation — **per route, not per source**: measured 2026-09-08 direct on oMLX 0.6.4 (`max_concurrent_requests` 8, `decode_fairness`), Huihui-Qwen3.8 (MTP) gains nothing at 2 and 1.6× aggregate at 8, while GLM-5.3-Flash-4bit gains 2.9× at 8; Anthropic and OpenAI wires mixed in flight cost nothing extra. The 2026-09-06 "26% worse than serial" was Huihui through the proxy | `qualify` |
| `thinking` | `{observed, tokens_on_probe}` — what the source's template did, not a setting | `qualify` |

The launch prints one line before spawning:

```
claude-on omlx/root4k--Huihui…  ctx 131072 (48312 baseline = 37%) · 63 tok/s · $0 · cache ✓ · serial · thinking on (~2.6K tok/probe)
```

Rendering: `cache ✓` for `true`, `cache ✗` for `false`, `cache ?` for
`unknown`; a `null` `tok_s` or baseline renders as `?` too. The line never
invents a value the probe did not produce.

## 13. What is deleted, and the size target

| lines | subsystem | replaced by |
|---|---|---|
| ~3,500 | LiteLLM runtime: hash-locked venv, requirements lock, runtime fingerprint, lifecycle, `proxy_bootstrap` | nothing runs |
| ~2,400 | OAuth lanes: `oauth_guard.py`, `chatgpt_stream_compat.py`, `oauth.py`, `verify_oauth_adapters.py`, `auth`, the GPT and xAI routes | D3 |
| ~1,100 | the LiteLLM callback layer (`config/ai_litellm_callbacks/`): budget derivation ×4, differential test, output clamp, cost guardrail, pre-call context check — the layer `litellm_config.yaml:271` references, deleted in Plan D | `CLAUDE_CODE_MAX_CONTEXT_TOKENS`; providers reject oversized prompts |
| ~1,352 | `check.zsh` battery | invariant registry + verifier processes |
| ~2,200 | `lib.zsh` doctors, matrices, registry readers in Ruby/Node | `status` |
| ~1,100 | legacy migration | one-time `mv` note |
| ~600 | multi-harness descriptor scaffolding | `harness.py` |
| ~580 | unreachable legacy mutators | — |
| ~500 | integrity chain (D9) | `copy.single` |
| ~600 | permission-mode subsystem, `--settings` overlay | pass-through + the 10-line helper file |
| ~320 | dead helpers (zero callers, verified) | — |
| ~1,800 | catalog reconciliation, glob policy, `model *` | `sync`, `add`, source limits |

Kept, retargeted: `verify_tool_call_fidelity.py` — ~400 of its 894 lines
survive once the mock/LiteLLM lane dies (its `--live-base-url` is confirmed);
the task-ledger schema (581 lines with its test, restructured); the
shared-settings lint; the config-dir symlink farm.

**Target, in the §1 measure:** Python ~3,500 (package + kept verifier +
ledger), tests ~1,000, `routes.toml` + knowledge seeds + docs ~800 —
**~5,300 lines; hard gate ≤ 6,000**, from 25,294. Rev 2's "~3,000" counted
only new code against a baseline that counted everything.

## 14. Migration — five plans, five spikes

Each plan is one implementation plan (`writing-plans`), lands as its own
commit series, is verified before the next starts, and records a
`decisions.jsonl` entry saying what it removed and why.

| id | spike | decides | status |
|---|---|---|---|
| S1 | forced tool call on direct oMLX with thinking on | whether `omlx` needs any translator or thinking policy | **DONE** — 6/6 direct **and** 6/6 via LiteLLM; D2, D12 ⟲ |
| S2 | in-session `/model <id>` switch (typed, not discovery): does Claude Code re-derive context/effort or inherit the launch route's? | whether the launch warns on switch | open — cheap |
| S3 | exo wire and fidelity | §5 exo row | blocked on exo existing |
| S4 | `omlx-tp2` on :8003: six gates direct, throughput | the second oMLX source | blocked — endpoint down on 2026-09-07 |
| S5 | `omlx@morty` over the tailnet: reachability, six gates, latency vs local | the tailnet source row | open — morty is on the tailnet now; needs oMLX running there |

| plan | steps | build | delete | verify |
|---|---|---|---|---|
| **0** | spec amendment | — | — | owner approved proceeding on rev 5 with two P2s carried into Plan A; rev 6 records them |
| **A** | 1–3 | `agent_on/` package; `routes.toml` + schema; `sync` → `observed.json`; `status` declared beside observed; invariant registry; the new gate with the mock source; `copy.*`; `add` (the only writer of `routes.toml`, so its lock rule lands with the storage layer); the §11 cost-attribution primitives as pure functions plus the ledger fold, exercised by unit tests (the launch that feeds them is Plan B). Runs beside `claude-litellm`. | **nothing** | `status --json` lists the checkout's routes minus the OAuth/xAI ones (D3, recorded); `route.served` fails on a planted dead `wire_model` (the old guard stays until D); every F1–F14 except F3/F11 has a predicate that fails on a reproduction, F11 by unit test; a deliberate skip prints `skip`; `spend.openrouter` recorded by `sync`; two `add`s under different `CLAUDE_ON_STATE` roots both survive (rev-6 P2); the ledger fold prices a paid-then-free resumed session as paid + 0 and reports `unknown` for turns no line covers (rev-6 P2) |
| **B** | 4–5, S2 | `harness.py`: parent-resolved credential file + helper, env injection, spawn + read-back, cost line; direct launch for `omlx` (free lane) then `openrouter`; `qualify --baseline` and `--limits` | **nothing** — the old launcher, its budget/overlay/permission code and the LiteLLM callbacks stay untouched, because `litellm_config.yaml` and the old gate still reference them and the old path must keep working until D | `credential.not_in_child_env` passes (child `printenv` empty) with the key supplied *only* by environment variable and, separately, only by `$STATE/env`; `huihui` launch completes a Read-tool loop; `harness_baseline_tokens` recorded by `qualify --baseline`; six gates direct per packaged OpenRouter route; `qualify` has run its two-turn cache probe on every packaged route and recorded `true` or `false` — never `false` inferred from a missing price; `unknown` remains only where the probe could not run, and that is reported, not hidden; both launchers coexist and `claude-litellm` still launches |
| **C** | 6 | `knowledge/` + `learn`; seeds; memory-note migration; the skill; `status` shows traps for the action in hand | **nothing** | a peer session answers Q1, Q3–Q6, Q8, Q10 from `status --json` and `knowledge/` alone |
| **D** | 7–8, S4, S5 | `install` as shims + state root; rename to `agent-on`; docs generated from `routes.toml`; `omlx-tp2` and `omlx@morty` qualified when reachable | **everything old, in one plan**: LiteLLM runtime, venv, OAuth code and routes, integrity chain, `lib.zsh`, `shell.zsh`, `check.zsh`, `harnesses/`, the budget/overlay/permission/callback layers, the context/reasoning ledgers, `model-qualifications.json`, all vestigial | a fresh clone + `install` launches every reachable route with stdlib Python only; no hit for `litellm` under `agent_on/`, `bin/`, `routes.toml`, `tests/`; Q2/Q7/Q9 moot and the peer check re-run; line count ≤ 6,000; gate green. Until this plan lands, `git revert` of any A–C commit restores the old path intact |
| **E** | 9, S3 | `exo` | — | six gates direct on :52415 |

Plan B is ordered free-before-paid deliberately. Plans A–C add and never
delete: the old path keeps every file it references until D, so each plan is
verifiable on its own and reversible by revert.

## 15. Answers to the ten questions

| # | answered by |
|---|---|
| Q1 | `status` → `routes.*.last_session.{this_run, session_total}` — turns, summed usage and `cost_usd` from each run's own price snapshot (`"unknown"` when a turn's price cannot be restored), read from Claude Code's transcript and the per-session run ledger; `first_request` shown beside them |
| Q2 | moot after Plan D: nothing runs between Claude Code and the source; `copy.*` answers the rest |
| Q3 | route name `<source>/<model>` + `status` → `routes.*.served` |
| Q4 | `status` → `last_gate_run` (written only by the gate runner) and `knowledge/gate-runs.jsonl`; `last_check` is shown beside it and never confused with it |
| Q5 | one copy (D9); `AGENT_ON_STATE=<dir>` for a scratch state root; `copy.*` on every command |
| Q6 | `status` → `spend.openrouter` (confirmed in Plan A) |
| Q7 | moot after Plan D |
| Q8 | `harness_baseline_tokens` per route; per-item attribution deferred, recorded in `decisions.jsonl` |
| Q9 | moot after Plan D |
| Q10 | the tower; `status --check` lists the invariants an action touches; §13 is the dependency ledger |

## 16. Risks and open items

- **OpenRouter's disclaimer** (§5, quoted in full). Measured 30/30 and a real session. If it becomes enforcement, the OpenRouter source dies and nothing else changes; there is no translator to fall back to, by design. That is the one bet this architecture makes.
- **Thinking on local models is uncontrolled from the harness** (D12 ⟲). A future discovered model whose thinking template emits textual `<tool_call>` (as Qwen3.5 did) will launch thinking-on with no per-request switch and only `qualify` to notice. Per-turn thinking cost on the direct wire is unbounded (>6,000 tokens once). The mitigations are the source's own defaults and `CLAUDE_CODE_MAX_OUTPUT_TOKENS`; `qualify` reports it.
- **Auto-mode classifier residual** (D7 ⟲): a server-supplied feature config may name a model before the SONNET slot is consulted; unverifiable offline.
- **`omlx-tp2`, `omlx@morty`, exo are unmeasured** (S3–S5).
- **The GPT routes packaged on 2026-09-06** are deleted in Plan D; `00b3fa5` and this reversal are both recorded.

## 17. What this document supersedes

- The 2026-08-20 artifact — its measurements and conclusion stand; this is the design that follows, with §1.1a correcting the thinking-off story in both directions.
- `docs/ARCHITECTURE.md` — replaced in Plan D by a page generated from `routes.toml`.
- The out-of-repo memory notes `measure-the-installed-copy-not-the-checkout`, `budget-formula-lives-in-code-not-docs`, `fix-claude-litellm-on-contact-with-problems`, `scope-openrouter-only-no-oauth-lanes`, `delegate-workflow-stages-to-cheaper-models` — migrated to `knowledge/` in Plan C.
