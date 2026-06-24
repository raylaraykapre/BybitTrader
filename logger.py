"""
logger.py - Clean short log formatter + errors.log writer
"""
import sys
import os
import threading
from datetime import datetime

_lock = threading.Lock()
_error_file = None
_base_dir = os.path.dirname(os.path.abspath(__file__))


def _get_error_file():
    global _error_file
    if _error_file is None:
        _error_file = open(os.path.join(_base_dir, "errors.log"), "a")
    return _error_file


def _ts():
    return datetime.now().strftime("%H:%M:%S")


def log(tag, msg):
    """Print a formatted log line to stdout."""
    line = f"[{_ts()}] {tag:<10}| {msg}"
    with _lock:
        print(line)
        sys.stdout.flush()


def log_error(tag, msg):
    """Write error to errors.log only (not stdout)."""
    line = f"[{_ts()}] {tag:<10}| {msg}\n"
    with _lock:
        try:
            f = _get_error_file()
            f.write(line)
            f.flush()
        except Exception:
            pass


def close():
    global _error_file
    if _error_file:
        try:
            _error_file.close()
        except Exception:
            pass
        _error_file = None
