"""0.9 safety regression tests. Cryptographic receipts are signed by a synthetic key;
these tests do not validate any real age-assurance provider or legal parenthood.
"""
import base64
import hashlib
import json
import os
import re
import time
from urllib.parse import urlsplit,parse_qs
from email import policy
from email.parser import BytesParser
import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
from test_api import client,register,post,create_image,HEADERS
from test_v07 import make_owner,as_prod,enroll
import server


def signal(me,band='adult'):
    with server.db() as con:con.execute('UPDATE actors SET email_verified=1,age_band=?,age_verified_until=? WHERE id=?',(band,time.time()+86400,me['id']))

def verifier(monkeypatch):
    private=Ed25519PrivateKey.generate()
    public=private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    monkeypatch.setenv('AGE_PUBLIC_KEY',base64.urlsafe_b64encode(public).decode().rstrip('='))
    monkeypatch.setenv('AGE_PROVIDER_ID','test-synthetic-verifier')
    monkeypatch.setenv('AGE_PROVIDER_URL','https://verifier.example.test/start')
    monkeypatch.setattr(server,'PUBLIC_ORIGIN','https://testserver')
    return private

def receipt(key,challenge,**changes):
    value={'v':1,'iss':'test-synthetic-verifier','aud':server.PUBLIC_ORIGIN,'challenge':challenge,'band':'adult','iat':int(time.time()),'exp':int(time.time())+180}
    value.update(changes)
    body=base64.urlsafe_b64encode(json.dumps(value,separators=(',',':')).encode()).decode().rstrip('=')
    signature=base64.urlsafe_b64encode(key.sign(body.encode())).decode().rstrip('=')
    return body+'.'+signature

def start_age(c):
    r=c.post('/api/account/age/start',json={});assert r.status_code==200,r.text
    return parse_qs(urlsplit(r.json()['url']).query)['challenge'][0]


def test_private_profile_hides_posts_media_stories_everywhere(client):
    me=register(client);pid=post(client,image_data=create_image())
    story=client.post('/api/stories',json={'body':'Reservado','image_data':create_image()});assert story.status_code==200
    own=client.get('/api/state').json();image=next(p['image_path'] for p in own['posts'] if p['id']==pid)
    assert client.patch('/api/account/privacy',json={'private':True}).status_code==200
    with TestClient(server.app,headers=HEADERS) as other:
        assert not any(p['id']==pid for p in other.get('/api/state').json()['posts'])
        assert not any(p['id']==pid for p in other.get('/api/feed').json()['posts'])
        assert not any(st['author_id']==me['id'] for st in other.get('/api/stories').json()['stories'])
        assert other.get(image).status_code==404
        guest=register(other,'convidado')
        assert other.post('/api/posts/'+pid+'/like',json={}).status_code==404
        r=other.post('/api/actors/'+me['id']+'/follow',json={});assert r.json()['pending'] and not r.json()['active']
        assert other.get(image).status_code==404
        pending=client.get('/api/account/security').json()['follow_requests'];assert pending[0]['id']==guest['id']
        assert client.post('/api/account/follow-requests/'+guest['id'],json={'approve':True}).status_code==200
        assert other.get(image).status_code==200
        assert any(p['id']==pid for p in other.get('/api/feed').json()['posts'])
        assert client.request('DELETE','/api/account/followers/'+guest['id'],json={}).status_code==200
        assert other.get(image).status_code==404


def test_privacy_request_cannot_be_approved_by_other_account(client):
    owner=register(client);client.patch('/api/account/privacy',json={'private':True})
    with TestClient(server.app,headers=HEADERS) as other:
        guest=register(other,'seguindo');other.post('/api/actors/'+owner['id']+'/follow',json={})
        assert other.post('/api/account/follow-requests/'+guest['id'],json={'approve':True}).status_code==404
        assert other.post('/api/actors/'+owner['id']+'/follow',json={}).json()['status']=='none'
        assert client.get('/api/account/security').json()['follow_requests']==[]
        other.post('/api/actors/'+owner['id']+'/follow',json={})
        assert client.post('/api/actors/'+guest['id']+'/block',json={}).status_code==200
        assert client.get('/api/account/security').json()['follow_requests']==[]


