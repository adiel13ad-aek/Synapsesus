"""Synapse 0.5 extensions. No cloud credentials, signing keys or user data are bundled.
Media processing is bounded and the HTTP handlers enforce ownership before sharing.
Push delivery and cross-network calls require external configuration; not certification.
"""

import asyncio
import base64
import hashlib
import hmac
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import Field, StringConstraints


def install(app, s):
    processing = asyncio.Semaphore(2)
    def production(): return os.getenv('SYNAPSE_ENV', 'development') == 'production'

    def is_operator(user):
        if production() and not user['email_verified']:return False
        with s.db() as con:
            saved = con.execute('SELECT 1 FROM operators WHERE user_id=?', (user['id'],)).fetchone()
        return bool(saved or (not production() and user['handle'].lower() in s.ADMIN_HANDLES))
    s.is_operator = is_operator

    def capabilities():
        push = bool(os.getenv('VAPID_PUBLIC_KEY') and os.getenv('VAPID_PRIVATE_KEY') and os.getenv('PUSH_SUBJECT') and importlib.util.find_spec('pywebpush'))
        return {'gallery': True, 'video': bool(shutil.which('ffmpeg') and shutil.which('ffprobe')),
                'push': push, 'calls': os.getenv('CALLS_ENABLED', '0') == '1',
                'max_photos': 6, 'max_video_mb': 25, 'max_video_seconds': 90}
    s.capabilities = capabilities

    def deployment_checks():
        origin=urlsplit(s.PUBLIC_ORIGIN)
        with s.db() as con:
            operator = bool(con.execute('SELECT 1 FROM operators o JOIN actors a ON a.id=o.user_id WHERE a.active=1').fetchone())
        return {
            'https_origin': origin.scheme=='https' and bool(origin.hostname) and not origin.username and not origin.password and origin.path in ('','/') and not origin.query and not origin.fragment,
            'demo_disabled': not s.SEED_DEMO_DATA,
            'smtp_configured': s.MAIL_MODE=='smtp' and all(os.getenv(k) for k in ('SMTP_HOST','SMTP_FROM','SMTP_USER','SMTP_PASSWORD')),
            'operator_account': operator,
            'policies_reviewed': os.getenv('POLICIES_REVIEWED')=='1',
            'operator_identity': bool(os.getenv('OPERATOR_NAME')),
            'support_contact': bool(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',os.getenv('SUPPORT_EMAIL',''))),
            'child_safety_contact': bool(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',os.getenv('CHILD_SAFETY_EMAIL',''))),
        }
    s.deployment_checks=deployment_checks
    def validate_deployment():
        if production():
            failed=[k for k,v in deployment_checks().items() if not v]
            if failed: raise RuntimeError('Public launch blocked; configure: '+', '.join(failed)+'. See docs/DEPLOY.md.')
    s.validate_deployment=validate_deployment
    def bootstrap_operator():
        handle=os.getenv('BOOTSTRAP_HANDLE','');email=os.getenv('BOOTSTRAP_EMAIL','');password=os.getenv('BOOTSTRAP_PASSWORD','')
        if not (handle and email and password):return
        with s.db() as con:
            if con.execute('SELECT 1 FROM operators').fetchone():return
        from manage import create_operator
        create_operator(handle,email,os.getenv('OPERATOR_NAME','Operador Synapse'),password)
    s.bootstrap_operator=bootstrap_operator

    def media_items(con, post_id):
        return [dict(r) for r in con.execute('SELECT id,kind,path,thumbnail,width,height,duration FROM media_assets WHERE post_id=? ORDER BY position', (post_id,))]
    s.media_items=media_items
    def attach_media(con, post_id, owner_id, ids):
        if not ids: return
        if len(ids)>6 or len(ids)!=len(set(ids)): raise HTTPException(422,'Selecione até seis fotos diferentes ou um vídeo.')
        items=[]
        for aid in ids:
            item=con.execute('SELECT * FROM media_assets WHERE id=? AND owner_id=? AND post_id IS NULL',(aid,owner_id)).fetchone()
            if not item: raise HTTPException(404,'Arquivo não disponível para esta conta.')
            items.append(item)
        if any(i['kind']=='video' for i in items) and len(items)!=1:
            raise HTTPException(422,'Publique um vídeo por post, sem misturar com a galeria.')
        for n,item in enumerate(items):
            con.execute('UPDATE media_assets SET post_id=?,position=? WHERE id=?',(post_id,n,item['id']))
    s.attach_media=attach_media
    def owned_post_files(con,post_id):
        return [dict(r) for r in con.execute('SELECT path,thumbnail FROM media_assets WHERE post_id=?',(post_id,))]
    s.owned_post_files=owned_post_files
    def delete_media_files(items):
        for item in items:
            for field in ('path','thumbnail'):
                value=item.get(field,'')
                if re.fullmatch(r'/media/[a-f0-9]{32}\.(jpg|mp4)',value or ''):
                    (s.MEDIA_DIR/Path(value).name).unlink(missing_ok=True)
    s.delete_media_files=delete_media_files

    def process_file(path:Path, mime:str):
        asset_id=s.uid()
        if mime in ('image/jpeg','image/png','image/webp'):
            raw=path.read_bytes()
            if len(raw)>3*1024*1024: raise HTTPException(413,'Cada foto deve ter até 3 MB.')
            location=s.persist_image('data:'+mime+';base64,'+base64.b64encode(raw).decode())
            from PIL import Image
            output=s.MEDIA_DIR/Path(location).name
            with Image.open(output) as image: width,height=image.size
            return {'id':asset_id,'kind':'image','path':location,'thumbnail':'','bytes':output.stat().st_size,'width':width,'height':height,'duration':0}
        if mime not in ('video/mp4','video/webm','video/quicktime'): raise HTTPException(422,'Formato não permitido. Use fotos JPEG/PNG/WebP ou vídeo MP4/WebM/MOV.')
        if not capabilities()['video']: raise HTTPException(503,'O servidor precisa de FFmpeg para receber vídeos.')
        name=s.uid()+'.mp4';thumb=s.uid()+'.jpg'
        output=s.MEDIA_DIR/name;poster=s.MEDIA_DIR/thumb
        try:
            probe=subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-format_whitelist','mov,matroska,webm','-show_format','-show_streams','-of','json',str(path)],capture_output=True,timeout=15,check=True)
            info=json.loads(probe.stdout)
            streams=[st for st in info.get('streams',[]) if st.get('codec_type')=='video']
            if not streams: raise ValueError('no video')
            v=streams[0];width=int(v.get('width',0));height=int(v.get('height',0));duration=float(info.get('format',{}).get('duration',v.get('duration',0)))
            if not math.isfinite(duration) or duration<=0 or duration>90 or not 0<width*height<=9_000_000 or max(width,height)>4096:
                raise HTTPException(422,'Use vídeo de até 90 segundos, resolução até 4096 e 9 megapixels.')
            # Only local protocols; no shell, no input filename provided by the user, no copied metadata.
            subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-protocol_whitelist','file,pipe','-format_whitelist','mov,matroska,webm','-i',str(path),
                '-map','0:v:0','-map','0:a:0?','-sn','-dn','-map_metadata','-1','-vf','scale=w=min(720\\,iw):h=min(1280\\,ih):force_original_aspect_ratio=decrease:force_divisible_by=2',
                '-t','90','-r','30','-c:v','libx264','-preset','veryfast','-crf','26','-pix_fmt','yuv420p','-c:a','aac','-b:a','96k',
                '-threads','2','-movflags','+faststart','-fs',str(30*1024*1024),'-y',str(output)],capture_output=True,timeout=150,check=True)
            subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-i',str(output),'-frames:v','1','-threads','1','-y',str(poster)],capture_output=True,timeout=15,check=True)
            from PIL import Image
            with Image.open(poster) as image: width,height=image.size
            return {'id':asset_id,'kind':'video','path':'/media/'+name,'thumbnail':'/media/'+thumb,'bytes':output.stat().st_size+poster.stat().st_size,'width':width,'height':height,'duration':duration}
        except HTTPException:
            output.unlink(missing_ok=True);poster.unlink(missing_ok=True);raise
        except (OSError,subprocess.SubprocessError,ValueError,KeyError,TypeError):
            output.unlink(missing_ok=True);poster.unlink(missing_ok=True)
            raise HTTPException(422,'Não foi possível processar este vídeo. Use MP4 ou WebM válido, até 90 segundos.')

    @app.post('/api/media/uploads')
    async def upload(file:UploadFile=File(...),user=Depends(s.member)):
        s.rate_limit('uploads:'+user['id'],12,600)
        s.ensure_storage_capacity(35*1024*1024)
        with s.db() as con:
            total=con.execute('SELECT COALESCE(SUM(bytes),0) AS b FROM media_assets WHERE owner_id=?',(user['id'],)).fetchone()['b']
            global_total=con.execute('SELECT COALESCE(SUM(bytes),0) AS b FROM media_assets').fetchone()['b']
        user_limit=int(os.getenv('MEDIA_USER_LIMIT_MB','250'))*1024*1024
        global_limit=int(os.getenv('MEDIA_TOTAL_LIMIT_MB','5000'))*1024*1024
        if total>=user_limit or global_total>=global_limit: raise HTTPException(413,'Limite de armazenamento atingido. Remova arquivos ou contate o operador.')
        staging=s.MEDIA_DIR/'.staging';staging.mkdir(parents=True,exist_ok=True)
        try:
            with tempfile.NamedTemporaryFile(dir=staging,suffix='.upload',delete=False) as out:
                filename=Path(out.name);size=0
                while chunk:=await file.read(1024*1024):
                    size+=len(chunk)
                    if size>25*1024*1024: raise HTTPException(413,'O arquivo deve ter até 25 MB.')
                    out.write(chunk)
            if not size: raise HTTPException(422,'Arquivo vazio.')
            async with processing:
                item=await asyncio.to_thread(process_file,filename,file.content_type or '')
            try:
                with s.db() as con:
                    con.execute('BEGIN IMMEDIATE')
                    totals=con.execute('SELECT COALESCE(SUM(bytes),0) AS all_b, COALESCE(SUM(CASE WHEN owner_id=? THEN bytes ELSE 0 END),0) AS user_b FROM media_assets',(user['id'],)).fetchone()
                    if totals['all_b']+item['bytes']>global_limit or totals['user_b']+item['bytes']>user_limit: raise HTTPException(413,'Limite de armazenamento atingido.')
                    con.execute('INSERT INTO media_assets(id,owner_id,kind,path,thumbnail,bytes,width,height,duration,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                (item['id'],user['id'],item['kind'],item['path'],item['thumbnail'],item['bytes'],item['width'],item['height'],item['duration'],s.now()))
            except Exception: delete_media_files([item]);raise
            return item
        finally:
            if 'filename' in locals(): filename.unlink(missing_ok=True)
            await file.close()

    @app.delete('/api/media/uploads/{asset_id}')
    def delete_upload(asset_id:str,user=Depends(s.member)):
        with s.db() as con:
            row=con.execute('SELECT * FROM media_assets WHERE id=? AND owner_id=? AND post_id IS NULL',(asset_id,user['id'])).fetchone()
            if not row: raise HTTPException(404,'Arquivo indisponível ou já publicado.')
            con.execute('DELETE FROM media_assets WHERE id=?',(asset_id,))
        delete_media_files([dict(row)]);return {'ok':True}

    @app.get('/media/{filename}')
    def serve_media(filename:str,request:Request):
        if not re.fullmatch(r'[a-f0-9]{32}\.(jpg|mp4)',filename): raise HTTPException(404)
        path='/media/'+filename;user=s.session(request);me=user['id'] if user else ''
        visible=False;private=False
        with s.db() as con:
            row=con.execute('SELECT m.*,a.active FROM media_assets m JOIN actors a ON a.id=m.owner_id WHERE m.path=? OR m.thumbnail=?',(path,path)).fetchone()
            if row and row['active']:
                if row['post_id']:
                    s.visible_post(con,row['post_id'],me);visible=True
                elif row['owner_id']==me: visible=True;private=True
            if not visible:
                for row in con.execute('SELECT id FROM actors WHERE active=1 AND (avatar_path=? OR cover_path=?)',(path,path)):
                    if s.can_view_author(con,row['id'],me): visible=True;break
            if not visible:
                for row in con.execute('SELECT p.id FROM posts p JOIN actors a ON a.id=p.author_id WHERE p.image_path=? AND p.hidden=0 AND a.active=1',(path,)):
                    try: s.visible_post(con,row['id'],me);visible=True;break
                    except HTTPException: pass
            if not visible:
                for row in con.execute('SELECT st.author_id FROM stories st JOIN actors a ON a.id=st.author_id WHERE st.image_path=? AND st.expires>? AND a.active=1',(path,time.time())):
                    if s.can_view_author(con,row['author_id'],me):visible=True;break
        if not visible or not (s.MEDIA_DIR/filename).is_file(): raise HTTPException(404)
        return FileResponse(s.MEDIA_DIR/filename,media_type='video/mp4' if filename.endswith('.mp4') else 'image/jpeg',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})

    @app.get('/api/feed')
    def feed_page(request:Request,cursor:str='',limit:int=Query(25,ge=1,le=50),kind:Literal['all','video','following','saved']='all'):
        user=s.session(request);me=user['id'] if user else ''
        if os.getenv('SYNAPSE_ENV')=='production' and s.social_status(user)!='ready':return {'posts':[],'actors':[],'next_cursor':''}
        clauses=["a.kind='human'","a.active=1","p.hidden=0",'NOT EXISTS (SELECT 1 FROM blocks b WHERE (b.user_id=? AND b.target_id=p.author_id) OR (b.target_id=? AND b.user_id=p.author_id))'];params=[me,me]
        clauses.append('(a.account_private=0 OR a.id=? OR EXISTS (SELECT 1 FROM follows f WHERE f.user_id=? AND f.target_id=a.id))');params.extend([me,me])
        if cursor:
            try:
                stamp,pid=base64.urlsafe_b64decode(cursor.encode()+b'='*(-len(cursor)%4)).decode().split('|',1)
                if len(stamp)>40 or not re.fullmatch('[a-f0-9]{32}|[A-Za-z0-9_-]{1,80}',pid):raise ValueError()
            except Exception:raise HTTPException(422,'Cursor inválido.')
            clauses.append('(p.created_at<? OR (p.created_at=? AND p.id<?))');params += [stamp,stamp,pid]
        if kind=='video':clauses.append("EXISTS (SELECT 1 FROM media_assets m WHERE m.post_id=p.id AND m.kind='video')")
        if kind=='following':clauses.append('(p.author_id=? OR EXISTS (SELECT 1 FROM follows f WHERE f.user_id=? AND f.target_id=p.author_id))');params += [me,me]
        if kind=='saved':clauses.append('EXISTS (SELECT 1 FROM bookmarks b WHERE b.user_id=? AND b.post_id=p.id)');params.append(me)
        with s.db() as con:
            rows=con.execute('SELECT p.*, (SELECT COUNT(*) FROM likes l WHERE l.post_id=p.id) AS likes, EXISTS(SELECT 1 FROM likes l WHERE l.post_id=p.id AND l.user_id=?) AS liked FROM posts p JOIN actors a ON a.id=p.author_id WHERE '+ ' AND '.join(clauses)+' ORDER BY p.created_at DESC,p.id DESC LIMIT ?', [me]+params+[limit+1]).fetchall()
            posts=[];authors={}
            for row in rows[:limit]:
                if not s.can_view_author(con,row['author_id'],me):continue
                post=dict(row);post['media']=media_items(con,row['id'])
                post['comments']=[dict(c) for c in con.execute('SELECT c.* FROM comments c JOIN actors a ON a.id=c.author_id WHERE c.post_id=? AND a.active=1 ORDER BY c.created_at LIMIT 100',(row['id'],)) if not me or not s.blocked(con,me,c['author_id'])]
                posts.append(post);authors[row['author_id']]=s.actor_for_viewer(con,s.actor(con,row['author_id']),me)
        next_cursor=base64.urlsafe_b64encode((rows[limit-1]['created_at']+'|'+rows[limit-1]['id']).encode()).decode().rstrip('=') if len(rows)>limit else ''
        return {'posts':posts,'actors':list(authors.values()),'next_cursor':next_cursor}

    @app.get('/api/operator/readiness')
    def readiness(user=Depends(s.admin)):
        checks=deployment_checks()
        return {'checks':checks,'configuration_ready':all(checks.values()),'capabilities':capabilities(),
                'notice':'Configuração não substitui testes de segurança, restauração de backups, revisão das políticas ou aprovação da loja.'}

    @app.get('/api/public-info')
    def public_info():
        return {'operator':os.getenv('OPERATOR_NAME','Operador ainda não configurado'),
                'support_email':os.getenv('SUPPORT_EMAIL',''),'child_safety_email':os.getenv('CHILD_SAFETY_EMAIL',''),
                'policies_reviewed':os.getenv('POLICIES_REVIEWED')=='1','production':production()}

    # Web Push: browser-controlled permission; allow only known vendor endpoints, not arbitrary URLs.
    class PushBody(s.Data):
        endpoint:Annotated[str,StringConstraints(max_length=2048)]
        p256dh:Annotated[str,StringConstraints(pattern=r'^[A-Za-z0-9_-]{80,140}={0,2}$')]
        auth:Annotated[str,StringConstraints(pattern=r'^[A-Za-z0-9_-]{20,30}={0,2}$')]
    def endpoint_allowed(url):
        try:
            u=urlsplit(url);h=(u.hostname or '').lower()
            return u.scheme=='https' and u.port in (None,443) and not u.username and not u.password and not u.fragment and (
                h in ('fcm.googleapis.com','updates.push.services.mozilla.com','web.push.apple.com') or h.endswith('.push.apple.com') or h.endswith('.notify.windows.com'))
        except ValueError:return False
    s.push_endpoint_allowed=endpoint_allowed
    @app.get('/api/push/config')
    def push_config(user=Depends(s.member)):
        enabled=capabilities()['push']
        return {'enabled':enabled,'public_key':os.getenv('VAPID_PUBLIC_KEY','') if enabled else ''}
    @app.post('/api/push/subscriptions')
    def subscribe(data:PushBody,user=Depends(s.member)):
        if not capabilities()['push']:raise HTTPException(503,'Web Push não configurado pelo operador.')
        if not endpoint_allowed(data.endpoint):raise HTTPException(422,'Provedor de notificação não permitido.')
        with s.db() as con:
            prior=con.execute('SELECT user_id FROM push_subscriptions WHERE endpoint=?',(data.endpoint,)).fetchone()
            if prior and prior['user_id']!=user['id']:raise HTTPException(409,'Este navegador está associado a outra conta. Desative as notificações e tente novamente.')
            if con.execute('SELECT COUNT(*) AS n FROM push_subscriptions WHERE user_id=?',(user['id'],)).fetchone()['n']>=5 and not prior:raise HTTPException(422,'Limite de cinco dispositivos por conta.')
            con.execute('INSERT INTO push_subscriptions(id,user_id,endpoint,p256dh,auth,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(endpoint) DO UPDATE SET p256dh=excluded.p256dh,auth=excluded.auth,failures=0',(s.uid(),user['id'],data.endpoint,data.p256dh,data.auth,s.now()))
        return {'ok':True}
    class UnsubscribeBody(s.Data):endpoint:Annotated[str,StringConstraints(max_length=2048)]
    @app.delete('/api/push/subscriptions')
    def unsubscribe(data:UnsubscribeBody,user=Depends(s.member)):
        with s.db() as con:con.execute('DELETE FROM push_subscriptions WHERE user_id=? AND endpoint=?',(user['id'],data.endpoint))
        return {'ok':True}
    def deliver_push_once():
        if not capabilities()['push']:return
        from pywebpush import webpush,WebPushException
        with s.db() as con:
            subscriptions=[dict(r) for r in con.execute('SELECT p.* FROM push_subscriptions p JOIN actors a ON a.id=p.user_id WHERE a.active=1 AND p.last_attempt<? AND p.failures<8 LIMIT 20',(time.time()-60,))]
        for sub in subscriptions:
            with s.db() as con:
                latest=con.execute("SELECT MAX(n.created_at) AS latest FROM notifications n WHERE n.user_id=? AND n.seen=0 AND n.created_at>? AND n.created_at>? AND NOT EXISTS(SELECT 1 FROM blocks b WHERE (b.user_id=n.user_id AND b.target_id=n.actor_id) OR (b.target_id=n.user_id AND b.user_id=n.actor_id))",(sub['user_id'],sub['created_at'],sub['delivered_through'])).fetchone()['latest']
            if not latest:continue
            try:
                webpush(subscription_info={'endpoint':sub['endpoint'],'keys':{'p256dh':sub['p256dh'],'auth':sub['auth']}},data=json.dumps({'title':'Synapse','body':'Você tem novas interações. Abra o aplicativo para conferir.','url':'/?activity=1'}),vapid_private_key=os.getenv('VAPID_PRIVATE_KEY'),vapid_claims={'sub':os.getenv('PUSH_SUBJECT')},timeout=10,ttl=300)
                with s.db() as con:con.execute('UPDATE push_subscriptions SET delivered_through=?,last_attempt=?,failures=0 WHERE id=?',(latest,time.time(),sub['id']))
            except WebPushException as exc:
                with s.db() as con:
                    if exc.response is not None and exc.response.status_code in (404,410):con.execute('DELETE FROM push_subscriptions WHERE id=?',(sub['id'],))
                    else:con.execute('UPDATE push_subscriptions SET last_attempt=?,failures=failures+1 WHERE id=?',(time.time(),sub['id']))
            except Exception:
                with s.db() as con:con.execute('UPDATE push_subscriptions SET last_attempt=?,failures=failures+1 WHERE id=?',(time.time(),sub['id']))
    s.deliver_push_once=deliver_push_once
    async def delivery_worker():
        next_cleanup=time.monotonic()+3600
        while True:
            await asyncio.sleep(10)
            try:await asyncio.to_thread(deliver_push_once)
            except Exception:pass # No secrets or endpoint tokens in logs; operator checks configuration.
            if time.monotonic() >= next_cleanup:
                try:
                    from manage import cleanup
                    await asyncio.to_thread(cleanup)
                except Exception:pass
                next_cleanup=time.monotonic()+3600
    s.delivery_worker=delivery_worker

    # One-to-one WebRTC signalling, authenticated and short-lived. No video recording.
    def calls_enabled():
        if not capabilities()['calls']:raise HTTPException(503,'Chamadas não habilitadas pelo operador.')
    def get_call(con,cid,user):
        row=con.execute('SELECT * FROM calls WHERE id=? AND expires>?',(cid,time.time())).fetchone()
        if not row or user['id'] not in (row['caller_id'],row['callee_id']):raise HTTPException(404,'Chamada indisponível.')
        if s.blocked(con,row['caller_id'],row['callee_id']):raise HTTPException(403,'Chamada bloqueada.')
        s.actor(con,row['caller_id']);s.actor(con,row['callee_id'])
        return row
    class CallBody(s.Data):
        target_id:Annotated[str,StringConstraints(pattern='^[a-f0-9]{32}$')]
        mode:Literal['audio','video']='audio'
    class SignalBody(s.Data):
        kind:Literal['offer','answer','candidate']
        data:Annotated[str,StringConstraints(max_length=60000)]
    @app.get('/api/calls/config')
    def call_config(user=Depends(s.member)):
        calls_enabled();servers=[]
        stun=os.getenv('STUN_URL','')
        if stun.startswith(('stun:','stuns:')):servers.append({'urls':[stun]})
        turn=os.getenv('TURN_URL','');secret=os.getenv('TURN_SHARED_SECRET','')
        if turn.startswith(('turn:','turns:')) and secret:
            username=str(int(time.time())+3600)+':'+user['id']
            credential=base64.b64encode(hmac.new(secret.encode(),username.encode(),hashlib.sha1).digest()).decode()
            servers.append({'urls':[turn],'username':username,'credential':credential})
        return {'iceServers':servers,'iceTransportPolicy':'relay' if os.getenv('CALLS_RELAY_ONLY','1')=='1' else 'all',
                'notice':'Chamadas exigem HTTPS/localhost, permissão de microfone/câmera e TURN configurado entre redes. O par pode ver seu IP quando o modo relay está desativado.'}
    @app.post('/api/calls')
    def start_call(data:CallBody,user=Depends(s.member)):
        calls_enabled();s.rate_limit('calls:'+user['id'],5,600)
        if data.target_id==user['id']:raise HTTPException(422,'Escolha outra conta.')
        with s.db() as con:
            con.execute('BEGIN IMMEDIATE');con.execute('DELETE FROM calls WHERE expires<?',(time.time(),))
            target=s.actor(con,data.target_id)
            if target['seeded'] or s.blocked(con,user['id'],data.target_id) or target['dm_policy']=='off' or (target['dm_policy']=='following' and not con.execute('SELECT 1 FROM follows WHERE user_id=? AND target_id=?',(target['id'],user['id'])).fetchone()):raise HTTPException(403,'Este perfil não permite esta chamada.')
            if con.execute("SELECT 1 FROM calls WHERE status IN ('ringing','active') AND (caller_id IN (?,?) OR callee_id IN (?,?))",(user['id'],target['id'],user['id'],target['id'])).fetchone():raise HTTPException(409,'Um participante já está em chamada.')
            cid=s.uid();con.execute('INSERT INTO calls VALUES(?,?,?,?,?,?,?)',(cid,user['id'],target['id'],data.mode,'ringing',s.now(),time.time()+60))
        return {'id':cid,'status':'ringing'}
    @app.get('/api/calls/pending')
    def pending_calls(user=Depends(s.member)):
        calls_enabled()
        with s.db() as con:
            calls=[]
            for row in con.execute("SELECT * FROM calls WHERE callee_id=? AND status='ringing' AND expires>?",(user['id'],time.time())):
                if not s.blocked(con,row['caller_id'],user['id']):
                    item=dict(row);item['caller']=s.public_actor(s.actor(con,row['caller_id']));calls.append(item)
        return {'calls':calls}
    @app.post('/api/calls/{cid}/accept')
    def accept_call(cid:str,user=Depends(s.member)):
        calls_enabled()
        with s.db() as con:
            row=get_call(con,cid,user)
            if row['callee_id']!=user['id'] or row['status']!='ringing':raise HTTPException(409,'Não é possível aceitar esta chamada.')
            con.execute("UPDATE calls SET status='active',expires=? WHERE id=?",(time.time()+3600,cid))
        return {'ok':True}
    @app.post('/api/calls/{cid}/end')
    def end_call(cid:str,user=Depends(s.member)):
        with s.db() as con:
            get_call(con,cid,user)
            con.execute("UPDATE calls SET status='ended',expires=? WHERE id=?",(time.time()+60,cid));con.execute('DELETE FROM call_signals WHERE call_id=?',(cid,))
        return {'ok':True}
    @app.get('/api/calls/{cid}/signals')
    def read_signals(cid:str,after:int=Query(0,ge=0),user=Depends(s.member)):
        with s.db() as con:
            row=get_call(con,cid,user)
            signals=[{'seq':r['seq'],**json.loads(r['payload'])} for r in con.execute('SELECT * FROM call_signals WHERE call_id=? AND sender_id!=? AND seq>? ORDER BY seq LIMIT 200',(cid,user['id'],after))]
        return {'status':row['status'],'signals':signals}
    @app.post('/api/calls/{cid}/signals')
    def add_signal(cid:str,data:SignalBody,user=Depends(s.member)):
        calls_enabled();s.rate_limit('signal:'+user['id'],120)
        with s.db() as con:
            row=get_call(con,cid,user)
            if row['status']!='active':raise HTTPException(409,'A chamada precisa ser aceita antes de transmitir.')
            if data.kind=='offer' and row['caller_id']!=user['id'] or data.kind=='answer' and row['callee_id']!=user['id']:raise HTTPException(403,'Sinal não autorizado.')
            if con.execute('SELECT COUNT(*) AS n FROM call_signals WHERE call_id=?',(cid,)).fetchone()['n']>=300:raise HTTPException(429,'Limite de sinalização atingido.')
            if data.kind=='candidate':
                try: value=json.loads(data.data)
                except ValueError:raise HTTPException(422,'Sinal inválido.')
                if not isinstance(value,dict) or len(data.data)>4000:raise HTTPException(422,'Sinal inválido.')
            con.execute('INSERT INTO call_signals(call_id,sender_id,payload,created_at) VALUES(?,?,?,?)',(cid,user['id'],json.dumps(data.model_dump()),s.now()))
        return {'ok':True}
