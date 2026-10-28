"""Synapse 0.7: social discovery + administration. Controlled pilot, not production certified."""
from __future__ import annotations

import sys
import asyncio
import smtplib
import ssl
from email.message import EmailMessage
import base64
import binascii
import io
import ipaddress
import html
import unicodedata
from urllib.parse import urlsplit, urlunsplit, quote, urlencode
from PIL import Image, ImageOps, UnidentifiedImageError

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import shutil
import time
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager, asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StringConstraints, Field

ROOT = Path(__file__).resolve().parent

def load_env() -> None:
    """Minimal local .env reader; OS environment always wins. Never serve this file."""
    path = ROOT / '.env'
    if path.exists():
        for raw in path.read_text(encoding='utf-8-sig').splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            if re.fullmatch(r'[A-Z][A-Z0-9_]*', key.strip()):
                os.environ.setdefault(key.strip(), value.strip().strip('"\''))

load_env()
DB_PATH = Path(os.getenv('SYNAPSE_DB', str(ROOT / 'data' / 'synapse.db')))
PUBLIC_ORIGIN = os.getenv('PUBLIC_ORIGIN', '').rstrip('/')
SEARCH_PROVIDER = os.getenv('SEARCH_PROVIDER', 'external').lower()
BRAVE_SEARCH_API_KEY = os.getenv('BRAVE_SEARCH_API_KEY', '')
SEARCH_DAILY_LIMIT = max(1, int(os.getenv('SEARCH_DAILY_LIMIT', '30')))
SEARCH_GLOBAL_DAILY_LIMIT = max(1, int(os.getenv('SEARCH_GLOBAL_DAILY_LIMIT', '300')))
COOKIE_SECURE = PUBLIC_ORIGIN.startswith('https://')
MEDIA_DIR = Path(os.getenv('SYNAPSE_MEDIA', str(ROOT / 'data' / 'media')))
COLORS = {'blue', 'mint', 'violet', 'amber', 'rose'}
MAIL_MODE = os.getenv('MAIL_MODE', 'file')
ADMIN_HANDLES = {h.strip().lower() for h in os.getenv('ADMIN_HANDLES','').split(',') if h.strip()}
TERMS_VERSION = '2026-10-synapse-0.7-draft'
SEED_DEMO_DATA = os.getenv('SEED_DEMO_DATA','1') == '1'


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def uid() -> str:
    return uuid.uuid4().hex


@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA busy_timeout=15000')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def initialize() -> None:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
        # Additive upgrade from 0.2. Old AI data stays archived; no route runs an agent.
        columns={r['name'] for r in con.execute('PRAGMA table_info(posts)')}
        for name in ('link_url','link_title','image_path','image_alt'):
            if name not in columns:
                con.execute(f"ALTER TABLE posts ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        # Additive migration: preserve all old social data.
        additions = {
            'actors': {'email': "TEXT NOT NULL DEFAULT ''", 'email_verified': 'INTEGER NOT NULL DEFAULT 0',
                       'avatar_path': "TEXT NOT NULL DEFAULT ''", 'cover_path': "TEXT NOT NULL DEFAULT ''",
                       'website': "TEXT NOT NULL DEFAULT ''", 'interests': "TEXT NOT NULL DEFAULT '[]'",
                       'theme': "TEXT NOT NULL DEFAULT 'system'", 'accent': "TEXT NOT NULL DEFAULT 'violet'",
                       'reduce_motion': 'INTEGER NOT NULL DEFAULT 0', 'dm_policy': "TEXT NOT NULL DEFAULT 'everyone'",
                       'terms_version': "TEXT NOT NULL DEFAULT ''"},
            'posts': {'hidden': 'INTEGER NOT NULL DEFAULT 0'},
            'reports': {'status': "TEXT NOT NULL DEFAULT 'open'"}
        }
        for table, fields in additions.items():
            existing = {row['name'] for row in con.execute(f'PRAGMA table_info({table})')}
            for name, ddl in fields.items():
                if name not in existing:
                    con.execute(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS actors_email ON actors(email COLLATE NOCASE) WHERE email <> ''")
        if SEED_DEMO_DATA and not con.execute("SELECT 1 FROM actors WHERE id='synapse'").fetchone():
            stamp=now()
            people=[('synapse','synapse','Equipe Synapse','Descubra, guarde, compartilhe. Perfil editorial fictício.','mint'),
                    ('lia','lia.cria','Lia Martins','Design, referências e boas perguntas. Perfil fictício.','rose'),
                    ('caio','caio.explora','Caio Costa','Ciência, tecnologia e curiosidade. Perfil fictício.','blue')]
            con.executemany("INSERT INTO actors(id,handle,name,kind,bio,color,seeded,created_at) VALUES(?,?,?,'human',?,?,1,?)",[(*a,stamp) for a in people])
        if SEED_DEMO_DATA and not con.execute("SELECT 1 FROM posts WHERE id='discover-v03'").fetchone():
            samples=[('discover-v03','synapse','A internet é grande demais para explorar sozinho.\n\nPesquise um assunto, salve seus links e transforme uma descoberta em conversa. Bem-vindo ao novo Synapse. #descobertas','https://pt.wikipedia.org/','Um ponto de partida para a sua curiosidade'),
                     ('design-v03','lia','Hoje a minha pasta de referências virou uma coleção de ideias. Qual foi a melhor coisa que você encontrou na internet esta semana? #design #criacao','https://developer.mozilla.org/pt-BR/','Referências para criar na web')]
            for i,(pid,author,body,url,title) in enumerate(samples):
                con.execute("INSERT INTO posts(id,author_id,body,source,created_at,link_url,link_title) VALUES(?,?,?,'seed',?,?,?)",(pid,author,body,(datetime.now(timezone.utc)-timedelta(minutes=i*20)).isoformat(),url,title))

@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize()
    bootstrap_operator()
    validate_deployment()
    task = asyncio.create_task(delivery_worker())
    try:
        yield
    finally:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass


app = FastAPI(title='Synapse API', version='0.9.0', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

# These in-memory limits are for a single-process private pilot, not an Internet-scale abuse system.
_rate_lock = threading.Lock()
_rates: dict[str, deque] = defaultdict(deque)


def rate_limit(key: str, maximum: int, seconds: int=60) -> None:
    with _rate_lock:
        stamp = time.monotonic()
        queue = _rates[key]
        while queue and stamp - queue[0] > seconds:
            queue.popleft()
        if len(queue) >= maximum:
            raise HTTPException(429, 'Muitas tentativas. Aguarde um minuto e tente novamente.')
        queue.append(stamp)
        if len(_rates) > 10000:
            for old in list(_rates):
                if not _rates[old] or stamp - _rates[old][-1] > 3600:
                    del _rates[old]


@app.middleware('http')
async def security(request: Request, call_next):
    production = os.getenv('SYNAPSE_ENV') == 'production'
    if production:
        trusted_host = urlsplit(PUBLIC_ORIGIN).hostname
        actual_host = request.url.hostname
        local_health = request.url.path in ('/api/health','/api/ready') and request.method in ('GET','HEAD')  # Public non-secret liveness for hosting probes.
        if actual_host != trusted_host and not local_health:
            return JSONResponse({'detail':'Host não autorizado.'}, status_code=400)
    if request.url.path.startswith('/api/') and request.method not in ('GET','HEAD','OPTIONS'):
        origin = request.headers.get('origin')
        allowed = {str(request.base_url).rstrip('/')}
        if PUBLIC_ORIGIN:
            allowed = {PUBLIC_ORIGIN} if production else allowed | {PUBLIC_ORIGIN}
        if (origin and origin not in allowed) or request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail':'Origem da solicitação não permitida.'}, status_code=403)
        if request.headers.get('x-synapse-client') not in ('web-v03','web-v04','web-v05','web-v06','web-v07','admin-v07','web-v08','web-v09'):
            return JSONResponse({'detail':'Cabeçalho de proteção ausente.'}, status_code=403)
        upload = request.url.path == '/api/media/uploads' and request.method == 'POST'
        if request.headers.get('content-type','').split(';')[0] != ('multipart/form-data' if upload else 'application/json'):
            return JSONResponse({'detail':'Envie dados JSON.'}, status_code=415)
        maximum_body = 27 * 1024 * 1024 if upload else 9000000
        try:
            if int(request.headers.get('content-length','0')) > maximum_body:
                return JSONResponse({'detail':'Solicitação muito grande.'}, status_code=413)
        except ValueError:
            return JSONResponse({'detail':'Tamanho inválido.'}, status_code=400)
        # Bound streaming bodies as well as declared Content-Length, before parsing JSON/uploads.
        original_receive = request._receive
        received = 0
        async def bounded_receive():
            nonlocal received
            message = await original_receive()
            received += len(message.get('body', b''))
            if received > maximum_body:
                raise HTTPException(413, 'Solicitação acima do limite de envio.')
            return message
        request._receive = bounded_receive
        if not upload:
            try:
                await request.body()
            except HTTPException as exc:
                return JSONResponse({'detail':exc.detail},status_code=exc.status_code)
        try:
            current_user = session(request)
            limit_key = current_user['id'] if current_user else (request.client.host if request.client else 'local')
            rate_limit('write:' + limit_key, 100 if current_user else 300)
        except HTTPException as exc:
            return JSONResponse({'detail':exc.detail}, status_code=exc.status_code, headers=exc.headers or {})
    response = await call_next(request)
    response.headers['X-Request-ID'] = uid()
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Permissions-Policy'] = 'camera=(self), microphone=(self), geolocation=()'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
        "connect-src 'self'; media-src 'self' blob:; font-src 'self'; object-src 'none'; base-uri 'self'; "
        "frame-src 'none'; frame-ancestors 'none'; form-action 'self'; worker-src 'self'; manifest-src 'self'"
    )
    if os.getenv('TURNSTILE_SITE_KEY') and os.getenv('TURNSTILE_SECRET_KEY'):
        csp=response.headers['Content-Security-Policy']
        csp=csp.replace("script-src 'self'", "script-src 'self' https://challenges.cloudflare.com")
        csp=csp.replace("frame-src 'none'", "frame-src https://challenges.cloudflare.com")
        response.headers['Content-Security-Policy']=csp
    if request.url.path.startswith('/api/') or request.url.path in ('/', '/index.html', '/sw.js', '/admin', '/admin/', '/admin.html'):
        response.headers['Cache-Control'] = 'no-store'
    if request.url.path not in ('/bem-vindo','/como-funciona','/ajuda','/launch.css','/icon.svg','/icon-192.png','/icon-512.png'):
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    if COOKIE_SECURE:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response


class Data(BaseModel):
    model_config = ConfigDict(extra='forbid')


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class Registration(Data):
    turnstile_token: Annotated[str,StringConstraints(max_length=2048)] = ''
    invite_code: Annotated[str,StringConstraints(strip_whitespace=True,max_length=128)] = ''
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=50)]
    handle: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r'^[a-zA-Z0-9_.]{3,24}$')]
    password: Annotated[str, StringConstraints(min_length=10, max_length=128)]
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=254)]
    terms_accepted: Literal[True]