def test_sessions_opaque_owned_and_revocable(client):
    register(client)
    with TestClient(server.app,headers=HEADERS) as other:
        login=other.post('/api/auth/login',json={'handle':'criador','password':'test-password-2026'})
        other.headers['X-CSRF-Token']=login.json()['csrf']
        sessions=client.get('/api/account/sessions');assert len(sessions.json()['items'])==2
        assert 'token_hash' not in sessions.text and 'csrf' not in sessions.text
        current=next(x for x in sessions.json()['items'] if x['current'])
        assert client.request('DELETE','/api/account/sessions/'+current['id'],json={}).status_code==409
        assert client.post('/api/account/sessions/revoke-others',json={}).json()['revoked']==1
        assert other.get('/api/account/security').status_code==401
        assert client.get('/api/account/security').status_code==200


def test_accept_latest_terms_required_for_protected_writes(client,monkeypatch):
    me=register(client);signal(me);monkeypatch.setenv('AGE_ENFORCED','1')
    with server.db() as con:con.execute("INSERT INTO site_policies VALUES('terms',?,?,?)",('Termos alterados para teste, não para publicação.',me['id'],server.now()))
    assert client.post('/api/posts',json={'body':'Não deve passar sem aceite'}).status_code==409
    d=client.get('/api/account/security').json();assert not d['terms_accepted']
    assert client.post('/api/account/terms',json={'version':'old','accepted':True}).status_code==409
    assert client.post('/api/account/terms',json={'version':d['terms_current'],'accepted':True}).status_code==200
    assert client.post('/api/posts',json={'body':'Agora com aceite atual'}).status_code==200


def test_age_unconfigured_denies_and_no_self_attestation(client,monkeypatch):
    me=register(client);monkeypatch.setenv('AGE_ENFORCED','1')
    assert client.post('/api/posts',json={'body':'Não confirmado'}).status_code==403
    with server.db() as con:con.execute('UPDATE actors SET email_verified=1 WHERE id=?',(me['id'],))
    assert client.post('/api/account/age/start',json={}).status_code==503
    assert client.post('/api/account/age/confirm',json={'age':18}).status_code==422
    assert client.get('/api/account/security').json()['social_status']=='age_required'


def test_signed_age_receipt_is_single_use_and_contains_no_document(client,monkeypatch):
    me=register(client);signal(me);key=verifier(monkeypatch);challenge=start_age(client)
    value=receipt(key,challenge)
    r=client.post('/api/account/age/confirm',json={'receipt':value});assert r.status_code==200,r.text
    assert client.post('/api/account/age/confirm',json={'receipt':value}).status_code==400
    assert client.get('/api/account/security').json()['age_band']=='adult'
    with server.db() as con:
        assert not con.execute('SELECT 1 FROM age_challenges').fetchone()
        serialized=json.dumps(dict(con.execute('SELECT * FROM actors WHERE id=?',(me['id'],)).fetchone()))
        assert value not in serialized and challenge not in serialized
    assert 'age_band' not in client.get('/api/state').json()['me']


@pytest.mark.parametrize('mutation',[{'aud':'https://other.test'},{'iss':'impostor'},{'exp':1},{'iat':int(time.time())+900},{'exp':int(time.time())+900},{'band':'I_am_18'},{'document_number':'never-store-this'}])
def test_age_invalid_receipts_rejected(client,monkeypatch,mutation):
    me=register(client);signal(me);key=verifier(monkeypatch);challenge=start_age(client)
    assert client.post('/api/account/age/confirm',json={'receipt':receipt(key,challenge,**mutation)}).status_code==400


def test_age_signature_and_account_binding(client,monkeypatch):
    me=register(client);signal(me);key=verifier(monkeypatch);challenge=start_age(client)
    badkey=Ed25519PrivateKey.generate()
    assert client.post('/api/account/age/confirm',json={'receipt':receipt(badkey,challenge)}).status_code==400
    with TestClient(server.app,headers=HEADERS) as other:
        other_me=register(other,'otherproof');signal(other_me)
        assert other.post('/api/account/age/confirm',json={'receipt':receipt(key,challenge)}).status_code==400
    assert client.post('/api/account/age/confirm',json={'receipt':receipt(key,challenge)}).status_code==200


