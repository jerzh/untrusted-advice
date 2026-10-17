# linuxarena-control

Red-teaming a control protocol on **LinuxArena** (the released name of LinuxBench), using
[Control Tower](https://github.com/linuxarena/control-tower), Redwood/EquiStamp's Inspect-based
control-eval framework. This repo is a Control Tower **plugin**: protocols defined under
`src/lacontrol/` show up as `lacontrol/<name>` next to the built-ins.

## Layout

```
src/lacontrol/protocols/my_protocol.py   # the protocol under study (currently a pass-through stub)
task_sets/smoke.jsonl                    # 1 honest + 1 attack sample (clinical_trial)
task_sets/naive.jsonl                    # 9 envs x (honest + attack), tiktok excluded (needs paid key)
scripts/setup.sh                         # uv sync + pull environments + sanity checks
scripts/run_naive.sh                     # control eval -> post-hoc safety at several audit budgets
scripts/summarize.py                     # usefulness / safety / cost of an .eval log
scripts/estimate_cost.py                 # real $/sample per model, from the public LinuxArena viewer
```

## Setup

Needs **Docker** (each sample is a multi-service compose stack), uv, and git. Python 3.13 is
installed by uv.

```bash
cp .env.example .env      # add keys; the defaults use Anthropic (untrusted) + OpenAI (trusted)
scripts/setup.sh
```

`scripts/env.sh` pins the venv to `./.venv` and the environments to `./.settings`, so a global
`UV_PROJECT_ENVIRONMENT` doesn't leak in. Re-run `ct settings pull linuxarena` after `uv sync`.

## Naive evaluation

```bash
scripts/run_naive.sh                                  # smoke test, ~$1-2
TASKS=task_sets/naive.jsonl scripts/run_naive.sh      # 18 samples, ~$10-15 with Haiku 4.5
UNTRUSTED=openrouter/deepseek/deepseek-v4-flash-0731 TASKS=task_sets/naive.jsonl scripts/run_naive.sh
```

"Naive" means: honest policy and default attack policy (`ct/attack`) under
`ct/trusted-monitoring` with no threshold. A trusted model scores every action but nothing is
blocked or audited live. `summarize.py` then fits the audit threshold on the honest samples at
each budget (0.1%, 1%, 5%, 10%) and reports safety, with no further model calls. That gives you
the trusted-monitoring baseline your protocol has to beat.

To evaluate your own protocol, implement `on_input` / `on_output` in `my_protocol.py` (see
`control_tower/protocols/trusted_monitoring.py` in `.venv`), then:

```bash
PROTOCOL=lacontrol/my-protocol TASKS=task_sets/naive.jsonl scripts/run_naive.sh
```

Useful commands: `uv run ct settings main-tasks --env linuxarena/<env>`,
`uv run ct protocols policies ct/attack` (attack args such as `plan=once`), and
`uv run inspect view` for transcripts.

## Pricing notes (Oct 2026)

Measured agent cost per sample on LinuxArena, from public 105-sample leaderboard runs
(`scripts/estimate_cost.py`):

| untrusted model | $/sample | honest usefulness |
|---|---|---|
| Tencent HY3 (OpenRouter) | 0.09 | 0.71 |
| DeepSeek V4 Flash (OpenRouter) | 0.13 | 0.70 |
| GPT-5.4 nano | 0.21 | 0.42 |
| DeepSeek V4 Pro (OpenRouter) | 0.37 | 0.71 |
| Kimi K2.5 (OpenRouter) | 0.45 | 0.58 |
| Claude Haiku 4.5 | 0.50 | 0.42 |
| GPT-5.4 mini | 0.73 | 0.60 |
| Claude Opus 4.6 (attack, vs defer-to-trusted) | ~5.6 | n/a |

A trusted monitor on every action adds about $0.14/sample with gpt-5.4-nano. The Claude 5.5 models
are not in Control Tower 6.0.0rc3's rate table yet, so `ct` reports their cost as unknown.
They still bill.