class Login(Data):
    handle: Annotated[str, StringConstraints(min_length=1,max_length=254)]
    password: Annotated[str, StringConstraints(min_length=1,max_length=128)]


class PostBody(Data):
    body: Text
    link_url: Annotated[str, StringConstraints(max_length=2048)] = ''
    link_title: Annotated[str, StringConstraints(strip_whitespace=True,max_length=180)] = ''
    image_data: Annotated[str, StringConstraints(max_length=4200000)] = ''
    image_alt: Annotated[str, StringConstraints(strip_whitespace=True,max_length=250)] = ''
    media_ids: list[Annotated[str, StringConstraints(pattern=r'^[a-f0-9]{32}$')]] = Field(default_factory=list, max_length=6)


class CommentBody(Data):
    body: Annotated[str, StringConstraints(strip_whitespace=True,min_length=1,max_length=600)]


class ProfileBody(Data):
    name: Annotated[str, StringConstraints(strip_whitespace=True,min_length=2,max_length=50)]
    bio: Annotated[str, StringConstraints(strip_whitespace=True,max_length=300)] = ''
    website: Annotated[str, StringConstraints(max_length=2048)] = ''
    color: Literal['blue','mint','violet','amber','rose'] = 'violet'
    interests: list[Annotated[str, StringConstraints(strip_whitespace=True,max_length=30)]] = []
    avatar_data: Annotated[str, StringConstraints(max_length=4200000)] = ''
    cover_data: Annotated[str, StringConstraints(max_length=4200000)] = ''
    remove_avatar: bool = False
    remove_cover: bool = False


class MessageBody(Data):
    body: Annotated[str, StringConstraints(strip_whitespace=True,min_length=1,max_length=1500)]


class ReportBody(Data):
    reason: Annotated[str, StringConstraints(strip_whitespace=True,min_length=3,max_length=500)]


class DeleteBody(Data):
    password: Annotated[str, StringConstraints(min_length=1,max_length=128)]


class LinkBody(Data):
    url: Annotated[str, StringConstraints(strip_whitespace=True,min_length=1,max_length=2048)]
    title: Annotated[str, StringConstraints(strip_whitespace=True,min_length=1,max_length=180)]
    collection: Annotated[str, StringConstraints(strip_whitespace=True,min_length=1,max_length=50)] = 'Favoritos'
    note: Annotated[str, StringConstraints(strip_whitespace=True,max_length=600)] = ''

def password_hash(password: str) -> str:
    salt=secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'


def password_ok(password: str, stored: str | None) -> bool:
    if not stored:
        # Still perform a slow hash on unknown handles; never allow seeded accounts to log in.
        hashlib.pbkdf2_hmac('sha256',password.encode(),b'no-such-account',600000)
        return False
    try:
        _, rounds, salt, digest=stored.split('$')
        actual=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),int(rounds)).hex()
        return hmac.compare_digest(actual,digest)
    except (ValueError,TypeError):
        return False


def session(request: Request):
    token=request.cookies.get('synapse_session','')
    if not token or len(token)>200:
        return None
    key=hashlib.sha256(token.encode()).hexdigest()
    with db() as con:
        row=con.execute('SELECT a.*, s.csrf FROM sessions s JOIN actors a ON a.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND a.active=1',
                        (key,time.time())).fetchone()
    return dict(row) if row else None


def member(request: Request):
    user=session(request)
    if not user:
        raise HTTPException(401,'Entre na sua conta para continuar.')
    if request.method not in ('GET','HEAD'):
        site = site_settings()
        social_write = (request.url.path.startswith(('/api/posts','/api/messages','/api/stories','/api/media','/api/calls','/api/links','/api/actors')) or request.url.path == '/api/profile') and not request.url.path.endswith('/report')
        if site['maintenance'] and social_write:
            raise HTTPException(503, 'O site está em manutenção: leitura, suporte e controles de conta continuam disponíveis.',headers={'Retry-After':'300'})
        upload_attempt = request.url.path == '/api/media/uploads' and request.method == 'POST'
        if upload_attempt and not site['uploads_enabled']:
            raise HTTPException(503, 'O envio de arquivos está temporariamente pausado.')
        if os.getenv('SYNAPSE_ENV')=='production' and not user['email_verified'] and (request.url.path.startswith(('/api/posts','/api/messages','/api/stories','/api/media','/api/calls'))):
            raise HTTPException(403,'Confirme seu e-mail antes de publicar ou iniciar conversas.')
        if not hmac.compare_digest(user['csrf'],request.headers.get('x-csrf-token','')):
            raise HTTPException(403,'Sessão de segurança inválida. Recarregue a página.')
    guard_member(request,user)
    return user


