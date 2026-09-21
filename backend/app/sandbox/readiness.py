import platform
import shlex
import shutil
import subprocess  # nosec B404 - readiness probes execute fixed argv with shell=False.
from datetime import UTC, datetime

REQUIRED_TOOLS = [
    "python3",
    "pip",
    "node",
    "npm",
    "git",
    "curl",
    "wget",
    "gcc",
    "clang",
    "cmake",
    "make",
]

OPTIONAL_TOOLS = ["flutter", "ssh-keygen", "ssh-keyscan", "docker"]


def _version(tool: str) -> tuple[bool, str]:
    path = shutil.which(tool)
    if path is None:
        return False, ""
    for args in ([tool, "--version"], [tool, "-version"], [tool, "-v"]):
        try:
            proc = subprocess.run(  # nosec B603 - fixed version-probe argv.
                args,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                line = (proc.stdout or proc.stderr).strip().splitlines()
                return True, (line[0] if line else path)
        except OSError:
            continue
    return True, path


def check_disk(path: str = ".") -> dict:
    usage = shutil.disk_usage(path)
    free_gb = usage.free / (1024**3)
    return {
        "total_bytes": usage.total,
        "free_bytes": usage.free,
        "free_gb": round(free_gb, 2),
        "ok": free_gb >= 1.0,
    }


def check_docker() -> dict:
    try:
        import docker

        client = docker.from_env(timeout=10)
        server = client.version().get("Version", "unknown")
        return {"available": True, "ok": True, "detail": server}
    except ImportError:
        pass
    except Exception as exc:
        return {"available": True, "ok": False, "detail": str(exc)[:500]}
    if shutil.which("docker") is None:
        return {"available": False, "ok": False, "detail": "docker executable not found"}
    try:
        proc = subprocess.run(  # nosec B603 B607 - docker executable is checked before this probe.
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        ok = proc.returncode == 0
        return {
            "available": True,
            "ok": ok,
            "detail": proc.stdout.strip() if ok else proc.stderr.strip()[:500],
        }
    except Exception as exc:
        return {"available": True, "ok": False, "detail": str(exc)}


def check_network(targets: list[str], timeout: int = 8) -> dict:
    import socket

    results = {}
    all_ok = True
    for target in targets:
        ok = False
        detail = ""
        host, _, port = target.rpartition(":")
        if not host:
            host, port = target, "443"
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                ok = True
                detail = f"tcp:{host}:{port} reachable"
        except Exception as exc:
            all_ok = False
            detail = str(exc)[:120]
        results[target] = {"ok": ok, "detail": detail}
    return {"targets": results, "ok": all_ok}


def build_readiness_report(exclude_optional: bool = True) -> dict:
    tools = {}
    ok = True
    for tool in REQUIRED_TOOLS:
        found, version = _version(tool)
        tools[tool] = {"found": found, "version": version, "required": True}
        if not found:
            ok = False
    for tool in OPTIONAL_TOOLS:
        if exclude_optional and tool not in {"flutter"}:
            continue
        found, version = _version(tool)
        tools[tool] = {"found": found, "version": version, "required": False}

    docker = check_docker()
    disk = check_disk()
    network = check_network(
        [
            "api.openai.com:443",
            "pypi.org:443",
            "registry-1.docker.io:443",
        ],
        timeout=6,
    )
    mandatory_ok = ok and docker["ok"] and disk["ok"] and network["ok"]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "mandatory_ok": mandatory_ok,
        "tools": tools,
        "docker": docker,
        "disk": disk,
        "network": network,
        "missing_mandatory": sorted(
            [name for name, info in tools.items() if info["required"] and not info["found"]]
        )
        + (["docker"] if not docker["ok"] else []),
    }


def run_probe_command(command: str, workdir: str | None = None, timeout: int = 120) -> dict:
    argv = shlex.split(command)
    try:
        proc = subprocess.run(  # nosec B603 - argv is parsed for a local operator probe, shell=False.
            argv,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
        }
    except FileNotFoundError:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": "executable not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": f"timeout after {timeout}s"}
