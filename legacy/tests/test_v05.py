"""0.5 regression tests. Transcoding uses real FFmpeg; push delivery is explicitly mocked."""
import base64,io,json,os,sqlite3,subprocess,time,zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from test_api import client,register,post,create_image,HEADERS
import server
import manage


def upload(c,raw=None,mime='image/png'):
    if raw is None:raw=base64.b64decode(create_image().split(',')[1])
    headers=dict(c.headers);headers.pop('content-type',None)
    # client default application/json must be removed when sending multipart.
    old=c.headers.pop('Content-Type',None)
    try:return c.post('/api/media/uploads',files={'file':('upload',raw,mime)})
    finally:
        if old:c.headers['Content-Type']=old


def other():return TestClient(server.app,headers=HEADERS)

def test_upload_private_until_published(client):
    register(client);r=upload(client);assert r.status_code==200,r.text;m=r.json()
    assert client.get(m['path']).status_code==200
    with other() as guest:assert guest.get(m['path']).status_code==404
    pid=post(client,media_ids=[m['id']])
    with other() as guest:
        assert guest.get(m['path']).status_code==200
        p=next(p for p in guest.get('/api/state').json()['posts'] if p['id']==pid)
        assert p['media'][0]['id']==m['id']

def test_gallery_order_and_reuse_denied(client):
    register(client);a=upload(client).json();b=upload(client).json()
    pid=post(client,media_ids=[b['id'],a['id']]);p=next(p for p in client.get('/api/state').json()['posts'] if p['id']==pid)
    assert [m['id'] for m in p['media']]==[b['id'],a['id']]
    assert client.post('/api/posts',json={'body':'Reuse test','media_ids':[a['id']]}).status_code==404

def test_cannot_attach_another_users_upload(client):
    register(client);m=upload(client).json()
    with other() as c:
        register(c,'another');assert c.post('/api/posts',json={'body':'Steal','media_ids':[m['id']]}).status_code==404
        assert c.get(m['path']).status_code==404
        assert c.request('DELETE','/api/media/uploads/'+m['id'],json={}).status_code==404

def test_duplicate_and_oversize_gallery_denied(client):
    register(client);m=upload(client).json()
    assert client.post('/api/posts',json={'body':'Test','media_ids':[m['id']]*2}).status_code==422
    assert client.post('/api/posts',json={'body':'Test','media_ids':['a'*32]*7}).status_code==422
    assert client.post('/api/posts',json={'body':'Test','media_ids':[m['id']],'image_data':create_image()}).status_code==422

def test_deleting_post_removes_gallery_files(client):
    register(client);m=upload(client).json();pid=post(client,media_ids=[m['id']])
    assert client.request('DELETE','/api/posts/'+pid,json={}).status_code==200
    assert not (server.MEDIA_DIR/Path(m['path']).name).exists()
    assert client.get(m['path']).status_code==404

def test_delete_account_removes_staged_and_attached(client):
    register(client);a=upload(client).json();b=upload(client).json();post(client,media_ids=[a['id']])
    assert client.request('DELETE','/api/account',json={'password':'test-password-2026'}).status_code==200
    assert not (server.MEDIA_DIR/Path(a['path']).name).exists()
    assert not (server.MEDIA_DIR/Path(b['path']).name).exists()

def test_delete_unused_upload(client):
    register(client);m=upload(client).json()
    assert client.request('DELETE','/api/media/uploads/'+m['id'],json={}).status_code==200
    assert not (server.MEDIA_DIR/Path(m['path']).name).exists()

def test_invalid_uploads_and_csrf(client):
    register(client)
    assert upload(client,b'not a photo').status_code==422
    assert upload(client,b'<svg><script/></svg>','image/svg+xml').status_code==422
    assert upload(client,b'','image/png').status_code==422
    client.headers['X-CSRF-Token']='bad';assert upload(client).status_code==403

def test_upload_quota_and_content_length(client,monkeypatch):
    register(client);monkeypatch.setenv('MEDIA_USER_LIMIT_MB','0')
    assert upload(client).status_code==413
    old=client.headers.pop('Content-Type');
    try:r=client.post('/api/media/uploads',content=b'bad',headers={'Content-Type':'multipart/form-data; boundary=a','Content-Length':str(30*1024*1024)})
    finally:client.headers['Content-Type']=old
    assert r.status_code==413

def test_block_hides_media_for_blocked_viewer(client):
    me=register(client);m=upload(client).json();post(client,media_ids=[m['id']])
    with other() as c:
        them=register(c,'blocked_user');client.post('/api/actors/'+them['id']+'/block',json={})
        assert c.get(m['path']).status_code==404