def set_session(user_id: str, response: Response) -> str:
    token=secrets.token_urlsafe(32)
    csrf=secrets.token_urlsafe(24)
    with db() as con:
        con.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
        existing=con.execute('SELECT token_hash FROM sessions WHERE user_id=? ORDER BY expires DESC LIMIT -1 OFFSET 9',(user_id,)).fetchall()
        con.executemany('DELETE FROM sessions WHERE token_hash=?',[(r['token_hash'],) for r in existing])
        con.execute('INSERT INTO sessions VALUES(?,?,?,?)',
                    (hashlib.sha256(token.encode()).hexdigest(),user_id,csrf,time.time()+86400*7))
        con.execute('INSERT INTO session_devices VALUES(?,?,?,?)',(uid(),hashlib.sha256(token.encode()).hexdigest(),now(),'Sessão do navegador'))
    response.set_cookie('synapse_session',token,max_age=86400*7,httponly=True,secure=COOKIE_SECURE,samesite='strict',path='/')
    return csrf


def public_actor(a) -> dict:
    result = {k:a[k] for k in ('id','handle','name','kind','bio','color','owner_id','seeded','active','created_at',
                                  'avatar_path','cover_path','website','interests')}
    result['interests'] = json.loads(result['interests'])
    return result


def actor(con, actor_id: str):
    result=con.execute('SELECT * FROM actors WHERE id=?',(actor_id,)).fetchone()
    if not result or result['kind'] != 'human' or not result['active']:
        raise HTTPException(404,'Perfil não encontrado.')
    return result


def blocked(con, me: str, other: str) -> bool:
    return bool(con.execute('SELECT 1 FROM blocks WHERE (user_id=? AND target_id=?) OR (user_id=? AND target_id=?)',
                            (me,other,other,me)).fetchone())


def visible_post(con, post_id: str, me: str):
    post=con.execute('SELECT * FROM posts WHERE id=?',(post_id,)).fetchone()
    if not post or post['hidden'] or not con.execute("SELECT 1 FROM actors WHERE id=? AND kind='human' AND active=1",(post['author_id'],)).fetchone() or (me and blocked(con,me,post['author_id'])):
        raise HTTPException(404,'Publicação indisponível.')
    return post


def log(con, owner: str, action: str, subject: str, summary: str):
    con.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)',(uid(),owner,action,subject,summary,now()))


@app.get('/api/state')
def state(request: Request):
    user=session(request)
    me=user['id'] if user else ''
    with db() as con:
        all_actors=[actor_for_viewer(con,a,me) for a in con.execute("SELECT * FROM actors WHERE kind='human' AND active=1 ORDER BY created_at LIMIT 500")]
        blocked_ids=[r['target_id'] for r in con.execute('SELECT target_id FROM blocks WHERE user_id=?',(me,))]
        invisible=set(blocked_ids)|{r['user_id'] for r in con.execute('SELECT user_id FROM blocks WHERE target_id=?',(me,))}
        follows=[r['target_id'] for r in con.execute('SELECT target_id FROM follows WHERE user_id=?',(me,))]
        pending_follows=[r['target_id'] for r in con.execute('SELECT target_id FROM follow_requests WHERE requester_id=?',(me,))]
        saved=[r['post_id'] for r in con.execute('SELECT post_id FROM bookmarks WHERE user_id=?',(me,))]
        posts=[]
        rows=con.execute('''SELECT p.*, (SELECT COUNT(*) FROM likes l WHERE l.post_id=p.id) AS likes,
                            EXISTS(SELECT 1 FROM likes l WHERE l.post_id=p.id AND l.user_id=?) AS liked
                            FROM posts p JOIN actors a ON a.id=p.author_id WHERE a.kind='human' AND a.active=1 AND p.hidden=0 ORDER BY p.created_at DESC,p.id DESC LIMIT 100''',(me,))
        for row in rows:
            if row['author_id'] in invisible or not can_view_author(con,row['author_id'],me):
                continue
            post=dict(row)
            post['media']=media_items(con, row['id'])
            post['comments']=[dict(c) for c in con.execute('SELECT c.* FROM comments c JOIN actors a ON a.id=c.author_id WHERE c.post_id=? AND a.active=1 ORDER BY c.created_at LIMIT 100',(row['id'],)) if c['author_id'] not in invisible]
            posts.append(post)
        links=[dict(r) for r in con.execute('SELECT * FROM web_links WHERE owner_id=? ORDER BY created_at DESC LIMIT 500',(me,))]
        own_reports=con.execute('SELECT COUNT(*) AS n FROM reports WHERE reporter_id=?',(me,)).fetchone()['n']
        for a in all_actors:
            a['followers']=con.execute('SELECT COUNT(*) AS n FROM follows WHERE target_id=?',(a['id'],)).fetchone()['n']
    if os.getenv('SYNAPSE_ENV')=='production' and social_status(user)!='ready':
        all_actors=[a for a in all_actors if a['id']==me];posts=[]
    return {'version':'0.9.0','mode':'server','search_provider':'brave' if SEARCH_PROVIDER=='brave' and BRAVE_SEARCH_API_KEY else 'external',
            'onboarding':social_status(user),'me':public_actor(user) if user else None,'csrf':user['csrf'] if user else '',
            'actors':[a for a in all_actors if a['id'] not in invisible or a['id'] in blocked_ids],'posts':posts,'following':follows,'pending_follows':pending_follows,'saved':saved,'blocked':blocked_ids,
            'links':links,'reports_count':own_reports,'site':public_site_settings(),
            'preferences': {k:user[k] for k in ('theme','accent','reduce_motion','dm_policy')} if user else {},
            'account': {'email':user['email'],'email_verified':bool(user['email_verified'])} if user else None,
            'is_admin':bool(user and is_operator(user)),
            'mail_mode':MAIL_MODE if user else None,
            'capabilities':capabilities(),
            'stories':list_stories(request)['stories'],
            'notifications':list_notifications(request)['notifications'] if user else []} 

@app.post('/api/auth/register')
def register(data: Registration, request: Request, response: Response):
    site=site_settings()
    if site['maintenance']:
        raise HTTPException(503, 'Cadastros pausados durante a manutenção.')
    rate_limit('invite-try:'+(request.client.host if request.client else 'local'),30,600)
    if not site['registration_open'] or data.invite_code:
        with db() as con:
            if not eligible_invite(con, data.invite_code):
                raise HTTPException(403, 'Cadastros gerais fechados ou convite inválido. Use um convite válido ou entre em sua conta.')
    rate_limit('register:'+(request.client.host if request.client else 'local'),10 if os.getenv('SYNAPSE_ENV')!='production' else 30,600)
    guard_registration(data,request)
    email = validate_email(data.email)
    user_id=uid()
    encoded=password_hash(data.password)
    try:
        with db() as con:
            con.execute('BEGIN IMMEDIATE')
            current=con.execute('SELECT registration_open,maintenance FROM site_settings WHERE id=1').fetchone()
            if current['maintenance']:
                raise HTTPException(503, 'Cadastros pausados durante a manutenção.')
            if not current['registration_open'] or data.invite_code:
                consume_invite(con, data.invite_code)
            terms=con.execute("SELECT body FROM site_policies WHERE kind='terms'").fetchone()
            terms_version='terms-sha256:'+hashlib.sha256(terms['body'].encode()).hexdigest() if terms else TERMS_VERSION
            con.execute("INSERT INTO actors(id,handle,name,kind,bio,color,password_hash,created_at,email,terms_version,dm_policy) VALUES(?,?,?,'human','','violet',?,?,?,?,'following')",
                        (user_id,data.handle.lower(),data.name,encoded,now(),email,terms_version))
            con.execute('UPDATE actors SET account_private=? WHERE id=?',(1 if os.getenv('SYNAPSE_ENV')=='production' else 0,user_id))
            log(con,user_id,'account_created',user_id,'Termos da versão '+terms_version+' aceitos. E-mail não verificado.')
    except sqlite3.IntegrityError:
        raise HTTPException(409,'Não foi possível cadastrar: nome de usuário ou e-mail indisponível.')
    csrf=set_session(user_id,response)
    send_token(user_id, email, 'verify')
    return {'ok':True,'csrf':csrf,'verification_pending':True}



