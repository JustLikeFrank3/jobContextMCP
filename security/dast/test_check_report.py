"""Dependency-free unit tests for the fail-closed DAST gate."""
import json
from pathlib import Path
import tempfile
import unittest

from check_report import check_report


class ReportPolicyTests(unittest.TestCase):
    def evaluate(self, value):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.json'
            path.write_text(json.dumps(value), encoding='utf-8')
            return check_report(path)

    def report(self, risk):
        return {'site': [{'@name': 'http://app:8000', 'alerts': [
            {'riskcode': str(risk), 'pluginid': '123', 'alert': 'test finding'}
        ]}]}

    def test_low_and_info_are_report_only(self):
        for risk in (0, 1):
            self.assertEqual(self.evaluate(self.report(risk)), [])

    def test_medium_and_high_block(self):
        for risk in (2, 3):
            self.assertEqual(len(self.evaluate(self.report(risk))), 1)

    def test_unknown_severity_fails(self):
        with self.assertRaises(ValueError):
            self.evaluate(self.report(4))

    def test_empty_sites_fails(self):
        with self.assertRaises(ValueError):
            self.evaluate({'site': []})

    def test_external_and_wrong_port_targets_fail(self):
        for target in ('https://jobcontext.ai', 'http://app:9000', 'http://app.evil:8000'):
            report = self.report(0)
            report['site'][0]['@name'] = target
            with self.assertRaises(ValueError):
                self.evaluate(report)

    def test_malformed_alerts_collection_fails(self):
        for alerts in ({}, '', None, 0):
            with self.subTest(alerts=alerts), self.assertRaises(ValueError):
                self.evaluate({'site': [{'@name': 'http://app:8000', 'alerts': alerts}]})

    def test_malformed_severity_fails(self):
        for risk in (True, 1.5, '1.5', None):
            report = self.report(0)
            report['site'][0]['alerts'][0]['riskcode'] = risk
            with self.subTest(risk=risk), self.assertRaises(ValueError):
                self.evaluate(report)

    def test_deceptive_target_fails(self):
        for target in ('http://user@app:8000', 'http://app:8000/?target=external',
                       'http://app:8000/other', 'http://app:8000/#external'):
            report = self.report(0)
            report['site'][0]['@name'] = target
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.evaluate(report)

    def test_missing_alerts_fails(self):
        with self.assertRaises(KeyError):
            self.evaluate({'site': [{'@name': 'http://app:8000'}]})

    def test_missing_file_fails(self):
        with self.assertRaises(OSError):
            check_report('/nonexistent/dast-report.json')

    def test_invalid_json_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.json'
            path.write_text('not json', encoding='utf-8')
            with self.assertRaises(ValueError):
                check_report(path)


if __name__ == '__main__':
    unittest.main()
