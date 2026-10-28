"""Admin authorization, TOTP, launch controls and public isolation.
Only temporary local accounts. No external integrations or real e-mails in this suite.
"""
import hashlib
import json
import time
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import server
from administration import totp
from test_api import client, register, post, HEADERS, create_image

PASSWORD='test-password-2026'

def make_owner(c):
    me=register(c,'responsavel')
    with server.db() as con:
        con.execute('INSERT INTO operators VALUES(?,?)',(me['id'],server.now()))
        con.execute('UPDATE actors SET email_verified=1 WHERE id=?',(me['id'],))
    r=c.post('/api/manage/unlock',json={'password':PASSWORD})
    assert r.status_code==200,r.text
    return me

def enroll(c):
    result=c.post('/api/manage/security/enroll',json={'password':PASSWORD})
    assert result.status_code==200,result.text
    secret=result.json()['secret'];code=totp(secret,int(time.time()//30))
    r=c.post('/api/manage/security/confirm',json={'code':code})
    assert r.status_code==200,r.text
    return secret,code,r.json()['recovery_codes']

def as_prod(monkeypatch):
    monkeypatch.setenv('SYNAPSE_ENV','production')
    monkeypatch.setattr(server,'PUBLIC_ORIGIN','https://testserver')
    monkeypatch.setenv('ADMIN_ENCRYPTION_KEY',Fernet.generate_key().decode())

def test_totp_known_vector():
    # RFC 6238 SHA-1 test, first 30s counter. 94287082 modulo one million.
    secret='GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
    assert totp(secret,1)=='287082'

@pytest.mark.parametrize('path',['session','overview','users','posts','reports','settings','audit','launch','policies','health'])
def test_public_and_member_denied_admin(client,path):
    assert client.get('/api/manage/'+path).status_code==401
    register(client)
    assert client.get('/api/manage/'+path).status_code==403

def test_admin_shell_is_public_but_not_data(client):
    r=client.get('/admin')
    assert r.status_code==200 and 'admin.js' in r.text
    assert r.headers['cache-control']=='no-store'
    assert 'noindex' in r.headers['x-robots-tag']
    assert 'password_hash' not in r.text

def test_unlock_password_csrf_and_expiry(client):
    me=make_owner(client)
    assert client.get('/api/manage/overview').status_code==200
    assert client.post('/api/manage/lock',json={}).status_code==200
    assert client.get('/api/manage/users').status_code==403
    assert client.post('/api/manage/unlock',json={'password':'wrong'}).status_code==401
    assert client.post('/api/manage/unlock',json={'password':PASSWORD},headers={'X-CSRF-Token':'bad'}).status_code==403
    assert client.post('/api/manage/unlock',json={'password':PASSWORD}).status_code==200
    with server.db() as con:con.execute('UPDATE admin_grants SET expires=0')
    assert client.get('/api/manage/audit').status_code==403

def test_mfa_encrypted_replay_and_recovery_once(client):
    me=make_owner(client)
    secret,code,codes=enroll(client)
    assert len(codes)==8 and len(set(codes))==8
    with server.db() as con:
        row=dict(con.execute('SELECT * FROM operator_security WHERE user_id=?',(me['id'],)).fetchone())
    assert secret not in row['secret'] and code not in row['secret']
    assert codes[0] not in row['recovery_hashes'] and row['enabled']
    state=client.get('/api/state').text
    for private in (secret,codes[0],row['secret'],PASSWORD):assert private not in state
    assert client.post('/api/manage/lock',json={}).status_code==200
    # Enrollment already consumed the code.
    assert client.post('/api/manage/unlock',json={'password':PASSWORD,'code':code}).status_code==401
    assert client.post('/api/manage/unlock',json={'password':PASSWORD,'code':codes[0]}).status_code==200
    client.post('/api/manage/lock',json={})
    assert client.post('/api/manage/unlock',json={'password':PASSWORD,'code':codes[0]}).status_code==401

def test_mfa_cannot_be_reenrolled_over_existing_secret(client):
    make_owner(client);enroll(client)
    assert client.post('/api/manage/security/enroll',json={'password':PASSWORD}).status_code==409

def test_production_mfa_required_for_new_and_legacy_panels(client,monkeypatch):
    make_owner(client)
    as_prod(monkeypatch)
    assert client.get('/api/manage/overview').status_code==403
    assert client.get('/api/admin/reports').status_code==403
    assert client.get('/api/operator/readiness').status_code==403
    assert client.post('/api/manage/unlock',json={'password':PASSWORD}).status_code==403
    # Enroll using the actual production encryption key, then read protected endpoints.
    enroll(client)
    assert client.get('/api/manage/overview').status_code==200
    assert client.get('/api/admin/reports').status_code==200

def test_prod_host_and_origin_checks(client,monkeypatch):
    make_owner(client);as_prod(monkeypatch)
    assert client.get('/api/site',headers={'Host':'evil.invalid'}).status_code==400
    assert client.post('/api/manage/lock',json={},headers={'Origin':'http://testserver'}).status_code==403
    assert client.post('/api/manage/lock',json={},headers={'Origin':'https://testserver'}).status_code==200

def test_suspend_revokes_sessions_and_restore(client):
    make_owner(client)
    with TestClient(server.app,headers=HEADERS) as other:
        u=register(other,'pessoa');pid=post(other)
        assert other.post('/api/posts/'+pid+'/comments',json={'body':'Meu comentário'}).status_code==200
        r=client.post('/api/manage/users/'+u['id']+'/actions',json={'action':'suspend','reason':'Violação verificada das regras.'})
        assert r.status_code==200,r.text
        assert other.get('/api/state').json()['me'] is None
        assert client.get('/api/feed').json()['posts']==[p for p in client.get('/api/feed').json()['posts'] if p['id']!=pid]
        assert other.post('/api/auth/login',json={'handle':'pessoa','password':PASSWORD}).status_code==401
        assert client.post('/api/manage/users/'+u['id']+'/actions',json={'action':'reactivate','reason':'Recurso analisado e aceito.'}).status_code==200
        assert other.post('/api/auth/login',json={'handle':'pessoa','password':PASSWORD}).status_code==200
    events=client.get('/api/manage/audit').json()['items']
    assert any(e['action']=='user_suspend' for e in events)

def test_owner_self_protected_and_last_owner_deletion(client):
    me=make_owner(client)
    assert client.post('/api/manage/users/'+me['id']+'/actions',json={'action':'suspend','reason':'Teste inválido de suspensão.'}).status_code==409
    assert client.request('DELETE','/api/account',json={'password':PASSWORD}).status_code==409
    assert client.get('/api/state').json()['me']['id']==me['id']

def test_moderator_least_privilege(client):
    make_owner(client)
    with TestClient(server.app,headers=HEADERS) as mod:
        u=register(mod,'moderador')
        r=client.post('/api/manage/users/'+u['id']+'/role',json={'role':'moderator','reason':'Autorizar integrante da moderação.'})
        assert r.status_code==409 # must verify email first
        with server.db() as con:con.execute('UPDATE actors SET email_verified=1 WHERE id=?',(u['id'],))
        assert client.post('/api/manage/users/'+u['id']+'/role',json={'role':'moderator','reason':'Autorizar integrante verificado.'}).status_code==200
        assert mod.post('/api/manage/unlock',json={'password':PASSWORD}).status_code==200
        for path in ('overview','users','posts','reports'):assert mod.get('/api/manage/'+path).status_code==200
        for path in ('settings','audit','launch','policies','health'):assert mod.get('/api/manage/'+path).status_code==403
        assert 'email' not in mod.get('/api/manage/users').json()['items'][0]
        owner=client.get('/api/state').json()['me']
        assert mod.post('/api/manage/users/'+owner['id']+'/actions',json={'action':'suspend','reason':'Não permitido pela permissão.'}).status_code==409
        assert client.post('/api/manage/users/'+u['id']+'/role',json={'role':'member','reason':'Permissão revogada pelo responsável.'}).status_code==200
        assert mod.get('/api/manage/overview').status_code==403

def test_hidden_post_and_media_inaccessible_then_restore(client):
    make_owner(client)
    pid=post(client,image_data=create_image())
    media=next(p for p in client.get('/api/state').json()['posts'] if p['id']==pid)['image_path']
    assert client.get(media).status_code==200
    r=client.post('/api/manage/posts/'+pid,json={'hidden':True,'reason':'Conteúdo em revisão temporária.'})
    assert r.status_code==200 and client.get(media).status_code==404
    assert all(p['id']!=pid for p in client.get('/api/state').json()['posts'])
    assert client.post('/api/manage/posts/'+pid,json={'hidden':False,'reason':'Publicação revisada e aprovada.'}).status_code==200
    assert client.get(media).status_code==200

def test_private_messages_visible_only_when_reported(client):
    admin=make_owner(client)
    with TestClient(server.app,headers=HEADERS) as other:
        u=register(other,'pessoa')
        secret='UMA MENSAGEM PRIVADA NAO DENUNCIADA'
        r=other.post('/api/messages/'+admin['id'],json={'body':secret});assert r.status_code==200
        reports=client.get('/api/manage/reports').json()
        assert secret not in json.dumps(reports)
        msgs=client.get('/api/messages/'+u['id']).json()['messages']
        mid=msgs[0]['id']
        assert client.post('/api/reports',json={'kind':'message','target_id':mid,'reason':'Revisar esta mensagem específica.'}).status_code==200
        reports=client.get('/api/manage/reports').json()
        assert secret in reports['items'][0]['content']
        rid=reports['items'][0]['id']
        assert client.post('/api/manage/reports/'+rid,json={'action':'remove','reason':'Revisado de acordo com as regras.'}).status_code==200
        assert client.post('/api/manage/reports/'+rid,json={'action':'remove','reason':'Não repetir uma decisão concluída.'}).status_code==409

def test_registration_toggle_and_public_notice(client):
    make_owner(client)
    body={'registration_open':False,'maintenance':False,'uploads_enabled':True,'announcement':'Abertura em preparação.','reason':'Fechar inscrições durante a preparação.'}
    assert client.patch('/api/manage/settings',json=body).status_code==200
    assert not client.get('/api/site').json()['registration_open']
    assert 'Abertura em preparação.' in client.get('/api/state').text
    with TestClient(server.app,headers=HEADERS) as other:
        r=other.post('/api/auth/register',json={'name':'Teste','handle':'novapessoa','email':'nova@example.com','password':PASSWORD,'terms_accepted':True})
        assert r.status_code==403
    assert client.post('/api/auth/login',json={'handle':'responsavel','password':PASSWORD}).status_code==200

def test_maintenance_and_upload_controls(client):
    make_owner(client)
    data={'registration_open':True,'maintenance':False,'uploads_enabled':False,'announcement':'','reason':'Pausar arquivos para manutenção.'}
    assert client.patch('/api/manage/settings',json=data).status_code==200
    assert client.post('/api/posts',json={'body':'foto','image_data':create_image()}).status_code==503
    posted=client.post('/api/posts',json={'body':'texto permitido'})
    assert posted.status_code==200
    own_post=posted.json()['id']
    data['maintenance']=True
    assert client.patch('/api/manage/settings',json=data).status_code==200
    assert client.post('/api/posts',json={'body':'pausado'}).status_code==503
    assert client.get('/api/feed').status_code==200
    assert client.get('/api/account/export').status_code==200
    assert client.post('/api/reports',json={'kind':'profile','target_id':'lia','reason':'Reporte durante manutenção.'}).status_code==200
    assert client.post('/api/posts/'+own_post+'/report',json={'reason':'Reporte de post durante manutenção.'}).status_code==200

def test_policy_content_escaped_and_nonadmin_cannot_edit(client):
    make_owner(client)
    text='<script>alert("no")</script>\n\n'+'Documento revisado de teste. '*20
    r=client.put('/api/manage/policies/privacy',json={'body':text,'reason':'Publicar revisão da política.','reviewed':True})
    assert r.status_code==200
    page=client.get('/privacy.html')
    assert '&lt;script&gt;' in page.text and '<script>alert' not in page.text
    assert 'Rascunho para beta privado' not in page.text
    assert client.put('/api/manage/policies/terms',json={'body':text,'reason':'Versão de termos para testar o aceite.','reviewed':True}).status_code==200
    with TestClient(server.app,headers=HEADERS) as other:
        user=register(other,'outro')
        with server.db() as con:
            version=con.execute('SELECT terms_version FROM actors WHERE id=?',(user['id'],)).fetchone()[0]
            assert version=='terms-sha256:'+hashlib.sha256(text.strip().encode()).hexdigest()
        assert other.put('/api/manage/policies/privacy',json={'body':text,'reason':'Acesso indevido não permitido.','reviewed':True}).status_code==403

def test_launch_gate_not_automatically_ready(client):
    make_owner(client)
    data=client.get('/api/manage/launch').json()
    assert not data['can_open']
    assert not next(c for c in data['checks'] if c['id']=='production_mode')['ok']
    assert not next(c for c in data['checks'] if c['id']=='public_policies')['ok']
    assert client.post('/api/manage/launch/email_test',json={'note':'Confirmação fictícia para teste automatizado.','confirmed':True}).status_code==200
    updated=client.get('/api/manage/launch').json()
    check=next(c for c in updated['checks'] if c['id']=='email_test')
    assert check['ok'] and check['kind']=='operator_attestation'
    assert not updated['can_open']

def test_production_open_blocked_until_requirements(client,monkeypatch):
    make_owner(client);as_prod(monkeypatch);enroll(client)
    body={'registration_open':True,'maintenance':False,'uploads_enabled':True,'announcement':'','reason':'Tentativa de abertura incompleta.'}
    assert client.patch('/api/manage/settings',json=body).status_code==409
    body['registration_open']=False
    assert client.patch('/api/manage/settings',json=body).status_code==200

def test_remove_examples_preserves_real_users(client):
    owner=make_owner(client);pid=post(client)
    result=client.post('/api/manage/remove-examples',json={'reason':'Limpar somente dados demonstrativos.'})
    assert result.status_code==200 and result.json()['removed_profiles']==3
    state=client.get('/api/state').json()
    assert all(not u['seeded'] for u in state['actors'])
    assert any(p['id']==pid for p in state['posts']) and state['me']['id']==owner['id']

def test_admin_role_never_assigned_by_public_profile(client):
    register(client)
    assert client.patch('/api/profile',json={'name':'Teste','role':'owner'}).status_code==422
    assert client.get('/api/manage/overview').status_code==403

def test_durable_rate_limits_survive_memory_reset(client,monkeypatch):
    as_prod(monkeypatch)
    server.rate_limit('sensitive-test',2,60)
    server.rate_limit('sensitive-test',2,60)
    server._rates.clear()
    with pytest.raises(server.HTTPException) as exc:server.rate_limit('sensitive-test',2,60)
    assert exc.value.status_code==429
    with server.db() as con:
        raw=str([dict(r) for r in con.execute('SELECT * FROM durable_rates')])
        assert 'sensitive-test' not in raw

def test_pagination_bounds_and_search_is_literal(client):
    make_owner(client)
    assert client.get('/api/manage/users?q=%25').json()['total']==0
    assert client.get('/api/manage/users?page=0').status_code==422
    assert client.get('/api/manage/posts?status=invalid').status_code==422

def test_logout_revokes_admin_grant(client):
    make_owner(client)
    assert client.post('/api/auth/logout',json={}).status_code==200
    assert client.get('/api/manage/overview').status_code==401
    with server.db() as con:assert not con.execute('SELECT 1 FROM admin_grants').fetchone()

def test_streamed_json_limit_without_content_length(client):
    body=(b'x'*1000000 for _ in range(10))
    r=client.post('/api/auth/login',content=body,headers={'Content-Type':'application/json','X-Synapse-Client':'web-v07'})
    assert r.status_code==413


def test_legacy_attestations_do_not_bypass_v09_requirements(client,monkeypatch):
    make_owner(client);as_prod(monkeypatch);enroll(client)
    monkeypatch.setattr(server,'SEED_DEMO_DATA',False)
    monkeypatch.setattr(server,'MAIL_MODE','smtp')
    for key,value in {'SMTP_HOST':'smtp.example.test','SMTP_FROM':'support@example.test','SMTP_USER':'test-only','SMTP_PASSWORD':'test-only','OPERATOR_NAME':'Operador de teste','SUPPORT_EMAIL':'support@example.test','CHILD_SAFETY_EMAIL':'safety@example.test'}.items():monkeypatch.setenv(key,value)
    assert client.post('/api/manage/remove-examples',json={'reason':'Remover exemplos em teste local.'}).status_code==200
    for kind in ('terms','privacy','safety'):
        assert client.put('/api/manage/policies/'+kind,json={'body':'Documento fictício de teste automatizado. '*20,'reason':'Texto para teste, não para publicação real.','reviewed':True}).status_code==200
    for check in ('email_test','backup_restore','moderation','browser_test','audience_review'):
        assert client.post('/api/manage/launch/'+check,json={'note':'Declaração simulada no teste, não executada externamente.','confirmed':True}).status_code==200
    ready=client.get('/api/manage/launch').json()
    assert not ready['can_open'],ready
    assert not next(c for c in ready['checks'] if c['id']=='age_verifier_configured')['ok']
    body={'registration_open':True,'maintenance':False,'uploads_enabled':True,'announcement':'','reason':'Abertura controlada somente no teste.'}
    assert client.patch('/api/manage/settings',json=body).status_code==409
    monkeypatch.setattr(server,'PUBLIC_ORIGIN','https://another.example.test')
    assert not all(c['ok'] for c in server.launch_checks()) # attestations do not carry to a new origin
