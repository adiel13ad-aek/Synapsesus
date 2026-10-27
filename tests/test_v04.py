"""0.4 account lifecycle, privacy, content and operator authorization tests."""
import json,re,hashlib,time
from email import policy
from email.parser import BytesParser
from urllib.parse import urlparse,parse_qs
from fastapi.testclient import TestClient
from test_api import client,register,post,create_image,HEADERS
import server

def token_for(purpose):
    messages=sorted((server.DB_PATH.parent/'outbox').glob('*.eml'),key=lambda p:p.stat().st_mtime)
    for path in reversed(messages):
        text=BytesParser(policy=policy.default).parsebytes(path.read_bytes()).get_content()
        found=re.search(r'https?://\S+',text)
        if found:
            qs=parse_qs(urlparse(found.group()).query)
            if purpose in qs:return qs[purpose][0]
    raise AssertionError('Missing development email')

def test_registration_requires_email_and_consent(client):
    data={'name':'Pessoa','handle':'pessoa','password':'test-password-2026'}
    assert client.post('/api/auth/register',json=data).status_code==422
    assert client.post('/api/auth/register',json={**data,'email':'no-at','terms_accepted':True}).status_code==422
    assert client.post('/api/auth/register',json={**data,'email':'pessoa@example.com','terms_accepted':False}).status_code==422

def test_private_email_not_public_or_in_tokens(client):
    me=register(client)
    data=client.get('/api/state').json()
    assert data['account']['email']=='criador@example.com'
    assert all('email' not in a and 'password_hash' not in a for a in data['actors'])
    assert 'email' not in data['me']
    token=token_for('verify')
    assert token not in json.dumps(data)
    with server.db() as con:
        row=con.execute('SELECT * FROM auth_tokens').fetchone()
        assert row['token_hash']==hashlib.sha256(token.encode()).hexdigest()
        assert token not in json.dumps(dict(row))
    with TestClient(server.app,headers=HEADERS) as guest:
        assert 'criador@example.com' not in guest.get('/api/state').text
        for path in ['/data/outbox/','/data/synapse.db','/.env','/tools/extensions.txt']:
            assert guest.get(path).status_code==404

def test_verify_email_single_use(client):
    register(client);token=token_for('verify')
    assert client.post('/api/auth/verify',json={'token':token}).status_code==200
    assert client.get('/api/state').json()['account']['email_verified']
    assert client.post('/api/auth/verify',json={'token':token}).status_code==400

def test_reset_single_use_revokes_sessions(client):
    register(client)
    r=client.post('/api/auth/forgot',json={'email':'criador@example.com'})
    assert r.status_code==200
    token=token_for('reset')
    assert token not in r.text
    assert client.post('/api/auth/reset',json={'token':token,'password':'new-password-2026'}).status_code==200
    assert client.get('/api/state').json()['me'] is None
    assert client.post('/api/auth/reset',json={'token':token,'password':'another-password'}).status_code==400
    assert client.post('/api/auth/login',json={'handle':'criador@example.com','password':'new-password-2026'}).status_code==200
    assert client.post('/api/auth/login',json={'handle':'criador','password':'test-password-2026'}).status_code==401

def test_forgot_response_does_not_reveal_email(client):
    register(client)
    real=client.post('/api/auth/forgot',json={'email':'criador@example.com'})
    absent=client.post('/api/auth/forgot',json={'email':'inexistente@example.com'})
    assert real.status_code==absent.status_code==200 and real.json()==absent.json()

def test_expired_tokens_rejected(client):
    register(client);token=token_for('verify')
    with server.db() as con:con.execute('UPDATE auth_tokens SET expires=?',(time.time()-1,))
    assert client.post('/api/auth/verify',json={'token':token}).status_code==400

def test_password_change_requires_current_and_revokes(client):
    register(client)
    assert client.patch('/api/account/password',json={'current_password':'wrong','password':'new-password-2026'}).status_code==401
    assert client.patch('/api/account/password',json={'current_password':'test-password-2026','password':'new-password-2026'}).status_code==200
    assert client.get('/api/state').json()['me'] is None
    with server.db() as con:assert con.execute("SELECT count(*) FROM auth_tokens WHERE purpose='reset'").fetchone()[0]==0

