"""Release 0.9 safety controls. A signed age receipt is not legal certification.
The verifier is an EXTERNAL integration with an explicit documented contract.
No birth dates, identity documents or biometric images are collected by this module.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Annotated, Literal
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import StringConstraints, Field


def unb64(value: str) -> bytes:
    if not re.fullmatch(r'[A-Za-z0-9_-]+', value): raise ValueError('Invalid base64url')
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def install(app, s):
    def production(): return os.getenv('SYNAPSE_ENV') == 'production'
    def enforced(): return production() or os.getenv('AGE_ENFORCED') == '1'
    schema = '''
    CREATE TABLE IF NOT EXISTS follow_requests (
      requester_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
      target_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
      created_at TEXT NOT NULL, PRIMARY KEY(requester_id,target_id));
    CREATE TABLE IF NOT EXISTS session_devices (
      id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL REFERENCES sessions(token_hash) ON DELETE CASCADE,
      created_at TEXT NOT NULL, device TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS age_challenges (
      challenge_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
      expires REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS guardian_invites (
      token_hash TEXT PRIMARY KEY, child_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
      email_hash TEXT NOT NULL, expires REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS guardianships (
      child_id TEXT PRIMARY KEY REFERENCES actors(id) ON DELETE CASCADE,
      guardian_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
      paused INTEGER NOT NULL DEFAULT 0, accepted_at TEXT NOT NULL,
      CHECK(child_id != guardian_id));
    CREATE INDEX IF NOT EXISTS guardian_accounts ON guardianships(guardian_id);
    CREATE TABLE IF NOT EXISTS support_tickets (
      id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
      kind TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'open', reply TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS policy_reviews (kind TEXT PRIMARY KEY REFERENCES site_policies(kind) ON DELETE CASCADE, release TEXT NOT NULL, body_hash TEXT NOT NULL, reviewed_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS support_open ON support_tickets(status,created_at);
    CREATE TABLE IF NOT EXISTS integration_checks (
      name TEXT PRIMARY KEY, origin TEXT NOT NULL, checked_at REAL NOT NULL, detail TEXT NOT NULL);
    '''
    previous_initialize = s.initialize
    def initialize():
        previous_initialize()
        with s.db() as con:
            con.executescript(schema)
            fields = {r['name'] for r in con.execute('PRAGMA table_info(actors)')}
            for key, ddl in {'account_private':'INTEGER NOT NULL DEFAULT 0',
                             'age_band':"TEXT NOT NULL DEFAULT 'unknown'",
                             'age_verified_until':'REAL NOT NULL DEFAULT 0',
                             'age_provider':"TEXT NOT NULL DEFAULT ''"}.items():
                if key not in fields: con.execute(f'ALTER TABLE actors ADD COLUMN {key} {ddl}')
            check_fields={r['name'] for r in con.execute('PRAGMA table_info(integration_checks)')}
            if 'fingerprint' not in check_fields:con.execute("ALTER TABLE integration_checks ADD COLUMN fingerprint TEXT NOT NULL DEFAULT ''")
            # Existing public profiles are preserved; new production profiles are private.
            con.execute('CREATE INDEX IF NOT EXISTS followers_target ON follows(target_id,user_id)')
            con.execute('CREATE INDEX IF NOT EXISTS blocks_target ON blocks(target_id,user_id)')
            con.execute('CREATE INDEX IF NOT EXISTS likes_post ON likes(post_id,user_id)')
            con.execute('CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id,expires)')
    s.initialize = initialize

    def is_minor(user): return user and user.get('age_band') in ('13_15','16_17')
    def age_current(user): return bool(user and user.get('age_verified_until', 0) > time.time())
    def social_status(user):
        if not user: return 'login_required'
        if not enforced(): return 'ready'
        if not user['email_verified']: return 'email_required'
        if not age_current(user): return 'age_required'
        if user['age_band'] == 'under_13': return 'age_not_supported'
        if is_minor(user):
            if os.getenv('MINOR_ACCOUNTS_ENABLED','0') != '1': return 'minors_not_enabled'
            with s.db() as con:
                link = con.execute('SELECT g.paused,a.* FROM guardianships g JOIN actors a ON a.id=g.guardian_id WHERE g.child_id=?', (user['id'],)).fetchone()
            if not link or not link['active'] or not link['email_verified'] or not age_current(dict(link)) or link['age_band'] != 'adult': return 'guardian_required'
            if link['paused']: return 'guardian_paused'
        return 'ready'
    s.social_status = social_status
    s.is_minor = is_minor
    messages = {'email_required':'Confirme seu e-mail na Central de segurança.',
                'age_required':'Conclua a aferição de faixa etária na Central de segurança.',
                'age_not_supported':'Esta versão não admite contas sociais de menores de 13 anos.',
                'minors_not_enabled':'O acesso social de menores ainda não foi habilitado nesta instalação.',
                'guardian_required':'Vincule um responsável com conta adulta verificada na Central de segurança.',
                'guardian_paused':'O responsável pausou as atividades sociais desta conta.'}
    def require_social(user):
        state = social_status(user)
        if state != 'ready': raise HTTPException(403, messages.get(state,'Entre na sua conta.'))
    s.require_social = require_social

    def terms_version(con):
        row = con.execute("SELECT body FROM site_policies WHERE kind='terms'").fetchone()
        return 'terms-sha256:'+hashlib.sha256(row['body'].encode()).hexdigest() if row else s.TERMS_VERSION
    s.current_terms_version = terms_version
    def guard_member(request, user):
        path = request.url.path
        # Account deletion, blocking, reporting, support and administration stay accessible.
        social = path.startswith(('/api/posts','/api/feed','/api/messages','/api/stories','/api/media','/api/calls','/api/links')) or path == '/api/profile' or path.endswith('/follow')
        if request.method == 'DELETE' or path.endswith('/report'): social = False
        if social:
            require_social(user)
            if request.method not in ('GET','HEAD') and enforced():
                with s.db() as con: current = terms_version(con)
                if user['terms_version'] != current: raise HTTPException(409,'Os Termos foram atualizados. Revise e aceite na Central de segurança antes de publicar.')
        if is_minor(user) and path.startswith(('/api/messages','/api/calls')) and request.method != 'DELETE':
            raise HTTPException(403,'Mensagens diretas e chamadas estão desativadas para contas de menores nesta versão.')
    s.guard_member = guard_member

    def can_view_author(con, author_id, me):
        if me == author_id: return True
        row = con.execute('SELECT active,account_private FROM actors WHERE id=?',(author_id,)).fetchone()
        if not row or not row['active'] or (me and s.blocked(con,me,author_id)): return False
        if enforced():
            viewer=con.execute('SELECT * FROM actors WHERE id=?',(me,)).fetchone()
            if not viewer or social_status(dict(viewer)) != 'ready': return False
            if is_minor(dict(viewer)):
                guardian=con.execute('SELECT guardian_id FROM guardianships WHERE child_id=?',(me,)).fetchone()
                approved=con.execute('SELECT 1 FROM follows f JOIN follows reverse ON reverse.user_id=f.target_id AND reverse.target_id=f.user_id WHERE f.user_id=? AND f.target_id=?',(me,author_id)).fetchone()
                if not approved and (not guardian or guardian['guardian_id']!=author_id):return False
        return not row['account_private'] or bool(me and con.execute('SELECT 1 FROM follows WHERE user_id=? AND target_id=?',(me,author_id)).fetchone())
    s.can_view_author = can_view_author

    old_public_actor=s.public_actor
    def public_actor(a):
        result=old_public_actor(a)
        result['account_private']=bool(a['account_private'])
        return result
    s.public_actor=public_actor
    def actor_for_viewer(con, a, me):
        result=public_actor(a)
        if not can_view_author(con,a['id'],me):
            result.update(bio='',cover_path='',avatar_path='',website='',interests=[],restricted=True)
        return result
    s.actor_for_viewer=actor_for_viewer
    old_visible=s.visible_post
    def visible_post(con,pid,me):
        row=old_visible(con,pid,me)
        if not can_view_author(con,row['author_id'],me): raise HTTPException(404,'Publicação indisponível.')
        return row
    s.visible_post=visible_post

    def integration_fingerprint(name):
        fields=('TURNSTILE_SITE_KEY','TURNSTILE_SECRET_KEY') if name=='turnstile' else ('AGE_PROVIDER_URL','AGE_PROVIDER_ID','AGE_PUBLIC_KEY')
        return hashlib.sha256(json.dumps([s.PUBLIC_ORIGIN,*[os.getenv(k,'') for k in fields]],separators=(',',':')).encode()).hexdigest()
    def record_check(name, detail):
        with s.db() as con: con.execute('INSERT OR REPLACE INTO integration_checks(name,origin,checked_at,detail,fingerprint) VALUES(?,?,?,?,?)',(name,s.PUBLIC_ORIGIN,time.time(),detail,integration_fingerprint(name)))
    s.record_integration_check=record_check

    def verifier_ready():
        try:
            u=urlsplit(os.getenv('AGE_PROVIDER_URL',''))
            key=Ed25519PublicKey.from_public_bytes(unb64(os.getenv('AGE_PUBLIC_KEY','')))
            return bool(key and u.scheme=='https' and u.hostname and not u.username and not u.password and not u.fragment and os.getenv('AGE_PROVIDER_ID'))
        except (ValueError,TypeError): return False
    s.age_verifier_ready=verifier_ready

    def bot_ready(): return bool(os.getenv('TURNSTILE_SITE_KEY') and os.getenv('TURNSTILE_SECRET_KEY'))
    def verify_bot(token, action='signup'):
        configured=bot_ready()
        if not configured:
            if production(): raise HTTPException(503,'Cadastro temporariamente indisponível: proteção antiautomação não configurada.')
            return
        if not token or len(token)>2048: raise HTTPException(422,'Conclua a verificação antiautomação e tente novamente.')
        try:
            with httpx.Client(timeout=8,follow_redirects=False) as client:
                response=client.post('https://challenges.cloudflare.com/turnstile/v0/siteverify',data={'secret':os.environ['TURNSTILE_SECRET_KEY'],'response':token})
                response.raise_for_status(); value=response.json()
            if not isinstance(value,dict) or value.get('success') is not True or value.get('hostname') != urlsplit(s.PUBLIC_ORIGIN).hostname or value.get('action') != action:
                raise HTTPException(403,'A verificação não foi aceita. Atualize o desafio e tente novamente.')
            record_check('turnstile','Token validado no servidor com domínio e ação correspondentes.')
        except (httpx.HTTPError,ValueError): raise HTTPException(503,'O serviço antiautomação não respondeu. Nenhuma conta foi criada; tente novamente.')
    s.verify_bot=verify_bot
    def guard_registration(data,request):
        # Defense in depth; rate limiting applies before calling the external verifier.
        s.rate_limit('signup-challenge:'+(request.client.host if request.client else 'local'),20,600)
        if production() and not data.invite_code and not all(c['ok'] for c in s.launch_checks()):
            raise HTTPException(503,'A abertura geral está temporariamente suspensa até o responsável concluir as verificações operacionais.')
        verify_bot(data.turnstile_token)
    s.guard_registration=guard_registration

    @app.get('/api/auth/options')
    def auth_options():
        return {'turnstile_site_key':os.getenv('TURNSTILE_SITE_KEY','') if bot_ready() else '',
                'turnstile_required':production() or bot_ready(),'age_required':enforced(),
                'age_verifier_ready':verifier_ready(),'minors_enabled':os.getenv('MINOR_ACCOUNTS_ENABLED')=='1',
                'notice':'Criar a conta não libera o feed: em produção, confirme e-mail e faixa etária. Contas menores exigem supervisão e habilitação específica.'}

    @app.get('/conta/seguranca')
    def security_page(): return FileResponse(s.ROOT/'web'/'security-center.html',headers={'Cache-Control':'no-store'})

    class Privacy(s.Data):
        private: bool
    class Decision(s.Data):
        approve: bool
    class Consent(s.Data):
        version: Annotated[str,StringConstraints(min_length=1,max_length=120)]
        accepted: Literal[True]
    class Receipt(s.Data):
        receipt: Annotated[str,StringConstraints(min_length=80,max_length=4096)]
    class GuardianEmail(s.Data):
        email: Annotated[str,StringConstraints(min_length=5,max_length=254)]
    class GuardianAccept(s.Data):
        token: Annotated[str,StringConstraints(min_length=32,max_length=128)]
        password: Annotated[str,StringConstraints(min_length=1,max_length=128)]
        responsible: Literal[True]
    class Paused(s.Data):
        paused: bool
    class Ticket(s.Data):
        kind: Literal['privacy','appeal','safety','bug']
        subject: Annotated[str,StringConstraints(strip_whitespace=True,min_length=5,max_length=120)]
        body: Annotated[str,StringConstraints(strip_whitespace=True,min_length=20,max_length=3000)]
    class TicketReply(s.Data):
        reply: Annotated[str,StringConstraints(strip_whitespace=True,min_length=10,max_length=3000)]
        status: Literal['open','closed']

    @app.get('/api/account/security')
    def security_status(request:Request,user=Depends(s.member)):
        with s.db() as con:
            current=terms_version(con)
            own=con.execute('SELECT g.paused,a.name,a.handle FROM guardianships g JOIN actors a ON a.id=g.guardian_id WHERE child_id=?',(user['id'],)).fetchone()
            children=[dict(r) for r in con.execute('SELECT g.child_id,g.paused,a.handle,a.name FROM guardianships g JOIN actors a ON a.id=g.child_id WHERE guardian_id=?',(user['id'],))]
            incoming=[dict(r) for r in con.execute('SELECT a.id,a.name,a.handle,r.created_at FROM follow_requests r JOIN actors a ON a.id=r.requester_id WHERE r.target_id=? AND a.active=1 AND NOT EXISTS(SELECT 1 FROM blocks b WHERE (b.user_id=r.target_id AND b.target_id=r.requester_id) OR (b.user_id=r.requester_id AND b.target_id=r.target_id)) ORDER BY r.created_at DESC LIMIT 100',(user['id'],))]
        state=social_status(user)
        return {'handle':user['handle'],'email_verified':bool(user['email_verified']),'private':bool(user['account_private']),
                'social_status':state,'message':messages.get(state,'Conta pronta para usar os recursos sociais.'),
                'age_band':user['age_band'],'age_verified_until':user['age_verified_until'],'age_required':enforced(),
                'verifier_ready':verifier_ready(),'minors_enabled':os.getenv('MINOR_ACCOUNTS_ENABLED')=='1',
                'terms_current':current,'terms_accepted':current==user['terms_version'],
                'follow_requests':incoming,'guardian':dict(own) if own else None,'children':children,
                'is_minor':is_minor(user),'csrf':user['csrf']}

    @app.patch('/api/account/privacy')
    def privacy(data:Privacy,user=Depends(s.member)):
        if not data.private:
            require_social(user)
            if is_minor(user): raise HTTPException(403,'Perfis de menores permanecem privados.')
        with s.db() as con:
            con.execute('UPDATE actors SET account_private=? WHERE id=?',(int(data.private),user['id']))
            s.log(con,user['id'],'privacy_changed',user['id'],'Perfil privado.' if data.private else 'Perfil visível aos membros habilitados.')
        return {'ok':True,'private':data.private}

    @app.post('/api/account/terms')
    def accept_terms(data:Consent,user=Depends(s.member)):
        with s.db() as con:
            version=terms_version(con)
            if data.version!=version:raise HTTPException(409,'Os Termos mudaram novamente. Atualize e leia a versão atual.')
            con.execute('UPDATE actors SET terms_version=? WHERE id=?',(version,user['id']))
            s.log(con,user['id'],'terms_accepted',user['id'],version)
        return {'ok':True}

    def decide_request(target_id,requester_id,approve,user):
        with s.db() as con:
            con.execute('BEGIN IMMEDIATE')
            if not con.execute('SELECT 1 FROM follow_requests WHERE target_id=? AND requester_id=?',(target_id,requester_id)).fetchone():raise HTTPException(404,'Solicitação indisponível.')
            if approve:
                target=s.actor(con,requester_id)
                if s.blocked(con,requester_id,target_id):raise HTTPException(409,'Existe um bloqueio entre os perfis.')
                con.execute('INSERT OR IGNORE INTO follows VALUES(?,?)',(requester_id,target_id))
            con.execute('DELETE FROM follow_requests WHERE target_id=? AND requester_id=?',(target_id,requester_id))
            s.log(con,user['id'],'follow_request_decided',requester_id,'Aprovada.' if approve else 'Recusada.')
        return {'ok':True}
    @app.post('/api/account/follow-requests/{requester_id}')
    def decide(requester_id:str,data:Decision,user=Depends(s.member)):
        require_social(user)
        if is_minor(user):raise HTTPException(403,'A aprovação de seguidores desta conta é feita pelo responsável vinculado.')
        return decide_request(user['id'],requester_id,data.approve,user)
    @app.delete('/api/account/followers/{follower_id}')
    def remove_follower(follower_id:str,user=Depends(s.member)):
        with s.db() as con:
            con.execute('DELETE FROM follows WHERE user_id=? AND target_id=?',(follower_id,user['id']))
            con.execute('DELETE FROM follow_requests WHERE requester_id=? AND target_id=?',(follower_id,user['id']))
        return {'ok':True}
    @app.get('/api/account/followers')
    def followers(user=Depends(s.member)):
        with s.db() as con: rows=[dict(r) for r in con.execute('SELECT a.id,a.handle,a.name FROM follows f JOIN actors a ON a.id=f.user_id WHERE f.target_id=? AND a.active=1 ORDER BY a.handle LIMIT 500',(user['id'],))]
        return {'items':rows}

    @app.get('/api/account/sessions')
    def sessions(request:Request,user=Depends(s.member)):
        current=hashlib.sha256(request.cookies.get('synapse_session','').encode()).hexdigest()
        with s.db() as con:
            # Add opaque handles for sessions created before this release.
            for r in con.execute('SELECT token_hash FROM sessions WHERE user_id=? AND expires>?',(user['id'],time.time())).fetchall():
                con.execute('INSERT OR IGNORE INTO session_devices VALUES(?,?,?,?)',(s.uid(),r['token_hash'],s.now(),'Sessão anterior à atualização — data de registro nesta lista'))
            rows=[{'id':r['id'],'created_at':r['created_at'],'expires':r['expires'],'current':r['token_hash']==current,'device':r['device']} for r in con.execute('SELECT d.*,se.expires FROM session_devices d JOIN sessions se ON se.token_hash=d.token_hash WHERE se.user_id=? AND se.expires>? ORDER BY d.created_at DESC LIMIT 50',(user['id'],time.time()))]
        return {'items':rows}
    @app.delete('/api/account/sessions/{session_id}')
    def revoke_session(session_id:str,request:Request,user=Depends(s.member)):
        current=hashlib.sha256(request.cookies.get('synapse_session','').encode()).hexdigest()
        with s.db() as con:
            row=con.execute('SELECT se.token_hash FROM session_devices d JOIN sessions se ON se.token_hash=d.token_hash WHERE d.id=? AND se.user_id=?',(session_id,user['id'])).fetchone()
            if not row:raise HTTPException(404,'Sessão não encontrada.')
            if row['token_hash']==current:raise HTTPException(409,'Use Sair para encerrar a sessão atual.')
            con.execute('DELETE FROM sessions WHERE token_hash=?',(row['token_hash'],))
        return {'ok':True}
    @app.post('/api/account/sessions/revoke-others')
    def revoke_others(request:Request,user=Depends(s.member)):
        current=hashlib.sha256(request.cookies.get('synapse_session','').encode()).hexdigest()
        with s.db() as con: count=con.execute('DELETE FROM sessions WHERE user_id=? AND token_hash!=?',(user['id'],current)).rowcount
        return {'ok':True,'revoked':count}

    @app.post('/api/account/age/start')
    def age_start(user=Depends(s.member)):
        if not user['email_verified']:raise HTTPException(403,'Confirme primeiro seu e-mail.')
        if not verifier_ready():raise HTTPException(503,'O responsável ainda não conectou um serviço de aferição. Nenhum documento deve ser enviado pelo suporte ou por esta página.')
        s.rate_limit('age-start:'+user['id'],4,600)
        challenge=secrets.token_urlsafe(32)
        with s.db() as con:
            con.execute('DELETE FROM age_challenges WHERE user_id=? OR expires<?',(user['id'],time.time()))
            con.execute('INSERT INTO age_challenges VALUES(?,?,?)',(hashlib.sha256(challenge.encode()).hexdigest(),user['id'],time.time()+900))
        endpoint=os.environ['AGE_PROVIDER_URL']
        url=endpoint+('&' if '?' in endpoint else '?')+urlencode({'challenge':challenge,'audience':s.PUBLIC_ORIGIN,'return_url':s.PUBLIC_ORIGIN+'/conta/seguranca'})
        return {'url':url,'notice':'Você será direcionado ao verificador contratado. O Synapse receberá uma faixa etária assinada, não seus documentos.'}

    @app.post('/api/account/age/confirm')
    def age_confirm(data:Receipt,user=Depends(s.member)):
        s.rate_limit('age-confirm:'+user['id'],8,600)
        if not verifier_ready():raise HTTPException(503,'Verificador não configurado.')
        try:
            body,signature=data.receipt.split('.')
            Ed25519PublicKey.from_public_bytes(unb64(os.environ['AGE_PUBLIC_KEY'])).verify(unb64(signature),body.encode('ascii'))
            payload=json.loads(unb64(body))
            if not isinstance(payload,dict) or set(payload)!={'v','iss','aud','challenge','band','iat','exp'}:raise ValueError()
            if payload['v']!=1 or payload['iss']!=os.environ['AGE_PROVIDER_ID'] or payload['aud']!=s.PUBLIC_ORIGIN:raise ValueError()
            if payload['band'] not in ('under_13','13_15','16_17','adult'):raise ValueError()
            if type(payload['iat']) not in (int,float) or type(payload['exp']) not in (int,float):raise ValueError()
            if not 0 < payload['exp']-payload['iat'] <= 300 or not time.time()-300 <= payload['iat'] <= time.time()+30 or payload['exp']<=time.time():raise ValueError()
            if not isinstance(payload['challenge'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{40,100}',payload['challenge']):raise ValueError()
        except (InvalidSignature,ValueError,TypeError,KeyError,UnicodeError):
            raise HTTPException(400,'Comprovante inválido, incompatível ou expirado. Reinicie a verificação.')
        with s.db() as con:
            con.execute('BEGIN IMMEDIATE')
            count=con.execute('DELETE FROM age_challenges WHERE challenge_hash=? AND user_id=? AND expires>?',(hashlib.sha256(payload['challenge'].encode()).hexdigest(),user['id'],time.time())).rowcount
            if count!=1:raise HTTPException(400,'Verificação já utilizada ou pertencente a outra conta.')
            band=payload['band']
            until=time.time()+86400*30
            con.execute('UPDATE actors SET age_band=?,age_verified_until=?,age_provider=? WHERE id=?',(band,until,os.environ['AGE_PROVIDER_ID'],user['id']))
            if band!='adult':
                con.execute("UPDATE actors SET account_private=1,dm_policy='off' WHERE id=?",(user['id'],))
                # Existing followers must be reviewed again after a minor signal.
                con.execute('INSERT OR IGNORE INTO follow_requests SELECT user_id,target_id,? FROM follows WHERE target_id=?',(s.now(),user['id']))
                con.execute('DELETE FROM follows WHERE target_id=?',(user['id'],))
                con.execute('DELETE FROM push_subscriptions WHERE user_id=?',(user['id'],))
                con.execute('DELETE FROM calls WHERE caller_id=? OR callee_id=?',(user['id'],user['id']))
            s.log(con,user['id'],'age_band_verified',user['id'],'Faixa etária recebida de emissor configurado; sem documento armazenado.')
        record_check('age_verifier','Assinatura e desafio aceitos; não certifica a confiabilidade do fornecedor nem parentesco.')
        return {'ok':True,'band':band,'verified_until':until}

    @app.post('/api/account/guardian/invite')
    def guardian_invite(data:GuardianEmail,user=Depends(s.member)):
        if not age_current(user) or not is_minor(user) or not user['email_verified']:raise HTTPException(403,'Este vínculo está disponível para conta de menor com faixa etária e e-mail confirmados.')
        s.rate_limit('guardian-invite:'+user['id'],3,3600)
        email=s.validate_email(data.email)
        if email==user['email']:raise HTTPException(422,'Informe o e-mail do responsável, não o da própria conta.')
        token=secrets.token_urlsafe(32)
        with s.db() as con:
            con.execute('DELETE FROM guardian_invites WHERE child_id=? OR expires<?',(user['id'],time.time()))
            con.execute('INSERT INTO guardian_invites VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],hashlib.sha256(email.encode()).hexdigest(),time.time()+86400))
        s.queue_message(user['id'],email,'Vínculo de responsável no Synapse',
                        'Uma conta solicitou supervisão por este endereço. Só confirme se você for o responsável legal. É necessária sua própria conta adulta verificada.\n\n'+s.PUBLIC_ORIGIN+'/conta/seguranca#guardian='+token+'\n\nSe não reconhece o pedido, ignore. Não encaminhe este link.',purpose='guardian',valid_for=86400)
        return {'ok':True}
    @app.post('/api/account/guardian/accept')
    def guardian_accept(data:GuardianAccept,user=Depends(s.member)):
        if not user['email_verified'] or not age_current(user) or user['age_band']!='adult':raise HTTPException(403,'Somente uma conta adulta com e-mail e faixa etária verificados pode aceitar.')
        s.rate_limit('guardian-accept:'+user['id'],5,600)
        if not s.password_ok(data.password,user['password_hash']):raise HTTPException(401,'Senha incorreta.')
        with s.db() as con:
            con.execute('BEGIN IMMEDIATE')
            row=con.execute('SELECT * FROM guardian_invites WHERE token_hash=? AND expires>?',(hashlib.sha256(data.token.encode()).hexdigest(),time.time())).fetchone()
            if not row or not hmac.compare_digest(row['email_hash'],hashlib.sha256(user['email'].encode()).hexdigest()) or row['child_id']==user['id']:raise HTTPException(400,'Convite inválido ou destinado a outro e-mail.')
            child=s.actor(con,row['child_id'])
            if not is_minor(dict(child)) or not age_current(dict(child)):raise HTTPException(409,'A conta precisa renovar a verificação de idade.')
            con.execute('INSERT INTO guardianships VALUES(?,?,0,?) ON CONFLICT(child_id) DO UPDATE SET guardian_id=excluded.guardian_id,paused=0,accepted_at=excluded.accepted_at',(row['child_id'],user['id'],s.now()))
            con.execute('DELETE FROM guardian_invites WHERE child_id=?',(row['child_id'],))
            con.execute("UPDATE actors SET account_private=1,dm_policy='off' WHERE id=?",(row['child_id'],))
            s.log(con,user['id'],'guardianship_accepted',row['child_id'],'Declaração de responsabilidade legal e senha confirmadas. A plataforma não atesta parentesco.')
        return {'ok':True}
    def own_child(con,user,child_id):
        if not user['email_verified'] or not age_current(user) or user['age_band']!='adult':raise HTTPException(403,'Renove a verificação da conta responsável.')
        row=con.execute('SELECT * FROM guardianships WHERE child_id=? AND guardian_id=?',(child_id,user['id'])).fetchone()
        if not row:raise HTTPException(404,'Vínculo não encontrado.')
        child=s.actor(con,child_id)
        if child['age_band']=='adult':raise HTTPException(409,'A conta agora é adulta; supervisão não pode ser imposta.')
        return row
    @app.patch('/api/account/guardian/{child_id}')
    def pause_child(child_id:str,data:Paused,user=Depends(s.member)):
        with s.db() as con:
            own_child(con,user,child_id)
            con.execute('UPDATE guardianships SET paused=? WHERE child_id=?',(int(data.paused),child_id))
            s.log(con,user['id'],'supervision_changed',child_id,'Pausa.' if data.paused else 'Retomada.')
        return {'ok':True}
    @app.get('/api/account/guardian/{child_id}/requests')
    def child_requests(child_id:str,user=Depends(s.member)):
        with s.db() as con:
            own_child(con,user,child_id)
            rows=[dict(r) for r in con.execute('SELECT a.id,a.name,a.handle FROM follow_requests r JOIN actors a ON a.id=r.requester_id WHERE r.target_id=? AND a.active=1 LIMIT 100',(child_id,))]
        return {'items':rows}
    @app.post('/api/account/guardian/{child_id}/requests/{requester_id}')
    def child_decide(child_id:str,requester_id:str,data:Decision,user=Depends(s.member)):
        with s.db() as con:own_child(con,user,child_id)
        return decide_request(child_id,requester_id,data.approve,user)
    @app.delete('/api/account/guardian')
    def unlink_guardian(user=Depends(s.member)):
        with s.db() as con:
            con.execute('DELETE FROM guardianships WHERE child_id=?',(user['id'],))
            con.execute('DELETE FROM guardian_invites WHERE child_id=?',(user['id'],))
        return {'ok':True,'notice':'Vínculo removido. Contas de menores ficam sem acesso social até a validação de um novo responsável.'}

    @app.post('/api/account/support')
    def ticket(data:Ticket,user=Depends(s.member)):
        s.rate_limit('support:'+user['id'],5,3600)
        tid=s.uid()
        with s.db() as con: con.execute('INSERT INTO support_tickets VALUES(?,?,?,?,?,\'open\',\'\',?,?)',(tid,user['id'],data.kind,data.subject,data.body,s.now(),s.now()))
        return {'id':tid,'status':'open'}
    @app.get('/api/account/support')
    def tickets(user=Depends(s.member)):
        with s.db() as con: rows=[dict(r) for r in con.execute('SELECT id,kind,subject,body,status,reply,created_at,updated_at FROM support_tickets WHERE owner_id=? ORDER BY created_at DESC LIMIT 50',(user['id'],))]
        return {'items':rows}
    def staff(request:Request,user=Depends(s.member)):
        if s.operator_role(user) not in ('owner','moderator'):raise HTTPException(403,'Acesso administrativo necessário.')
        if production() and not user['email_verified']:raise HTTPException(403,'Confirme seu e-mail.')
        s.require_admin_elevation(request,user)
        return user
    s.release_staff=staff
    def owner(user=Depends(staff)):
        if s.operator_role(user)!='owner':raise HTTPException(403,'Somente o responsável.')
        return user
    s.release_owner=owner
    @app.get('/api/manage/support')
    def support_queue(user=Depends(staff)):
        with s.db() as con: rows=[dict(r) for r in con.execute('SELECT t.*,a.handle FROM support_tickets t JOIN actors a ON a.id=t.owner_id ORDER BY (t.status=\'open\') DESC,t.created_at DESC LIMIT 100')]
        return {'items':rows}
    @app.post('/api/manage/support/{ticket_id}')
    def reply(ticket_id:str,data:TicketReply,user=Depends(staff)):
        with s.db() as con:
            row=con.execute('SELECT owner_id FROM support_tickets WHERE id=?',(ticket_id,)).fetchone()
            if not row:raise HTTPException(404,'Protocolo não encontrado.')
            con.execute('UPDATE support_tickets SET reply=?,status=?,updated_at=? WHERE id=?',(data.reply,data.status,s.now(),ticket_id))
            s.admin_event(con,user,'support_replied','ticket',ticket_id,'Resposta registrada; '+data.status)
        return {'ok':True}

    old_checks=s.launch_checks
    def launch_checks():
        items=old_checks()
        with s.db() as con: checks={r['name']:dict(r) for r in con.execute('SELECT * FROM integration_checks WHERE origin=?',(s.PUBLIC_ORIGIN,))}
        def recent(name):return name in checks and hmac.compare_digest(checks[name]['fingerprint'],integration_fingerprint(name))
        with s.db() as con:
            reviewed=con.execute("SELECT COUNT(*) FROM policy_reviews r JOIN site_policies p ON p.kind=r.kind WHERE r.release='0.9'").fetchone()[0]
            hashes_ok=all(hashlib.sha256(r['body'].encode()).hexdigest()==r['body_hash'] for r in con.execute("SELECT p.body,r.body_hash FROM policy_reviews r JOIN site_policies p ON p.kind=r.kind WHERE r.release='0.9'"))
        items.extend([
            {'id':'policy_review_current','ok':reviewed==3 and hashes_ok,'kind':'operator_review','label':'Políticas revisadas para privacidade e integrações da versão 0.9'},
            {'id':'bot_protection_configured','ok':bot_ready(),'kind':'configuration','label':'Proteção antiautomação configurada'},
            {'id':'bot_protection_validated','ok':recent('turnstile'),'kind':'integration','label':'Desafio validado no servidor com a configuração atual'},
            {'id':'age_verifier_configured','ok':verifier_ready(),'kind':'configuration','label':'Emissor externo de faixa etária configurado'},
            {'id':'age_verifier_validated','ok':recent('age_verifier'),'kind':'integration','label':'Comprovante de faixa etária validado com a configuração atual'},
            {'id':'minor_access_review','ok':os.getenv('MINOR_ACCOUNTS_ENABLED','0')!='1' or os.getenv('MINOR_SAFETY_REVIEWED')=='1','kind':'operator_review','label':'Acesso de menores desabilitado ou revisão especializada registrada (não certifica conformidade)'}
        ])
        return items
    s.launch_checks=launch_checks
