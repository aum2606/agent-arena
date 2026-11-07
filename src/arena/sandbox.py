import contextlib
import json
import logging
import os
import subprocess
import tempfile
import time
import uuid

from arena.config import ConfigError
from arena.verifier import Run, Verification, judge

logger = logging.getLogger(__name__)

# Limits for model-written code (D-044). gVisor intercepts the container's system calls, so a
# kernel exploit in the snippet meets gVisor's Go kernel instead of the host's.
RUNTIME = "runsc"
IMAGE = "python:3.12-slim"
MEMORY = "256m"
CPUS = "1"
PIDS_LIMIT = "64"
TMPFS = "/tmp:rw,noexec,size=16m"
NOBODY = "65534:65534"
MAX_OUTPUT_BYTES = 64 * 1024
# Starting a gVisor container is slow; the snippet's own limit comes on top of this.
STARTUP_ALLOWANCE_S = 10.0
_DOCKER_FAILED = 125  # `docker run`'s own exit code when it could not start the container
_POLL_S = 0.05


def _command(name: str) -> list[str]:
    return [
        "docker", "run", "--rm", "-i", "--name", name,
        f"--runtime={RUNTIME}", "--network=none", "--read-only", "--tmpfs", TMPFS,
        f"--memory={MEMORY}", f"--memory-swap={MEMORY}", f"--cpus={CPUS}",
        f"--pids-limit={PIDS_LIMIT}", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--user", NOBODY, IMAGE, "python", "-I", "-",
    ]  # fmt: skip


def _remove_container(name: str) -> None:
    """Killing the docker client leaves its container running, so remove the container itself."""
    done = subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
    if done.returncode != 0:
        logger.warning("could not remove sandbox container %s: %r", name, done.stderr[-200:])


def run_sandboxed(snippet: str, timeout_s: float) -> Run:
    """Run `snippet` as `python -I -` in a gVisor container with no network, a read-only disk,
    capped memory, CPU and processes, and capped output. A Docker failure raises ConfigError:
    it is not the snippet's fault, so it must not pass for a failed attack."""
    name = f"arena-snippet-{uuid.uuid4().hex}"
    deadline = time.monotonic() + timeout_s + STARTUP_ALLOWANCE_S
    # Output goes to files so a flooding snippet fills a capped file, not the worker's memory.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(_command(name), stdin=subprocess.PIPE, stdout=out, stderr=err)
        assert proc.stdin is not None
        with contextlib.suppress(BrokenPipeError):  # docker exited before reading the snippet
            proc.stdin.write(snippet.encode("utf-8"))
            proc.stdin.close()
        while proc.poll() is None:
            flooded = max(os.fstat(out.fileno()).st_size, os.fstat(err.fileno()).st_size)
            if time.monotonic() > deadline or flooded > MAX_OUTPUT_BYTES:
                _remove_container(name)
                proc.kill()
                proc.wait()
                if flooded > MAX_OUTPUT_BYTES:
                    return Run(1, "", f"output over {MAX_OUTPUT_BYTES} bytes")
                return Run(-1, "", "", timed_out=True)
            time.sleep(_POLL_S)
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


def ensure_ready() -> None:
    """Raise ConfigError unless Docker has the gVisor runtime; pulls the image if it is missing."""
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
            subprocess.run(["docker", "pull", IMAGE], check=True, timeout=600)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ConfigError(f"cannot use docker for the sandbox: {exc}") from exc
