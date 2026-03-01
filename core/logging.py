"""Logging helpers and safe API call wrapper."""

import sys

from botocore.exceptions import ClientError, BotoCoreError


def log_progress(msg: str) -> None:
    print(f"\033[0;36m>>>\033[0m {msg}", file=sys.stderr)


def log_warn(msg: str) -> None:
    print(f"\033[0;33mWARN:\033[0m {msg}", file=sys.stderr)


def safe_call(label: str, func, *args, **kwargs):
    """Call func and return result, or None on error with a warning."""
    try:
        return func(*args, **kwargs)
    except (ClientError, BotoCoreError) as e:
        log_warn(f"Could not fetch {label}: {e}")
        return None
