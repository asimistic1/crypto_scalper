"""Safe download, checksum verify, and zip extraction for Binance public data."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from urllib.parse import urlparse

import requests

ALLOWED_HOSTS = frozenset({"data.binance.vision", "fapi.binance.com"})
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024  # 512 MiB per zip entry


class ChecksumMismatchError(RuntimeError):
    pass


class ZipSafetyError(RuntimeError):
    pass


def assert_allowed_url(url: str) -> None:
    host = urlparse(url).hostname or ""
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"Host not allowed: {host}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_checksum_file(text: str) -> str:
    """Return hex digest from a Binance .CHECKSUM line."""
    line = text.strip().splitlines()[0]
    parts = line.split()
    if not parts:
        raise ValueError("empty checksum file")
    digest = parts[0].lower()
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError(f"invalid checksum digest: {digest!r}")
    return digest


def verify_checksum(content: bytes, checksum_text: str) -> None:
    expected = parse_checksum_file(checksum_text)
    actual = sha256_bytes(content)
    if actual != expected:
        raise ChecksumMismatchError(f"expected {expected}, got {actual}")


def safe_extract_csv(zip_bytes: bytes, expected_member: str) -> bytes:
    """Extract one CSV member; reject path traversal and zip bombs."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if expected_member not in names:
            # Binance zips usually contain one file matching the zip base name
            csv_names = [n for n in names if n.endswith(".csv")]
            if len(csv_names) != 1:
                raise ZipSafetyError(f"unexpected zip members: {names}")
            expected_member = csv_names[0]
        if ".." in expected_member or expected_member.startswith("/"):
            raise ZipSafetyError(f"unsafe path: {expected_member}")
        info = zf.getinfo(expected_member)
        if info.file_size > MAX_UNCOMPRESSED_BYTES:
            raise ZipSafetyError(f"entry too large: {info.file_size}")
        total = 0
        chunks: list[bytes] = []
        with zf.open(expected_member) as fh:
            while True:
                block = fh.read(1 << 20)
                if not block:
                    break
                total += len(block)
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise ZipSafetyError("uncompressed size exceeds limit")
                chunks.append(block)
        return b"".join(chunks)


def http_get_bytes(url: str, *, timeout: tuple[float, float] = (5.0, 120.0), retries: int = 4) -> bytes:
    assert_allowed_url(url)
    delay = 1.0
    last_err: Exception | None = None
    for _ in range(retries):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.content
        except Exception as exc:  # noqa: BLE001 — retry wrapper
            last_err = exc
            import time

            time.sleep(delay)
            delay = min(delay * 2, 30.0)
    assert last_err is not None
    raise last_err