def test_minor_signal_enforces_privacy_and_disables_direct_messages(client,monkeypatch):
    me=register(client);signal(me);key=verifier(monkeypatch)
    r=client.post('/api/account/age/confirm',json={'receipt':receipt(key,start_age(client),band='13_15')});assert r.status_code==200
    assert client.get('/api/state').json()['preferences']['dm_policy']=='off'
    assert client.get('/api/account/security').json()['private']
    assert client.patch('/api/account/privacy',json={'private':False}).status_code==403
    assert client.patch('/api/preferences',json={'dm_policy':'everyone'}).status_code==403
    assert client.get('/api/search',params={'q':'tema','scope':'wiki'}).status_code==403
    monkeypatch.setenv('AGE_ENFORCED','1')
    assert client.get('/api/account/security').json()['social_status']=='minors_not_enabled'
    assert client.post('/api/posts',json={'body':'Bloqueado'}).status_code==403


def guardian_token():
    for path in sorted((server.DB_PATH.parent/'outbox').glob('*.eml'),key=lambda x:x.stat().st_mtime,reverse=True):
        text=BytesParser(policy=policy.default).parsebytes(path.read_bytes()).get_content()
        match=re.search(r'#guardian=([A-Za-z0-9_-]+)',text)
        if match:return match.group(1)
    raise AssertionError('Guardian token missing')


def test_guardian_link_pause_unlink_and_no_message_access(client,monkeypatch):
    child=register(client,'adolescente');signal(child,'13_15')
    monkeypatch.setenv('AGE_ENFORCED','1');monkeypatch.setenv('MINOR_ACCOUNTS_ENABLED','1')
    assert client.post('/api/posts',json={'body':'Sem responsável'}).status_code==403
    assert client.post('/api/account/guardian/invite',json={'email':'responsavel@example.com'}).status_code==200
    token=guardian_token()
    with TestClient(server.app,headers=HEADERS) as adult:
        guardian=register(adult,'responsavel');signal(guardian)
        r=adult.post('/api/account/guardian/accept',json={'token':token,'password':'test-password-2026','responsible':True});assert r.status_code==200,r.text
        assert adult.post('/api/account/guardian/accept',json={'token':token,'password':'test-password-2026','responsible':True}).status_code==400
        assert client.get('/api/account/security').json()['social_status']=='ready'
        assert client.post('/api/posts',json={'body':'Com supervisão autorizada'}).status_code==200
        assert client.get('/api/messages/'+guardian['id']).status_code==403
        assert adult.patch('/api/account/guardian/'+child['id'],json={'paused':True}).status_code==200
        assert client.post('/api/posts',json={'body':'Agora pausado'}).status_code==403
        assert client.get('/api/account/support').status_code==200
        assert adult.patch('/api/account/guardian/'+child['id'],json={'paused':False}).status_code==200
        assert client.request('DELETE','/api/account/guardian',json={}).status_code==200
        assert client.get('/api/account/security').json()['social_status']=='guardian_required'
        assert adult.patch('/api/account/guardian/'+child['id'],json={'paused':True}).status_code==404


def test_ticket_privacy_and_operator_reply(client):
    owner=make_owner(client)
    with TestClient(server.app,headers=HEADERS) as other:
        me=register(other,'pessoasuporte')
        r=other.post('/api/account/support',json={'kind':'privacy','subject':'Dúvida de privacidade','body':'Gostaria de entender como os dados são removidos da conta.'})
        assert r.status_code==200;tid=r.json()['id']
        assert other.get('/api/manage/support').status_code==403
        assert client.get('/api/account/support').json()['items']==[]
        assert client.post('/api/manage/support/'+tid,json={'reply':'Os controles de dados ficam em Configurações.','status':'closed'}).status_code==200
        assert other.get('/api/account/support').json()['items'][0]['status']=='closed'
        assert client.get('/api/manage/support').json()['items'][0]['owner_id']==me['id']


