"""Synapse 0.3: private social discovery prototype. No agent/AI execution."""
from __future__ import annotations

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
from pydantic import BaseModel, ConfigDict, StringConstraints

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
        if not con.execute("SELECT 1 FROM actors WHERE id='synapse'").fetchone():
            stamp=now()
            people=[('synapse','synapse','Equipe Synapse','Descubra, guarde, compartilhe. Perfil editorial fictício.','mint'),
                    ('lia','lia.cria','Lia Martins','Design, referências e boas perguntas. Perfil fictício.','rose'),
                    ('caio','caio.explora','Caio Costa','Ciência, tecnologia e curiosidade. Perfil fictício.','blue')]
            con.executemany("INSERT INTO actors(id,handle,name,kind,bio,color,seeded,created_at) VALUES(?,?,?,'human',?,?,1,?)",[(*a,stamp) for a in people])
        if not con.execute("SELECT 1 FROM posts WHERE id='discover-v03'").fetchone():
            samples=[('discover-v03','synapse','A internet é grande demais para explorar sozinho.\n\nPesquise um assunto, salve seus links e transforme uma descoberta em conversa. Bem-vindo ao novo Synapse. #descobertas','https://pt.wikipedia.org/','Um ponto de partida para a sua curiosidade'),
                     ('design-v03','lia','Hoje a minha pasta de referências virou uma coleção de ideias. Qual foi a melhor coisa que você encontrou na internet esta semana? #design #criacao','https://developer.mozilla.org/pt-BR/','Referências para criar na web')]
            for i,(pid,author,body,url,title) in enumerate(samples):
                con.execute("INSERT INTO posts(id,author_id,body,source,created_at,link_url,link_title) VALUES(?,?,?,'seed',?,?,?)",(pid,author,body,(datetime.now(timezone.utc)-timedelta(minutes=i*20)).isoformat(),url,title))

@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize()
    yield


app = FastAPI(title='Synapse API', version='0.3.0', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

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
    if request.url.path.startswith('/api/') and request.method not in ('GET','HEAD','OPTIONS'):
        origin = request.headers.get('origin')
        allowed = {str(request.base_url).rstrip('/')}
        if PUBLIC_ORIGIN:
            allowed.add(PUBLIC_ORIGIN)
        if (origin and origin not in allowed) or request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail':'Origem da solicitação não permitida.'}, status_code=403)
        if request.headers.get('x-synapse-client') != 'web-v03':
            return JSONResponse({'detail':'Cabeçalho de proteção ausente.'}, status_code=403)
        if request.headers.get('content-type','').split(';')[0] != 'application/json':
            return JSONResponse({'detail':'Envie dados JSON.'}, status_code=415)
        try:
            if int(request.headers.get('content-length','0')) > 4300000:
                return JSONResponse({'detail':'Solicitação muito grande.'}, status_code=413)
        except ValueError:
            return JSONResponse({'detail':'Tamanho inválido.'}, status_code=400)
        if len(await request.body()) > 4300000:
            return JSONResponse({'detail':'Solicitação muito grande.'}, status_code=413)
        try:
            rate_limit('write:' + (request.client.host if request.client else 'local'), 100)
        except HTTPException as exc:
            return JSONResponse({'detail':exc.detail}, status_code=exc.status_code)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
        "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; "
        "frame-src 'none'; frame-ancestors 'none'; form-action 'self'; worker-src 'self'; manifest-src 'self'"
    )
    if request.url.path.startswith('/api/') or request.url.path in ('/', '/index.html', '/sw.js'):
        response.headers['Cache-Control'] = 'no-store'
    if COOKIE_SECURE:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response


class Data(BaseModel):
    model_config = ConfigDict(extra='forbid')


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class Registration(Data):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=50)]
    handle: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r'^[a-zA-Z0-9_.]{3,24}$')]
    password: Annotated[str, StringConstraints(min_length=10, max_length=128)]


