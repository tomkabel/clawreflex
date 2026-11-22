from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from clawreflex.config import load_config
from clawreflex.provider import WorkspaceDriver
from clawreflex.tests.test_provider import provider_server, stream_call
from clawreflex.tests.test_workspace import BROKEN, FIXED, PROBE, REGRESSION, HELDOUT, CONFIG
from clawreflex.workspace import Workspace


class WorkspaceProviderTests(unittest.TestCase):
    def test_streaming_driver_verifies_real_repository_without_revealing_oracles(self):
        def respond(body, index):
            self.assertNotIn('test_negative', json.dumps(body))
            self.assertNotIn('verification/reference', json.dumps(body))
            return stream_call('clawreflex_probe', {'test_source': PROBE}) if index == 1 else stream_call('clawreflex_patch', {'source': FIXED, 'summary': 'multiply by two'})
        with provider_server(respond) as (endpoint, requests), tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {endpoint.key_env: 'local-test-credential'}):
            base = Path(tmp)
            root = base / 'repo'
            root.mkdir()
            (root / 'module.py').write_text(BROKEN)
            (root / '.clawreflex.toml').write_text(CONFIG)
            (root / 'verification').mkdir()
            for name, content in [('reference', FIXED), ('regression', REGRESSION), ('heldout', HELDOUT)]:
                (root / 'verification' / (name + '.py')).write_text(content)
            (root / 'tests').mkdir()
            (root / 'tests' / 'test_module.py').write_text('import unittest,module\nclass T(unittest.TestCase):\n def test_repo(self): self.assertEqual(module.double(5),10)\n')
            config = replace(load_config(root), provider={'base_url': endpoint.base_url, 'model': endpoint.model,
                                                        'key_env': endpoint.key_env, 'stream': True})
            workspace = Workspace(config, base / 'state')
            driver = WorkspaceDriver(workspace)
            try:
                record = workspace.enqueue('module.py')
                workspace.process_next(driver)
                self.assertEqual(record.status, 'verified', record.error)
                self.assertEqual((root / 'module.py').read_text(), BROKEN)
                self.assertIn('provider_queue_ms', record.timings)
                self.assertEqual(len(requests), 2)
                self.assertTrue(record.engine.patch_receipt['verification']['repository_suite']['included'])
            finally:
                driver.close()
                workspace.close()