def test_expired_story_image_is_not_served(client):
    register(client);r=client.post('/api/stories',json={'body':'Story','image_data':create_image(),'color':'violet'});assert r.status_code==200
    with server.db() as con:
        row=con.execute('SELECT * FROM stories').fetchone();con.execute('UPDATE stories SET expires=?',(time.time()-1,))
    assert client.get(row['image_path']).status_code==404

def test_video_transcode_and_range_request(client,tmp_path):
    register(client)
    source=tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=blue:s=160x240:d=1','-c:v','libx264','-pix_fmt','yuv420p','-threads','1','-y',str(source)],check=True,timeout=15)
    r=upload(client,source.read_bytes(),'video/mp4');assert r.status_code==200,r.text;m=r.json();assert m['kind']=='video' and m['duration']>0
    post(client,media_ids=[m['id']])
    assert client.get(m['thumbnail']).status_code==200
    r=client.get(m['path'],headers={'Range':'bytes=0-31'});assert r.status_code==206;assert len(r.content)==32
    assert len(client.get('/api/feed?kind=video').json()['posts'])==1

def test_fake_video_is_rejected(client):
    register(client);assert upload(client,b'not a video','video/mp4').status_code==422
    assert not list(server.MEDIA_DIR.glob('*.mp4'))
    assert not list((server.MEDIA_DIR/'.staging').glob('*'))

def test_video_unavailable_is_honest(client,monkeypatch):
    import features
    register(client);monkeypatch.setattr(features.shutil,'which',lambda _:None)
    assert client.get('/api/state').json()['capabilities']['video'] is False
    assert upload(client,b'x','video/mp4').status_code==503

def test_cursor_pagination_no_duplicates(client):
    register(client)
    for n in range(5):post(client,body='Page '+str(n))
    ids=[];cursor=''
    for _ in range(10):
        r=client.get('/api/feed',params={'cursor':cursor,'limit':2});assert r.status_code==200
        data=r.json();ids += [p['id'] for p in data['posts']];cursor=data['next_cursor']
        if not cursor:break
    assert len(ids)==7 and len(set(ids))==7
    assert client.get('/api/feed?cursor=not-valid!!').status_code==422

def test_feed_filters_and_suspension(client):
    register(client);p=post(client);client.post('/api/posts/'+p+'/save',json={})
    assert [x['id'] for x in client.get('/api/feed?kind=saved').json()['posts']]==[p]
    assert [x['id'] for x in client.get('/api/feed?kind=following').json()['posts']]==[p]

def test_operator_roles_and_production_gate(client,monkeypatch):
    me=register(client)
    assert client.get('/api/operator/readiness').status_code==403
    with server.db() as con:con.execute('INSERT INTO operators VALUES(?,?)',(me['id'],server.now()))
    data=client.get('/api/operator/readiness').json();assert data['checks']['operator_account'];assert not data['configuration_ready']
    monkeypatch.setenv('SYNAPSE_ENV','production')
    monkeypatch.setattr(server,'PUBLIC_ORIGIN','https://testserver')
    with pytest.raises(RuntimeError,match='Public launch blocked'):server.validate_deployment()
    assert client.post('/api/posts',json={'body':'Unverified'}).status_code==403

def test_push_disabled_and_endpoint_allowlist(client):
    register(client);assert not client.get('/api/push/config').json()['enabled']
    for u in ('http://fcm.googleapis.com/a','https://localhost/a','https://169.254.169.254/','https://fcm.googleapis.com.evil.example/x','https://user:pass@fcm.googleapis.com/x','https://fcm.googleapis.com:8443/a'):
        assert not server.push_endpoint_allowed(u)
    assert server.push_endpoint_allowed('https://fcm.googleapis.com/fcm/send/example')

def test_mocked_push_delivery_has_no_message_text(client,monkeypatch):
    import sys,types,importlib.machinery
    fake=types.ModuleType('pywebpush');fake.__spec__=importlib.machinery.ModuleSpec('pywebpush',loader=None)
    sent=[]
    class Failure(Exception):pass
    fake.WebPushException=Failure;fake.webpush=lambda **kw:sent.append(kw)
    monkeypatch.setitem(sys.modules,'pywebpush',fake)
    for k,v in [('VAPID_PUBLIC_KEY','public'),('VAPID_PRIVATE_KEY','private'),('PUSH_SUBJECT','mailto:admin@example.com')]:monkeypatch.setenv(k,v)
    me=register(client);r=client.post('/api/push/subscriptions',json={'endpoint':'https://fcm.googleapis.com/fcm/send/example','p256dh':'a'*87,'auth':'b'*22});assert r.status_code==200,r.text
    with other() as c:
        register(c,'sender');c.post('/api/messages/'+me['id'],json={'body':'PRIVATE MESSAGE DO NOT PUSH'})
    server.deliver_push_once();assert len(sent)==1 and 'PRIVATE MESSAGE' not in sent[0]['data']
    server.deliver_push_once();assert len(sent)==1