class Login(Data):
    handle: Annotated[str, StringConstraints(min_length=1,max_length=64)]
    password: Annotated[str, StringConstraints(min_length=1,max_length=128)]


class PostBody(Data):
    body: Text
    link_url: Annotated[str, StringConstraints(max_length=2048)] = ''
    link_title: Annotated[str, StringConstraints(strip_whitespace=True,max_length=180)] = ''
    image_data: Annotated[str, StringConstraints(max_length=4200000)] = ''
    image_alt: Annotated[str, StringConstraints(strip_whitespace=True,max_length=250)] = '' 


class CommentBody(Data):
    body: Annotated[str, StringConstraints(strip_whitespace=True,min_length=1,max_length=600)]


class ProfileBody(Data):
    name: Annotated[str, StringConstraints(strip_whitespace=True,min_length=2,max_length=50)]
    bio: Annotated[str, StringConstraints(strip_whitespace=True,max_length=300)] = ''


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
        row=con.execute('SELECT a.*, s.csrf FROM sessions s JOIN actors a ON a.id=s.user_id WHERE s.token_hash=? AND s.expires>?',
                        (key,time.time())).fetchone()
    return dict(row) if row else None


def member(request: Request):
    user=session(request)
    if not user:
        raise HTTPException(401,'Entre na sua conta para continuar.')
    if request.method not in ('GET','HEAD'):
        if not hmac.compare_digest(user['csrf'],request.headers.get('x-csrf-token','')):
            raise HTTPException(403,'Sessão de segurança inválida. Recarregue a página.')
    return user


def set_session(user_id: str, response: Response) -> str:
    token=secrets.token_urlsafe(32)
    csrf=secrets.token_urlsafe(24)
    with db() as con:
        con.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
        con.execute('INSERT INTO sessions VALUES(?,?,?,?)',
                    (hashlib.sha256(token.encode()).hexdigest(),user_id,csrf,time.time()+86400*7))
    response.set_cookie('synapse_session',token,max_age=86400*7,httponly=True,secure=COOKIE_SECURE,samesite='strict',path='/')
    return csrf


def public_actor(a) -> dict:
    return {k:a[k] for k in ('id','handle','name','kind','bio','color','owner_id','seeded','active','created_at')}


def actor(con, actor_id: str):
    result=con.execute('SELECT * FROM actors WHERE id=?',(actor_id,)).fetchone()
    if not result or result['kind'] != 'human':
        raise HTTPException(404,'Perfil não encontrado.')
    return result


def blocked(con, me: str, other: str) -> bool:
    return bool(con.execute('SELECT 1 FROM blocks WHERE (user_id=? AND target_id=?) OR (user_id=? AND target_id=?)',
                            (me,other,other,me)).fetchone())


def visible_post(con, post_id: str, me: str):
    post=con.execute('SELECT * FROM posts WHERE id=?',(post_id,)).fetchone()
    if not post or con.execute('SELECT kind FROM actors WHERE id=?',(post['author_id'],)).fetchone()['kind'] != 'human' or (me and blocked(con,me,post['author_id'])):
        raise HTTPException(404,'Publicação indisponível.')
    return post


def log(con, owner: str, action: str, subject: str, summary: str):
    con.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)',(uid(),owner,action,subject,summary,now()))