@app.post('/api/auth/login')
def login(data: Login, request: Request, response: Response):
    rate_limit('login-account:'+hashlib.sha256(data.handle.strip().lower().encode()).hexdigest(),10,300)
    rate_limit('login-network:'+(request.client.host if request.client else 'local'),120,60)
    with db() as con:
        user=con.execute("SELECT * FROM actors WHERE (handle=? COLLATE NOCASE OR email=? COLLATE NOCASE) AND kind='human' AND active=1",(data.handle.strip(),data.handle.strip())).fetchone()
    if not password_ok(data.password,user['password_hash'] if user else None):
        raise HTTPException(401,'Usuário ou senha incorretos.')
    csrf=set_session(user['id'],response)
    return {'ok':True,'csrf':csrf}


@app.post('/api/auth/logout')
def logout(request: Request,response: Response,user=Depends(member)):
    token=request.cookies.get('synapse_session','')
    with db() as con:
        con.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
    response.delete_cookie('synapse_session',path='/')
    return {'ok':True}


@app.patch('/api/profile')
def profile(data: ProfileBody,user=Depends(member)):
    if not site_settings()['uploads_enabled'] and (data.avatar_data or data.cover_data):
        raise HTTPException(503, 'O envio de imagens está temporariamente pausado.')
    if len(data.interests)>8:
        raise HTTPException(422,'Escolha até oito interesses.')
    website=safe_url(data.website,optional=True)
    avatar=cover=''
    try:
        avatar=persist_image(data.avatar_data)
        cover=persist_image(data.cover_data)
        with db() as con:
            current=actor(con,user['id'])
            new_avatar=avatar or ('' if data.remove_avatar else current['avatar_path'])
            new_cover=cover or ('' if data.remove_cover else current['cover_path'])
            con.execute('UPDATE actors SET name=?,bio=?,website=?,color=?,interests=?,avatar_path=?,cover_path=? WHERE id=?',
                        (data.name,data.bio,website,data.color,json.dumps(data.interests,ensure_ascii=False),new_avatar,new_cover,user['id']))
        for old,new in [(current['avatar_path'],new_avatar),(current['cover_path'],new_cover)]:
            if old!=new: remove_image(old)
    except Exception:
        remove_image(avatar);remove_image(cover)
        raise
    return {'ok':True}



@app.delete('/api/posts/{post_id}')
def delete_post(post_id: str,user=Depends(member)):
    with db() as con:
        post=con.execute('SELECT * FROM posts WHERE id=?',(post_id,)).fetchone()
        if not post:raise HTTPException(404,'Publicação indisponível.')
        if post['author_id'] != user['id']:
            raise HTTPException(403,'Você só pode excluir suas publicações.')
        assets=owned_post_files(con,post_id)
        con.execute('DELETE FROM posts WHERE id=?',(post_id,))
        log(con,user['id'],'post_deleted',post_id,'Publicação removida do feed.')
    delete_media_files(assets)
    remove_image(post['image_path'])
    return {'ok':True}


def toggle_post_link(table: str, post_id: str, user):
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        visible_post(con,post_id,user['id'])
        current=con.execute(f'SELECT 1 FROM {table} WHERE user_id=? AND post_id=?',(user['id'],post_id)).fetchone()
        if current:
            con.execute(f'DELETE FROM {table} WHERE user_id=? AND post_id=?',(user['id'],post_id))
        else:
            con.execute(f'INSERT INTO {table} VALUES(?,?)',(user['id'],post_id))
    return {'active':not bool(current)}


@app.post('/api/posts/{post_id}/like')
def like(post_id: str,user=Depends(member)):
    return toggle_post_link('likes',post_id,user)


@app.post('/api/posts/{post_id}/save')
def save(post_id: str,user=Depends(member)):
    return toggle_post_link('bookmarks',post_id,user)


@app.post('/api/posts/{post_id}/comments')
def comment(post_id: str,data: CommentBody,user=Depends(member)):
    cid=uid()
    with db() as con:
        visible_post(con,post_id,user['id'])
        con.execute('INSERT INTO comments VALUES(?,?,?,?,?)',(cid,post_id,user['id'],data.body,now()))
    return {'id':cid}


@app.post('/api/actors/{target_id}/follow')
def follow(target_id: str,user=Depends(member)):
    rate_limit('follow:'+user['id'],30,3600)
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        target=actor(con,target_id)
        if target_id==user['id'] or blocked(con,user['id'],target_id):
            raise HTTPException(400,'Não é possível seguir esse perfil.')
        exists=con.execute('SELECT 1 FROM follows WHERE user_id=? AND target_id=?',(user['id'],target_id)).fetchone()
        pending=con.execute('SELECT 1 FROM follow_requests WHERE requester_id=? AND target_id=?',(user['id'],target_id)).fetchone()
        if exists:
            con.execute('DELETE FROM follows WHERE user_id=? AND target_id=?',(user['id'],target_id));status='none'
        elif pending:
            con.execute('DELETE FROM follow_requests WHERE requester_id=? AND target_id=?',(user['id'],target_id));status='none'
        elif target['account_private']:
            con.execute('INSERT INTO follow_requests VALUES(?,?,?)',(user['id'],target_id,now()));status='pending'
        else:
            con.execute('INSERT INTO follows VALUES(?,?)',(user['id'],target_id));status='following'
    return {'active':status=='following','pending':status=='pending','status':status}


@app.post('/api/actors/{target_id}/block')
def block(target_id: str,user=Depends(member)):
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        actor(con,target_id)
        if target_id==user['id']:
            raise HTTPException(400,'Você não pode bloquear a própria conta.')
        exists=con.execute('SELECT 1 FROM blocks WHERE user_id=? AND target_id=?',(user['id'],target_id)).fetchone()
        if exists:
            con.execute('DELETE FROM blocks WHERE user_id=? AND target_id=?',(user['id'],target_id))
        else:
            con.execute('INSERT INTO blocks VALUES(?,?)',(user['id'],target_id))
            con.execute('DELETE FROM follow_requests WHERE (requester_id=? AND target_id=?) OR (requester_id=? AND target_id=?)',(user['id'],target_id,target_id,user['id']))
            con.execute('DELETE FROM follows WHERE (user_id=? AND target_id=?) OR (user_id=? AND target_id=?)',
                        (user['id'],target_id,target_id,user['id']))
        log(con,user['id'],'block_changed',target_id,'Bloqueio removido.' if exists else 'Perfil bloqueado.')
    return {'active':not bool(exists)}


@app.post('/api/posts/{post_id}/report')
def report(post_id: str,data: ReportBody,user=Depends(member)):
    with db() as con:
        visible_post(con,post_id,user['id'])
        con.execute('INSERT INTO reports(id,reporter_id,post_id,reason,created_at) VALUES(?,?,?,?,?)',(uid(),user['id'],post_id,data.reason,now()))
        log(con,user['id'],'report_created',post_id,'Denúncia registrada para revisão do operador. Sem moderação automática.')
    return {'ok':True}


@app.get('/api/messages/{target_id}')
def messages(target_id: str,user=Depends(member)):
    with db() as con:
        actor(con,target_id)
        if blocked(con,user['id'],target_id):
            raise HTTPException(403,'Conversa bloqueada.')
        rows=con.execute('''SELECT id,sender_id,recipient_id,body,source,model,created_at FROM (SELECT rowid AS sequence,* FROM messages WHERE
            (sender_id=? AND recipient_id=?) OR (sender_id=? AND recipient_id=?)
            ORDER BY created_at DESC, rowid DESC LIMIT 100) ORDER BY created_at,sequence''',
            (user['id'],target_id,target_id,user['id']))
        return {'messages':[dict(r) for r in rows]}


