"""Deployment account policy checks using an isolated database and mocked Google."""
import runpy
from dataclasses import replace
from unittest.mock import AsyncMock, patch

state = runpy.run_path('tests/check_sections.py')
from settings import Settings, settings
from tests.support import TestClient, sign_in
from routes import auth
import security

base = dict(SECRET_KEY='x' * 48, DATABASE_URL='sqlite://', APP_ENV='production', ALLOWED_HOSTS='app.example.test')
for emails in ('', '*@example.test', 'not-an-email', '@example.test', 'owner@'):
    try:
        Settings.from_mapping(dict(base, ALLOWED_EMAILS=emails))
    except ValueError:
        pass
    else:
        raise AssertionError('Unsafe allowlist accepted')
policy = Settings.from_mapping(dict(base, ALLOWED_EMAILS=' Owner@Example.test '))
assert policy.permits_email('owner@example.test')
assert not policy.permits_email('other@example.test')
assert not policy.permits_email(None)

app, models, database = state['app'], state['models'], state['database']
with database.SessionLocal() as db:
    email = db.get(models.User, 1).email
allowed = replace(settings, allowed_emails=(email.casefold(),))
denied = replace(settings, allowed_emails=('different@example.test',))
with TestClient(app) as client:
    sign_in(client)
    with patch.object(security, 'settings', denied):
        assert client.get('/glucose', follow_redirects=False).status_code == 303
        assert 'session=' in client.get('/').headers.get('set-cookie', '')
    sign_in(client)
    with patch.object(security, 'settings', allowed):
        assert client.get('/glucose').status_code == 200
    with database.SessionLocal() as db:
        before = db.query(models.User).count()
    for verified, address in ((True, 'other@example.test'), (False, email), (None, email)):
        info = dict(sub='deployment-denied', email=address, email_verified=verified)
        with patch.object(auth, 'settings', allowed), patch.object(auth.oauth.google, 'authorize_access_token', AsyncMock(return_value={'userinfo': info})):
            response = client.get('/auth/google/callback', follow_redirects=False)
            assert response.headers['location'] == '/?login=unauthorized'
        with database.SessionLocal() as db:
            assert db.query(models.User).count() == before
    with database.SessionLocal() as db:
        subject = db.get(models.User, 1).google_id
    info = dict(sub=subject, email=email, email_verified=True)
    with patch.object(auth, 'settings', allowed), patch.object(auth.oauth.google, 'authorize_access_token', AsyncMock(return_value={'userinfo': info})):
        assert client.get('/auth/google/callback', follow_redirects=False).headers['location'] == '/'
    with patch.object(security, 'settings', allowed):
        assert client.get('/glucose').status_code == 200
print('PASS: production allowlist validation; approved sign-in; rejected/unverified accounts create no users; existing-session revocation.')

for host in ("*.example.test", "https://app.example.test", "app.example.test/path"):
    try:
        Settings.from_mapping(dict(base, ALLOWED_EMAILS="owner@example.test", ALLOWED_HOSTS=host))
    except ValueError:
        pass
    else:
        raise AssertionError("Unsafe production hostname accepted")