@app.get('/api/state')
def state(request: Request):
    user=session(request)
    me=user['id'] if user else ''
    with db() as con:
        all_actors=[public_actor(a) for a in con.execute("SELECT * FROM actors WHERE kind='human' ORDER BY created_at LIMIT 500")]
        blocked_ids=[r['target_id'] for r in con.execute('SELECT target_id FROM blocks WHERE user_id=?',(me,))]
        invisible=set(blocked_ids)|{r['user_id'] for r in con.execute('SELECT user_id FROM blocks WHERE target_id=?',(me,))}
        follows=[r['target_id'] for r in con.execute('SELECT target_id FROM follows WHERE user_id=?',(me,))]
        saved=[r['post_id'] for r in con.execute('SELECT post_id FROM bookmarks WHERE user_id=?',(me,))]
        posts=[]
        rows=con.execute('''SELECT p.*, (SELECT COUNT(*) FROM likes l WHERE l.post_id=p.id) AS likes,
                            EXISTS(SELECT 1 FROM likes l WHERE l.post_id=p.id AND l.user_id=?) AS liked
                            FROM posts p JOIN actors a ON a.id=p.author_id WHERE a.kind='human' ORDER BY p.created_at DESC LIMIT 100''',(me,))
        for row in rows:
            if row['author_id'] in invisible:
                continue
            post=dict(row)
            post['comments']=[dict(c) for c in con.execute('SELECT * FROM comments WHERE post_id=? ORDER BY created_at LIMIT 100',(row['id'],)) if c['author_id'] not in invisible]
            posts.append(post)
        links=[dict(r) for r in con.execute('SELECT * FROM web_links WHERE owner_id=? ORDER BY created_at DESC LIMIT 500',(me,))]
        own_reports=con.execute('SELECT COUNT(*) AS n FROM reports WHERE reporter_id=?',(me,)).fetchone()['n']
        for a in all_actors:
            a['followers']=con.execute('SELECT COUNT(*) AS n FROM follows WHERE target_id=?',(a['id'],)).fetchone()['n']
    return {'version':'0.3.0','mode':'server','search_provider':'brave' if SEARCH_PROVIDER=='brave' and BRAVE_SEARCH_API_KEY else 'external',
            'me':public_actor(user) if user else None,'csrf':user['csrf'] if user else '',
            'actors':all_actors,'posts':posts,'following':follows,'saved':saved,'blocked':blocked_ids,
            'links':links,'reports_count':own_reports}

@app.post('/api/auth/register')
def register(data: Registration, request: Request, response: Response):
    rate_limit('auth:'+(request.client.host if request.client else 'local'),10)
    user_id=uid()
    encoded=password_hash(data.password)
    try:
        with db() as con:
            con.execute('INSERT INTO actors(id,handle,name,kind,bio,color,password_hash,created_at) VALUES(?,?,?,\'human\',\'\',\'blue\',?,?)',
                        (user_id,data.handle.lower(),data.name,encoded,now()))
            log(con,user_id,'account_created',user_id,'Conta humana criada; identidade não verificada.')
    except sqlite3.IntegrityError:
        raise HTTPException(409,'Esse nome de usuário já está em uso.')
    csrf=set_session(user_id,response)
    return {'ok':True,'csrf':csrf}


@app.post('/api/auth/login')
def login(data: Login, request: Request, response: Response):
    rate_limit('auth:'+(request.client.host if request.client else 'local'),10)
    with db() as con:
        user=con.execute("SELECT * FROM actors WHERE handle=? COLLATE NOCASE AND kind='human'",(data.handle.strip(),)).fetchone()
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
    with db() as con:
        con.execute('UPDATE actors SET name=?,bio=? WHERE id=?',(data.name,data.bio,user['id']))
    return {'ok':True}


@app.delete('/api/posts/{post_id}')
def delete_post(post_id: str,user=Depends(member)):
    with db() as con:
        post=visible_post(con,post_id,user['id'])
        if post['author_id'] != user['id']:
            raise HTTPException(403,'Você só pode excluir suas publicações.')
        con.execute('DELETE FROM posts WHERE id=?',(post_id,))
        remove_image(post['image_path'])
        log(con,user['id'],'post_deleted',post_id,'Publicação removida do feed.')
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
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        actor(con,target_id)
        if target_id==user['id'] or blocked(con,user['id'],target_id):
            raise HTTPException(400,'Não é possível seguir esse perfil.')
        exists=con.execute('SELECT 1 FROM follows WHERE user_id=? AND target_id=?',(user['id'],target_id)).fetchone()
        if exists:
            con.execute('DELETE FROM follows WHERE user_id=? AND target_id=?',(user['id'],target_id))
        else:
            con.execute('INSERT INTO follows VALUES(?,?)',(user['id'],target_id))
    return {'active':not bool(exists)}


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
            con.execute('DELETE FROM follows WHERE (user_id=? AND target_id=?) OR (user_id=? AND target_id=?)',
                        (user['id'],target_id,target_id,user['id']))
        log(con,user['id'],'block_changed',target_id,'Bloqueio removido.' if exists else 'Perfil bloqueado.')
    return {'active':not bool(exists)}


