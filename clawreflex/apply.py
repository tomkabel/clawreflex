"""Recoverable atomic-exchange application and hash-guarded undo.

An editor need not honor our lock. Atomic exchange retains the displaced inode,
so a save in the final check/exchange window is detected and recoverable.
"""
from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
from typing import Callable, Any

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _exchange(left: Path, right: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
        result = libc.renameat2(-100, os.fsencode(left), -100, os.fsencode(right), 2)
    elif sys.platform == 'darwin' and hasattr(libc, 'renamex_np'):
        result = libc.renamex_np(os.fsencode(left), os.fsencode(right), 2)
    else:
        raise OSError(errno.ENOTSUP, 'atomic file exchange unavailable; propose-only on this platform')
    if result:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _regular(path: Path) -> os.stat_result:
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError('symlink targets and ancestors are forbidden')
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError('target must be a regular file without hard links')
    return metadata


def guarded_replace(target: Path, expected_sha256: str, source: bytes, backup_dir: Path,
                    idempotency_key: str, before_exchange: Callable[[], None] | None = None) -> dict[str, Any]:
    target = Path(os.path.abspath(target))
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    identity = digest((str(target) + '\0' + idempotency_key).encode())
    receipt_path = backup_dir / (identity + '.json')
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(str(target), threading.RLock())
    with lock:
        # Cross-process locking serializes ClawReflex, not arbitrary editor writers.
        with (backup_dir / 'apply.lock').open('a+b') as lock_file:
            try:
                import fcntl
            except ImportError:
                return {'ok': False, 'applied': False, 'target_changed': False,
                        'error': 'platform file locking unavailable; propose only'}
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            if receipt_path.exists():
                previous = json.loads(receipt_path.read_text())
                if previous.get('expected_sha256') != expected_sha256 or previous.get('patch_sha256') != digest(source):
                    return {'ok': False, 'applied': False, 'target_changed': False,
                            'error': 'idempotency key reused with different content'}
                previous['idempotent_replay'] = True
                return previous
            receipt: dict[str, Any] = {
                'ok': False, 'applied': False, 'target_changed': False,
                'expected_sha256': expected_sha256, 'patch_sha256': digest(source),
                'idempotency_key_sha256': digest(idempotency_key.encode()),
            }
            staged: Path | None = None
            try:
                metadata = _regular(target)
                if digest(target.read_bytes()) != expected_sha256:
                    receipt['target_changed'] = True
                    return receipt
                fd, temporary = tempfile.mkstemp(prefix='.clawreflex-exchange-', dir=target.parent)
                staged = Path(temporary)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(source)
                    stream.flush()
                    os.fsync(stream.fileno())
                    os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
                if before_exchange:
                    before_exchange()
                _regular(target)
                _exchange(staged, target)
                displaced = staged.read_bytes()
                # The old inode stays linked: an editor holding its fd does not write
                # into an unlinked/deleted file. Its path is always in the receipt.
                backup = backup_dir / (identity + '.bak')
                if digest(displaced) != expected_sha256:
                    receipt['target_changed'] = True
                    _exchange(staged, target)
                    receipt['error'] = 'save raced with apply; restored displaced save; retained both inodes'
                else:
                    receipt.update(ok=True, applied=True)
                try:
                    os.replace(staged, backup)
                except OSError as exc:
                    if exc.errno != errno.EXDEV:
                        raise
                    backup = staged  # preserve inode on its original filesystem
                staged = None
                receipt['backup'] = str(backup)
                receipt['backup_sha256'] = digest(backup.read_bytes())
                receipt['target_sha256_after'] = digest(target.read_bytes())
                # A save after the exchange belongs to the editor; never rewrite it.
                if receipt['applied'] and receipt['target_sha256_after'] != digest(source):
                    receipt.update(applied=False, ok=False, target_changed=True,
                                   error='editor saved after exchange; left editor bytes untouched')
                return receipt
            except (OSError, ValueError) as exc:
                receipt['error'] = str(exc)
                return receipt
            finally:
                if staged is not None:
                    # It may be a displaced user inode if a later operation failed.
                    # Preserve it instead of unlinking uncertain data.
                    receipt['recovery'] = str(staged)
                receipt_path.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
                fcntl.flock(lock_file, fcntl.LOCK_UN)


def guarded_revert(target: Path, applied_sha256: str, backup: Path, backup_dir: Path,
                   idempotency_key: str) -> dict[str, Any]:
    _regular(backup)
    return guarded_replace(target, applied_sha256, backup.read_bytes(), backup_dir, idempotency_key)
