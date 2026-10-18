"""Fault injection for the controller; real datasets and processes are untouched."""
import importlib.util
import json
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class FiQASupervisorTests(unittest.TestCase):
    def test_failed_stage_resumes_and_corrupt_completed_artifact_is_rejected(self):
        spec = importlib.util.spec_from_file_location('fiqa_controller_test',
            ROOT / 'build/accuracy_v3/launch_fiqa_full_test.py')
        controller = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(controller)
        from research.accuracy_v3.storage import write_checked, sha
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller.ROOT = root
            for name in ('STATE', 'PID', 'LOCK', 'LOG', 'FROZEN', 'SNAPSHOT'):
                setattr(controller, name, root / getattr(controller, name).name)
            controller.CONFIRM, controller.TEST, controller.LOGS = root / 'confirmation', root / 'test', root / 'logs'
            write_checked(controller.CONFIRM / 'manifest.json', {'query_ids': list(map(str, range(100)))})
            write_checked(controller.CONFIRM / 'evaluation.json', {'query_count': 100,
                'gate': {'passed': True}, 'manifest_sha256': sha(controller.CONFIRM / 'manifest.json')})
            fingerprint = {'controller_sha256': sha(controller.SELF)}
            attempts, fail_run = [], True
            class Child:
                pid = 1
                def __init__(child, command, **kwargs):
                    nonlocal fail_run
                    name = command[4]
                    attempts.append((name, '--resume' in command))
                    if name == 'preflight':
                        write_checked(root / 'build/accuracy_v3/preflight.json', {'passed': True})
                    elif name == 'freeze':
                        write_checked(controller.FROZEN, {'frozen': True})
                    elif name == 'run':
                        write_checked(controller.TEST / 'run.json', {'identity': {'dataset': 'fiqa'}})
                        if not fail_run:
                            write_checked(controller.TEST / 'manifest.json', {'query_ids': list(map(str, range(648)))})
                    elif name == 'evaluate':
                        write_checked(controller.TEST / 'evaluation.json', {'gate': {'passed': True}})
                    elif name == 'report':
                        (controller.TEST / 'REPORT.md').write_text('Complete')
                    child.returncode = 1 if name == 'run' and fail_run else 0
                def wait(child, timeout=None):
                    return child.returncode
                def poll(child):
                    return child.returncode
            with patch.object(controller, 'fingerprint', return_value=fingerprint), \
                 patch.object(controller.subprocess, 'Popen', Child), \
                 patch.object(controller.signal, 'signal'), \
                 patch('research.accuracy_v3.checks.require_smoke'):
                self.assertEqual(controller.supervise(), 1)
                fail_run = False
                self.assertEqual(controller.supervise(resume=True), 0)
                self.assertEqual(attempts, [('preflight', False), ('freeze', False), ('run', False),
                                           ('run', True), ('evaluate', False), ('report', False)])
                state = json.loads(controller.STATE.read_text())
                self.assertEqual(state['status'], 'completed')
                (controller.TEST / 'manifest.json').write_text('corrupt')
                self.assertEqual(controller.supervise(resume=True), 1)
                self.assertIn('Completed FiQA stage artifact changed', json.loads(controller.STATE.read_text())['error'])


if __name__ == '__main__':
    unittest.main()
