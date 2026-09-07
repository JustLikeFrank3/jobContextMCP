"""Discovery's public/auth boundaries and CLI/API ledger parity."""
import json
from contextlib import closing
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from lib import discovery as dr, discovery_ops as ops
from transport.http.routes import discovery as routes
from transport.http.security import User, AuthUnavailable
from transport.http.app import UserDataContextMiddleware
from scripts.discovery_report import main

DATA = dict(name="Test Participant", email="participant@example.com", segment_answer="job searching",
            current_tools="spreadsheet, notes", ai_assistant="Claude", best_window="Tuesday 3pm Eastern",
            incentive_preference="gift_card", channel="referral")
ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCOVERY_ENABLED", "qa")
    monkeypatch.setenv("DISCOVERY_DB", str(tmp_path / "discovery.db"))
    monkeypatch.setenv("DISCOVERY_ADMIN_OIDS", "founder")
    routes._limits.clear()
    def auth(authorization, session):
        return User(session, "Test") if session else None
    monkeypatch.setattr(routes, "get_auth_provider", lambda: SimpleNamespace(auth_enabled=True, authenticate_request=auth))
    import transport.http.app as app_module
    dist = tmp_path / "dist"; dist.mkdir(); (dist / "index.html").write_text('<div id="root"></div>')
    monkeypatch.setattr(app_module, "_SPA_DIST", dist)
    app = FastAPI(); app.add_middleware(UserDataContextMiddleware); app.include_router(routes.router)
    with TestClient(app) as browser:
        yield browser


def admin(client):
    client.cookies.set("jc_session", "founder")
    return client


def read():
    with closing(dr.connect(dr.default_ledger_path())) as con:
        return dr.load_ledger(con)


def test_signup_cookie_untouched_duplicate_and_storage(client, monkeypatch):
    def forbidden(*args):
        raise AssertionError('Signup read authentication or provisioned tenant')
    monkeypatch.setattr(routes, 'get_auth_provider', forbidden)
    def no_cookies(request):
        assert not request.headers.get('cookie')
        return {}
    monkeypatch.setattr(Request, 'cookies', property(no_cookies))
    client.cookies.set('jc_session', 'do-not-read')
    assert client.get('/discovery').status_code == 200
    first = client.post('/api/discovery/signup', json=DATA)
    assert first.status_code == 200 and 'set-cookie' not in first.headers
    assert first.headers['cache-control'] == 'no-store'
    duplicate = client.post('/api/discovery/signup', json={**DATA, 'email': 'PARTICIPANT@example.com'})
    assert duplicate.json() == first.json()
    people = read()['participants']; assert len(people) == 1
    p = people[0]; assert p['status'] == 'screened' and p['segment'] == 'job_seeker'
    assert p['screener']['best_window'] == DATA['best_window']
    assert p['screener']['incentive_preference'] == 'gift_card'
    assert not p['consent']['recorded_at']
    from lib.config import DATA_FOLDER
    from pathlib import Path
    assert not routes.ledger_path().is_relative_to(Path(str(DATA_FOLDER)).resolve() / 'users')


def test_honeypot_invalid_and_rate(client):
    assert client.post('/api/discovery/signup', json={'website': 'bot'}).status_code == 200
    assert not dr.default_ledger_path().exists()
    assert client.post('/api/discovery/signup', content='broken').status_code == 422
    assert client.post('/api/discovery/signup', json={**DATA, 'email': 'bad'}).status_code == 422
    assert client.post('/api/discovery/signup', json={**DATA, 'channel': 'invalid'}).status_code == 422
    assert client.post('/api/discovery/signup', content='a'*8193).status_code == 413
    for _ in range(5): client.post('/api/discovery/signup', json={'website': 'bot'})
    assert client.post('/api/discovery/signup', json=DATA).status_code == 429


@pytest.mark.parametrize('cookie,expected', [(None,404),('someone-else',404),('founder',200),('admin',404)])
def test_review_identity(client, cookie, expected):
    if cookie: client.cookies.set('jc_session', cookie)
    assert client.get('/discovery/review').status_code == expected
    response = client.get('/api/discovery/review'); assert response.status_code == expected
    if expected == 200:
        data = response.json(); assert data['report']['numbers'] == dr.build_report(data['ledger']).numbers


@pytest.mark.parametrize('path,method', [('/discovery','get'),('/discovery/review','get'),('/api/discovery/signup','post'),('/api/discovery/review','get'),('/api/discovery/snapshot','post')])
def test_disabled_is_404(client, monkeypatch, path, method):
    monkeypatch.delenv('DISCOVERY_ENABLED'); admin(client)
    assert getattr(client,method)(path).status_code == 404


