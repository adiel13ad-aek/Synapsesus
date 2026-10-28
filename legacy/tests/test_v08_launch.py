"""Local integration tests. No real hosting, SMTP or web indexing in this suite."""
import json
import time
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
import server
from launch import render_page,public_origin
from test_api import client,register,HEADERS,post
from test_v07 import make_owner
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from check_public import check
from export_landing import export

def issue(c,**extra):
    r=c.post('/api/manage/invites',json={'label':'Piloto de teste',**extra});assert r.status_code==200,r.text;return r.json()
def signup(c,handle,code=''):
    return c.post('/api/auth/register',json={'name':'Teste privado','handle':handle,'email':handle+'@example.test','password':'test-password-2026','terms_accepted':True,'invite_code':code})
def close_signup():
    with server.db() as con:con.execute('UPDATE site_settings SET registration_open=0')

@pytest.mark.parametrize('path',['/bem-vindo','/como-funciona','/ajuda'])
def test_public_pages_render_without_javascript(client,path):
    r=client.get(path);assert r.status_code==200
    assert '<h1>' in r.text and '<script' not in r.text
    assert 'noindex,follow' in r.text and 'launch.css' in r.text
    assert '<html lang="pt-BR">' in r.text

def test_seo_only_configured_canonical_public_pages(client,monkeypatch):
    monkeypatch.setattr(server,'PUBLIC_ORIGIN','https://synapse.example')
    monkeypatch.setenv('PUBLIC_INDEXING','1')
    monkeypatch.setenv('GOOGLE_SITE_VERIFICATION','test_token_0123456789')
    r=client.get('/bem-vindo',headers={'Host':'spoofed.example'})
    assert 'https://synapse.example/bem-vindo' in r.text and 'spoofed' not in r.text
    assert 'content="index,follow"' in r.text
    assert 'test_token_0123456789' in r.text
    xml=client.get('/sitemap.xml').text
    assert xml.count('<loc>')==3 and '/admin' not in xml and '/api/' not in xml
    assert 'https://synapse.example/sitemap.xml' in client.get('/robots.txt').text
    home=client.get('/')
    assert 'noindex' in home.headers['x-robots-tag']
    assert 'name="google-site-verification" content="test_token_0123456789"' in home.text
    assert 'data-mode="server"' in home.text
    monkeypatch.setenv('GOOGLE_SITE_VERIFICATION','"><script>alert(1)</script>')
    assert 'google-site-verification' not in client.get('/').text
    assert 'noindex' in client.get('/api/state').headers['x-robots-tag']

def test_no_index_by_default_even_https(client,monkeypatch):
    monkeypatch.setattr(server,'PUBLIC_ORIGIN','https://synapse.example');monkeypatch.delenv('PUBLIC_INDEXING',raising=False)
    assert '<loc>' not in client.get('/sitemap.xml').text
    assert 'Sitemap:' not in client.get('/robots.txt').text

def test_presentation_escaping_and_invalid_canonical():
    page=render_page('/bem-vindo','javascript:alert(1)',announcement='<img src=x onerror=alert(1)>',support_email='bad"@example.com',indexing=True,verification='"><script>')
    assert '<img src=x' not in page and '&lt;img' in page
    assert 'rel="canonical"' not in page and 'google-site-verification' not in page
    assert public_origin('https://user:password@example.com')==''
    assert public_origin('https://example.com/?x=1')==''

def test_closed_site_landing_does_not_claim_open(client):
    close_signup();r=client.get('/bem-vindo')
    assert 'Lançamento em preparação' in r.text and 'Criar minha conta' not in r.text
    assert 'signup=1' not in r.text

def test_invites_and_growth_are_owner_only(client):
    for path in ('/api/manage/invites','/api/manage/growth'):assert client.get(path).status_code==401
    register(client)
    for path in ('/api/manage/invites','/api/manage/growth'):assert client.get(path).status_code==403
    assert client.post('/api/manage/invites',json={'label':'Grupo de teste'}).status_code==403

def test_invites_csrf_and_elevation(client):
    make_owner(client)
    assert client.post('/api/manage/invites',json={'label':'Teste'},headers={'X-CSRF-Token':'invalid'}).status_code==403
    client.post('/api/manage/lock',json={})
    assert client.get('/api/manage/invites').status_code==403

def test_invite_hashed_and_returned_only_once(client):
    make_owner(client);v=issue(client)
    assert '#convite=' in v['url'] and v['code'] in v['url']
    with server.db() as con:
        raw=json.dumps([dict(x) for x in con.execute('SELECT * FROM pilot_invites')])
        audit=json.dumps([dict(x) for x in con.execute('SELECT * FROM admin_events')])
    assert v['code'] not in raw and v['code'] not in audit
    assert v['code'] not in client.get('/api/manage/invites').text
    assert v['code'] not in client.get('/api/state').text

def test_closed_signup_requires_invite_and_stops_after_one_use(client):
    make_owner(client);v=issue(client);close_signup()
    with TestClient(server.app,headers=HEADERS) as guest:
        assert signup(guest,'noinvite').status_code==403
        assert signup(guest,'invited',v['code']).status_code==200
        assert signup(guest,'second',v['code']).status_code==403
    assert client.get('/api/manage/invites').json()['items'][0]['uses']==1

