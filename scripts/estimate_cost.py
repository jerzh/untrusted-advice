"""Estimate API cost of a LinuxArena run from real per-trajectory costs on the public viewer.

    uv run python scripts/estimate_cost.py                  # table of recent leaderboard runs
    uv run python scripts/estimate_cost.py --samples 200    # also project a 200-sample run

Uses the public data API (https://data.linuxarena.ai/api/runs), whose leaderboard runs are
105-sample honest+attack control evals on the linuxarena setting.
"""

import argparse
import json
import urllib.request

API = "https://data.linuxarena.ai/api/runs?limit=500"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=0, help="Project the cost of this many samples")
    args = parser.parse_args()

    with urllib.request.urlopen(API, timeout=60) as response:
        runs = json.load(response)["items"]

    seen: set[str] = set()
    rows = []
    for run in sorted(runs, key=lambda r: r.get("created_at") or "", reverse=True):
        name = run.get("name") or ""
        if not (name.startswith("board-models-") and "linuxarena" in (run.get("control_settings") or [])):
            continue
        if name in seen:
            continue
        seen.add(name)
        audit = (run.get("metrics") or {}).get("audit") or {}
        if audit.get("honest_cost_incomplete") or audit.get("attack_cost_incomplete"):
            continue  # some model in the run had no price, so its cost is understated
        per_sample = (audit["honest_cost"] + audit["attack_cost"]) / 2
        model = name.removeprefix("board-models-").removesuffix("-linuxarena")
        rows.append((per_sample, model, audit.get("usefulness", float("nan"))))

    print(f"{'untrusted model':48} {'$/sample':>9} {'usefulness':>11}" + (f" {'$ for ' + str(args.samples):>12}" if args.samples else ""))
    for per_sample, model, usefulness in sorted(rows):
        line = f"{model:48} {per_sample:>9.3f} {usefulness:>11.2f}"
        if args.samples:
            line += f" {per_sample * args.samples:>12.2f}"
        print(line)
    print("\n$/sample is the agent's own model calls; a trusted monitor scoring every action adds")
    print("roughly $0.13-0.30/sample with gpt-5.4-nano, and gpt-5-nano is cheaper still.")


if __name__ == "__main__":
    main()
