"""Exercise orchestration with a fake Docker CLI; never run a real scan."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).parent
FAKE_DOCKER = '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['DOCKER_CALLS'], 'a') as f:
    f.write(json.dumps(args) + '\\n')
if 'zap-full-scan.py' in args:
    if os.environ.get('WRITE_REPORT') == 'yes':
        pathlib.Path('security/dast/reports/report.json').write_text(json.dumps({
            'site': [{'@name': 'http://app:8000', 'alerts': []}]
        }))
    sys.exit(int(os.environ.get('SCAN_EXIT', '0')))
'''


class RunnerTests(unittest.TestCase):
    def run_fixture(self, *, scan_exit='0', write_report='yes', arguments=()):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / 'security' / 'dast'
            dest.mkdir(parents=True)
            for name in ('run.sh', 'check_report.py'):
                shutil.copy(SOURCE / name, dest / name)
            binary = root / 'bin'
            binary.mkdir()
            docker = binary / 'docker'
            docker.write_text(FAKE_DOCKER)
            docker.chmod(0o755)
            calls = root / 'calls.jsonl'
            reports = dest / 'reports'
            reports.mkdir()
            # A stale passing report must never mask a failed new scan.
            (reports / 'report.json').write_text(json.dumps({
                'site': [{'@name': 'http://app:8000', 'alerts': []}]
            }))
            env = dict(os.environ, PATH=f'{binary}:{os.environ["PATH"]}',
                       DOCKER_CALLS=str(calls), SCAN_EXIT=scan_exit,
                       WRITE_REPORT=write_report, TARGET_URL='https://jobcontext.ai')
            result = subprocess.run(['bash', str(dest / 'run.sh'), *arguments],
                                    env=env, capture_output=True, text=True, timeout=10)
            commands = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
            return result.returncode, commands

    def test_fixed_target_and_isolation(self):
        code, calls = self.run_fixture()
        self.assertEqual(code, 0)
        network = next(c for c in calls if c[:2] == ['network', 'create'])
        self.assertIn('--internal', network)
        containers = [c for c in calls if c[0] == 'run']
        self.assertEqual(len(containers), 2)
        self.assertIn('--read-only', containers[0])
        for call in containers:
            self.assertNotIn('-p', call)
            self.assertNotIn('--privileged', call)
            self.assertIn('--cap-drop', call)
        scan = containers[1]
        self.assertEqual(scan[scan.index('-t') + 1], 'http://app:8000')
        self.assertTrue(any(c[:2] == ['rm', '-f'] for c in calls))
        self.assertTrue(any(c[:2] == ['network', 'rm'] for c in calls))

    def test_warning_exit_uses_report_policy(self):
        self.assertEqual(self.run_fixture(scan_exit='2')[0], 0)

    def test_execution_errors_and_timeouts_block(self):
        for status in ('3', '124'):
            self.assertNotEqual(self.run_fixture(scan_exit=status)[0], 0)

    def test_missing_new_report_cannot_reuse_stale_report(self):
        self.assertNotEqual(self.run_fixture(write_report='no')[0], 0)

    def test_target_argument_rejected_before_docker(self):
        code, calls = self.run_fixture(arguments=('https://jobcontext.ai',))
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, [])
