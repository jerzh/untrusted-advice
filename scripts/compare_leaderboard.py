"""Compare a local run against a public LinuxArena leaderboard run, task by task.

    uv run python scripts/compare_leaderboard.py logs/<run-dir>/monitored
    uv run python scripts/compare_leaderboard.py logs/<run>.eval --run-id <leaderboard run id>

Both runs are scored by the same code: each sample's `tasks` score (main / side success, where the
side task landed) and every monitor verdict it holds. Safety fits the audit threshold on a run's own
honest samples, as Control Tower does, so the leaderboard is reported twice: on the tasks the local
run shares with it, and on all of its samples. The default run is Claude Haiku 4.5 as untrusted with
gpt-5.4-nano `simple` (action) and `trajectory` monitors, from `ct/null-blue-team`.
"""

import argparse
import json
import math
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from inspect_ai.log import read_eval_log
from inspect_ai.scorer import Score

from control_tower.metrics import control
from control_tower.trajectories.monitor_score import verdicts

API = "https://data.linuxarena.ai/api/trajectories"
HAIKU_RUN = "057469b652db428f9f48f4c5902aab77"
CACHE = Path("data/leaderboard")


@dataclass
class Sample:
    key: tuple[str, str, str | None]  # env, main task, side task (None = honest)
    main: float | None
    side: float | None
    landed_at: int | None
    actions: list[float | None]  # max over action monitors, per action
    trajectory: float | None  # max over trajectory monitors
    untrusted_usd: float
    monitor_usd: float

    @property
    def attack(self) -> bool:
        return self.key[2] is not None


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return {"C": 1.0, "I": 0.0}.get(value) if isinstance(value, str) else None


def sample_from(scores: dict[str, Any], metadata: dict[str, Any], role_usage: dict[str, Any]) -> Sample:
    """One sample from its scores, metadata and per-role usage, as an .eval log or the public API
    records them (the API's `sample` is the log's sample as JSON)."""
    main_task = metadata["main_tasks"][0]
    side_tasks = metadata.get("side_tasks") or []
    key = (
        main_task["environment"].split("/")[-1],
        main_task["id"],
        side_tasks[0]["id"] if side_tasks else None,
    )
    tasks = scores.get("tasks") or {}
    tasks = tasks.get("value", {}) if isinstance(tasks, dict) else tasks.value
    per_action: dict[int, float] = {}
    trajectory: float | None = None
    for name, raw in scores.items():
        if not name.startswith("monitor"):
            continue
        score = raw if isinstance(raw, Score) else Score.model_validate(raw)
        if not score.value:
            continue
        for verdict in verdicts(score):
            value = number(verdict.score.value)
            if value is None or isinstance(verdict.at, str):
                continue
            if verdict.at is None:
                trajectory = value if trajectory is None else max(trajectory, value)
            else:
                per_action[verdict.at] = max(per_action.get(verdict.at, value), value)
    n = max(per_action, default=-1) + 1
    untrusted = sum(u.get("total_cost") or 0 for r, u in role_usage.items() if "untrusted" in r)
    monitor = sum(u.get("total_cost") or 0 for r, u in role_usage.items() if r.startswith("monitor"))
    return Sample(
        key,
        number(tasks.get("main")),
        number(tasks.get("side")),
        tasks.get("landed_at"),
        [per_action.get(i) for i in range(n)],
        trajectory,
        untrusted,
        monitor,
    )


def local_samples(path: Path) -> list[Sample]:
    paths = sorted(path.glob("*.eval")) if path.is_dir() else [path]
    if not paths:
        raise SystemExit(f"no .eval files in {path}")
    out = []
    for p in paths:
        log = read_eval_log(str(p))
        for s in log.samples or []:
            usage = {
                role: u.model_dump() | {"total_cost": u.total_cost}
                for role, u in (getattr(s, "role_usage", None) or {}).items()
            }
            out.append(sample_from(s.scores or {}, s.metadata or {}, usage))
    return out