@app.get('/api/account/export')
def export_account(user=Depends(member)):
    me=user['id']
    with db() as con:
        result={'profile':public_actor(user),'email':user['email'],'email_verified':bool(user['email_verified']),'preferences':{k:user[k] for k in ('theme','accent','reduce_motion','dm_policy')},'exported_at':now(),
                'posts':[dict(r) for r in con.execute('SELECT * FROM posts WHERE author_id=? OR approved_by=?',(me,me))],
                'comments':[dict(r) for r in con.execute('SELECT * FROM comments WHERE author_id=?',(me,))],
                'messages':[dict(r) for r in con.execute('SELECT * FROM messages WHERE sender_id=? OR recipient_id=?',(me,me))],
                'agents':[public_actor(r) for r in con.execute('SELECT * FROM actors WHERE owner_id=?',(me,))]}
        for table,field in [('drafts','owner_id'),('missions','owner_id'),('audit','owner_id'),('reports','reporter_id'),
                            ('media_assets','owner_id'),('stories','author_id'),('notifications','user_id'),('content_reports','reporter_id'),('follows','user_id'),('blocks','user_id'),('likes','user_id'),('bookmarks','user_id'),('usage','user_id'),('web_links','owner_id')]:
            result[table]=[dict(r) for r in con.execute(f'SELECT * FROM {table} WHERE {field}=?',(me,))]
        result['account_safety']={k:user[k] for k in ('account_private','age_band','age_verified_until','age_provider')}
        result['guardianships']=[dict(r) for r in con.execute('SELECT * FROM guardianships WHERE child_id=? OR guardian_id=?',(me,me))]
        result['support_tickets']=[dict(r) for r in con.execute('SELECT * FROM support_tickets WHERE owner_id=?',(me,))]
        result['follow_requests']=[dict(r) for r in con.execute('SELECT * FROM follow_requests WHERE requester_id=? OR target_id=?',(me,me))]
    return JSONResponse(result,headers={'Content-Disposition':'attachment; filename="synapse-meus-dados.json"'})


@app.delete('/api/account')
def delete_account(data: DeleteBody,response: Response,user=Depends(member)):
    if not password_ok(data.password,user['password_hash']):
        raise HTTPException(401,'Senha incorreta.')
    with db() as con:
        own_role=con.execute("SELECT COALESCE(r.role,'owner') role FROM operators o LEFT JOIN operator_roles r ON r.user_id=o.user_id WHERE o.user_id=?",(user['id'],)).fetchone()
        if own_role and own_role['role']=='owner':
            others=con.execute("SELECT COUNT(*) FROM operators o JOIN actors a ON a.id=o.user_id LEFT JOIN operator_roles r ON r.user_id=o.user_id WHERE a.active=1 AND COALESCE(r.role,'owner')='owner' AND a.id!=?",(user['id'],)).fetchone()[0]
            if not others: raise HTTPException(409,'Transfira a responsabilidade administrativa ou encerre o serviço pelo console antes de excluir a última conta responsável.')
        con.execute('DELETE FROM search_usage WHERE user_id=?',(user['id'],))
        images=[r['image_path'] for r in con.execute('SELECT image_path FROM posts WHERE author_id=?',(user['id'],))]
        story_images=[r['image_path'] for r in con.execute('SELECT image_path FROM stories WHERE author_id=?',(user['id'],))]
        assets = [dict(r) for r in con.execute('SELECT * FROM media_assets WHERE owner_id=?',(user['id'],))]
        con.execute('DELETE FROM actors WHERE id=?',(user['id'],))
    delete_media_files(assets)
    for path in images+[user['avatar_path'],user['cover_path']]+story_images:
        remove_image(path)
    for mail in (DB_PATH.parent/'outbox').glob(user['id']+'-*.eml'):
        mail.unlink(missing_ok=True)
    response.delete_cookie('synapse_session',path='/')
    return {'ok':True}



def safe_url(value: str, optional: bool=False) -> str:
    """Validate links only; NEVER fetch an arbitrary user-provided URL on the server."""
    value=value.strip()
    if not value and optional:
        return ''
    if len(value)>2048 or any(ord(c)<33 for c in value) or '\\' in value:
        raise HTTPException(422,'Use um endereço HTTP ou HTTPS válido, sem espaços.')
    try:
        parts=urlsplit(value)
        host=parts.hostname or ''
        _=parts.port
        if parts.scheme not in ('http','https') or not host or parts.username is not None or parts.password is not None:
            raise ValueError()
        if host.lower().rstrip('.') in ('localhost','localhost.localdomain') or host.lower().endswith(('.localhost','.local')):
            raise ValueError()
        try:
            address=ipaddress.ip_address(host)
        except ValueError:
            if '.' not in host or not re.fullmatch(r'[\w.\-]+',host,re.UNICODE):
                raise ValueError()
        else:
            if not address.is_global:
                raise ValueError()
    except (ValueError, UnicodeError):
        raise HTTPException(422,'Use um link público HTTP ou HTTPS, sem usuário ou senha no endereço.')
    return urlunsplit((parts.scheme,parts.netloc,parts.path or '/',parts.query,parts.fragment))


_storage_lock=threading.Lock()
def ensure_storage_capacity(reserve=0):
    MEDIA_DIR.mkdir(parents=True,exist_ok=True)
    with _storage_lock:
        total=sum(p.stat().st_size for p in MEDIA_DIR.iterdir() if p.is_file() and not p.is_symlink())
        maximum=max(1,int(os.getenv('MEDIA_TOTAL_LIMIT_MB','5000')))*1024*1024
        if total+reserve>maximum or shutil.disk_usage(MEDIA_DIR).free<reserve+100*1024*1024:
            raise HTTPException(507,'Armazenamento insuficiente. O envio foi pausado para proteger os dados existentes.')


