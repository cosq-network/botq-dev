import os
import subprocess  # nosec B404 - subprocess is used with fixed argv and shell=False.
from dataclasses import dataclass


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    command: str

    @property
    def error(self) -> str:
        return (self.stderr or self.stdout).strip()


class GitCommandBackend:
    name = "subprocess"

    def __init__(self, ssh_bin: str = "ssh", timeout: int = 30):
        self.ssh_bin = ssh_bin
        self.timeout = timeout

    def _run(
        self, args: list[str], cwd: str | None = None, env: dict | None = None
    ) -> CommandResult:
        merged = os.environ.copy()
        if env:
            merged.update(env)
        try:
            proc = subprocess.run(  # nosec B603 - argv is constructed by trusted backend methods.
                args,
                cwd=cwd,
                env=merged,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            return CommandResult(
                ok=proc.returncode == 0,
                stdout=proc.stdout.strip(),
                stderr=proc.stderr.strip(),
                command=" ".join(args),
            )
        except FileNotFoundError:
            return CommandResult(False, "", f"Executable not found: {args[0]}", " ".join(args))
        except subprocess.TimeoutExpired:
            return CommandResult(
                False, "", f"Command timed out after {self.timeout}s", " ".join(args)
            )

    def git(
        self, args: list[str], cwd: str | None = None, env: dict | None = None
    ) -> CommandResult:
        return self._run(["git", *args], cwd=cwd, env=env)

    def generate_keypair(self, key_path: str, key_type: str = "ed25519") -> CommandResult:
        # ssh-keygen refuses to overwrite an existing key without an interactive
        # prompt (which hangs under BatchMode), so clear any prior key pair first.
        for suffix in ("", ".pub"):
            existing = key_path + suffix
            if os.path.exists(existing):
                try:
                    os.remove(existing)
                except OSError:
                    pass
        return self._run(["ssh-keygen", "-t", key_type, "-N", "", "-f", key_path])

    def scan_host_key(self, host: str, port: int = 22) -> CommandResult:
        return self._run(["ssh-keyscan", "-t", "ed25519", "-p", str(port), host])

    def ls_remote(
        self, ssh_url: str, key_path: str, known_hosts: str, timeout: int = 15
    ) -> CommandResult:
        env = {
            "GIT_SSH_COMMAND": _ssh_command(self.ssh_bin, key_path, known_hosts, timeout),
            "GIT_TERMINAL_PROMPT": "0",
        }
        return self.git(["ls-remote", "--heads", ssh_url], env=env)

    def clone(
        self, ssh_url: str, dest: str, key_path: str, known_hosts: str, timeout: int = 180
    ) -> CommandResult:
        env = {
            "GIT_SSH_COMMAND": _ssh_command(self.ssh_bin, key_path, known_hosts, timeout),
            "GIT_TERMINAL_PROMPT": "0",
        }
        return self.git(["clone", "--recursive", ssh_url, dest], env=env)

    def fetch(
        self, dest: str, key_path: str, known_hosts: str, timeout: int = 120
    ) -> CommandResult:
        env = {
            "GIT_SSH_COMMAND": _ssh_command(self.ssh_bin, key_path, known_hosts, timeout),
            "GIT_TERMINAL_PROMPT": "0",
        }
        return self.git(["-C", dest, "fetch", "--all", "--tags"], env=env)

    def checkout(self, dest: str, branch: str) -> CommandResult:
        return self.git(["-C", dest, "checkout", branch])

    def reset_hard(self, dest: str, ref: str) -> CommandResult:
        return self.git(["-C", dest, "reset", "--hard", ref])

    def current_head(self, dest: str) -> str:
        return self.git(["-C", dest, "rev-parse", "HEAD"]).stdout.strip()


def _ssh_command(ssh_bin: str, key_path: str, known_hosts: str, timeout: int) -> str:
    opts = [
        "-o StrictHostKeyChecking=yes",
        f"-o UserKnownHostsFile={known_hosts}",
        "-o IdentitiesOnly=yes",
        f"-i {key_path}",
        f"-o ConnectTimeout={timeout}",
        "-o BatchMode=yes",
    ]
    return f"{ssh_bin} {' '.join(opts)}"


class FakeGitBackend:
    name = "fake"

    def __init__(self):
        self.calls: list[tuple[str, ...]] = []
        self.results: dict[str, CommandResult] = {}
        self.clone_destinations: list[str] = []

    def _result(self, key: str) -> CommandResult:
        return self.results.get(key, CommandResult(True, "ok", "", key))

    def git(self, args, cwd=None):
        self.calls.append(("git", *args))
        return self._result("git")

    def generate_keypair(self, key_path, key_type="ed25519"):
        self.calls.append(("generate_keypair", key_path, key_type))
        import pathlib

        public = f"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFake{abs(hash(key_path))}FakeKeyTest only\n"
        pathlib.Path(key_path).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(key_path).write_text("PRIVATE KEY (fake)", encoding="utf-8")
        pathlib.Path(f"{key_path}.pub").write_text(public, encoding="utf-8")
        return self._result("generate_keypair")

    def scan_host_key(self, host, port=22):
        self.calls.append(("scan_host_key", host, str(port)))
        return self._result("scan_host_key")

    def ls_remote(self, ssh_url, key_path, known_hosts, timeout=15):
        self.calls.append(("ls_remote", ssh_url))
        return self._result("ls_remote")

    def clone(self, ssh_url, dest, key_path, known_hosts, timeout=180):
        self.calls.append(("clone", ssh_url, dest))
        self.clone_destinations.append(dest)
        import pathlib

        pathlib.Path(dest).mkdir(parents=True, exist_ok=True)
        return self._result("clone")

    def fetch(self, dest, key_path, known_hosts, timeout=120):
        self.calls.append(("fetch", dest))
        return self._result("fetch")

    def checkout(self, dest, branch):
        self.calls.append(("checkout", dest, branch))
        return self._result("checkout")

    def reset_hard(self, dest, ref):
        self.calls.append(("reset_hard", dest, ref))
        return self._result("reset_hard")

    def current_head(self, dest):
        self.calls.append(("current_head", dest))
        return "c0ffee0000000000000000000000000000000000"
