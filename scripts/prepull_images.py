"""Pull the images a task set's environments need, so the eval can run with SKIP_DOCKER_PULL=1.

    uv run python scripts/prepull_images.py task_sets/leaderboard18.jsonl

`ct settings pull-images` with only those environments, except that images already present are
skipped and Docker Hub's rate limit (about 10 pulls/hour per IP when anonymous) is waited out
instead of failing. `docker login` first, or put DOCKERHUB_USERNAME / DOCKERHUB_TOKEN in .env,
to raise the limit.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

from control_tower.environments.build import get_compose_files_from_tasks
from control_tower.environments.internet_simulator.runtimes.docker import (
    EXPOSED_SERVICES_PROXY_IMAGE,
    resolve_image_name,
)
from control_tower.environments.registry import environments
from control_tower.environments.remote.remote import RemoteDockerEnvironment
from control_tower.sandbox.intranet import ensure_guard_image
from control_tower.utils.versioning import expand_compose_vars, pin_missing_image_tag_to_checkout

WAIT_SECONDS = 360


def needed_images(env_names: set[str]) -> set[str]:
    """The images an eval over these environments pulls, as `pull_environment_images` lists them."""
    docker_envs = [e for e in environments.all().values() if isinstance(e, RemoteDockerEnvironment)]
    images = {EXPOSED_SERVICES_PROXY_IMAGE, resolve_image_name()}
    for compose_path in sorted(get_compose_files_from_tasks(docker_envs)):
        if not any(f"/{name}/" in str(compose_path) for name in env_names):
            continue
        services = (yaml.safe_load(Path(compose_path).read_text()) or {}).get("services")
        for service in (services or {}).values():
            image = service.get("image") if isinstance(service, dict) else None
            if not isinstance(image, str) or ("build" in service and "/" not in image):
                continue
            pin = pin_missing_image_tag_to_checkout(image, Path(compose_path).parent)
            images.add(expand_compose_vars(image, dict([pin]) if pin else None))
    return images


def present(image: str) -> bool:
    return subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0


def pull(image: str) -> bool:
    while True:
        result = subprocess.run(["docker", "pull", "-q", image], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"pulled {image}", flush=True)
            return True
        error = result.stderr.strip()
        if "toomanyrequests" in error or "429" in error:
            print(f"rate limited on {image}; waiting {WAIT_SECONDS // 60} min", flush=True)
            time.sleep(WAIT_SECONDS)
            continue
        print(f"FAILED {image}: {error[-300:]}", flush=True)
        return False


def main() -> None:
    tasks = sys.argv[1] if len(sys.argv) > 1 else "task_sets/smoke.jsonl"
    env_names = {json.loads(line)["env"].split("/")[-1] for line in open(tasks) if line.strip()}
    if os.environ.get("DOCKERHUB_USERNAME") and os.environ.get("DOCKERHUB_TOKEN"):
        subprocess.run(
            ["docker", "login", "-u", os.environ["DOCKERHUB_USERNAME"], "--password-stdin"],
            input=os.environ["DOCKERHUB_TOKEN"],
            text=True,
            check=True,
        )
    ensure_guard_image(seeding=True)
    images = sorted(needed_images(env_names))
    missing = [i for i in images if not present(i)]
    print(f"{len(images)} images, {len(missing)} to pull", flush=True)
    failed = [i for i in missing if not pull(i)]
    if failed:
        sys.exit(f"failed to pull: {failed}")
    print("all images present", flush=True)


if __name__ == "__main__":
    main()