def test_profile_photos_interests_and_removal(client):
    register(client)
    r=client.patch('/api/profile',json={'name':'Meu perfil','bio':'Sou curioso','website':'https://example.com','color':'rose','interests':['Design','Ciência'],'avatar_data':create_image(),'cover_data':create_image()})
    assert r.status_code==200,r.text
    me=client.get('/api/state').json()['me']
    assert me['interests']==['Design','Ciência'] and me['website']=='https://example.com/'
    assert len(list(server.MEDIA_DIR.glob('*.jpg')))==2
    assert client.patch('/api/profile',json={'name':'Meu perfil','remove_avatar':True,'remove_cover':True}).status_code==200
    assert len(list(server.MEDIA_DIR.glob('*.jpg')))==0
    assert client.patch('/api/profile',json={'name':'Meu perfil','interests':['a']*9}).status_code==422
    assert client.patch('/api/profile',json={'name':'Meu perfil','website':'javascript:alert(1)'}).status_code==422

def test_preferences_private_and_validated(client):
    register(client)
    pref={'theme':'dark','accent':'mint','reduce_motion':True,'dm_policy':'following'}
    assert client.patch('/api/preferences',json=pref).status_code==200
    s=client.get('/api/state').json();assert s['preferences']==pref
    assert all('dm_policy' not in a and 'theme' not in a for a in s['actors'])
    assert client.patch('/api/preferences',json={'theme':'evil'}).status_code==422

def test_direct_message_preferences_enforced(client):
    me=register(client)
    with TestClient(server.app,headers=HEADERS) as other:
        b=register(other,'outra')
        other.patch('/api/preferences',json={'dm_policy':'off'})
        assert client.post('/api/messages/'+b['id'],json={'body':'Oi'}).status_code==403
        other.patch('/api/preferences',json={'dm_policy':'following'})
        assert client.post('/api/messages/'+b['id'],json={'body':'Oi'}).status_code==403
        other.post('/api/actors/'+me['id']+'/follow',json={})
        assert client.post('/api/messages/'+b['id'],json={'body':'Oi'}).status_code==200

def test_stories_expire_with_media_cleanup(client):
    me=register(client)
    r=client.post('/api/stories',json={'body':'Meu momento','image_data':create_image()})
    assert r.status_code==200
    sid=r.json()['id'];stories=client.get('/api/stories').json()['stories'];assert stories[0]['id']==sid
    assert len(list(server.MEDIA_DIR.glob('*.jpg')))==1
    with server.db() as con:con.execute('UPDATE stories SET expires=?',(time.time()-1,))
    assert client.get('/api/stories').json()['stories']==[]
    assert not list(server.MEDIA_DIR.glob('*.jpg'))

def test_story_deletion_ownership_and_block(client):
    a=register(client);sid=client.post('/api/stories',json={'body':'Momento'}).json()['id']
    with TestClient(server.app,headers=HEADERS) as other:
        register(other,'outra')
        assert other.request('DELETE','/api/stories/'+sid,json={}).status_code==404
        other.post('/api/actors/'+a['id']+'/block',json={})
        assert other.get('/api/stories').json()['stories']==[]
    assert client.request('DELETE','/api/stories/'+sid,json={}).status_code==200

def test_notifications_owner_only_and_mark_read(client):
    a=register(client);pid=post(client)
    with TestClient(server.app,headers=HEADERS) as other:
        b=register(other,'outra')
        other.post('/api/posts/'+pid+'/like',json={})
        other.post('/api/posts/'+pid+'/comments',json={'body':'Comentário'})
        other.post('/api/actors/'+a['id']+'/follow',json={})
        other.post('/api/messages/'+a['id'],json={'body':'Oi'})
        assert other.get('/api/notifications').json()['notifications']==[]
    notifications=client.get('/api/notifications').json()['notifications']
    assert {n['kind'] for n in notifications}=={'like','comment','follow','message'}
    client.post('/api/notifications/read',json={})
    assert all(n['seen'] for n in client.get('/api/notifications').json()['notifications'])

