#!/usr/bin/env python3
"""
Generate APP_PASSWORD_HASH for .env or Streamlit secrets.

Usage (venv):
  python tools/make_password_hash.py
  python tools/make_password_hash.py "my-secret-password"
"""

from __future__ import annotations

import getpass
import hashlib
import os
import sys

_ITERATIONS = 200_000


def make_hash(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{salt.hex()}:{derived.hex()}"


def main() -> int:
    if len(sys.argv) > 1:
        pwd = sys.argv[1]
    else:
        pwd = getpass.getpass("Password to hash: ")
        confirm = getpass.getpass("Confirm: ")
        if pwd != confirm:
            print("Passwords do not match.", file=sys.stderr)
            return 1
    if len(pwd) < 8:
        print("Use at least 8 characters.", file=sys.stderr)
        return 1
    h = make_hash(pwd)
    print("Add to .env or Streamlit secrets:")
    print(f"APP_PASSWORD_HASH={h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())