def test_founder_csrf_and_invalid_action(client):
    admin(client)
    assert client.post('/api/discovery/status',json={}).status_code == 403
    assert client.post('/api/discovery/status',json={},headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.post('/api/discovery/status',json={},headers={**ORIGIN,'Sec-Fetch-Site':'same-site'}).status_code == 403
    assert client.post('/api/discovery/missing',json={},headers=ORIGIN).status_code == 404
    assert client.post('/api/discovery/status',json={'participant':1,'status':'active'},headers=ORIGIN).status_code == 422


def test_actions_match_cli_and_consent_gate(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ops, '_now', lambda: '2026-09-07T12:00:00')
    monkeypatch.setattr(dr, '_now', lambda: '2026-09-07T12:00:00')
    client.post('/api/discovery/signup',json=DATA); admin(client)
    other = tmp_path / 'cli.db'
    with closing(dr.connect(other)) as con:
        dr.add_signup(con,DATA['name'],DATA['email'],DATA['segment_answer'],DATA['current_tools'],DATA['ai_assistant'],DATA['channel'],incentive_preference='gift_card',best_window=DATA['best_window'])
    operations = [
      ('schedule',dict(participant=1,kind='interview',when='2026-09-08T12:00:00'),['session','add','1','--when','2026-09-08T12:00:00']),
      ('complete',dict(session=1,minutes=30,themes='trust',notes='',no_show=False),['session','done','1','--minutes','30','--themes','trust','--notes','']),
      ('consent',dict(participant=1,version='2026-09',recording_ok=False,quote_ok=True),['consent','1','--version','2026-09','--quote-ok']),
      ('quote',dict(session=1,text='Less repetition',public=True),['quote','1','Less repetition','--public']),
      ('incentive',dict(participant=1,earned_by='1',type='gift_card',amount=25,reference='receipt-1',pending=False),['incentive','1','--earned-by','1','--amount','25','--reference','receipt-1']),
      ('status',dict(participant=1,status='declined'),['status','1','declined']),
    ]
    for action, payload, args in operations:
        response=client.post('/api/discovery/'+action,json=payload,headers=ORIGIN)
        assert response.status_code == 200, response.text
        assert main(['--ledger',str(other),*args]) == 0
        with closing(dr.connect(other)) as con: assert read() == dr.load_ledger(con)
        if action == 'complete':
            report=client.get('/api/discovery/review').json()['report']
            assert any('without consent' in e for e in report['errors'])
            assert report['numbers']['customer_interviews_completed'] == 0
            assert client.post('/api/discovery/snapshot',json={},headers=ORIGIN).status_code == 409
    response=client.post('/api/discovery/snapshot',json={},headers=ORIGIN)
    assert response.status_code == 200
    snap=json.loads((dr.default_ledger_path().parent / response.json()['filename']).read_text())
    assert snap['numbers']['customer_interviews_completed'] == 1
    assert snap['ledger_sha256'] == dr.ledger_sha256(dr.default_ledger_path())


def test_wal_snapshot_immutable_and_findings_restricted(tmp_path):
    path=tmp_path/'ledger.db'
    with closing(dr.connect(path)) as con:
        before=dr.ledger_sha256(path)
        dr.add_signup(con,'A','a@example.com','coach','','none')
        assert dr.ledger_sha256(path) != before
        a=dr.write_snapshot(path,dr.Report(),'2026-09-07')
        b=dr.write_snapshot(path,dr.Report(),'2026-09-07')
        assert a != b and a.exists() and b.exists()
        assert json.loads(a.read_text())['numbers']['participants_total'] == 1
    with pytest.raises(ValueError): dr.write_findings(tmp_path/'elsewhere.md',dr.Report(),'2026-09-07')
    with pytest.raises(ValueError): dr.render_findings_block(dr.Report(errors=['invalid']),'2026-09-07')
    assert 'participants_total' not in dr.render_text(dr.Report(numbers={'participants_total':3},errors=['invalid']))


def test_storage_auth_and_missing_build(client, monkeypatch, tmp_path):
    from lib import config
    monkeypatch.setenv('DISCOVERY_DB',str(config.DATA_FOLDER / 'users' / 'bad.db'))
    with pytest.raises(Exception) as exc: routes.ledger_path()
    assert exc.value.status_code == 503
    monkeypatch.setenv('DISCOVERY_DB',str(tmp_path/'ledger.db'))
    def unavailable(*args): raise AuthUnavailable()
    monkeypatch.setattr(routes,'get_auth_provider',lambda: SimpleNamespace(authenticate_request=unavailable))
    assert client.get('/api/discovery/review').status_code == 503
    import transport.http.app as app_module
    monkeypatch.setattr(app_module,'_SPA_DIST',tmp_path/'missing')
    assert client.get('/discovery').status_code == 503


def test_ops_reject_invalid_and_no_show(tmp_path):
    with closing(dr.connect(tmp_path/'db')) as con:
        dr.add_signup(con,'A','a@example.com','coach','','none')
        for action, values in [('unknown',{}),('consent',dict(participant=99,version='a')),('consent',dict(participant=1,version=' ')),('schedule',dict(participant=1,kind='bad')),('status',dict(participant=1,status='active')),('incentive',dict(participant=1,earned_by='1',amount=-1))]:
            with pytest.raises(ValueError): ops.mutate(con,action,values)
        sid=ops.mutate(con,'schedule',dict(participant=1))
        for action, values in [('complete',dict(session=sid,minutes=-1)),('quote',dict(session=sid,text=' '))]:
            with pytest.raises(ValueError): ops.mutate(con,action,values)
        ops.mutate(con,'complete',dict(session=sid,no_show=True))
        assert dr.load_ledger(con)['sessions'][0]['status'] == 'no_show'
        ops.mutate(con,'incentive',dict(participant=1,earned_by='1',pending=True))
        assert dr.load_ledger(con)['incentives'][0]['status'] == 'pending'
