import hashlib
from pathlib import Path
import tempfile
import threading
import unittest

from clawreflex.apply import guarded_replace, guarded_revert
from clawreflex.privacy import redact, provider_source


def sha(value):
    return hashlib.sha256(value).hexdigest()


class ApplyTests(unittest.TestCase):
    def test_100_saves_in_final_check_exchange_window_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'app.py'
            for iteration in range(100):
                with self.subTest(iteration=iteration):
                    original = b'def answer(): return 0\n'
                    newer = f'# developer save {iteration}\n'.encode()
                    target.write_bytes(original)
                    def writer():
                        if iteration % 2:
                            saved = root / 'editor.tmp'
                            saved.write_bytes(newer)
                            saved.replace(target)
                        else:
                            target.write_bytes(newer)
                    def race():
                        thread = threading.Thread(target=writer)
                        thread.start()
                        thread.join()
                    result = guarded_replace(target, sha(original), b'def answer(): return 42\n',
                                             root / 'backups', str(iteration), before_exchange=race)
                    self.assertFalse(result['applied'], result)
                    self.assertTrue(result['target_changed'], result)
                    self.assertEqual(target.read_bytes(), newer)
                    self.assertTrue(Path(result['backup']).exists())

    def test_apply_idempotency_backup_mode_and_revert(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'app.py'
            target.write_bytes(b'original\n')
            target.chmod(0o640)
            result = guarded_replace(target, sha(b'original\n'), b'patched\n', root / 'backup', 'apply')
            self.assertTrue(result['applied'], result)
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)
            self.assertEqual(Path(result['backup']).read_bytes(), b'original\n')
            replay = guarded_replace(target, sha(b'original\n'), b'patched\n', root / 'backup', 'apply')
            self.assertTrue(replay['idempotent_replay'])
            reverted = guarded_revert(target, sha(b'patched\n'), Path(result['backup']), root / 'backup', 'undo')
            self.assertTrue(reverted['applied'], reverted)
            self.assertEqual(target.read_bytes(), b'original\n')

    def test_changed_target_and_symlinks_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'app.py'
            target.write_bytes(b'new save')
            result = guarded_replace(target, sha(b'old'), b'patch', root / 'backup', 'x')
            self.assertTrue(result['target_changed'])
            link = root / 'link.py'
            link.symlink_to(target)
            result = guarded_replace(link, sha(b'new save'), b'patch', root / 'backup', 'y')
            self.assertFalse(result['applied'])
            self.assertEqual(target.read_bytes(), b'new save')

    def test_revert_refuses_newer_editor_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'app.py'
            target.write_bytes(b'original')
            result = guarded_replace(target, sha(b'original'), b'patch', root / 'backup', 'apply')
            target.write_bytes(b'developer')
            reverted = guarded_revert(target, sha(b'patch'), Path(result['backup']), root / 'backup', 'undo')
            self.assertFalse(reverted['applied'])
            self.assertTrue(reverted['target_changed'])
            self.assertEqual(target.read_bytes(), b'developer')

    def test_secret_redaction(self):
        source = 'CEREBRAS_API_KEY="sk-' + 'x'*30 + '"\nghp_' + 'z'*30
        result = redact(source)
        self.assertEqual(result.count, 3)
        self.assertNotIn('x'*30, result.text)
        self.assertNotIn('z'*30, result.text)
        self.assertEqual(provider_source(source), result.text)
        self.assertEqual(redact('def f(x): return x').count, 0)

class ApplyEdgeTests(unittest.TestCase):
    def test_idempotency_key_reuse_with_different_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'app.py'
            target.write_bytes(b'old')
            self.assertTrue(guarded_replace(target, sha(b'old'), b'new', root / 'backup', 'same')['applied'])
            result = guarded_replace(target, sha(b'new'), b'other', root / 'backup', 'same')
            self.assertFalse(result['applied'])
            self.assertIn('idempotency', result['error'])
            self.assertEqual(target.read_bytes(), b'new')

    def test_hard_link_target_is_refused(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'app.py'
            target.write_bytes(b'old')
            os.link(target, root / 'other.py')
            self.assertFalse(guarded_replace(target, sha(b'old'), b'new', root / 'backup', 'x')['applied'])
            self.assertEqual(target.read_bytes(), b'old')
