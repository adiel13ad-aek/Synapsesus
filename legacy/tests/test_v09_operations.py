"""Operational tests use temporary data. SMTP and object storage are mocked;
AES-GCM, SQLite, media snapshots and restoration execute for real locally.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
import sqlite3
import time
import zipfile
import pytest
from cryptography.fernet import Fernet
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
from test_api import client,register,post,create_image,HEADERS
from test_v07 import make_owner
import server
from operations import encrypt_archive,decrypt_archive,Barrier
from tools.restore_encrypted import restore_encrypted


def email_for(me):
    with server.db() as con:return con.execute("SELECT email FROM actors WHERE id=?",(me["id"],)).fetchone()[0]

def smtp(monkeypatch):
    monkeypatch.setattr(server,'MAIL_MODE','smtp')
    monkeypatch.setenv('ADMIN_ENCRYPTION_KEY',Fernet.generate_key().decode())
    monkeypatch.setattr(server,'smtp_send',lambda raw:None)

def backup_key(monkeypatch):
    key=os.urandom(32);monkeypatch.setenv('BACKUP_ENCRYPTION_KEY',base64.urlsafe_b64encode(key).decode());return key


def test_mail_is_durable_encrypted_and_scrubbed_after_send(client,monkeypatch):
    me=register(client);smtp(monkeypatch)
    server.send_token(me['id'],email_for(me),'verify')
    with server.db() as con:
        job=dict(con.execute("SELECT * FROM mail_jobs WHERE purpose='verify'").fetchone())
        token_hash=con.execute("SELECT token_hash FROM auth_tokens WHERE user_id=?",(me['id'],)).fetchone()[0]
    assert job['status']=='queued' and email_for(me) not in job['encrypted_message']
    raw=Fernet(os.environ['ADMIN_ENCRYPTION_KEY'].encode()).decrypt(job['encrypted_message'].encode())
    assert b'/#verify=' in raw and b'/?verify=' not in raw
    captured=[];monkeypatch.setattr(server,'smtp_send',lambda raw:captured.append(raw))
    server.deliver_mail_batch();assert captured==[raw]
    with server.db() as con:
        row=con.execute('SELECT * FROM mail_jobs WHERE id=?',(job['id'],)).fetchone()
        assert row['status']=='sent' and row['encrypted_message']=='' and row['attempts']==1
        assert con.execute('SELECT 1 FROM auth_tokens WHERE token_hash=?',(token_hash,)).fetchone()


def test_mail_retry_then_success_with_redacted_error(client,monkeypatch):
    me=register(client);smtp(monkeypatch)
    jid=server.queue_message(me['id'],email_for(me),'Assunto','Mensagem de teste')
    def fail(raw):raise OSError('credential-secret@example.test token=do-not-log')
    monkeypatch.setattr(server,'smtp_send',fail);server.deliver_mail_batch()
    with server.db() as con:
        row=dict(con.execute('SELECT * FROM mail_jobs WHERE id=?',(jid,)).fetchone())
        assert row['status']=='queued' and row['attempts']==1 and row['next_attempt']>time.time()
        assert row['error_code']=='smtp_delivery_error'
        con.execute('UPDATE mail_jobs SET next_attempt=0 WHERE id=?',(jid,))
    monkeypatch.setattr(server,'smtp_send',lambda raw:None);server.deliver_mail_batch()
    with server.db() as con:assert con.execute('SELECT status FROM mail_jobs WHERE id=?',(jid,)).fetchone()[0]=='sent'


def test_six_failures_stop_retrying_and_operator_can_retry(client,monkeypatch):
    me=make_owner(client);smtp(monkeypatch)
    jid=server.queue_message(me['id'],email_for(me),'Assunto','Teste de falha transitória')
    def fail(raw):raise OSError('simulated')
    monkeypatch.setattr(server,'smtp_send',fail)
    for i in range(6):
        with server.db() as con:con.execute('UPDATE mail_jobs SET next_attempt=0 WHERE id=?',(jid,))
        server.deliver_mail_batch()
    data=client.get('/api/manage/operations').json()
    assert data['mail']['failed']==1 and 'encrypted_message' not in json.dumps(data)
    assert not next(c for c in server.launch_checks() if c['id']=='mail_queue_healthy')['ok']
    assert client.post('/api/manage/mail/'+jid+'/retry',json={}).status_code==200
    with server.db() as con:
        job=con.execute('SELECT * FROM mail_jobs WHERE id=?',(jid,)).fetchone()
        assert job['status']=='queued' and job['attempts']==0


def test_new_auth_link_cancels_older_queued_mail(client,monkeypatch):
    me=register(client);smtp(monkeypatch)
    server.send_token(me['id'],email_for(me),'verify');server.send_token(me['id'],email_for(me),'verify')
    with server.db() as con:
        rows=con.execute('SELECT * FROM mail_jobs').fetchall()
        assert sum(r['status']=='queued' for r in rows)==1
        assert sum(r['status']=='cancelled' and not r['encrypted_message'] for r in rows)==1
    server.deliver_mail_batch()
    with server.db() as con:assert con.execute("SELECT COUNT(*) FROM mail_jobs WHERE status='sent'").fetchone()[0]==1


def test_expired_and_revoked_tokens_are_never_sent(client,monkeypatch):
    me=register(client);smtp(monkeypatch);sent=[];monkeypatch.setattr(server,'smtp_send',sent.append)
    server.send_token(me['id'],email_for(me),'reset')
    with server.db() as con:con.execute('DELETE FROM auth_tokens WHERE user_id=?',(me['id'],))
    expired=server.queue_message(me['id'],email_for(me),'Old','Expired',valid_for=-1)
    server.deliver_mail_batch();assert sent==[]
    with server.db() as con:
        assert con.execute('SELECT status FROM mail_jobs WHERE id=?',(expired,)).fetchone()[0]=='expired'
        assert con.execute("SELECT status FROM mail_jobs WHERE purpose='reset'").fetchone()[0]=='cancelled'


def test_account_deletion_removes_pending_email(client,monkeypatch):
    me=register(client);smtp(monkeypatch);server.send_token(me['id'],email_for(me),'verify')
    assert client.request('DELETE','/api/account',json={'password':'test-password-2026'}).status_code==200
    with server.db() as con:assert con.execute('SELECT COUNT(*) FROM mail_jobs').fetchone()[0]==0


def test_crypto_roundtrip_tamper_and_wrong_key(tmp_path):
    key=os.urandom(32);data=os.urandom(2*1024*1024+7)
    plain=tmp_path/'input.zip';plain.write_bytes(data)
    encrypted=tmp_path/'archive.synapsebak';encrypt_archive(plain,encrypted,key)
    recovered=tmp_path/'recovered.zip';decrypt_archive(encrypted,recovered,key)
    assert recovered.read_bytes()==data and data[:100] not in encrypted.read_bytes()
    with pytest.raises(InvalidTag):decrypt_archive(encrypted,tmp_path/'wrong.zip',os.urandom(32))
    assert not (tmp_path/'wrong.zip').exists()
    corrupt=bytearray(encrypted.read_bytes());corrupt[-30]^=1
    bad=tmp_path/'corrupt.synapsebak';bad.write_bytes(corrupt)
    with pytest.raises(InvalidTag):decrypt_archive(bad,tmp_path/'bad.zip',key)
    assert not (tmp_path/'bad.zip').exists()


def test_crypto_never_overwrites_existing_files(tmp_path):
    key=os.urandom(32);source=tmp_path/'source';source.write_bytes(b'payload')
    target=tmp_path/'output';target.write_text('existing data')
    with pytest.raises(FileExistsError):encrypt_archive(source,target,key)
    assert target.read_text()=='existing data'
    encrypted=tmp_path/'encrypted';encrypt_archive(source,encrypted,key)
    with pytest.raises(FileExistsError):decrypt_archive(encrypted,target,key)
    assert target.read_text()=='existing data'


def test_real_snapshot_restore_and_session_revocation(client,monkeypatch,tmp_path):
    owner=make_owner(client);post(client,image_data=create_image());backup_key(monkeypatch)
    server.queue_message(owner['id'],email_for(owner),'Subject','Notice')
    result=client.post('/api/manage/backups',json={});assert result.status_code==200,result.text
    jid=result.json()['id'];asyncio.run(server.run_backup_once())
    with server.db() as con:
        row=dict(con.execute('SELECT * FROM backup_jobs WHERE id=?',(jid,)).fetchone())
    assert row['status']=='local_only' and row['sha256'] and row['bytes']>100
    path=server.DB_PATH.parent/'backups'/row['file_name'];destination=tmp_path/'restored'
    restore_encrypted(path,destination)
    with sqlite3.connect(destination/'synapse.db') as con:
        assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert con.execute('SELECT COUNT(*) FROM posts').fetchone()[0]>=1
        assert con.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0
        assert con.execute('SELECT COUNT(*) FROM mail_jobs').fetchone()[0]==0
        assert con.execute('SELECT registration_open,maintenance FROM site_settings').fetchone()==(0,1)
    assert len(list((destination/'media').glob('*.jpg')))>=1
    with pytest.raises(ValueError):restore_encrypted(path,destination)
    assert not server.snapshot_barrier.paused
    assert not list((server.DB_PATH.parent/'.snapshots').glob('*'))


def test_offsite_mock_and_launch_evidence(client,monkeypatch):
    me=make_owner(client);backup_key(monkeypatch)
    monkeypatch.setattr(server,'upload_backup_offsite',lambda p:'synthetic/'+p.name)
    jid=server.enqueue_backup(me['id']);asyncio.run(server.run_backup_once())
    with server.db() as con:
        row=dict(con.execute('SELECT * FROM backup_jobs WHERE id=?',(jid,)).fetchone())
    assert row['status']=='offsite' and row['remote_key'].startswith('synthetic/')
    assert next(c for c in server.launch_checks() if c['id']=='recent_offsite_backup')['ok']
    # Evidence cannot be transplanted to another origin.
    monkeypatch.setattr(server,'PUBLIC_ORIGIN','https://other.example.test')
    assert not next(c for c in server.launch_checks() if c['id']=='recent_offsite_backup')['ok']


def test_offsite_failure_is_not_claimed_as_success(client,monkeypatch):
    me=make_owner(client);backup_key(monkeypatch)
    def fail(path):raise OSError('synthetic network failure')
    monkeypatch.setattr(server,'upload_backup_offsite',fail)
    jid=server.enqueue_backup(me['id']);asyncio.run(server.run_backup_once())
    with server.db() as con:row=dict(con.execute('SELECT * FROM backup_jobs WHERE id=?',(jid,)).fetchone())
    assert row['status']=='failed' and row['error_code']=='backup_OSError'
    assert not next(c for c in server.launch_checks() if c['id']=='recent_offsite_backup')['ok']
    assert not server.snapshot_barrier.paused


def test_snapshot_pause_blocks_new_writes_but_health_available(client):
    register(client)
    asyncio.run(server.snapshot_barrier.pause())
    try:
        result=client.post('/api/posts',json={'body':'Snapshot in progress'})
        assert result.status_code==503 and result.headers['retry-after']=='5'
        assert client.get('/api/ready').status_code==200
        assert client.get('/api/health').status_code==200
    finally:server.snapshot_barrier.resume()
    assert client.post('/api/posts',json={'body':'Snapshot released'}).status_code==200


def test_backup_queue_deduplicates_and_requires_key(client,monkeypatch):
    make_owner(client)
    assert client.post('/api/manage/backups',json={}).status_code==503
    backup_key(monkeypatch)
    assert client.post('/api/manage/backups',json={}).status_code==200
    assert client.post('/api/manage/backups',json={}).status_code==409


def test_regular_users_cannot_access_operations_or_backups(client,monkeypatch):
    register(client);backup_key(monkeypatch)
    for path in ['/api/manage/operations','/api/manage/support']:
        assert client.get(path).status_code==403
    for path in ['/api/manage/backups','/api/manage/mail/test']:
        assert client.post(path,json={}).status_code==403


def test_health_status_security_contact_exposes_no_secrets(client,monkeypatch):
    monkeypatch.setenv('SECURITY_EMAIL','security@example.test')
    assert client.get('/api/ready').json()=={'ready':True}
    result=client.get('/api/status')
    assert result.status_code==200 and 'database' not in result.text
    text=client.get('/.well-known/security.txt').text
    assert 'Contact: mailto:security@example.test' in text and 'Expires:' in text
    monkeypatch.setenv('SECURITY_EMAIL','bad\r\nInjected: value')
    assert client.get('/.well-known/security.txt').status_code==404


def test_upload_quota_protects_legacy_inline_images(client,monkeypatch):
    register(client)
    monkeypatch.setenv('MAX_STORAGE_MB','0')
    # Enforced minimum keeps the configured operational quota meaningful.
    original=server.shutil.disk_usage
    Usage=type(original(server.DB_PATH.parent))
    monkeypatch.setattr(server.shutil,'disk_usage',lambda p:Usage(1000,999,1))
    result=client.post('/api/posts',json={'body':'No disk','image_data':create_image()})
    assert result.status_code==507,result.text


def test_production_launch_and_signup_with_explicit_synthetic_integrations(client,monkeypatch):
    """Exercise a successful production branch. All provider/operational evidence
    here is SYNTHETIC; this does not mark any real deployment ready.
    """
    import httpx
    from test_v07 import as_prod,enroll
    from test_v09_safety import verifier
    me=make_owner(client);as_prod(monkeypatch);enroll(client)
    monkeypatch.setattr(server,'SEED_DEMO_DATA',False);monkeypatch.setattr(server,'MAIL_MODE','smtp')
    config={'SMTP_HOST':'smtp.example.test','SMTP_FROM':'support@example.test','SMTP_USER':'synthetic','SMTP_PASSWORD':'synthetic','OPERATOR_NAME':'Operador sintético','SUPPORT_EMAIL':'support@example.test','CHILD_SAFETY_EMAIL':'safety@example.test','TURNSTILE_SITE_KEY':'synthetic-site','TURNSTILE_SECRET_KEY':'synthetic-secret','AUTO_BACKUP_ENABLED':'1','BACKUP_S3_BUCKET':'synthetic','AWS_ACCESS_KEY_ID':'synthetic','AWS_SECRET_ACCESS_KEY':'synthetic'}
    for key,value in config.items():monkeypatch.setenv(key,value)
    monkeypatch.setattr(server,'smtp_send',lambda raw:None)
    verifier(monkeypatch);backup_key(monkeypatch)
    server.record_integration_check('age_verifier','Synthetic evidence only')
    server.record_integration_check('turnstile','Synthetic evidence only')
    monkeypatch.setattr(server,'upload_backup_offsite',lambda p:'synthetic/'+p.name)
    jid=server.enqueue_backup(me['id']);asyncio.run(server.run_backup_once())
    assert client.post('/api/manage/remove-examples',json={'reason':'Preparação sintética de teste automatizado.'}).status_code==200
    for kind in ('terms','privacy','safety'):
        assert client.put('/api/manage/policies/'+kind,json={'body':'Documento sintético para teste. Não publicar este texto. '*20,'reason':'Teste sintético, nenhuma revisão jurídica alegada.','reviewed':True}).status_code==200
    for name in ('email_test','backup_restore','moderation','browser_test','audience_review'):
        assert client.post('/api/manage/launch/'+name,json={'note':'Declaração sintética restrita ao teste automatizado.','confirmed':True}).status_code==200
    data=client.get('/api/manage/launch').json();assert data['can_open'],data
    body={'registration_open':True,'maintenance':False,'uploads_enabled':True,'announcement':'Teste sintético, não é lançamento.','reason':'Ramo de sucesso da validação automatizada.'}
    assert client.patch('/api/manage/settings',json=body).status_code==200
    assert client.get('/api/site').json()['registration_open']
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'success':True,'hostname':'testserver','action':'signup'})),**kw))
    # Reuse request client but remove the administrative identity; no extra lifespan.
    client.cookies.clear();client.headers.pop('X-CSRF-Token',None)
    r=client.post('/api/auth/register',json={'name':'Conta sintética','handle':'new.production','email':'new@example.test','password':'local-production-test-2026','terms_accepted':True,'turnstile_token':'synthetic-token'})
    assert r.status_code==200,r.text
    client.headers['X-CSRF-Token']=r.json()['csrf']
    state=client.get('/api/state').json()
    assert state['me']['account_private'] and state['onboarding']=='email_required' and state['posts']==[]
    assert client.post('/api/posts',json={'body':'Must wait for verified activation'}).status_code==403