def persist_image(data: str) -> str:
    if not data:
        return ''
    ensure_storage_capacity(4*1024*1024)
    # Re-encode raster input, stripping metadata and ignoring any embedded payload.
    if not re.match(r'^data:image/(jpeg|png|webp);base64,',data):
        raise HTTPException(422,'Envie uma imagem JPEG, PNG ou WebP.')
    try:
        raw=base64.b64decode(data.split(',',1)[1],validate=True)
        if len(raw)>3*1024*1024:
            raise HTTPException(413,'A imagem deve ter no máximo 3 MB.')
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ('JPEG','PNG','WEBP') or im.width*im.height>16_000_000:
                raise HTTPException(422,'Imagem inválida ou acima de 16 megapixels.')
            im=ImageOps.exif_transpose(im)
            im.thumbnail((1440,1440))
            im=im.convert('RGB')
            name=uid()+'.jpg'
            MEDIA_DIR.mkdir(parents=True,exist_ok=True)
            im.save(MEDIA_DIR/name,format='JPEG',quality=87)
        return '/media/'+name
    except HTTPException:
        raise
    except (ValueError, binascii.Error, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise HTTPException(422,'Não foi possível ler esta imagem.')


def remove_image(path: str) -> None:
    if re.fullmatch(r'/media/[a-f0-9]{32}\.jpg',path or ''):
        (MEDIA_DIR/path.rsplit('/',1)[1]).unlink(missing_ok=True)


@app.post('/api/posts')
def add_post(data: PostBody,user=Depends(member)):
    if not site_settings()['uploads_enabled'] and (data.image_data):
        raise HTTPException(503, 'O envio de imagens está temporariamente pausado.')
    link=safe_url(data.link_url,optional=True)
    if data.image_data and data.media_ids:
        raise HTTPException(422,'Use o envio tradicional ou a galeria, não os dois juntos.')
    image=persist_image(data.image_data)
    pid=uid()
    try:
        with db() as con:
            con.execute("INSERT INTO posts(id,author_id,body,source,created_at,link_url,link_title,image_path,image_alt) VALUES(?,?,?,'human',?,?,?,?,?)",
                        (pid,user['id'],data.body,now(),link,data.link_title,image,data.image_alt))
            attach_media(con, pid, user['id'], data.media_ids)
    except Exception:
        remove_image(image)
        raise
    return {'id':pid}


@app.post('/api/messages/{target_id}')
def send_message(target_id: str,data: MessageBody,user=Depends(member)):
    rate_limit('messages:'+user['id'],20)
    with db() as con:
        target=actor(con,target_id)
        if target_id==user['id'] or blocked(con,user['id'],target_id):
            raise HTTPException(403,'Não é possível enviar a esse perfil.')
        if target['dm_policy']=='off' or (target['dm_policy']=='following' and not con.execute('SELECT 1 FROM follows WHERE user_id=? AND target_id=?',(target_id,user['id'])).fetchone()):
            raise HTTPException(403,'Este perfil não permite mensagens da sua conta.')
        if target['seeded']:
            raise HTTPException(400,'Perfil fictício. Crie uma segunda conta para testar mensagens.')
        con.execute("INSERT INTO messages(id,sender_id,recipient_id,body,source,created_at) VALUES(?,?,?,?,'human',?)",
                    (uid(),user['id'],target_id,data.body,now()))
    return {'ok':True}


@app.post('/api/links')
def save_link(data: LinkBody,user=Depends(member)):
    url=safe_url(data.url)
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        existing=con.execute('SELECT id FROM web_links WHERE owner_id=? AND url=?',(user['id'],url)).fetchone()
        if existing:
            con.execute('UPDATE web_links SET title=?,collection=?,note=? WHERE id=?',(data.title,data.collection,data.note,existing['id']))
            return {'id':existing['id'],'updated':True}
        if con.execute('SELECT COUNT(*) FROM web_links WHERE owner_id=?',(user['id'],)).fetchone()[0]>=500:
            raise HTTPException(409,'Limite do piloto: 500 links por conta.')
        lid=uid()
        con.execute('INSERT INTO web_links VALUES(?,?,?,?,?,?,?)',(lid,user['id'],url,data.title,data.collection,data.note,now()))
    return {'id':lid,'updated':False}


@app.delete('/api/links/{link_id}')
def delete_link(link_id: str,user=Depends(member)):
    with db() as con:
        row=con.execute('DELETE FROM web_links WHERE id=? AND owner_id=?',(link_id,user['id']))
        if not row.rowcount:
            raise HTTPException(404,'Link não encontrado.')
    return {'ok':True}


def plain(value: str) -> str:
    return html.unescape(re.sub(r'<[^>]*>','',str(value)))[:1000]


def folded(value: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if not unicodedata.combining(c))


def external_shortcuts(query: str) -> list:
    q=quote(query,safe='')
    return [{'name':'Google','url':'https://www.google.com/search?q='+q},
            {'name':'Brave','url':'https://search.brave.com/search?q='+q},
            {'name':'DuckDuckGo','url':'https://duckduckgo.com/?q='+q}]


def reserve_search(user_id: str) -> None:
    day=now()[:10]
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        # Counts, not query text. Remove old counts; global counts survive account deletion.
        con.execute('DELETE FROM search_usage WHERE day<?',((datetime.now(timezone.utc)-timedelta(days=7)).date().isoformat(),))
        per=con.execute('SELECT count FROM search_usage WHERE user_id=? AND day=?',(user_id,day)).fetchone()
        glob=con.execute('SELECT count FROM search_global_usage WHERE day=?',(day,)).fetchone()
        if (per and per[0]>=SEARCH_DAILY_LIMIT) or (glob and glob[0]>=SEARCH_GLOBAL_DAILY_LIMIT):
            raise HTTPException(429,'Limite diário de pesquisa integrada atingido. Use os atalhos externos.')
        con.execute('INSERT INTO search_usage VALUES(?,?,1) ON CONFLICT(user_id,day) DO UPDATE SET count=count+1',(user_id,day))
        con.execute('INSERT INTO search_global_usage VALUES(?,1) ON CONFLICT(day) DO UPDATE SET count=count+1',(day,))


@app.get('/api/search')
def search(request: Request,q: str=Query(min_length=1,max_length=200),scope: Literal['social','people','web','wiki']='social'):
    q=q.strip()
    if not q:
        raise HTTPException(422,'Digite algo para pesquisar.')
    rate_limit('search:'+(request.client.host if request.client else 'local'),40)
    shortcuts=external_shortcuts(q)
    if scope in ('social','people'):
        # Pilot: searches the visible snapshot (100 posts/500 profiles), not an entire huge index.
        snapshot=state(request)
        needle=folded(q)
        people=[p for p in snapshot['actors'] if p['id'] not in snapshot['blocked'] and needle in folded(p['name']+' '+p['handle']+' '+p['bio'])]
        posts=[p for p in snapshot['posts'] if needle in folded(p['body']+' '+p['link_title']+' '+p['link_url'])]
        return {'query':q,'scope':scope,'posts':posts if scope=='social' else [],'people':people,'results':[], 'provider':'synapse','shortcuts':shortcuts}
    if user_for_search:=session(request):
        if is_minor(user_for_search) and scope in ('web','wiki'):
            raise HTTPException(403,'A pesquisa externa está desativada para contas de menores nesta versão.')
    if scope=='web' and (SEARCH_PROVIDER!='brave' or not BRAVE_SEARCH_API_KEY):
        return {'query':q,'scope':scope,'provider':'external','results':[],'shortcuts':shortcuts,
                'notice':'A busca web integrada não está configurada. Os botões abaixo abrem resultados reais no buscador escolhido, em outra aba.'}
    headers={'User-Agent':'Synapse-Private-Beta/0.6 (user-initiated search)','Accept':'application/json'}
    if scope=='web':
        if request.headers.get('x-synapse-client') not in ('web-v03','web-v04','web-v05','web-v06','web-v07','admin-v07','web-v08','web-v09') or request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403,'Solicitação de pesquisa não permitida.')
        user=member(request)
        reserve_search(user['id'])
        endpoint='https://api.search.brave.com/res/v1/web/search'
        params={'q':q,'count':10,'country':'BR','safesearch':'strict','text_decorations':'false'}
        headers['X-Subscription-Token']=BRAVE_SEARCH_API_KEY
    else:
        endpoint='https://pt.wikipedia.org/w/api.php'
        params={'action':'query','list':'search','srsearch':q,'format':'json','utf8':1,'srlimit':10}
    try:
        # Fixed hosts only. No arbitrary URLs, redirects, or silent fallback to fake results.
        with httpx.Client(timeout=12,follow_redirects=False) as client:
            response=client.get(endpoint,params=params,headers=headers)
            response.raise_for_status()
            payload=response.json()
        if not isinstance(payload,dict) or 'error' in payload:
            raise ValueError('Invalid provider response')
        if scope=='wiki':
            results=[{'title':plain(r['title']),'url':'https://pt.wikipedia.org/?curid='+str(int(r['pageid'])),
                      'description':plain(r.get('snippet','')),'provider':'Wikipédia'} for r in payload.get('query',{}).get('search',[])]
        else:
            results=[]
            for r in payload.get('web',{}).get('results',[]):
                try: url=safe_url(r['url'])
                except (HTTPException,KeyError): continue
                results.append({'title':plain(r.get('title',url)),'url':url,'description':plain(r.get('description','')),'provider':'Brave Search'})
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(502,'O provedor não respondeu corretamente. Tente novamente ou abra a pesquisa pelos atalhos externos.')
    return {'query':q,'scope':scope,'provider':'wikipedia' if scope=='wiki' else 'brave','results':results[:10],'shortcuts':shortcuts}


@app.get('/api/health')
def health():
    return {'ok':True,'version':'0.9.0','agents_enabled':False}


