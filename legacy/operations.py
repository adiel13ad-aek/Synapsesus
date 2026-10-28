"""Single-instance operational controls: durable mail, coherent encrypted backups,
readiness and operator diagnostics. External services are not provisioned here.
"""
from __future__ import annotations
import asyncio
import base64
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import smtplib
import sqlite3
import ssl
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone, timedelta
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from typing import Annotated
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import StringConstraints

MAGIC=b'SYNAPSE-BACKUP-09\x00'
logger=logging.getLogger('synapse.operations')


def encryption_key() -> bytes:
    try:
        key=base64.urlsafe_b64decode(os.environ.get('BACKUP_ENCRYPTION_KEY',''))
        if len(key)!=32:raise ValueError()
        return key
    except (ValueError,TypeError):raise ValueError('Configure BACKUP_ENCRYPTION_KEY com 32 bytes aleatórios em base64url.')


def encrypt_archive(source:Path,destination:Path,key:bytes):
    """AES-256-GCM in bounded memory. An incomplete file is never published."""
    iv=secrets.token_bytes(12);header=MAGIC+iv
    encryptor=Cipher(algorithms.AES(key),modes.GCM(iv)).encryptor()
    encryptor.authenticate_additional_data(header)
    with source.open('rb') as src,destination.open('xb') as dst:
        destination.chmod(0o600);dst.write(header)
        while chunk:=src.read(1024*1024):dst.write(encryptor.update(chunk))
        dst.write(encryptor.finalize());dst.write(encryptor.tag)
        dst.flush();os.fsync(dst.fileno())


def decrypt_archive(source:Path,destination:Path,key:bytes):
    """Writes ONLY into a private temporary path; removes it on authentication failure."""
    total=source.stat().st_size
    if total<len(MAGIC)+12+16 or total>20*1024**3:raise ValueError('Tamanho de backup inválido.')
    created=False
    try:
        with source.open('rb') as src:
            header=src.read(len(MAGIC)+12)
            if not header.startswith(MAGIC):raise ValueError('Formato de backup inválido.')
            src.seek(-16,2);tag=src.read(16);src.seek(len(header))
            decryptor=Cipher(algorithms.AES(key),modes.GCM(header[-12:],tag)).decryptor()
            decryptor.authenticate_additional_data(header)
            remaining=total-len(header)-16
            with destination.open('xb') as dst:
                created=True
                destination.chmod(0o600)
                while remaining:
                    chunk=src.read(min(1024*1024,remaining));remaining-=len(chunk)
                    if not chunk:raise ValueError('Backup truncado.')
                    dst.write(decryptor.update(chunk))
                dst.write(decryptor.finalize())
    except Exception:
        if created:destination.unlink(missing_ok=True)
        raise


class Barrier:
    """Briefly refuses NEW API requests while a coherent DB/media snapshot is captured.
    A threading lock protects counters across test event loops. No await under that lock.
    All background DB/media writers in this release share one worker.
    """
    def __init__(self):self.lock=threading.Lock();self.active=0;self.paused=False
    def enter(self):
        with self.lock:
            if self.paused:return False
            self.active+=1;return True
    def leave(self):
        with self.lock:self.active-=1
    async def pause(self):
        with self.lock:self.paused=True
        started=time.monotonic()
        while True:
            with self.lock:active=self.active
            if not active:return
            if time.monotonic()-started>30:
                self.resume();raise RuntimeError('snapshot_busy')
            await asyncio.sleep(.05)
    def resume(self):
        with self.lock:self.paused=False