def test_turnstile_server_checks_hostname_action_and_fails_closed(client,monkeypatch):
    monkeypatch.setenv('TURNSTILE_SITE_KEY','site-test-key');monkeypatch.setenv('TURNSTILE_SECRET_KEY','private-test-key')
    monkeypatch.setattr(server,'PUBLIC_ORIGIN','https://testserver')
    original=httpx.Client
    def attempt(payload):
        monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload)),**kw))
        return client.post('/api/auth/register',json={'name':'Teste','handle':'captchauser','email':'captcha@example.test','password':'test-password-2026','terms_accepted':True,'turnstile_token':'synthetic'})
    assert attempt({'success':False}).status_code==403
    assert attempt({'success':True,'hostname':'evil.test','action':'signup'}).status_code==403
    assert attempt({'success':True,'hostname':'testserver','action':'login'}).status_code==403
    assert attempt({'success':True,'hostname':'testserver','action':'signup'}).status_code==200
    assert 'private-test-key' not in client.get('/api/auth/options').text


def test_sensitive_pages_and_errors_have_security_headers(client):
    for path in ['/conta/seguranca','/operacao']:
        r=client.get(path);assert r.status_code==200
        assert 'noindex' in r.headers['x-robots-tag'] and 'frame-ancestors' in r.headers['content-security-policy']
    r=client.post('/api/auth/login',json={},headers={'X-Synapse-Client':'bad'})
    assert r.status_code==403 and r.headers['cache-control']=='no-store' and r.headers.get('x-request-id')


def test_production_guest_does_not_receive_user_content(client,monkeypatch):
    register(client);post(client)
    monkeypatch.setenv('SYNAPSE_ENV','production');monkeypatch.setattr(server,'PUBLIC_ORIGIN','https://testserver')
    # No nested lifespan under incomplete production configuration.
    client.cookies.clear()
    assert client.get('/api/state').json()['posts']==[]
    assert client.get('/api/state').json()['actors']==[]
    assert client.get('/api/feed').json()['posts']==[]


def test_integration_evidence_invalidated_after_configuration_change(client,monkeypatch):
    key=verifier(monkeypatch)
    server.record_integration_check('age_verifier','Synthetic local test evidence')
    assert next(x for x in server.launch_checks() if x['id']=='age_verifier_validated')['ok']
    monkeypatch.setenv('AGE_PROVIDER_ID','changed-provider')
    assert not next(x for x in server.launch_checks() if x['id']=='age_verifier_validated')['ok']


def test_incomplete_production_never_advertises_open_registration(client,monkeypatch):
    register(client)
    monkeypatch.setenv('SYNAPSE_ENV','production');monkeypatch.setattr(server,'PUBLIC_ORIGIN','https://testserver')
    assert not client.get('/api/site').json()['registration_open']
    assert not client.get('/api/status').json()['registration_open']
    assert 'Lançamento em preparação' in client.get('/bem-vindo').text
    assert 'Cadastros abertos' not in client.get('/bem-vindo').text


def test_hidden_post_still_deletable_by_its_owner(client):
    make_owner(client);pid=post(client,image_data=create_image())
    assert client.post('/api/manage/posts/'+pid,json={'hidden':True,'reason':'Revisão de conteúdo durante teste.'}).status_code==200
    assert client.request('DELETE','/api/posts/'+pid,json={}).status_code==200
    with server.db() as con:assert not con.execute('SELECT 1 FROM posts WHERE id=?',(pid,)).fetchone()


def test_old_policy_review_does_not_cover_new_features(client):
    owner=make_owner(client)
    with server.db() as con:
        for kind in ('terms','privacy','safety'):
            con.execute('INSERT INTO site_policies VALUES(?,?,?,?)',(kind,'Texto legado de uma versão anterior.',owner['id'],server.now()))
    assert not next(x for x in server.launch_checks() if x['id']=='policy_review_current')['ok']
    for kind in ('terms','privacy','safety'):
        r=client.put('/api/manage/policies/'+kind,json={'body':'Texto sintético de revisão técnica, não publicar. '*20,'reason':'Revisão sintética das funcionalidades novas.','reviewed':True});assert r.status_code==200
    assert next(x for x in server.launch_checks() if x['id']=='policy_review_current')['ok']
