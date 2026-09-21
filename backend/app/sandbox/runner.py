import logging
import os
import shlex
from pathlib import Path


class SandboxUnavailable(RuntimeError):
    pass


class SandboxDenied(PermissionError):
    pass


class DockerSandboxRunner:
    def __init__(self, app):
        self.app = app

    def _client(self):
        try:
            import docker
        except ImportError:
            raise SandboxUnavailable("docker python SDK is not installed") from None
        try:
            return docker.from_env()
        except Exception as exc:
            raise SandboxUnavailable(f"cannot connect to docker daemon: {exc}") from exc

    def run(
        self,
        image: str,
        command: str | list[str],
        *,
        workspace: str | None = None,
        cpu: str | None = None,
        memory: str | None = None,
        pids: int | None = None,
        timeout: int | None = None,
        network: str = "none",
    ) -> dict:
        self._validate_image(image)
        self._validate_network(network)

        cfg = self.app.config["SANDBOX_DEFAULT_LIMITS"]
        try:
            cpu_value = float(cpu or cfg["cpu"])
            pids_value = int(pids or cfg["pids"])
            timeout_value = int(timeout or cfg["timeout"])
        except (TypeError, ValueError) as exc:
            raise SandboxDenied("sandbox resource limits are invalid") from exc
        if cpu_value <= 0 or cpu_value > self.app.config["SANDBOX_MAX_CPU"]:
            raise SandboxDenied("cpu limit is outside the configured range")
        memory_value = memory or cfg["memory"]
        memory_bytes = _memory_bytes(memory_value)
        if memory_bytes <= 0 or memory_bytes > self.app.config["SANDBOX_MAX_MEMORY_BYTES"]:
            raise SandboxDenied("memory limit is outside the configured range")
        if pids_value <= 0 or pids_value > self.app.config["SANDBOX_MAX_PIDS"]:
            raise SandboxDenied("PID limit is outside the configured range")
        if timeout_value <= 0 or timeout_value > self.app.config["SANDBOX_MAX_TIMEOUT"]:
            raise SandboxDenied("timeout is outside the configured range")
        limits = {
            "cpu_quota": int(cpu_value * 100000),
            "mem_limit": memory_value,
            "pids_limit": pids_value,
            "network_mode": network,
        }
        client = self._client()
        volumes = {}
        if workspace:
            workspace_root = Path(self.app.config["SANDBOX_WORKSPACE_DIR"]).resolve()
            workspace = str(Path(workspace).resolve())
            try:
                Path(workspace).relative_to(workspace_root)
            except ValueError:
                if not self.app.config.get("SANDBOX_ALLOW_HOST_MOUNTS", False):
                    raise SandboxDenied(
                        "workspace must be inside the sandbox workspace root"
                    ) from None
            if not os.path.isdir(workspace):
                os.makedirs(workspace, exist_ok=True)
            volumes[workspace] = {"bind": "/workspace", "mode": "rw"}
        try:
            argv = command if isinstance(command, list) else shlex.split(command)
        except ValueError as exc:
            raise SandboxDenied("command is not valid shell syntax") from exc
        if not argv or not all(isinstance(arg, str) for arg in argv):
            raise SandboxDenied("command must be a non-empty string or list of strings")
        try:
            container = client.containers.run(
                image,
                command=argv,
                detach=True,
                volumes=volumes,
                cpu_quota=limits["cpu_quota"],
                mem_limit=limits["mem_limit"],
                pids_limit=limits["pids_limit"],
                network_mode=limits["network_mode"],
                working_dir="/workspace" if workspace else None,
                privileged=False,
            )
            result = container.wait(timeout=timeout_value)
            logs = container.logs(stdout=True, stderr=True).decode(errors="replace")
            return {
                "ok": result.get("StatusCode") == 0,
                "status_code": result.get("StatusCode"),
                "image": image,
                "logs": logs[-8000:],
            }
        except Exception as exc:
            if "TimeoutExpired" in type(exc).__name__:
                raise SandboxUnavailable(f"job timed out after {timeout_value}s") from exc
            raise SandboxUnavailable(str(exc)) from None
        finally:
            if "container" in locals():
                try:
                    container.remove(force=True)
                except Exception as exc:
                    logging.getLogger(__name__).debug(
                        "Sandbox container cleanup failed: %s", type(exc).__name__
                    )

    def readiness_probe(
        self, image: str, command: str = "/bin/sh -c 'echo ready && env && pwd'"
    ) -> dict:
        result = self.run(image, command, network="none")
        return {
            "ok": result["ok"],
            "status_code": result["status_code"],
            "logs": result["logs"],
        }

    def _validate_image(self, image: str) -> None:
        allowlist = self.app.config["SANDBOX_IMAGES_ALLOWLIST"]
        if image not in allowlist:
            raise SandboxDenied(f"image '{image}' is not in the allowlist")

    def _validate_network(self, network: str) -> None:
        if network not in self.app.config["SANDBOX_NETWORK_ALLOWLIST"]:
            raise SandboxDenied(f"network '{network}' is not allowed")


def _memory_bytes(value: str) -> int:
    text = str(value).strip().lower()
    units = {
        "b": 1,
        "k": 1024,
        "kb": 1024,
        "m": 1024**2,
        "mb": 1024**2,
        "g": 1024**3,
        "gb": 1024**3,
    }
    for suffix, multiplier in sorted(units.items(), key=lambda item: -len(item[0])):
        if text.endswith(suffix):
            try:
                return int(float(text[: -len(suffix)].strip()) * multiplier)
            except ValueError:
                break
    try:
        return int(text)
    except ValueError as exc:
        raise SandboxDenied("memory limit is invalid") from exc
