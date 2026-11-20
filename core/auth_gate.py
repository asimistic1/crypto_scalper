"""
Optional password gate for deployed instances (PBKDF2-HMAC-SHA256).

Set APP_PASSWORD_HASH in .env or Streamlit secrets (see tools/make_password_hash.py).
If unset, the gate is skipped (local development).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time

import streamlit as st

logger = logging.getLogger(__name__)

_PBKDF2_ITERATIONS = 200_000
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 60


def _load_hash() -> str | None:
    env_val = os.environ.get("APP_PASSWORD_HASH", "").strip()
    if env_val:
        return env_val
    try:
        val = st.secrets.get("APP_PASSWORD_HASH", "")
        if str(val).strip():
            return str(val).strip()
    except (FileNotFoundError, KeyError, AttributeError):
        pass
    return None


def verify_password(password: str, stored: str) -> bool:
    """stored format: salt_hex:hash_hex"""
    try:
        salt_hex, hash_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        logger.warning("Invalid APP_PASSWORD_HASH format")
        return False
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
    )
    return hmac.compare_digest(derived, expected)


def require_auth() -> bool:
    """
    Show login UI when a hash is configured. Returns True when access is allowed.
    """
    stored = _load_hash()
    if not stored:
        return True

    if st.session_state.get("auth_ok"):
        return True

    lock_until = float(st.session_state.get("auth_lock_until", 0.0))
    if time.time() < lock_until:
        remain = int(lock_until - time.time())
        st.error(f"Too many attempts. Try again in {remain}s.")
        return False

    st.title("Crypto Scalper")
    st.caption("Enter the app password to continue.")
    pwd = st.text_input("Password", type="password", autocomplete="current-password")
    if st.button("Unlock", type="primary"):
        attempts = int(st.session_state.get("auth_attempts", 0))
        if pwd and verify_password(pwd, stored):
            st.session_state["auth_ok"] = True
            st.session_state["auth_attempts"] = 0
            st.rerun()
        else:
            attempts += 1
            st.session_state["auth_attempts"] = attempts
            if attempts >= _MAX_ATTEMPTS:
                st.session_state["auth_lock_until"] = time.time() + _LOCKOUT_SECONDS
                st.session_state["auth_attempts"] = 0
                st.error("Locked out for 60 seconds after 5 wrong attempts.")
            else:
                st.error("Wrong password.")
    return False