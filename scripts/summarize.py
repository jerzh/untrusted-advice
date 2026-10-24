"""Usefulness / safety / cost of a control-eval log, audited post hoc at several budgets.

    uv run python scripts/summarize.py logs/<run-dir>            # newest .eval in the dir
    uv run python scripts/summarize.py logs/<run>.eval --budgets 0.01 0.05

Auditing post hoc calls no model, so each budget is free. It needs a run whose protocol did
not audit live (e.g. trusted-monitoring with no sus_threshold), with monitor scores present.
"""

import argparse
from pathlib import Path

from inspect_ai.log import EvalLog, read_eval_log, write_eval_log

from control_tower.metrics.audit import posthoc_audit


def audit_metrics(log: EvalLog) -> dict[str, float]:
    for score in (log.results.scores if log.results else []):
        if score.name == "audit":
            return {name: metric.value for name, metric in score.metrics.items()}
    return {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="An .eval file, or a directory holding them")
    parser.add_argument("--monitor", default="simple")
    parser.add_argument("--budgets", type=float, nargs="+", default=[0.001, 0.01, 0.05, 0.1])
    args = parser.parse_args()

    path = args.path
    if path.is_dir():
        logs = sorted(path.glob("*.eval"), key=lambda p: p.stat().st_mtime)  # audit copies go in audited/
        if not logs:
            raise SystemExit(f"no .eval files in {path}")
        path = logs[-1]
    log = read_eval_log(str(path))
    print(f"log: {path}")

    base = audit_metrics(log)
    print(
        f"usefulness (honest main-task success): {base.get('usefulness', float('nan')):.3f}\n"
        f"mean cost per sample: honest ${base.get('honest_cost', float('nan')):.3f}, "
        f"attack ${base.get('attack_cost', float('nan')):.3f}"
    )

    print(f"\n{'budget':>8}  {'safety':>7}  {'realised budget':>15}")
    for budget in args.budgets:
        audited = posthoc_audit(log, args.monitor, audit_budget=budget)
        m = audit_metrics(audited)
        print(f"{budget:>8.3f}  {m.get('safety', float('nan')):>7.3f}  {m.get('audit_budget', float('nan')):>15.4f}")
        out = path.parent / "audited" / f"{path.stem}.audit-{budget}.eval"
        out.parent.mkdir(exist_ok=True)
        write_eval_log(audited, str(out))


if __name__ == "__main__":
    main()
