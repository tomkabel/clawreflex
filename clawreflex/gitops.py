"""Explicit optional repair commit on a new branch, without changing the user's index."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess  # nosec B404 # fixed git plumbing argv; no shell or repository hooks
import tempfile
from typing import Any

from .privacy import redact


def git(root: Path, *args: str, data: bytes | None = None, env: dict[str, str] | None = None) -> bytes:
    command = ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
               '-c', 'commit.gpgsign=false', '-C', str(root), *args]
    result = subprocess.run(command, input=data, capture_output=True, check=False, env=env, timeout=15)  # nosec B603 # fixed plumbing argv
    if result.returncode:
        raise ValueError('git plumbing failed: ' + redact(result.stderr.decode(errors='replace')).text[-1000:])
    return result.stdout


def commit_proposal(root: Path, relative: str, source: str, expected_sha256: str,
                    run_id: str, message: str) -> dict[str, Any]:
    root = root.resolve(strict=True)
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] == '.git':
        raise ValueError('invalid target path')
    target = root / path
    if any(parent.is_symlink() for parent in (target, *target.parents)):
        raise ValueError('symlink paths forbidden')
    if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError('target changed; commit refused')
    if redact(source).count or redact(message).count:
        raise ValueError('secret-shaped candidate or commit message refused')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', run_id):
        raise ValueError('invalid run ID')
    if not message.strip() or len(message) > 1000:
        raise ValueError('commit message must be 1–1000 characters')
    top = Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve()
    if top != root:
        raise ValueError('root must be the git repository root')
    head = git(root, 'rev-parse', 'HEAD').decode().strip()
    # A repair verified with other uncommitted source is not a standalone commit.
    dirty = git(root, 'diff', '--name-only', '-z', 'HEAD').split(b'\0')
    if any(name and name.decode() != path.as_posix() for name in dirty):
        raise ValueError('other tracked changes present; commit refused')
    staged = git(root, 'diff', '--cached', '--name-only', '-z')
    if staged.strip(b'\0'):
        raise ValueError('user index contains staged work; commit refused')
    mode = git(root, 'ls-files', '-s', '--', path.as_posix()).decode().split()
    if not mode or mode[0] not in {'100644', '100755'}:
        raise ValueError('commit requires a tracked regular Python target')
    blob = git(root, 'hash-object', '-w', '--stdin', data=source.encode()).decode().strip()
    with tempfile.TemporaryDirectory(prefix='clawreflex-index-') as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / 'index'))
        git(root, 'read-tree', head, env=env)
        git(root, 'update-index', '--add', '--cacheinfo', mode[0], blob, path.as_posix(), env=env)
        tree = git(root, 'write-tree', env=env).decode().strip()
        commit = git(root, 'commit-tree', tree, '-p', head, data=(message + '\n').encode(), env=env).decode().strip()
    # Atomic ref creation refuses an existing run branch. HEAD/index/tree are untouched.
    branch = 'refs/heads/clawreflex/' + run_id
    git(root, 'update-ref', branch, commit, '0' * len(head))
    return {'ok': True, 'branch': branch.removeprefix('refs/heads/'), 'commit': commit,
            'parent': head, 'target': path.as_posix(), 'patch_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'user_branch_changed': False, 'user_index_changed': False,
            'note': 'Commit created on a new branch; review or cherry-pick explicitly. User working files are untouched.'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--message', default='Apply verified ClawReflex repair')
    args = parser.parse_args()
    result = commit_proposal(args.repo, args.target, args.candidate.read_text(), args.expected_sha256,
                             args.run_id, args.message)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