def test_invite_duplicate_registration_rolls_back_use(client):
    make_owner(client);v=issue(client);close_signup()
    with TestClient(server.app,headers=HEADERS) as guest:
        assert signup(guest,'responsavel',v['code']).status_code==409
        assert signup(guest,'freshuser',v['code']).status_code==200
    assert client.get('/api/manage/invites').json()['items'][0]['uses']==1

def test_invite_expired_or_revoked_is_refused(client):
    make_owner(client);v=issue(client);close_signup()
    assert client.post('/api/manage/invites/'+v['id']+'/revoke',json={'reason':'Encerrar convite de teste.'}).status_code==200
    with TestClient(server.app,headers=HEADERS) as guest:
        assert signup(guest,'revokeduser',v['code']).status_code==403
    v=issue(client)
    with server.db() as con:con.execute('UPDATE pilot_invites SET expires=0 WHERE id=?',(v['id'],))
    with TestClient(server.app,headers=HEADERS) as guest:assert signup(guest,'expireduser',v['code']).status_code==403

def test_maintenance_disables_invite_signup(client):
    make_owner(client);v=issue(client)
    with server.db() as con:con.execute('UPDATE site_settings SET maintenance=1')
    with TestClient(server.app,headers=HEADERS) as guest:assert signup(guest,'maintenance',v['code']).status_code==503

def test_invite_atomic_capacity(client):
    make_owner(client);v=issue(client);close_signup()
    # Each worker has its own connection; BEGIN IMMEDIATE serializes consume+insert.
    def consume(_):
        try:
            with server.db() as con:
                con.execute('BEGIN IMMEDIATE');server.consume_invite(con,v['code'])
            return True
        except server.HTTPException:return False
    with ThreadPoolExecutor(max_workers=4) as pool:assert sum(pool.map(consume,range(4)))==1

@pytest.mark.parametrize('extra',[{'days':0},{'days':31},{'max_uses':0},{'max_uses':51},{'label':'x'},{'max_uses':True}])
def test_invite_limits(client,extra):
    make_owner(client);assert client.post('/api/manage/invites',json={'label':'Grupo de teste',**extra}).status_code==422

def test_new_account_dm_defaults_following(client):
    with TestClient(server.app,headers=HEADERS) as guest:
        assert signup(guest,'saferdm').status_code==200
        assert guest.get('/api/state').json()['preferences']['dm_policy']=='following'

def test_growth_aggregate_no_member_emails(client):
    make_owner(client);v=issue(client);close_signup()
    with TestClient(server.app,headers=HEADERS) as guest:
        r=signup(guest,'memberzero',v['code']);assert r.status_code==200
        guest.headers['X-CSRF-Token']=r.json()['csrf'];post(guest)
    d=client.get('/api/manage/growth').json();assert d['counts']['members']==1
    assert d['counts']['creators']==1 and d['counts']['activation_percent']==100
    assert d['counts']['invited_signups']==1 and d['counts']['new_7d']==1
    assert 'memberzero' not in json.dumps(d) and '@example' not in json.dumps(d)

def test_health_accepts_hosting_probe_without_exposing_private_routes(client,monkeypatch):
    monkeypatch.setenv('SYNAPSE_ENV','production');monkeypatch.setattr(server,'PUBLIC_ORIGIN','https://example.test')
    assert client.get('/api/health',headers={'Host':'hosting-probe.internal'}).status_code==200
    assert client.get('/api/state',headers={'Host':'hosting-probe.internal'}).status_code==400

def test_static_export_contains_no_backend(tmp_path):
    path=export(tmp_path/'landing','https://intro.example','https://app.example')
    assert 'https://app.example/' in (path/'bem-vindo.html').read_text()
    assert 'data-mode="demo"' not in (path/'bem-vindo.html').read_text()
    assert not (path/'api').exists() and not (path/'data').exists()
    assert (path/'404.html').exists()
    with pytest.raises(ValueError):export(path,'https://intro.example','https://app.example')

def test_diagnostic_does_not_label_local_dev_as_ready(client):
    d=check(client,'http://testserver')
    assert not d['ok'] and not next(x for x in d['checks'] if x['check']=='https')['ok']
    assert next(x for x in d['checks'] if x['check']=='backend')['ok']
    assert not next(x for x in d['checks'] if x['check']=='production')['ok']

def test_diagnostic_rejects_static_demo():
    import httpx
    def handler(request):return httpx.Response(200,text='<html data-mode="demo">Um HTML sem servidor</html>')
    with httpx.Client(transport=httpx.MockTransport(handler),base_url='https://demo.example') as c:d=check(c,'https://demo.example')
    assert not d['ok'];assert not next(x for x in d['checks'] if x['check']=='backend')['ok']

def test_diagnostic_positive_is_local_configuration_not_external_validation(client,monkeypatch):
    make_owner(client)
    with server.db() as con:con.execute('DELETE FROM actors WHERE seeded=1')
    monkeypatch.setenv('SYNAPSE_ENV','production');monkeypatch.setenv('PUBLIC_INDEXING','1');monkeypatch.setenv('SECURITY_EMAIL','security@example.test')
    monkeypatch.setattr(server,'PUBLIC_ORIGIN','https://testserver');monkeypatch.setattr(server,'COOKIE_SECURE',True)
    client.cookies.clear()
    d=check(client,'https://testserver')
    assert d['ok'],d
    assert len(d['limitations'])>=4
