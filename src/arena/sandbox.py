import contextlib
import json
import logging
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import IO

from arena.config import ConfigError
from arena.verifier import Run, Verification, judge

logger = logging.getLogger(__name__)

# Limits for model-written code (D-044). gVisor intercepts the container's system calls, so a
# kernel exploit in the snippet meets gVisor's Go kernel instead of the host's.
RUNTIME = "runsc"
IMAGE = (
    "arena-sandbox:1"  # built from docker/sandbox.Dockerfile: the base pinned by digest, plus SymPy
)
_DOCKERFILE = Path(__file__).resolve().parents[2] / "docker" / "sandbox.Dockerfile"
_NAME_PREFIX = "arena-snippet-"
MEMORY = "256m"
CPUS = "1"
PIDS_LIMIT = "64"
TMPFS = "/tmp:rw,noexec,size=16m"
NOBODY = "65534:65534"
MAX_OUTPUT_BYTES = 64 * 1024
# Starting a gVisor container is slow; the snippet's own limit comes on top of this.
STARTUP_ALLOWANCE_S = 10.0
_DOCKER_FAILED = 125  # `docker run`'s own exit code when it could not start the container
# Only docker may produce 125 and up: a snippet's own exit code of 125 or more becomes 1, so it
# cannot pass for a Docker failure and void a match (D-069).
_WRAPPER = 'python -I -; c=$?; [ "$c" -lt 125 ] || c=1; exit "$c"'
_POLL_S = 0.05


def _command(name: str) -> list[str]:
    return [
        "docker", "run", "--rm", "-i", "--name", name,
        f"--runtime={RUNTIME}", "--network=none", "--read-only", "--tmpfs", TMPFS,
        f"--memory={MEMORY}", f"--memory-swap={MEMORY}", f"--cpus={CPUS}",
        f"--pids-limit={PIDS_LIMIT}", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pull=never", "--user", NOBODY, IMAGE, "sh", "-c", _WRAPPER,
    ]  # fmt: skip


def _remove_container(name: str) -> None:
    """Killing the docker client leaves its container running, so remove the container itself."""
    try:
        done = subprocess.run(
            ["docker", "rm", "-f", name], capture_output=True, check=False, timeout=30
        )
    except subprocess.TimeoutExpired:
        logger.warning("removing sandbox container %s timed out", name)
        return
    if done.returncode != 0:
        logger.warning("could not remove sandbox container %s: %r", name, done.stderr[-200:])


def _flooded(*files: IO[bytes]) -> bool:
    return max(os.fstat(f.fileno()).st_size for f in files) > MAX_OUTPUT_BYTES


def run_sandboxed(snippet: str, timeout_s: float) -> Run:
    """Run `snippet` as `python -I -` in a gVisor container with no network, a read-only disk,
    capped memory, CPU and processes, and capped output. A Docker failure raises ConfigError:
    it is not the snippet's fault, so it must not pass for a failed attack."""
    name = f"{_NAME_PREFIX}{uuid.uuid4().hex}"
    deadline = time.monotonic() + timeout_s + STARTUP_ALLOWANCE_S
    # Output goes to files so a flooding snippet fills a capped file, not the worker's memory.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(_command(name), stdin=subprocess.PIPE, stdout=out, stderr=err)
        assert proc.stdin is not None
        with contextlib.suppress(BrokenPipeError):  # docker exited before reading the snippet
            proc.stdin.write(snippet.encode("utf-8"))
            proc.stdin.close()
        while proc.poll() is None:
            flooded = _flooded(out, err)
            if time.monotonic() > deadline or flooded:
                # The client first: while it lives it keeps copying a flood into the files.
                proc.kill()
                proc.wait()
                _remove_container(name)
                if flooded:
                    return Run(1, "", f"output over {MAX_OUTPUT_BYTES} bytes")
                return Run(-1, "", "", timed_out=True)
            time.sleep(_POLL_S)
        if _flooded(out, err):  # written in one burst and finished between two polls
            return Run(1, "", f"output over {MAX_OUTPUT_BYTES} bytes")
        out.seek(0)
        err.seek(0)
        stdout = out.read().decode("utf-8", errors="replace")
        stderr = err.read().decode("utf-8", errors="replace")
    if proc.returncode == _DOCKER_FAILED:
        lines = stderr.strip().splitlines()
        raise ConfigError(f"the sandbox could not run: {lines[-1] if lines else 'docker failed'}")
    return Run(proc.returncode, stdout, stderr)


def sandboxed_verify(stated_answer: str, snippet: str, timeout_s: float) -> Verification:
    """Same contract as `verifier.verify_attack`, but the snippet runs in the sandbox."""
    return judge(run_sandboxed(snippet, timeout_s), stated_answer, timeout_s)


def _build_image() -> None:
    if not _DOCKERFILE.is_file():
        raise ConfigError(
            f"the sandbox image {IMAGE} is missing and {_DOCKERFILE} is not here: build it with "
            f"`docker build -t {IMAGE} -f docker/sandbox.Dockerfile docker/` from the repository"
        )
    logger.info("building the sandbox image %s (once)", IMAGE)
    subprocess.run(
        ["docker", "build", "-t", IMAGE, "-f", str(_DOCKERFILE), str(_DOCKERFILE.parent)],
        check=True,
        capture_output=True,
        timeout=900,
    )


def _remove_leftovers() -> None:
    """A worker that died mid-snippet leaves its container running for ever."""
    listed = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"name={_NAME_PREFIX}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    ids = listed.stdout.split()
    if ids:
        logger.warning("removing %d sandbox container(s) left by an earlier worker", len(ids))
        subprocess.run(["docker", "rm", "-f", *ids], capture_output=True, timeout=60, check=False)


def ensure_ready() -> None:
    """Raise ConfigError unless Docker has the gVisor runtime and the image. Builds the image if it
    is missing and removes containers a dead worker left."""
    try:
        info = subprocess.run(
            ["docker", "info", "--format", "{{json .Runtimes}}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if info.returncode != 0:
            raise ConfigError(f"docker info failed: {info.stderr.strip()[-200:]}")
        if RUNTIME not in json.loads(info.stdout):
            raise ConfigError(
                f"docker has no {RUNTIME!r} runtime: install gVisor and register it with Docker, "
                "or set ARENA_SANDBOX=off for local development only"
            )
        if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode:
            _build_image()
        _remove_leftovers()
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ConfigError(f"cannot use docker for the sandbox: {exc}") from exc
