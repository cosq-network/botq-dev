import os
import pathlib
import re

from ..errors import ValidationError


def normalize_host(host: str) -> str:
    host = host.strip().lower().rstrip(".")
    host = re.sub(r"^ssh://", "", host)
    host = re.sub(r"^git@", "", host)
    host = host.split("/")[0]
    host = host.split("@")[-1]
    if ":" in host:
        host = host.split(":")[0]
    return host


def parse_ssh_url(url: str) -> tuple[str, int]:
    url = url.strip()
    port = 22
    if "://" in url:
        scheme, rest = url.split("://", 1)
        if scheme not in {"ssh", "git"}:
            raise ValidationError("Only ssh:// or git@ SCP-style URLs are supported")
        authority, _, path = rest.strip().partition("/")
        if "@" in authority:
            _, authority = authority.rsplit("@", 1)
        host, port = _split_host_port(authority, port)
        return normalize_host(host), port
    if "@" in url and ":" in url:
        host_part, _path = url.rsplit(":", 1)
        host, port = _split_host_port(host_part, port)
        return normalize_host(host), port
    raise ValidationError("Invalid SSH git URL")


def _split_host_port(authority: str, default_port: int) -> tuple[str, int]:
    if authority.startswith("["):
        end = authority.index("]")
        host = authority[1:end]
        rest = authority[end + 1 :]
        if rest.startswith(":"):
            port = int(rest[1:])
        else:
            port = default_port
        return host, port
    if authority.count(":") == 1:
        maybe_host, maybe_port = authority.rsplit(":", 1)
        if maybe_port.isdigit():
            return normalize_host(maybe_host), int(maybe_port)
    return normalize_host(authority), default_port


class KnownHosts:
    def __init__(self, path: str):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def contains(self, host: str) -> bool:
        return host in self.read_entries()

    def read_entries(self) -> dict[str, str]:
        entries: dict[str, str] = {}
        text = self.path.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 3:
                hostname = parts[0]
                entries[hostname] = line
        return entries

    def fingerprints(self, host: str) -> list[str]:
        return [self.read_entries().get(host, "")]

    def add(self, host: str, keyscan_line: str) -> None:
        keyscan_line = keyscan_line.strip()
        if not keyscan_line or keyscan_line[-1] == ",":
            raise ValidationError(
                "Host key scan returned no valid keys", code="host_key_scan_empty"
            )
        entries = self.read_entries()
        entries[host] = keyscan_line
        self.write_entries(entries)

    def remove(self, host: str) -> None:
        entries = self.read_entries()
        entries.pop(host, None)
        self.write_entries(entries)

    def write_entries(self, entries: dict[str, str]) -> None:
        self.path.write_text(
            "\n".join(entries.values()) + ("\n" if entries else ""), encoding="utf-8"
        )


KEY_PATH = "deploy_key"


def deploy_key_paths(key_dir: str) -> tuple[pathlib.Path, pathlib.Path]:
    key_dir = pathlib.Path(key_dir)
    key_dir.mkdir(parents=True, exist_ok=True)
    return key_dir / KEY_PATH, key_dir / f"{KEY_PATH}.pub"


def ensure_restrictive_permissions(path: str) -> None:
    if os.name == "posix":
        os.chmod(path, 0o600)