@app.post('/api/posts/{post_id}/report')
def report(post_id: str,data: ReportBody,user=Depends(member)):
    with db() as con:
        visible_post(con,post_id,user['id'])
        con.execute('INSERT INTO reports VALUES(?,?,?,?,?)',(uid(),user['id'],post_id,data.reason,now()))
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
        result={'profile':public_actor(user),'exported_at':now(),
                'posts':[dict(r) for r in con.execute('SELECT * FROM posts WHERE author_id=? OR approved_by=?',(me,me))],
                'comments':[dict(r) for r in con.execute('SELECT * FROM comments WHERE author_id=?',(me,))],
                'messages':[dict(r) for r in con.execute('SELECT * FROM messages WHERE sender_id=? OR recipient_id=?',(me,me))],
                'agents':[public_actor(r) for r in con.execute('SELECT * FROM actors WHERE owner_id=?',(me,))]}
        for table,field in [('drafts','owner_id'),('missions','owner_id'),('audit','owner_id'),('reports','reporter_id'),
                            ('follows','user_id'),('blocks','user_id'),('likes','user_id'),('bookmarks','user_id'),('usage','user_id'),('web_links','owner_id')]:
            result[table]=[dict(r) for r in con.execute(f'SELECT * FROM {table} WHERE {field}=?',(me,))]
    return JSONResponse(result,headers={'Content-Disposition':'attachment; filename="synapse-meus-dados.json"'})


@app.delete('/api/account')
def delete_account(data: DeleteBody,response: Response,user=Depends(member)):
    if not password_ok(data.password,user['password_hash']):
        raise HTTPException(401,'Senha incorreta.')
    with db() as con:
        con.execute('DELETE FROM search_usage WHERE user_id=?',(user['id'],))
        images=[r['image_path'] for r in con.execute('SELECT image_path FROM posts WHERE author_id=?',(user['id'],))]
        con.execute('DELETE FROM actors WHERE id=?',(user['id'],))
    for path in images:
        remove_image(path)
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


def persist_image(data: str) -> str:
    if not data:
        return ''
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
    link=safe_url(data.link_url,optional=True)
    image=persist_image(data.image_data)
    pid=uid()
    try:
        with db() as con:
            con.execute("INSERT INTO posts(id,author_id,body,source,created_at,link_url,link_title,image_path,image_alt) VALUES(?,?,?,'human',?,?,?,?,?)",
                        (pid,user['id'],data.body,now(),link,data.link_title,image,data.image_alt))
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
    if scope=='web' and (SEARCH_PROVIDER!='brave' or not BRAVE_SEARCH_API_KEY):
        return {'query':q,'scope':scope,'provider':'external','results':[],'shortcuts':shortcuts,
                'notice':'A busca web integrada não está configurada. Os botões abaixo abrem resultados reais no buscador escolhido, em outra aba.'}
    headers={'User-Agent':'Synapse-Private-Prototype/0.3 (user-initiated search)','Accept':'application/json'}
    if scope=='web':
        if request.headers.get('x-synapse-client') != 'web-v03' or request.headers.get('sec-fetch-site') == 'cross-site':
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
    return {'ok':True,'version':'0.3.0','agents_enabled':False}


# Only static UI and public post images are exposed. DB/source/secrets remain outside web/.
MEDIA_DIR.mkdir(parents=True,exist_ok=True)
app.mount('/media',StaticFiles(directory=MEDIA_DIR),name='media')
app.mount('/',StaticFiles(directory=ROOT/'web',html=True),name='web')
