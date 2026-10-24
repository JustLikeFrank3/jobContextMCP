"""Fail closed on missing/invalid reports or medium/high ZAP findings."""
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit


def check_report(path):
    report = json.loads(Path(path).read_text(encoding='utf-8'))
    sites = report['site']
    if not isinstance(sites, list) or not sites:
        raise ValueError('ZAP produced no scanned sites')
    findings = []
    for site in sites:
        url = urlsplit(site['@name'])
        if ((url.scheme, url.hostname, url.port) != ('http', 'app', 8000)
                or url.username is not None or url.password is not None
                or url.path not in ('', '/') or url.query or url.fragment):
            raise ValueError('Unexpected scan target in ZAP report')
        alerts = site['alerts']
        if not isinstance(alerts, list):
            raise ValueError('Invalid ZAP alerts collection')
        for alert in alerts:
            raw_risk = alert['riskcode']
            if type(raw_risk) not in (int, str) or str(raw_risk) not in ('0', '1', '2', '3'):
                raise ValueError('Invalid ZAP severity')
            risk = int(raw_risk)
            if risk >= 2:
                findings.append(f"{alert['pluginid']}: {alert['alert']}")
    return findings


if __name__ == '__main__':
    try:
        findings = check_report(sys.argv[1])
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        sys.exit(f'Invalid/missing DAST report: {exc}')
    for finding in findings:
        print(finding)
    sys.exit(1 if findings else 0)