def test_edit_posts_and_comment_deletion_authorization(client):
    a=register(client);pid=post(client)
    with TestClient(server.app,headers=HEADERS) as other:
        register(other,'outra')
        assert other.patch('/api/posts/'+pid,json={'body':'Roubar post'}).status_code==403
        cid=other.post('/api/posts/'+pid+'/comments',json={'body':'Meu comentário'}).json()['id']
        with TestClient(server.app,headers=HEADERS) as third:
            register(third,'terceira')
            assert third.request('DELETE','/api/comments/'+cid,json={}).status_code==403
        assert client.request('DELETE','/api/comments/'+cid,json={}).status_code==200
    assert client.patch('/api/posts/'+pid,json={'body':'Editado'}).status_code==200

def test_moderation_requires_operator_and_removes_post(client,monkeypatch):
    a=register(client);pid=post(client,image_data=create_image())
    with TestClient(server.app,headers=HEADERS) as other:
        register(other,'operador')
        other.post('/api/posts/'+pid+'/report',json={'reason':'Teste de denúncia'})
        assert other.get('/api/admin/reports').status_code==403
        monkeypatch.setattr(server,'ADMIN_HANDLES',{'operador'})
        reports=other.get('/api/admin/reports').json()['reports']
        assert reports[0]['content']=='Minha descoberta sobre tecnologia.'
        assert other.post('/api/admin/reports/'+reports[0]['id'],json={'action':'remove'}).status_code==200
        assert not any(p['id']==pid for p in client.get('/api/state').json()['posts'])
        assert not list(server.MEDIA_DIR.glob('*.jpg'))

def test_report_message_is_private(client):
    a=register(client)
    with TestClient(server.app,headers=HEADERS) as other:
        b=register(other,'outra');client.post('/api/messages/'+b['id'],json={'body':'Mensagem privada'})
        mid=client.get('/api/messages/'+b['id']).json()['messages'][0]['id']
        with TestClient(server.app,headers=HEADERS) as third:
            register(third,'terceira')
            assert third.post('/api/reports',json={'kind':'message','target_id':mid,'reason':'Tentativa indevida'}).status_code==404
        assert other.post('/api/reports',json={'kind':'message','target_id':mid,'reason':'Denúncia autorizada'}).status_code==200

def test_account_delete_removes_new_records_and_images(client):
    a=register(client)
    client.patch('/api/profile',json={'name':'Pessoa','avatar_data':create_image(),'cover_data':create_image()})
    client.post('/api/stories',json={'body':'Story','image_data':create_image()})
    assert len(list(server.MEDIA_DIR.glob('*.jpg')))==3
    assert client.request('DELETE','/api/account',json={'password':'test-password-2026'}).status_code==200
    assert not list(server.MEDIA_DIR.glob('*.jpg'))
    with server.db() as con:
        for table in ['auth_tokens','stories','notifications']:
            assert con.execute('SELECT count(*) FROM '+table).fetchone()[0]==0

def test_admin_suspension_revokes_login_and_hides_posts(client,monkeypatch):
    a=register(client);pid=post(client)
    with TestClient(server.app,headers=HEADERS) as operator:
        register(operator,'operador');monkeypatch.setattr(server,'ADMIN_HANDLES',{'operador'})
        operator.post('/api/reports',json={'kind':'profile','target_id':a['id'],'reason':'Teste de suspensão'})
        rid=operator.get('/api/admin/reports').json()['reports'][0]['id']
        assert operator.post('/api/admin/reports/'+rid,json={'action':'remove'}).status_code==200
    assert client.get('/api/state').json()['me'] is None
    assert not any(p['id']==pid for p in client.get('/api/state').json()['posts'])
    assert client.post('/api/auth/login',json={'handle':'criador','password':'test-password-2026'}).status_code==401