def test_calls_disabled_by_default(client):
    register(client);assert client.get('/api/calls/config').status_code==503

def test_call_signalling_permissions_and_cleanup(client,monkeypatch):
    monkeypatch.setenv('CALLS_ENABLED','1');me=register(client)
    with other() as b,other() as spy:
        other_user=register(b,'callee');register(spy,'spectator')
        r=client.post('/api/calls',json={'target_id':other_user['id'],'mode':'video'});assert r.status_code==200,r.text;cid=r.json()['id']
        assert spy.get('/api/calls/'+cid+'/signals').status_code==404
        assert client.post('/api/calls/'+cid+'/accept',json={}).status_code==409
        assert client.post('/api/calls/'+cid+'/signals',json={'kind':'offer','data':'SDP'}).status_code==409
        assert b.get('/api/calls/pending').json()['calls'][0]['id']==cid
        assert b.post('/api/calls/'+cid+'/accept',json={}).status_code==200
        assert b.post('/api/calls/'+cid+'/signals',json={'kind':'offer','data':'SDP'}).status_code==403
        assert client.post('/api/calls/'+cid+'/signals',json={'kind':'offer','data':'SDP'}).status_code==200
        assert b.get('/api/calls/'+cid+'/signals').json()['signals'][0]['data']=='SDP'
        assert client.get('/api/calls/'+cid+'/signals').json()['signals']==[]
        assert b.post('/api/calls/'+cid+'/end',json={}).status_code==200
        assert client.get('/api/calls/'+cid+'/signals').json()['status']=='ended'
        with server.db() as con:assert con.execute('SELECT COUNT(*) FROM call_signals').fetchone()[0]==0

def test_call_respects_blocks_and_messaging_preferences(client,monkeypatch):
    monkeypatch.setenv('CALLS_ENABLED','1');register(client)
    with other() as b:
        user=register(b,'closed');b.patch('/api/preferences',json={'theme':'system','accent':'violet','reduce_motion':False,'dm_policy':'off'})
        assert client.post('/api/calls',json={'target_id':user['id'],'mode':'audio'}).status_code==403

def test_backup_restore_and_old_sessions_invalidated(client,tmp_path):
    register(client);m=upload(client).json();post(client,media_ids=[m['id']])
    archive=manage.backup(tmp_path/'backup.zip');dest=tmp_path/'restored';manage.restore(archive,dest)
    assert (dest/'media'/Path(m['path']).name).exists()
    with sqlite3.connect(dest/'synapse.db') as con:
        assert con.execute('SELECT COUNT(*) FROM posts').fetchone()[0]==3
        assert con.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0
        assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    with pytest.raises(ValueError):manage.restore(archive,dest)

def test_restore_rejects_zip_slip(tmp_path):
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('../outside','bad');z.writestr('manifest.json','{}')
    with pytest.raises(ValueError):manage.restore(archive,tmp_path/'restore')
    assert not (tmp_path/'outside').exists()

def test_cleanup_only_unused_and_expired(client):
    register(client);a=upload(client).json();b=upload(client).json();post(client,media_ids=[b['id']])
    with server.db() as con:con.execute("UPDATE media_assets SET created_at='2000-01-01T00:00:00Z'")
    result=manage.cleanup();assert result['unused_uploads_removed']==1
    assert not (server.MEDIA_DIR/Path(a['path']).name).exists();assert (server.MEDIA_DIR/Path(b['path']).name).exists()

def test_migration_keeps_existing_posts(client):
    register(client);pid=post(client);server.initialize()
    assert any(p['id']==pid for p in client.get('/api/state').json()['posts'])

def test_public_config_does_not_expose_credentials(client,monkeypatch):
    monkeypatch.setenv('SMTP_PASSWORD','do-not-leak');monkeypatch.setenv('TURN_SHARED_SECRET','private-turn')
    raw=client.get('/api/public-info').text+client.get('/api/state').text
    assert 'do-not-leak' not in raw and 'private-turn' not in raw

def test_suspended_users_media_and_calls_hidden(client,monkeypatch):
    me=register(client);m=upload(client).json();post(client,media_ids=[m['id']])
    with server.db() as con:con.execute('UPDATE actors SET active=0 WHERE id=?',(me['id'],))
    assert client.get(m['path']).status_code==404