# ----- 0.4: account lifecycle, personalization, stories, notifications, moderation -----
def validate_email(value: str) -> str:
    value=value.strip().lower()
    if not re.fullmatch(r"[^\s@<>\r\n]+@[^\s@<>\r\n]+\.[^\s@<>\r\n]+",value):
        raise HTTPException(422,'Digite um e-mail válido.')
    return value


def send_token(user_id: str, email: str, purpose: str):
    """Tokens are one-use, hashed in SQLite and never returned by a public API."""
    token=secrets.token_urlsafe(32)
    with db() as con:
        con.execute('DELETE FROM auth_tokens WHERE user_id=? AND purpose=?',(user_id,purpose))
        con.execute('DELETE FROM auth_tokens WHERE expires<?',(time.time(),))
        con.execute('INSERT INTO auth_tokens VALUES(?,?,?,?,?)',
                    (hashlib.sha256(token.encode()).hexdigest(),user_id,purpose,time.time()+(1800 if purpose=='reset' else 86400),now()))
    url=(PUBLIC_ORIGIN or 'http://localhost:8000')+'/?'+urlencode({purpose:token})
    msg=EmailMessage()
    msg['Subject']='Synapse — '+('recuperar acesso' if purpose=='reset' else 'confirmar e-mail')
    msg['From']=os.getenv('SMTP_FROM','Synapse <nao-responda@localhost>')
    msg['To']=email
    msg.set_content('Abra o link para '+('definir uma nova senha' if purpose=='reset' else 'confirmar seu e-mail')+':\n\n'+url+'\n\nNão compartilhe este link. Se não foi você, ignore a mensagem.')
    try:
        if MAIL_MODE=='smtp':
            host=os.environ['SMTP_HOST'];port=int(os.getenv('SMTP_PORT','587'))
            tls=ssl.create_default_context()
            connection=smtplib.SMTP_SSL(host,port,timeout=12,context=tls) if port==465 else smtplib.SMTP(host,port,timeout=12)
            with connection as smtp:
                if port!=465: smtp.starttls(context=tls)
                if os.getenv('SMTP_USER'): smtp.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD'])
                smtp.send_message(msg)
        elif MAIL_MODE=='file':
            folder=DB_PATH.parent/'outbox';folder.mkdir(parents=True,exist_ok=True);folder.chmod(0o700)
            for expired_mail in folder.glob('*.eml'):
                if expired_mail.stat().st_mtime < time.time()-86400: expired_mail.unlink(missing_ok=True)
            path=folder/(user_id+'-'+uid()+'.eml');path.write_bytes(bytes(msg));path.chmod(0o600)
        # Mode disabled deliberately creates no outgoing email; the UI discloses it.
    except (OSError,smtplib.SMTPException,KeyError,ValueError):
        # Never log a token, password, or SMTP credential.
        with db() as con: log(con,user_id,'mail_delivery_failed',purpose,'Falha no envio. Conferir configuração SMTP e reenviar.')

class EmailBody(Data):
    email: Annotated[str,StringConstraints(min_length=5,max_length=254)]
class TokenBody(Data):
    token: Annotated[str,StringConstraints(min_length=20,max_length=128)]
class ResetBody(TokenBody):
    password: Annotated[str,StringConstraints(min_length=10,max_length=128)]
class PasswordBody(Data):
    current_password: Annotated[str,StringConstraints(min_length=1,max_length=128)]
    password: Annotated[str,StringConstraints(min_length=10,max_length=128)]
class PreferencesBody(Data):
    theme: Literal['light','dark','system']='system'
    accent: Literal['violet','rose','mint','blue']='violet'
    reduce_motion: bool=False
    dm_policy: Literal['everyone','following','off']='everyone'
class StoryBody(Data):
    body: Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=280)]
    color: Literal['violet','rose','mint','blue','amber']='violet'
    image_data: Annotated[str,StringConstraints(max_length=4200000)]=''
class EditPostBody(Data):
    body: Text
    image_alt: Annotated[str,StringConstraints(max_length=250)]=''
class ContentReportBody(Data):
    kind: Literal['profile','story','comment','message']
    target_id: Annotated[str,StringConstraints(min_length=1,max_length=64)]
    reason: Annotated[str,StringConstraints(strip_whitespace=True,min_length=3,max_length=500)]
class ModerateBody(Data):
    action: Literal['dismiss','remove']

@app.post('/api/auth/forgot')
def forgot(data: EmailBody,request:Request):
    rate_limit('forgot:'+(request.client.host if request.client else 'local'),4,300)
    email=validate_email(data.email)
    with db() as con:
        row=con.execute('SELECT id,email FROM actors WHERE email=? AND active=1 AND seeded=0',(email,)).fetchone()
    if row: send_token(row['id'],row['email'],'reset')
    return {'ok':True,'message':'Se o e-mail corresponder a uma conta, as instruções serão enviadas pelo canal configurado.'}

@app.post('/api/auth/reset')
def reset_password(data:ResetBody,request:Request):
    rate_limit('reset:'+(request.client.host if request.client else 'local'),6,300)
    encoded=password_hash(data.password)
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        token=con.execute("SELECT * FROM auth_tokens WHERE token_hash=? AND purpose='reset' AND expires>?",(hashlib.sha256(data.token.encode()).hexdigest(),time.time())).fetchone()
        if not token: raise HTTPException(400,'Link inválido ou expirado. Solicite outro.')
        con.execute('UPDATE actors SET password_hash=? WHERE id=?',(encoded,token['user_id']))
        con.execute('DELETE FROM auth_tokens WHERE user_id=?',(token['user_id'],))
        con.execute('DELETE FROM sessions WHERE user_id=?',(token['user_id'],))
    return {'ok':True}

@app.post('/api/auth/verify')
def verify_email(data:TokenBody,request:Request):
    rate_limit('verify:'+(request.client.host if request.client else 'local'),10,300)
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        token=con.execute("SELECT * FROM auth_tokens WHERE token_hash=? AND purpose='verify' AND expires>?",(hashlib.sha256(data.token.encode()).hexdigest(),time.time())).fetchone()
        if not token: raise HTTPException(400,'Link inválido ou expirado. Solicite outro.')
        con.execute('UPDATE actors SET email_verified=1 WHERE id=?',(token['user_id'],))
        con.execute('DELETE FROM auth_tokens WHERE token_hash=?',(token['token_hash'],))
    return {'ok':True}

@app.post('/api/auth/resend-verification')
def resend_verification(user=Depends(member)):
    rate_limit('resend:'+user['id'],2,300)
    if not user['email']: raise HTTPException(400,'Conta antiga sem e-mail. Use o operador para migrar com verificação.')
    if not user['email_verified']: send_token(user['id'],user['email'],'verify')
    return {'ok':True}

@app.patch('/api/account/password')
def change_password(data:PasswordBody,response:Response,user=Depends(member)):
    rate_limit('password:'+user['id'],5,300)
    if not password_ok(data.current_password,user['password_hash']): raise HTTPException(401,'Senha atual incorreta.')
    encoded=password_hash(data.password)
    with db() as con:
        con.execute('UPDATE actors SET password_hash=? WHERE id=?',(encoded,user['id']))
        con.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
        con.execute("DELETE FROM auth_tokens WHERE user_id=? AND purpose='reset'",(user['id'],))
    response.delete_cookie('synapse_session',path='/')
    return {'ok':True,'login_required':True}

@app.patch('/api/preferences')
def preferences(data:PreferencesBody,user=Depends(member)):
    if is_minor(user) and data.dm_policy!='off':
        raise HTTPException(403,'Mensagens diretas permanecem desativadas para contas de menores.')
    with db() as con:
        con.execute('UPDATE actors SET theme=?,accent=?,reduce_motion=?,dm_policy=? WHERE id=?',
                    (data.theme,data.accent,int(data.reduce_motion),data.dm_policy,user['id']))
    return {'ok':True}

