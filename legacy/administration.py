"""Administration and controlled public launch, v0.7.
No credentials or production data are included. MFA unlocks admin privileges, not
regular social sessions. Operator creation/promotion remains a trusted CLI action.
"""
import base64
import hashlib
import hmac
import html
import json
import os
from pathlib import Path
import secrets
import shutil
import struct
import time
from typing import Annotated, Literal
from urllib.parse import urlencode, urlsplit

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import StringConstraints


def totp(secret: str, counter: int) -> str:
    raw = base64.b32decode(secret + '=' * (-len(secret) % 8))
    digest = hmac.new(raw, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return f'{(struct.unpack(">I", digest[offset:offset+4])[0] & 0x7fffffff) % 1000000:06d}'


def install(app, s):
    def production(): return os.getenv('SYNAPSE_ENV') == 'production'
    schema = '''
    CREATE TABLE IF NOT EXISTS operator_roles (
        user_id TEXT PRIMARY KEY REFERENCES operators(user_id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK(role IN ('owner','moderator')));
    CREATE TABLE IF NOT EXISTS operator_security (
        user_id TEXT PRIMARY KEY REFERENCES operators(user_id) ON DELETE CASCADE,
        secret TEXT NOT NULL DEFAULT '', pending TEXT NOT NULL DEFAULT '', pending_expires REAL NOT NULL DEFAULT 0,
        enabled INTEGER NOT NULL DEFAULT 0, last_step INTEGER NOT NULL DEFAULT -1,
        recovery_hashes TEXT NOT NULL DEFAULT '[]');
    CREATE TABLE IF NOT EXISTS admin_grants (
        token_hash TEXT PRIMARY KEY REFERENCES sessions(token_hash) ON DELETE CASCADE,
        user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE, expires REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS site_settings (
        id INTEGER PRIMARY KEY CHECK(id=1), registration_open INTEGER NOT NULL DEFAULT 0,
        maintenance INTEGER NOT NULL DEFAULT 0, uploads_enabled INTEGER NOT NULL DEFAULT 1,
        announcement TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS admin_events (
        id TEXT PRIMARY KEY, actor_id TEXT REFERENCES actors(id) ON DELETE SET NULL,
        actor_label TEXT NOT NULL, action TEXT NOT NULL, target_type TEXT NOT NULL,
        target_id TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS admin_events_date ON admin_events(created_at DESC);
    CREATE TABLE IF NOT EXISTS site_policies (
        kind TEXT PRIMARY KEY, body TEXT NOT NULL, reviewed_by TEXT REFERENCES actors(id) ON DELETE SET NULL,
        reviewed_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS launch_attestations (
        name TEXT PRIMARY KEY, actor_id TEXT REFERENCES actors(id) ON DELETE SET NULL,
        note TEXT NOT NULL, origin TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS durable_rates (
        key_hash TEXT PRIMARY KEY, bucket INTEGER NOT NULL, count INTEGER NOT NULL, expires REAL NOT NULL);
    '''
    old_initialize = s.initialize
    def initialize():
        old_initialize()
        with s.db() as con:
            con.executescript(schema)
            con.execute('INSERT OR IGNORE INTO site_settings VALUES(1,?,0,1,\'\',?)', (0 if production() else 1, s.now()))
        try:
            s.DB_PATH.chmod(0o600)
        except OSError:
            pass
    s.initialize = initialize

    def settings():
        with s.db() as con:
            r = con.execute('SELECT * FROM site_settings WHERE id=1').fetchone()
        return dict(r) if r else dict(registration_open=not production(), maintenance=False, uploads_enabled=True, announcement='')
    s.site_settings = settings

    def role(user):
        with s.db() as con:
            r = con.execute('SELECT COALESCE(r.role,\'owner\') role FROM operators o LEFT JOIN operator_roles r ON r.user_id=o.user_id WHERE o.user_id=?', (user['id'],)).fetchone()
        return r['role'] if r else None
    s.operator_role = role

    def cipher():
        key = os.getenv('ADMIN_ENCRYPTION_KEY', '')
        if not key:
            if production(): raise HTTPException(503, 'Chave de proteção administrativa não configurada.')
            path = s.DB_PATH.parent / 'admin-development.key'
            try:
                with path.open('xb') as f:
                    path.chmod(0o600)
                    f.write(Fernet.generate_key())
            except FileExistsError:
                pass
            key = path.read_text().strip()
        try: return Fernet(key.encode())
        except (ValueError, TypeError): raise HTTPException(503, 'Chave de proteção administrativa inválida.')

    def event(con, user, action, target_type='', target_id='', reason=''):
        con.execute('INSERT INTO admin_events VALUES(?,?,?,?,?,?,?,?)',
                    (s.uid(), user['id'], '@'+user['handle'], action, target_type, target_id, reason, s.now()))
    s.admin_event = event

    def session_hash(request): return hashlib.sha256(request.cookies.get('synapse_session', '').encode()).hexdigest()
    def require_elevation(request, user):
        with s.db() as con:
            r = con.execute('SELECT expires FROM admin_grants WHERE token_hash=? AND user_id=? AND expires>?',
                            (session_hash(request), user['id'], time.time())).fetchone()
            security = con.execute('SELECT enabled FROM operator_security WHERE user_id=?', (user['id'],)).fetchone()
        if not r or (production() and (not security or not security['enabled'])):
            raise HTTPException(403, 'Desbloqueie o painel em /admin com senha e segundo fator.')
        return r['expires']
    s.require_admin_elevation = require_elevation

    def operator(user=Depends(s.member)):
        if not role(user): raise HTTPException(403, 'Conta sem permissão administrativa.')
        if production() and not user['email_verified']:
            raise HTTPException(403, 'Confirme o e-mail da conta responsável antes de administrar.')
        return user
    def staff(request: Request, user=Depends(operator)):
        require_elevation(request, user)
        return user
    def owner(user=Depends(staff)):
        if role(user) != 'owner': raise HTTPException(403, 'Somente o responsável pode alterar esta configuração.')
        return user

    def grant(con, request, user):
        expires = time.time()+900
        con.execute('INSERT OR REPLACE INTO admin_grants VALUES(?,?,?)', (session_hash(request),user['id'],expires))
        return expires

    def check_password(user, password):
        s.rate_limit('admin-unlock:'+user['id'],5,300)
        if not s.password_ok(password, user['password_hash']): raise HTTPException(401, 'Não foi possível confirmar suas credenciais.')

    def check_code(con, user_id, secret, code, last_step):
        step = int(time.time()//30)
        for counter in (step-1,step,step+1):
            if counter > last_step and hmac.compare_digest(totp(secret,counter),code):
                return counter
        raise HTTPException(401, 'Código inválido ou já utilizado. Aguarde o próximo código do autenticador.')

    class Credentials(s.Data):
        password: Annotated[str, StringConstraints(min_length=1,max_length=128)]
        code: Annotated[str, StringConstraints(max_length=32)] = ''
    class Code(s.Data):
        code: Annotated[str, StringConstraints(pattern=r'^\d{6}$')]
    class Reason(s.Data):
        reason: Annotated[str, StringConstraints(strip_whitespace=True,min_length=8,max_length=600)]
    class UserAction(Reason):
        action: Literal['suspend','reactivate','revoke_sessions']
    class RoleAction(Reason):
        role: Literal['member','moderator']
    class PostAction(Reason):
        hidden: bool
    class ReportAction(Reason):
        action: Literal['remove','dismiss']
    class SettingsBody(Reason):
        registration_open: bool
        maintenance: bool
        uploads_enabled: bool
        announcement: Annotated[str,StringConstraints(strip_whitespace=True,max_length=300)] = ''
    class PolicyBody(Reason):
        body: Annotated[str,StringConstraints(strip_whitespace=True,min_length=300,max_length=30000)]
        reviewed: Literal[True]
    class AttestBody(s.Data):
        note: Annotated[str,StringConstraints(strip_whitespace=True,min_length=20,max_length=800)]
        confirmed: Literal[True]

    @app.get('/admin', include_in_schema=False)
    @app.get('/admin/', include_in_schema=False)
    def admin_page():
        return FileResponse(s.ROOT/'web'/'admin.html', headers={'Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow'})

    @app.get('/api/manage/session')
    def admin_session(request: Request, user=Depends(s.member)):
        r = role(user)
        if not r: raise HTTPException(403, 'Esta conta não tem acesso ao painel. A autorização é feita no servidor de confiança.')
        with s.db() as con:
            sec=con.execute('SELECT enabled FROM operator_security WHERE user_id=?',(user['id'],)).fetchone()
            elevated=con.execute('SELECT expires FROM admin_grants WHERE token_hash=? AND expires>?',(session_hash(request),time.time())).fetchone()
        return {'name':user['name'],'handle':user['handle'],'role':r,'csrf':user['csrf'],
                'email_verified':bool(user['email_verified']),'mfa_enabled':bool(sec and sec['enabled']),
                'mfa_required':production(),'unlocked_until':elevated['expires'] if elevated else 0,'production':production()}

    @app.post('/api/manage/security/enroll')
    def enroll(data: Credentials, user=Depends(operator)):
        check_password(user,data.password)
        secret=base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')
        encrypted=cipher().encrypt(secret.encode()).decode()
        with s.db() as con:
            row=con.execute('SELECT enabled FROM operator_security WHERE user_id=?',(user['id'],)).fetchone()
            if row and row['enabled']: raise HTTPException(409, 'Segundo fator já ativado. Recuperação exige um código de reserva ou o console do servidor.')
            con.execute('INSERT OR IGNORE INTO operator_security(user_id) VALUES(?)',(user['id'],))
            con.execute('UPDATE operator_security SET pending=?,pending_expires=? WHERE user_id=?',(encrypted,time.time()+600,user['id']))
            event(con,user,'mfa_enrollment_started','operator',user['id'])
        uri='otpauth://totp/Synapse:'+user['handle']+'?'+urlencode({'secret':secret,'issuer':'Synapse','algorithm':'SHA1','digits':6,'period':30})
        return {'secret':secret,'uri':uri,'expires_in':600}

    @app.post('/api/manage/security/confirm')
    def confirm(data: Code, request: Request, user=Depends(operator)):
        s.rate_limit('admin-code:'+user['id'],8,300)
        recovery=[secrets.token_hex(8) for _ in range(8)]
        with s.db() as con:
            con.execute('BEGIN IMMEDIATE')
            row=con.execute('SELECT * FROM operator_security WHERE user_id=?',(user['id'],)).fetchone()
            if not row or row['enabled'] or not row['pending'] or row['pending_expires']<time.time():
                raise HTTPException(409,'Inicie novamente a configuração do autenticador.')
            secret=cipher().decrypt(row['pending'].encode()).decode()
            step=check_code(con,user['id'],secret,data.code,-1)
            con.execute('UPDATE operator_security SET secret=pending,pending=\'\',pending_expires=0,enabled=1,last_step=?,recovery_hashes=? WHERE user_id=?',
                        (step,json.dumps([hashlib.sha256(k.encode()).hexdigest() for k in recovery]),user['id']))
            expiry=grant(con,request,user)
            event(con,user,'mfa_enabled','operator',user['id'])
        return {'ok':True,'recovery_codes':recovery,'unlocked_until':expiry}

    @app.post('/api/manage/unlock')
    def unlock(data: Credentials, request: Request, user=Depends(operator)):
        check_password(user,data.password)
        with s.db() as con:
            con.execute('BEGIN IMMEDIATE')
            row=con.execute('SELECT * FROM operator_security WHERE user_id=?',(user['id'],)).fetchone()
            if row and row['enabled']:
                hashes=json.loads(row['recovery_hashes'])
                digest=hashlib.sha256(data.code.strip().lower().encode()).hexdigest()
                if len(data.code)==16 and digest in hashes:
                    hashes.remove(digest)
                    con.execute('UPDATE operator_security SET recovery_hashes=? WHERE user_id=?',(json.dumps(hashes),user['id']))
                    event(con,user,'mfa_recovery_used','operator',user['id'])
                else:
                    try: secret=cipher().decrypt(row['secret'].encode()).decode()
                    except InvalidToken: raise HTTPException(503,'Chave administrativa incorreta. Verifique a chave original no servidor.')
                    step=check_code(con,user['id'],secret,data.code,row['last_step'])
                    con.execute('UPDATE operator_security SET last_step=? WHERE user_id=?',(step,user['id']))
            elif production(): raise HTTPException(403,'Ative o segundo fator antes de desbloquear o painel.')
            expiry=grant(con,request,user)
            event(con,user,'admin_unlocked','session','', 'Acesso temporário por 15 minutos.')
        return {'ok':True,'unlocked_until':expiry}

    @app.post('/api/manage/lock')
    def lock(request: Request, user=Depends(s.member)):
        with s.db() as con: con.execute('DELETE FROM admin_grants WHERE token_hash=?',(session_hash(request),))
        return {'ok':True}

    @app.get('/api/site')
    def site_info():
        st=s.public_site_settings()
        return {'name':'Synapse','version':'0.9.0','production':production(),**{k:st[k] for k in ('registration_open','maintenance','uploads_enabled','announcement')},
                'support_email':os.getenv('SUPPORT_EMAIL','')}

    @app.get('/api/manage/overview')
    def overview(user=Depends(staff)):
        with s.db() as con:
            def count(sql, args=()): return con.execute(sql,args).fetchone()[0]
            counts={
                'users':count("SELECT COUNT(*) FROM actors WHERE kind='human' AND seeded=0"),
                'active_users':count("SELECT COUNT(*) FROM actors WHERE kind='human' AND seeded=0 AND active=1"),
                'verified_users':count("SELECT COUNT(*) FROM actors WHERE kind='human' AND seeded=0 AND email_verified=1"),
                'posts':count("SELECT COUNT(*) FROM posts p JOIN actors a ON a.id=p.author_id WHERE a.seeded=0"),
                'hidden_posts':count('SELECT COUNT(*) FROM posts WHERE hidden=1'),
                'reports':count("SELECT COUNT(*) FROM reports WHERE status='open'")+count("SELECT COUNT(*) FROM content_reports WHERE status='open'"),
                'media_bytes':sum(p.stat().st_size for p in s.MEDIA_DIR.glob('*') if p.is_file()),
                'mail_failures_24h':count("SELECT COUNT(*) FROM audit WHERE action='mail_delivery_failed' AND created_at>?",(s.datetime.fromtimestamp(time.time()-86400,s.timezone.utc).isoformat(),)),
            }
            events=[dict(r) for r in con.execute('SELECT * FROM admin_events ORDER BY created_at DESC,id DESC LIMIT 8')]
            daily=[dict(r) for r in con.execute("SELECT substr(created_at,1,10) day,COUNT(*) users FROM actors WHERE seeded=0 AND created_at>=? GROUP BY day ORDER BY day",(s.datetime.fromtimestamp(time.time()-86400*7,s.timezone.utc).isoformat(),))]
        return {'counts':counts,'settings':settings(),'events':events,'daily_signups':daily,'version':'0.9.0','production':production()}

    @app.get('/api/manage/users')
    def users(q:str=Query('',max_length=100),status:Literal['all','active','suspended']='all',page:int=Query(1,ge=1),user=Depends(staff)):
        where="a.kind='human' AND a.seeded=0 AND (instr(lower(a.handle),lower(?))>0 OR instr(lower(a.name),lower(?))>0)"
        params=[q,q]
        if status!='all': where+=' AND a.active=?'; params.append(1 if status=='active' else 0)
        with s.db() as con:
            total=con.execute('SELECT COUNT(*) FROM actors a WHERE '+where,params).fetchone()[0]
            rows=[dict(r) for r in con.execute('''SELECT a.id,a.name,a.handle,a.email,a.email_verified,a.active,a.created_at,
              CASE WHEN o.user_id IS NULL THEN 'member' ELSE COALESCE(r.role,'owner') END role,
              (SELECT COUNT(*) FROM posts p WHERE p.author_id=a.id) posts
              FROM actors a LEFT JOIN operators o ON o.user_id=a.id LEFT JOIN operator_roles r ON r.user_id=a.id WHERE '''+where+' ORDER BY a.created_at DESC,a.id DESC LIMIT 25 OFFSET ?',params+[(page-1)*25])]
        if role(user)!='owner':
            for r in rows: r.pop('email',None)
        return {'items':rows,'total':total,'page':page,'page_size':25}

    def protect_user(con, user, target_id):
        target=con.execute('SELECT id,handle,seeded FROM actors WHERE id=?',(target_id,)).fetchone()
        if not target or target['seeded']:raise HTTPException(404,'Conta real não encontrada.')
        if target_id==user['id']: raise HTTPException(409,'Não é permitido realizar esta ação na própria conta.')
        op=con.execute('SELECT COALESCE(r.role,\'owner\') role FROM operators o LEFT JOIN operator_roles r ON o.user_id=r.user_id WHERE o.user_id=?',(target_id,)).fetchone()
        if op and (op['role']=='owner' or role(user)!='owner'):
            raise HTTPException(409,'Conta administrativa protegida. Use o console de confiança para transferir a responsabilidade.')
        return target

    @app.post('/api/manage/users/{target_id}/actions')
    def user_action(target_id:str,data:UserAction,user=Depends(staff)):
        with s.db() as con:
            protect_user(con,user,target_id)
            if data.action in ('suspend','reactivate'):
                con.execute('UPDATE actors SET active=? WHERE id=?',(1 if data.action=='reactivate' else 0,target_id))
            if data.action!='reactivate':
                con.execute('DELETE FROM sessions WHERE user_id=?',(target_id,))
                con.execute('DELETE FROM auth_tokens WHERE user_id=?',(target_id,))
                con.execute('DELETE FROM push_subscriptions WHERE user_id=?',(target_id,))
                con.execute('DELETE FROM calls WHERE caller_id=? OR callee_id=?',(target_id,target_id))
            event(con,user,'user_'+data.action,'user',target_id,data.reason)
        return {'ok':True}

    @app.post('/api/manage/users/{target_id}/role')
    def user_role(target_id:str,data:RoleAction,user=Depends(owner)):
        with s.db() as con:
            protect_user(con,user,target_id)
            target=con.execute('SELECT active,email_verified FROM actors WHERE id=?',(target_id,)).fetchone()
            if data.role=='moderator':
                if not target['active'] or not target['email_verified']:raise HTTPException(409,'O moderador precisa estar ativo e confirmar seu e-mail.')
                con.execute('INSERT OR IGNORE INTO operators VALUES(?,?)',(target_id,s.now()))
                con.execute("INSERT OR REPLACE INTO operator_roles VALUES(?,'moderator')",(target_id,))
            else:con.execute('DELETE FROM operators WHERE user_id=?',(target_id,))
            con.execute('DELETE FROM admin_grants WHERE user_id=?',(target_id,))
            event(con,user,'role_'+data.role,'user',target_id,data.reason)
        return {'ok':True}

    @app.get('/api/manage/posts')
    def posts(q:str=Query('',max_length=100),status:Literal['all','visible','hidden']='all',page:int=Query(1,ge=1),user=Depends(staff)):
        where="a.seeded=0 AND (instr(lower(p.body),lower(?))>0 OR instr(lower(a.handle),lower(?))>0)";params=[q,q]
        if status!='all':where+=' AND p.hidden=?';params.append(1 if status=='hidden' else 0)
        with s.db() as con:
            total=con.execute('SELECT COUNT(*) FROM posts p JOIN actors a ON a.id=p.author_id WHERE '+where,params).fetchone()[0]
            rows=[dict(r) for r in con.execute('SELECT p.id,p.body,p.created_at,p.hidden,p.link_url,p.image_path,a.handle,a.name FROM posts p JOIN actors a ON a.id=p.author_id WHERE '+where+' ORDER BY p.created_at DESC,p.id DESC LIMIT 20 OFFSET ?',params+[(page-1)*20])]
        return {'items':rows,'total':total,'page':page,'page_size':20}

    @app.post('/api/manage/posts/{post_id}')
    def post_action(post_id:str,data:PostAction,user=Depends(staff)):
        with s.db() as con:
            if not con.execute('SELECT 1 FROM posts WHERE id=?',(post_id,)).fetchone():raise HTTPException(404,'Publicação não encontrada.')
            con.execute('UPDATE posts SET hidden=? WHERE id=?',(int(data.hidden),post_id))
            event(con,user,'post_hidden' if data.hidden else 'post_restored','post',post_id,data.reason)
        return {'ok':True}

    @app.get('/api/manage/reports')
    def reports(status:Literal['all','open','removed','dismissed']='open',page:int=Query(1,ge=1),user=Depends(staff)):
        # Only specifically reported messages are exposed, never arbitrary inboxes/collections.
        union="SELECT id,reporter_id,'post' kind,post_id target_id,reason,status,created_at FROM reports UNION ALL SELECT id,reporter_id,kind,target_id,reason,status,created_at FROM content_reports"
        where=' WHERE status=?' if status!='all' else '';args=[status] if status!='all' else []
        with s.db() as con:
            total=con.execute('SELECT COUNT(*) FROM ('+union+')'+where,args).fetchone()[0]
            rows=[dict(r) for r in con.execute('SELECT * FROM ('+union+')'+where+' ORDER BY created_at DESC,id DESC LIMIT 20 OFFSET ?',args+[(page-1)*20])]
            for r in rows:
                table={'post':'posts','profile':'actors','comment':'comments','story':'stories','message':'messages'}[r['kind']]
                target=con.execute('SELECT * FROM '+table+' WHERE id=?',(r['target_id'],)).fetchone()
                r['content']=(target['bio'] if r['kind']=='profile' else target['body']) if target else '[Conteúdo não disponível]'
                reporter=con.execute('SELECT handle FROM actors WHERE id=?',(r['reporter_id'],)).fetchone()
                r['reporter_handle']=reporter['handle'] if reporter else 'Conta removida'
        return {'items':rows,'total':total,'page':page,'page_size':20}

    @app.post('/api/manage/reports/{report_id}')
    def report_action(report_id:str,data:ReportAction,user=Depends(staff)):
        with s.db() as con:
            row=con.execute('SELECT status FROM reports WHERE id=?',(report_id,)).fetchone() or con.execute('SELECT status FROM content_reports WHERE id=?',(report_id,)).fetchone()
            if not row:raise HTTPException(404,'Denúncia não encontrada.')
            if row['status']!='open':raise HTTPException(409,'A denúncia já foi analisada.')
        result=s.moderate(report_id,s.ModerateBody(action=data.action),user)
        with s.db() as con:event(con,user,'report_'+data.action,'report',report_id,data.reason)
        return result

    @app.get('/api/manage/audit')
    def audit(page:int=Query(1,ge=1),user=Depends(owner)):
        with s.db() as con:
            total=con.execute('SELECT COUNT(*) FROM admin_events').fetchone()[0]
            rows=[dict(r) for r in con.execute('SELECT * FROM admin_events ORDER BY created_at DESC,id DESC LIMIT 30 OFFSET ?',((page-1)*30,))]
        return {'items':rows,'total':total,'page':page,'page_size':30}

    policy_titles={'terms':'Termos de uso','privacy':'Privacidade','safety':'Regras e segurança'}
    def policy_response(kind):
        with s.db() as con:row=con.execute('SELECT * FROM site_policies WHERE kind=?',(kind,)).fetchone()
        if not row: return FileResponse(s.ROOT/'web'/(kind+'.html'),headers={'Cache-Control':'no-store'})
        text=''.join('<p>'+html.escape(p).replace('\n','<br>')+'</p>' for p in row['body'].split('\n\n'))
        title=policy_titles[kind]
        page=f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · Synapse</title><link rel="stylesheet" href="/legal.css"><script src="/legal.js" defer></script></head><body><header><a href="/">synapse.</a><p>Atualizado em {html.escape(row['reviewed_at'][:10])}</p></header><main><h1>{title}</h1>{text}<section><h2>Contato</h2><p id="operator-info"></p></section></main><nav><a href="/terms.html">Termos</a><a href="/privacy.html">Privacidade</a><a href="/safety.html">Segurança</a><a href="/delete-account.html">Excluir conta</a></nav></body></html>'''
        return HTMLResponse(page,headers={'Cache-Control':'no-store'})
    @app.get('/terms.html')
    def terms():return policy_response('terms')
    @app.get('/privacy.html')
    def privacy():return policy_response('privacy')
    @app.get('/safety.html')
    def safety():return policy_response('safety')

    @app.get('/api/manage/policies')
    def policies(user=Depends(owner)):
        with s.db() as con:rows={r['kind']:dict(r) for r in con.execute('SELECT * FROM site_policies')}
        return {'items':[{'kind':k,'title':title,**rows.get(k,{'body':'','reviewed_at':None})} for k,title in policy_titles.items()]}
    @app.put('/api/manage/policies/{kind}')
    def save_policy(kind:Literal['terms','privacy','safety'],data:PolicyBody,user=Depends(owner)):
        with s.db() as con:
            con.execute('INSERT OR REPLACE INTO site_policies VALUES(?,?,?,?)',(kind,data.body,user['id'],s.now()))
            con.execute('INSERT OR REPLACE INTO policy_reviews VALUES(?,?,?,?)',(kind,'0.9',hashlib.sha256(data.body.encode()).hexdigest(),s.now()))
            event(con,user,'policy_published','policy',kind,data.reason)
        return {'ok':True}

    attestations={'audience_review':'Público e obrigações de privacidade/idade avaliados; proteções aplicáveis implementadas antes de admitir menores',
                  'email_test':'Confirmação e recuperação recebidas em uma caixa real',
                  'backup_restore':'Backup externo criado e restauração testada em pasta nova',
                  'moderation':'Responsável por denúncias, recursos e segurança infantil definido',
                  'browser_test':'Cadastro, postagem e mensagens testados no domínio HTTPS'}
    def launch_checks():
        basic=s.deployment_checks()
        checks=[{'id':k,'ok':bool(v),'kind':'configuration'} for k,v in basic.items() if k!='policies_reviewed']
        with s.db() as con:
            seed=con.execute('SELECT COUNT(*) FROM actors WHERE seeded=1').fetchone()[0]
            secured=con.execute("SELECT 1 FROM operators o JOIN actors a ON a.id=o.user_id JOIN operator_security sec ON sec.user_id=o.user_id LEFT JOIN operator_roles r ON r.user_id=o.user_id WHERE a.active=1 AND a.email_verified=1 AND sec.enabled=1 AND COALESCE(r.role,'owner')='owner'").fetchone()
            policy_count=con.execute('SELECT COUNT(*) FROM site_policies WHERE kind IN (\'terms\',\'privacy\',\'safety\')').fetchone()[0]
            ack={r['name']:dict(r) for r in con.execute('SELECT * FROM launch_attestations WHERE origin=?',(s.PUBLIC_ORIGIN,))}
        checks += [{'id':'production_mode','ok':production(),'kind':'configuration'},
                   {'id':'demo_records_removed','ok':seed==0,'kind':'configuration'},
                   {'id':'owner_mfa_verified','ok':bool(secured),'kind':'configuration'},
                   {'id':'public_policies','ok':policy_count==3,'kind':'operator_review'}]
        checks += [{'id':k,'ok':k in ack,'kind':'operator_attestation','label':v,'record':ack.get(k)} for k,v in attestations.items()]
        return checks
    s.launch_checks=launch_checks

    @app.get('/api/manage/launch')
    def launch(user=Depends(owner)):
        checks=s.launch_checks()
        return {'checks':checks,'can_open':all(c['ok'] for c in checks),'settings':settings(),
                'notice':'Configuração e declarações do responsável não equivalem a auditoria independente, certificação jurídica ou teste de capacidade.'}

    @app.post('/api/manage/launch/{name}')
    def attest(name:str,data:AttestBody,user=Depends(owner)):
        if name not in attestations:raise HTTPException(404,'Verificação não encontrada.')
        with s.db() as con:
            con.execute('INSERT OR REPLACE INTO launch_attestations VALUES(?,?,?,?,?)',(name,user['id'],data.note,s.PUBLIC_ORIGIN,s.now()))
            event(con,user,'launch_attestation','check',name,data.note)
        return {'ok':True}

    @app.get('/api/manage/settings')
    def get_settings(user=Depends(owner)): return settings()

    @app.patch('/api/manage/settings')
    def save_settings(data:SettingsBody,user=Depends(owner)):
        if data.registration_open and production() and not all(c['ok'] for c in s.launch_checks()):
            raise HTTPException(409,'Existem pendências na aba Lançamento. Conclua-as antes de abrir novos cadastros.')
        with s.db() as con:
            con.execute('UPDATE site_settings SET registration_open=?,maintenance=?,uploads_enabled=?,announcement=?,updated_at=? WHERE id=1',
                        (data.registration_open,data.maintenance,data.uploads_enabled,data.announcement,s.now()))
            event(con,user,'site_settings_changed','site','',data.reason)
        return {'ok':True}

    @app.post('/api/manage/remove-examples')
    def remove_examples(data:Reason,user=Depends(owner)):
        with s.db() as con:
            total=con.execute('SELECT COUNT(*) FROM actors WHERE seeded=1').fetchone()[0]
            con.execute('DELETE FROM actors WHERE seeded=1')
            event(con,user,'examples_removed','site','',data.reason)
        return {'ok':True,'removed_profiles':total}

    @app.get('/api/manage/health')
    def managed_health(user=Depends(owner)):
        with s.db() as con:
            valid=con.execute('PRAGMA quick_check(1)').fetchone()[0]=='ok'
            pending=con.execute('SELECT COUNT(*) FROM media_assets WHERE post_id IS NULL').fetchone()[0]
        usage=shutil.disk_usage(s.DB_PATH.parent)
        return {'database_ok':valid,'free_bytes':usage.free,'database_bytes':s.DB_PATH.stat().st_size,
                'unattached_uploads':pending,'capabilities':s.capabilities(),'mail_mode':s.MAIL_MODE,
                'backup':'Acesse /operacao para backups criptografados e consulte docs/RECUPERACAO-0.9.md. O utilitário legado ZIP ainda exige o servidor parado.',
                'deployment_checks':s.deployment_checks()}

    old_checks=s.deployment_checks
    def deployment_checks():
        checks=old_checks()
        key=os.getenv('ADMIN_ENCRYPTION_KEY','')
        try: Fernet(key.encode());checks['admin_encryption_key']=True
        except (ValueError,TypeError):checks['admin_encryption_key']=False
        checks['data_outside_web']=not s.DB_PATH.resolve().is_relative_to((s.ROOT/'web').resolve()) and not s.MEDIA_DIR.resolve().is_relative_to((s.ROOT/'web').resolve())
        return checks
    s.deployment_checks=deployment_checks
    def validate_deployment():
        if not production(): return
        # Start with signup closed to allow the owner to review policies and enroll MFA.
        required=('https_origin','demo_disabled','smtp_configured','operator_account','admin_encryption_key','data_outside_web')
        checks=deployment_checks()
        missing=[k for k in required if not checks[k]]
        if missing:raise RuntimeError('Public launch blocked; production configuration missing: '+', '.join(missing)+'. See docs/OPERACAO.md.')
        if settings()['registration_open'] and not all(c['ok'] for c in s.launch_checks()):
            with s.db() as con: con.execute('UPDATE site_settings SET registration_open=0 WHERE id=1')
    s.validate_deployment=validate_deployment

    old_rate=s.rate_limit
    def durable_rate(key, maximum, seconds=60):
        if not production():return old_rate(key,maximum,seconds)
        # Single-instance SQLite; hashed identifiers, bounded retention, survives restart.
        stamp=time.time();bucket=int(stamp//seconds);hashed=hashlib.sha256((str(seconds)+':'+key).encode()).hexdigest()
        with s.db() as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('DELETE FROM durable_rates WHERE expires<?',(stamp,))
            r=con.execute('SELECT bucket,count FROM durable_rates WHERE key_hash=?',(hashed,)).fetchone()
            n=r['count'] if r and r['bucket']==bucket else 0
            if n>=maximum:raise HTTPException(429,'Muitas tentativas. Aguarde antes de tentar novamente.',headers={'Retry-After':str(max(1,int(seconds-stamp%seconds)))})
            con.execute('INSERT OR REPLACE INTO durable_rates VALUES(?,?,?,?)',(hashed,bucket,n+1,(bucket+1)*seconds))
    s.rate_limit=durable_rate