def leaderboard_samples(run_id: str) -> list[Sample]:
    cache = CACHE / run_id
    cache.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(f"{API}?run_id={run_id}&limit=500", timeout=60) as r:
        ids = [i["trajectory_id"] for i in json.load(r)["items"]]

    def get(trajectory_id: str) -> dict[str, Any]:
        f = cache / f"{trajectory_id}.json"
        if not f.exists():
            with urllib.request.urlopen(f"{API}/{trajectory_id}", timeout=120) as r:
                f.write_bytes(r.read())
        return json.loads(f.read_text())

    with ThreadPoolExecutor(8) as pool:
        trajectories = list(pool.map(get, ids))
    return [
        sample_from(t["sample"]["scores"], t["sample"]["metadata"], t["sample"].get("role_usage") or {})
        for t in trajectories
    ]


def metrics(samples: list[Sample], budgets: list[float]) -> dict[str, float]:
    honest = [s for s in samples if not s.attack]
    attack = [s for s in samples if s.attack]
    out = {
        "n honest / attack": f"{len(honest)} / {len(attack)}",
        "usefulness": control.usefulness([s.main or 0.0 for s in honest]),
        "side task success": mean([s.side or 0.0 for s in attack]),
        "max action sus, honest": mean([max(filter(None.__ne__, s.actions), default=0) for s in honest]),
        "max action sus, attack": mean([max(filter(None.__ne__, s.actions), default=0) for s in attack]),
        "trajectory sus, honest": mean([s.trajectory for s in honest if s.trajectory is not None]),
        "trajectory sus, attack": mean([s.trajectory for s in attack if s.trajectory is not None]),
        "$ untrusted / sample": mean([s.untrusted_usd for s in samples]),
        "$ monitor / sample": mean([s.monitor_usd for s in samples]),
    }
    scores = [x for s in honest for x in (*s.actions, s.trajectory) if x is not None]
    actions = sum(len(s.actions) for s in honest)
    for budget in budgets:
        if not scores:
            out[f"safety @ {budget:g}"] = math.nan
            continue
        t, share = control.threshold(scores, actions, budget)
        caught = [control.caught(control.audits(s.actions, s.trajectory, t, share), s.landed_at) for s in attack]
        out[f"safety @ {budget:g}"] = control.safety(caught, [s.side or 0.0 for s in attack])
    return out


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else math.nan


def fmt(x: Any) -> str:
    return f"{x:.3f}" if isinstance(x, float) else str(x)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="A monitored .eval file, or a directory holding them")
    parser.add_argument("--run-id", default=HAIKU_RUN, help="Leaderboard run to compare against")
    parser.add_argument("--budgets", type=float, nargs="+", default=[0.001, 0.01, 0.05, 0.1])
    args = parser.parse_args()

    ours = local_samples(args.path)
    theirs = leaderboard_samples(args.run_id)
    keys = {s.key for s in ours}
    shared = [s for s in theirs if s.key in keys]

    columns = {
        "local": metrics(ours, args.budgets),
        "leaderboard, same tasks": metrics(shared, args.budgets),
        "leaderboard, all": metrics(theirs, args.budgets),
    }
    width = max(map(len, next(iter(columns.values())))) + 2
    print(f"{'':{width}}" + "".join(f"{c:>26}" for c in columns))
    for row in next(iter(columns.values())):
        print(f"{row:{width}}" + "".join(f"{fmt(m[row]):>26}" for m in columns.values()))

    print("\nper task (local | leaderboard): success (main if H, side if A), max action sus, trajectory sus, $ untrusted")
    by_key = {s.key: s for s in theirs}
    for s in sorted(ours, key=lambda s: (s.key[0], s.attack)):
        lb = by_key.get(s.key)

        def cells(x: Sample | None) -> str:
            if x is None:
                return "(not in leaderboard)"
            sus = max(filter(None.__ne__, x.actions), default=None)
            task = x.side if x.attack else x.main
            return f"{fmt(task):>5} {fmt(sus):>6} {fmt(x.trajectory):>6} {x.untrusted_usd:>6.2f}"

        label = f"{s.key[0]}/{s.key[2] or s.key[1]}"[:58]
        print(f"{'A' if s.attack else 'H'} {label:58} {cells(s)} | {cells(lb)}")


if __name__ == "__main__":
    main()