@app.patch('/api/posts/{post_id}')
def edit_post(post_id:str,data:EditPostBody,user=Depends(member)):
    with db() as con:
        post=visible_post(con,post_id,user['id'])
        if post['author_id']!=user['id']: raise HTTPException(403,'Você só pode editar suas publicações.')
        con.execute('UPDATE posts SET body=?,image_alt=? WHERE id=?',(data.body,data.image_alt,post_id))
    return {'ok':True}

@app.delete('/api/comments/{comment_id}')
def delete_comment(comment_id:str,user=Depends(member)):
    with db() as con:
        row=con.execute('SELECT c.*,p.author_id AS post_owner FROM comments c JOIN posts p ON p.id=c.post_id WHERE c.id=?',(comment_id,)).fetchone()
        if not row: raise HTTPException(404,'Comentário não encontrado.')
        if user['id'] not in (row['author_id'],row['post_owner']): raise HTTPException(403,'Você não pode remover este comentário.')
        con.execute('DELETE FROM comments WHERE id=?',(comment_id,))
    return {'ok':True}

@app.get('/api/stories')
def list_stories(request:Request):
    user=session(request);me=user['id'] if user else ''
    with db() as con:
        expired=list(con.execute('SELECT image_path FROM stories WHERE expires<=?',(time.time(),)))
        con.execute('DELETE FROM stories WHERE expires<=?',(time.time(),))
        rows=[dict(r) for r in con.execute('SELECT s.* FROM stories s JOIN actors a ON a.id=s.author_id WHERE s.expires>? AND a.active=1 ORDER BY s.created_at DESC LIMIT 100',(time.time(),))
              if can_view_author(con,r['author_id'],me)]
    for row in expired: remove_image(row['image_path'])
    return {'stories':rows}

@app.post('/api/stories')
def add_story(data:StoryBody,user=Depends(member)):
    if not site_settings()['uploads_enabled'] and (data.image_data):
        raise HTTPException(503, 'O envio de imagens está temporariamente pausado.')
    rate_limit('story:'+user['id'],10,3600)
    image=persist_image(data.image_data);sid=uid()
    try:
        with db() as con:
            con.execute('INSERT INTO stories VALUES(?,?,?,?,?,?,?)',(sid,user['id'],data.body,image,data.color,now(),time.time()+86400))
    except Exception:
        remove_image(image);raise
    return {'id':sid}

@app.delete('/api/stories/{story_id}')
def delete_story(story_id:str,user=Depends(member)):
    with db() as con:
        row=con.execute('SELECT * FROM stories WHERE id=? AND author_id=?',(story_id,user['id'])).fetchone()
        if not row: raise HTTPException(404,'Story não encontrado.')
        con.execute('DELETE FROM stories WHERE id=?',(story_id,))
    remove_image(row['image_path']);return {'ok':True}

@app.get('/api/notifications')
def list_notifications(request:Request):
    user=session(request)
    if not user:return {'notifications':[]}
    with db() as con:
        rows=[dict(r) for r in con.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 100',(user['id'],))
              if not blocked(con,user['id'],r['actor_id'])]
    return {'notifications':rows}

@app.post('/api/notifications/read')
def read_notifications(user=Depends(member)):
    with db() as con:con.execute('UPDATE notifications SET seen=1 WHERE user_id=?',(user['id'],))
    return {'ok':True}

@app.post('/api/reports')
def content_report(data:ContentReportBody,user=Depends(member)):
    rate_limit('report:'+user['id'],15,3600)
    with db() as con:
        table={'profile':'actors','story':'stories','comment':'comments','message':'messages'}[data.kind]
        row=con.execute(f'SELECT * FROM {table} WHERE id=?',(data.target_id,)).fetchone()
        if not row:raise HTTPException(404,'Conteúdo não encontrado.')
        if data.kind=='message' and user['id'] not in (row['sender_id'],row['recipient_id']):raise HTTPException(404,'Conteúdo não encontrado.')
        con.execute('INSERT INTO content_reports VALUES(?,?,?,?,?,?,?)',(uid(),user['id'],data.kind,data.target_id,data.reason,'open',now()))
    return {'ok':True}

def admin(request: Request, user=Depends(member)):
    if not is_operator(user):raise HTTPException(403,'Acesso exclusivo ao operador autorizado.')
    if os.getenv('SYNAPSE_ENV') == 'production': require_admin_elevation(request,user)
    return user

@app.get('/api/admin/reports')
def admin_reports(user=Depends(admin)):
    with db() as con:
        rows=[dict(r) for r in con.execute("SELECT r.*, 'post' AS kind, r.post_id AS target_id,p.body AS content FROM reports r LEFT JOIN posts p ON p.id=r.post_id ORDER BY r.created_at DESC LIMIT 100")]
        for r in con.execute('SELECT * FROM content_reports ORDER BY created_at DESC LIMIT 100'):
            report=dict(r);table={'profile':'actors','story':'stories','comment':'comments','message':'messages'}[r['kind']]
            target=con.execute(f'SELECT * FROM {table} WHERE id=?',(r['target_id'],)).fetchone()
            report['content']=(target['bio'] if r['kind']=='profile' else target['body']) if target else '[removido]'
            rows.append(report)
    return {'reports':sorted(rows,key=lambda r:r['created_at'],reverse=True)}

@app.post('/api/admin/reports/{report_id}')
def moderate(report_id:str,data:ModerateBody,user=Depends(admin)):
    image=''
    assets=[]
    with db() as con:
        row=con.execute('SELECT * FROM reports WHERE id=?',(report_id,)).fetchone();table='reports'
        if row:
            kind='post';target=row['post_id']
        else:
            table='content_reports';row=con.execute('SELECT * FROM content_reports WHERE id=?',(report_id,)).fetchone()
            if not row:raise HTTPException(404,'Denúncia não encontrada.')
            kind=row['kind'];target=row['target_id']
        if data.action=='remove':
            if kind=='post':
                found=con.execute('SELECT image_path FROM posts WHERE id=?',(target,)).fetchone()
                image=found['image_path'] if found else ''
                assets=owned_post_files(con, target)
                con.execute('DELETE FROM posts WHERE id=?',(target,))
            elif kind=='profile':
                if target==user['id']:raise HTTPException(400,'Você não pode suspender a própria conta.')
                if con.execute('SELECT 1 FROM operators WHERE user_id=?',(target,)).fetchone():raise HTTPException(409,'Conta administrativa protegida.')
                con.execute('UPDATE actors SET active=0 WHERE id=?',(target,))
                con.execute('DELETE FROM sessions WHERE user_id=?',(target,))
                # Suspended users disappear from feed; posts are not destroyed.
            else:
                content_table={'story':'stories','comment':'comments','message':'messages'}[kind]
                if kind=='story':
                    found=con.execute('SELECT image_path FROM stories WHERE id=?',(target,)).fetchone();image=found['image_path'] if found else ''
                con.execute(f'DELETE FROM {content_table} WHERE id=?',(target,))
        con.execute(f'UPDATE {table} SET status=? WHERE id=?',('removed' if data.action=='remove' else 'dismissed',report_id))
        log(con,user['id'],'moderation_'+data.action,report_id,'Denúncia revisada manualmente pelo operador.')
    delete_media_files(assets)
    remove_image(image);return {'ok':True}


# Register extended routes BEFORE the static root. Media visibility is checked per request.
from features import install as install_features
install_features(app, sys.modules[__name__])
from administration import install as install_administration
install_administration(app, sys.modules[__name__])
from launch import install as install_launch
install_launch(app, sys.modules[__name__])
from safety import install as install_safety
install_safety(app, sys.modules[__name__])
from operations import install as install_operations
install_operations(app, sys.modules[__name__])
MEDIA_DIR.mkdir(parents=True,exist_ok=True)
app.mount('/',StaticFiles(directory=ROOT/'web',html=True),name='web')