def install(app,s):
    barrier=Barrier();s.snapshot_barrier=barrier
    stats={'requests':0,'errors_5xx':0,'rate_limited':0}
    stats_lock=threading.Lock();mail_lock=threading.Lock();backup_lock=threading.Lock()
    schema='''CREATE TABLE IF NOT EXISTS mail_jobs (
      id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
      purpose TEXT NOT NULL, token_hash TEXT NOT NULL DEFAULT '', encrypted_message TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
      next_attempt REAL NOT NULL, expires REAL NOT NULL, lease_until REAL NOT NULL DEFAULT 0,
      error_code TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, completed_at TEXT NOT NULL DEFAULT '');
    CREATE INDEX IF NOT EXISTS mail_due ON mail_jobs(status,next_attempt);
    CREATE TABLE IF NOT EXISTS backup_jobs (
      id TEXT PRIMARY KEY, requested_by TEXT REFERENCES actors(id) ON DELETE SET NULL,
      status TEXT NOT NULL, file_name TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL DEFAULT '',
      bytes INTEGER NOT NULL DEFAULT 0, remote_key TEXT NOT NULL DEFAULT '', error_code TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL, completed_at TEXT NOT NULL DEFAULT '', origin TEXT NOT NULL DEFAULT '');
    '''
    previous_init=s.initialize
    def initialize():
        previous_init()
        with s.db() as con:
            con.executescript(schema)
            con.execute("UPDATE mail_jobs SET status='queued' WHERE status='sending' AND lease_until<?",(time.time(),))
        # Keep private runtime directories outside the static application.
        for path in [s.DB_PATH.parent,s.MEDIA_DIR]:
            try:path.chmod(0o700)
            except OSError:pass
    s.initialize=initialize

    def mail_cipher():
        key=os.getenv('ADMIN_ENCRYPTION_KEY','')
        if not key:
            if os.getenv('SYNAPSE_ENV')=='production':raise ValueError('mail_encryption_key_missing')
            path=s.DB_PATH.parent/'mail-development.key'
            try:
                with path.open('xb') as f:path.chmod(0o600);f.write(Fernet.generate_key())
            except FileExistsError:pass
            key=path.read_text().strip()
        return Fernet(key.encode())
    def make_message(email,subject,text):
        msg=EmailMessage();msg['Subject']=subject;msg['To']=s.validate_email(email)
        msg['From']=os.getenv('SMTP_FROM','Synapse <nao-responda@localhost>')
        msg.set_content(text);return msg
    def queue_message(user_id,email,subject,text,purpose='notice',valid_for=86400,token_hash='',connection=None):
        msg=make_message(email,subject,text);mid=s.uid()
        if s.MAIL_MODE=='file':
            folder=s.DB_PATH.parent/'outbox';folder.mkdir(parents=True,exist_ok=True);folder.chmod(0o700)
            target=folder/(user_id+'-'+mid+'.eml')
            with target.open('xb') as stream:target.chmod(0o600);stream.write(bytes(msg))
            return mid
        if s.MAIL_MODE!='smtp':return None
        encrypted=mail_cipher().encrypt(bytes(msg)).decode()
        def insert(con):
            # New auth links supersede queued old links, reducing expired emails.
            if purpose in ('verify','reset'):
                con.execute("UPDATE mail_jobs SET status='cancelled',encrypted_message='' WHERE user_id=? AND purpose=? AND status IN ('queued','failed')",(user_id,purpose))
            con.execute('INSERT INTO mail_jobs(id,user_id,purpose,token_hash,encrypted_message,next_attempt,expires,created_at) VALUES(?,?,?,?,?,?,?,?)',(mid,user_id,purpose,token_hash,encrypted,time.time(),time.time()+valid_for,s.now()))
        if connection is not None:insert(connection)
        else:
            with s.db() as con:insert(con)
        return mid
    s.queue_message=queue_message
    def send_token(user_id,email,purpose):
        token=secrets.token_urlsafe(32);digest=hashlib.sha256(token.encode()).hexdigest();valid=1800 if purpose=='reset' else 86400
        # URL fragment is not sent in HTTP requests or referrers.
        origin=s.PUBLIC_ORIGIN or 'http://localhost:8000'
        url=origin+'/#'+purpose+'='+token
        subject='Synapse — '+('recuperar acesso' if purpose=='reset' else 'confirmar e-mail')
        text='Abra para '+('definir uma nova senha' if purpose=='reset' else 'confirmar seu e-mail')+':\n\n'+url+'\n\nNão compartilhe o link. Se não foi você, ignore a mensagem.'
        with s.db() as con:
            con.execute('DELETE FROM auth_tokens WHERE (user_id=? AND purpose=?) OR expires<?',(user_id,purpose,time.time()))
            con.execute('INSERT INTO auth_tokens VALUES(?,?,?,?,?)',(digest,user_id,purpose,time.time()+valid,s.now()))
            queue_message(user_id,email,subject,text,purpose,valid,digest,connection=con)
    s.send_token=send_token

    def smtp_send(raw):
        msg=BytesParser(policy=policy.default).parsebytes(raw)
        host=os.environ['SMTP_HOST'];port=int(os.getenv('SMTP_PORT','587'));tls=ssl.create_default_context()
        conn=smtplib.SMTP_SSL(host,port,timeout=12,context=tls) if port==465 else smtplib.SMTP(host,port,timeout=12)
        with conn as smtp:
            if port!=465:smtp.starttls(context=tls)
            if os.getenv('SMTP_USER'):smtp.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD'])
            smtp.send_message(msg)
    s.smtp_send=smtp_send
    def deliver_mail_batch():
        if s.MAIL_MODE!='smtp' or not mail_lock.acquire(blocking=False):return
        try:
            for _ in range(3):
                stamp=time.time()
                with s.db() as con:
                    con.execute('BEGIN IMMEDIATE')
                    con.execute("UPDATE mail_jobs SET status='expired',encrypted_message='' WHERE status IN ('queued','sending','failed') AND expires<?",(stamp,))
                    con.execute("UPDATE mail_jobs SET status='queued' WHERE status='sending' AND lease_until<?",(stamp,))
                    row=con.execute("SELECT j.* FROM mail_jobs j JOIN actors a ON a.id=j.user_id WHERE a.active=1 AND j.status='queued' AND j.next_attempt<=? AND j.expires>? ORDER BY j.created_at LIMIT 1",(stamp,stamp)).fetchone()
                    if not row:return
                    job=dict(row)
                    if job['purpose'] in ('verify','reset') and not con.execute('SELECT 1 FROM auth_tokens WHERE token_hash=? AND expires>?',(job['token_hash'],stamp)).fetchone():
                        con.execute("UPDATE mail_jobs SET status='cancelled',encrypted_message='' WHERE id=?",(job['id'],));continue
                    con.execute("UPDATE mail_jobs SET status='sending',lease_until=?,attempts=attempts+1 WHERE id=?",(stamp+90,job['id']))
                try:
                    raw=mail_cipher().decrypt(job['encrypted_message'].encode())
                    s.smtp_send(raw)
                    with s.db() as con:con.execute("UPDATE mail_jobs SET status='sent',encrypted_message='',error_code='',completed_at=? WHERE id=?",(s.now(),job['id']))
                except Exception as exc:
                    # No raw SMTP responses, addresses, password or token in logs/API.
                    code='mail_key_error' if isinstance(exc,(InvalidToken,ValueError)) else 'smtp_delivery_error'
                    attempts=job['attempts']+1
                    with s.db() as con:
                        con.execute('UPDATE mail_jobs SET status=?,error_code=?,next_attempt=? WHERE id=?',('failed' if attempts>=6 else 'queued',code,stamp+min(30*2**attempts,1800),job['id']))
        finally:mail_lock.release()
    s.deliver_mail_batch=deliver_mail_batch

    class OperationMiddleware:
        def __init__(self,app):self.app=app
        async def __call__(self,scope,receive,send):
            if scope['type']!='http':return await self.app(scope,receive,send)
            path=scope.get('path','');rid=s.uid();scope.setdefault('state',{})['request_id']=rid
            counted=path.startswith(('/api/','/media/')) and path not in ('/api/health','/api/ready','/api/status')
            if counted and not barrier.enter():
                return await JSONResponse({'detail':'Criando um ponto de recuperação. Tente novamente em instantes.','request_id':rid},status_code=503,headers={'Retry-After':'5','Cache-Control':'no-store','X-Request-ID':rid,'X-Content-Type-Options':'nosniff'})(scope,receive,send)
            async def wrapped_send(message):
                if message['type']=='http.response.start':
                    headers=[(k,v) for k,v in message.get('headers',[]) if k.lower()!=b'x-request-id']
                    headers.append((b'x-request-id',rid.encode()))
                    # Ensure error responses too are never cached or sniffed.
                    if path.startswith(('/api/','/media/')) or message['status']>=400:
                        headers=[(k,v) for k,v in headers if k.lower() not in (b'cache-control',b'x-content-type-options')]
                        headers.extend([(b'cache-control',b'no-store'),(b'x-content-type-options',b'nosniff')])
                    message['headers']=headers
                    with stats_lock:
                        stats['requests']+=1;stats['errors_5xx']+=message['status']>=500;stats['rate_limited']+=message['status']==429
                await send(message)
            try:await self.app(scope,receive,wrapped_send)
            finally:
                if counted:barrier.leave()
    app.add_middleware(OperationMiddleware)
    @app.exception_handler(Exception)
    async def unexpected(request,exc):
        rid=getattr(request.state,'request_id',s.uid())
        logger.error('request_failed id=%s type=%s',rid,type(exc).__name__)
        with stats_lock:stats['errors_5xx']+=1;stats['requests']+=1
        return JSONResponse({'detail':'Falha interna. Nenhum detalhe privado foi exposto. Informe este protocolo ao suporte.','request_id':rid},status_code=500,headers={'Cache-Control':'no-store','X-Request-ID':rid,'X-Content-Type-Options':'nosniff'})

    def backup_directory():return s.DB_PATH.parent/'backups'
    def s3_configured():return bool(os.getenv('BACKUP_S3_BUCKET') and os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY'))
    def backup_configured():
        try:encryption_key();return True
        except ValueError:return False
    def capture_snapshot(destination):
        destination.mkdir(parents=True,exist_ok=False);destination.chmod(0o700)
        database=destination/'database.sqlite3'
        with sqlite3.connect(database) as target,s.db() as source:source.backup(target)
        database.chmod(0o600)
        media=destination/'media';media.mkdir(mode=0o700)
        for path in s.MEDIA_DIR.iterdir():
            if path.is_symlink() or not path.is_file() or not re.fullmatch(r'[a-f0-9]{32}\.(jpg|mp4)',path.name):continue
            try:os.link(path,media/path.name)
            except OSError:shutil.copyfile(path,media/path.name)
        return destination
    def compress_encrypt(snapshot,job_id):
        from manage import sha256_file
        archive=snapshot/'archive.zip';manifest={'version':'0.9.0','created_at':s.now(),'files':{}}
        with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
            for path in [snapshot/'database.sqlite3',*sorted((snapshot/'media').iterdir())]:
                name=path.relative_to(snapshot).as_posix();manifest['files'][name]=sha256_file(path);z.write(path,name)
            z.writestr('manifest.json',json.dumps(manifest))
        folder=backup_directory();folder.mkdir(exist_ok=True,parents=True);folder.chmod(0o700)
        pending=folder/(job_id+'.partial');final=folder/(job_id+'.synapsebak')
        try:encrypt_archive(archive,pending,encryption_key());pending.replace(final)
        finally:pending.unlink(missing_ok=True)
        return final,sha256_file(final)
    def upload_offsite(path):
        if not s3_configured():return ''
        import boto3
        from botocore.config import Config
        endpoint=os.getenv('BACKUP_S3_ENDPOINT') or None
        if endpoint:
            u=urlsplit(endpoint)
            if u.scheme!='https' or not u.hostname or u.username or u.password:raise ValueError('Invalid S3 endpoint')
        bucket=os.environ['BACKUP_S3_BUCKET'];prefix=os.getenv('BACKUP_S3_PREFIX','synapse').strip('/')
        if not re.fullmatch(r'[A-Za-z0-9_/-]{1,120}',prefix):raise ValueError('Invalid S3 prefix')
        key=prefix+'/'+path.name
        client=boto3.client('s3',endpoint_url=endpoint,region_name=os.getenv('AWS_DEFAULT_REGION','auto'),config=Config(connect_timeout=10,read_timeout=30,retries={'max_attempts':2}))
        client.upload_file(str(path),bucket,key,ExtraArgs={'ContentType':'application/octet-stream'})
        # HEAD checks size after multipart completion; this is not a restoration test.
        meta=client.head_object(Bucket=bucket,Key=key)
        if meta.get('ContentLength')!=path.stat().st_size:raise ValueError('Remote size mismatch')
        return key
    s.upload_backup_offsite=upload_offsite
    def enqueue_backup(user_id=None):
        if not backup_configured():raise HTTPException(503,'Configure a chave de criptografia de backup no servidor.')
        with s.db() as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute("SELECT 1 FROM backup_jobs WHERE status IN ('queued','running')").fetchone():raise HTTPException(409,'Já existe um backup pendente.')
            jid=s.uid();con.execute("INSERT INTO backup_jobs(id,requested_by,status,created_at,origin) VALUES(?,?,'queued',?,?)",(jid,user_id,s.now(),s.PUBLIC_ORIGIN))
        return jid
    s.enqueue_backup=enqueue_backup
    async def guarded_thread(fn,*args):
        task=asyncio.create_task(asyncio.to_thread(fn,*args))
        try:return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise
    async def run_backup_once():
        if not backup_lock.acquire(blocking=False):return
        snapshot=None;job=None
        try:
            with s.db() as con:
                row=con.execute("SELECT * FROM backup_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
                if not row:return
                job=dict(row);con.execute("UPDATE backup_jobs SET status='running' WHERE id=?",(job['id'],))
            snapshot=s.DB_PATH.parent/'.snapshots'/job['id'];snapshot.parent.mkdir(parents=True,exist_ok=True);snapshot.parent.chmod(0o700)
            await barrier.pause()
            try:
                task=asyncio.create_task(asyncio.to_thread(capture_snapshot,snapshot))
                try:await asyncio.shield(task)
                except asyncio.CancelledError:
                    await task;raise
            finally:barrier.resume()
            path,digest=await guarded_thread(compress_encrypt,snapshot,job['id'])
            with s.db() as con:con.execute('UPDATE backup_jobs SET file_name=?,sha256=?,bytes=? WHERE id=?',(path.name,digest,path.stat().st_size,job['id']))
            remote=await guarded_thread(s.upload_backup_offsite,path)
            with s.db() as con:con.execute('UPDATE backup_jobs SET status=?,remote_key=?,completed_at=?,error_code=\'\' WHERE id=?',('offsite' if remote else 'local_only',remote,s.now(),job['id']))
            # Keep a bounded local history; remote retention is configured separately.
            keep=max(2,min(int(os.getenv('BACKUP_LOCAL_KEEP','3')),30))
            files=sorted(backup_directory().glob('*.synapsebak'),key=lambda p:p.stat().st_mtime,reverse=True)
            for old in files[keep:]:old.unlink(missing_ok=True)
        except asyncio.CancelledError:
            if job:
                with s.db() as con:con.execute("UPDATE backup_jobs SET status='failed',error_code='interrupted' WHERE id=?",(job['id'],))
            raise
        except Exception as exc:
            if job:
                with s.db() as con:con.execute("UPDATE backup_jobs SET status='failed',error_code=?,completed_at=? WHERE id=?",('backup_'+type(exc).__name__,s.now(),job['id']))
            logger.error('backup_failed type=%s',type(exc).__name__)
        finally:
            barrier.resume()
            if snapshot and snapshot.exists():shutil.rmtree(snapshot)
            backup_lock.release()
    s.run_backup_once=run_backup_once

    def maintenance_cleanup():
        from manage import cleanup
        cleanup()
        cutoff=(datetime.now(timezone.utc)-timedelta(days=14)).isoformat()
        with s.db() as con:
            con.execute("DELETE FROM mail_jobs WHERE status IN ('sent','cancelled','expired') AND created_at<?",(cutoff,))
            con.execute('DELETE FROM age_challenges WHERE expires<?',(time.time(),))
            con.execute('DELETE FROM guardian_invites WHERE expires<?',(time.time(),))
            con.execute('DELETE FROM admin_grants WHERE expires<?',(time.time(),))
            con.execute('DELETE FROM durable_rates WHERE expires<?',(time.time(),))
            # Adult signals terminate supervision and pending requests; no new public exposure.
            con.execute("DELETE FROM guardianships WHERE child_id IN (SELECT id FROM actors WHERE age_band='adult')")
    s.maintenance_cleanup=maintenance_cleanup
    async def delivery_worker():
        next_cleanup=time.monotonic()+3600
        # Only a real startup, not initialize() called by a maintenance utility.
        with s.db() as con:con.execute("UPDATE backup_jobs SET status='failed',error_code='server_restarted' WHERE status='running'")
        while True:
            await asyncio.sleep(5)
            try:
                await asyncio.to_thread(deliver_mail_batch)
                await asyncio.to_thread(s.deliver_push_once)
                hours=max(1,min(int(os.getenv('BACKUP_INTERVAL_HOURS','24')),168))
                if os.getenv('AUTO_BACKUP_ENABLED','0')=='1' and backup_configured():
                    with s.db() as con:
                        last=con.execute('SELECT created_at FROM backup_jobs ORDER BY created_at DESC LIMIT 1').fetchone()
                        pending=con.execute("SELECT 1 FROM backup_jobs WHERE status IN ('queued','running')").fetchone()
                    if not pending and (not last or datetime.fromisoformat(last['created_at']).timestamp()<time.time()-hours*3600):enqueue_backup()
                await run_backup_once()
                if time.monotonic()>=next_cleanup:
                    await asyncio.to_thread(maintenance_cleanup);next_cleanup=time.monotonic()+3600
            except asyncio.CancelledError:raise
            except Exception as exc:logger.error('operation_failed type=%s',type(exc).__name__)
    s.delivery_worker=delivery_worker

    def public_site_settings():
        st=s.site_settings()
        if os.getenv('SYNAPSE_ENV')=='production' and st['registration_open']:
            st['registration_open']=int(all(c['ok'] for c in s.launch_checks()))
        return st
    s.public_site_settings=public_site_settings

    @app.get('/api/ready')
    def ready():
        try:
            with s.db() as con:con.execute('SELECT 1 FROM actors LIMIT 1').fetchone()
            good=shutil.disk_usage(s.DB_PATH.parent).free>=100*1024*1024
        except (OSError,sqlite3.Error):good=False
        return JSONResponse({'ready':good},status_code=200 if good else 503,headers={'Cache-Control':'no-store'})
    @app.get('/api/status')
    def public_status():
        st=public_site_settings()
        return {'service':'Synapse','maintenance':bool(st['maintenance']),'registration_open':bool(st['registration_open'] and not st['maintenance']),'notice':st['announcement']}
    @app.get('/.well-known/security.txt')
    def security_txt():
        email=os.getenv('SECURITY_EMAIL') or os.getenv('SUPPORT_EMAIL','')
        if not re.fullmatch(r'[^\s@<>\r\n]+@[^\s@<>\r\n]+\.[^\s@<>\r\n]+',email):raise HTTPException(404)
        expires=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(timespec='seconds')
        return Response(f'Contact: mailto:{email}\nExpires: {expires}\nPreferred-Languages: pt-BR, en\n',media_type='text/plain')
    @app.get('/operacao')
    def operations_page():return FileResponse(s.ROOT/'web'/'operations.html',headers={'Cache-Control':'no-store'})
    @app.get('/api/manage/operations')
    def operations_status(user=Depends(s.release_owner)):
        with s.db() as con:
            mail={r['status']:r['n'] for r in con.execute('SELECT status,COUNT(*) n FROM mail_jobs GROUP BY status')}
            backups=[dict(r) for r in con.execute('SELECT id,status,sha256,bytes,remote_key,error_code,created_at,completed_at FROM backup_jobs ORDER BY created_at DESC LIMIT 15')]
            failures=[dict(r) for r in con.execute("SELECT id,purpose,status,attempts,error_code,created_at FROM mail_jobs WHERE status IN ('failed','queued') ORDER BY created_at DESC LIMIT 30")]
            db_ok=con.execute('PRAGMA quick_check(1)').fetchone()[0]=='ok'
            tickets=con.execute("SELECT COUNT(*) FROM support_tickets WHERE status='open'").fetchone()[0]
        with stats_lock:metrics=dict(stats)
        return {'mail':mail,'mail_jobs':failures,'backups':backups,'database_ok':db_ok,'disk_free_bytes':shutil.disk_usage(s.DB_PATH.parent).free,
                'metrics_since_restart':metrics,'open_tickets':tickets,'backup_encrypted':backup_configured(),'backup_offsite_configured':s3_configured(),
                'auto_backup_enabled':os.getenv('AUTO_BACKUP_ENABLED')=='1','single_instance':True,
                'notice':'Contadores locais, desde o início do processo. SMTP aceito não comprova entrega na caixa. Cópia externa não comprova restauração.'}
    @app.post('/api/manage/backups')
    def request_backup(user=Depends(s.release_owner)):
        s.rate_limit('backup-request:'+user['id'],4,3600)
        jid=enqueue_backup(user['id'])
        with s.db() as con:s.admin_event(con,user,'backup_queued','backup',jid,'Solicitação de backup criptografado.')
        return {'id':jid,'status':'queued'}
    @app.post('/api/manage/mail/{job_id}/retry')
    def retry_mail(job_id:str,user=Depends(s.release_owner)):
        with s.db() as con:
            row=con.execute('SELECT * FROM mail_jobs WHERE id=?',(job_id,)).fetchone()
            if not row or row['status']!='failed' or row['expires']<=time.time():raise HTTPException(409,'Mensagem sem possibilidade de reenvio. O usuário deve solicitar um novo link.')
            con.execute("UPDATE mail_jobs SET status='queued',attempts=0,next_attempt=? WHERE id=?",(time.time(),job_id))
            s.admin_event(con,user,'mail_retry','mail',job_id,'Reenvio solicitado sem exibir conteúdo ou destinatário.')
        return {'ok':True}
    @app.post('/api/manage/mail/test')
    def test_mail(user=Depends(s.release_owner)):
        s.rate_limit('mail-test:'+user['id'],2,300)
        jid=queue_message(user['id'],user['email'],'Synapse — teste de entrega','Mensagem de teste solicitada no painel. Recebê-la não testa recuperação de senha nem SPF/DKIM/DMARC. Não responda com senhas.',purpose='test')
        return {'ok':True,'job_id':jid,'mode':s.MAIL_MODE}

    previous_checks=s.launch_checks
    def launch_checks():
        checks=previous_checks()
        with s.db() as con:
            row=con.execute("SELECT completed_at FROM backup_jobs WHERE status='offsite' AND origin=? ORDER BY completed_at DESC LIMIT 1",(s.PUBLIC_ORIGIN,)).fetchone()
            failed=con.execute("SELECT COUNT(*) FROM mail_jobs WHERE status='failed' AND expires>?",(time.time(),)).fetchone()[0]
        recent=bool(row and datetime.fromisoformat(row['completed_at']).timestamp()>time.time()-48*3600)
        checks.extend([
            {'id':'backup_encryption','ok':backup_configured(),'kind':'configuration','label':'Criptografia de backups configurada'},
            {'id':'scheduled_backup','ok':os.getenv('AUTO_BACKUP_ENABLED')=='1' and s3_configured(),'kind':'configuration','label':'Backup periódico e destino externo configurados'},
            {'id':'recent_offsite_backup','ok':recent,'kind':'integration','label':'Backup externo concluído nas últimas 48 horas (restauração verificada separadamente)'},
            {'id':'mail_queue_healthy','ok':failed==0,'kind':'integration','label':'Sem mensagens com falha definitiva e ainda válidas'},
        ])
        return checks
    s.launch_checks=launch_checks
