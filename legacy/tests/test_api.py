"""Private-pilot integration tests. Provider responses are mocked, never billed."""
import base64
import io
import json
import sys
from pathlib import Path
import pytest
import httpx
from fastapi.testclient import TestClient
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
HEADERS={'X-Synapse-Client':'web-v03','Content-Type':'application/json'}

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'DB_PATH',tmp_path/'test.db')
    monkeypatch.setattr(server,'MEDIA_DIR',tmp_path/'media')
    monkeypatch.setattr(server,'SEARCH_PROVIDER','external')
    monkeypatch.setattr(server,'BRAVE_SEARCH_API_KEY','')
    server._rates.clear()
    with TestClient(server.app,headers=HEADERS) as c:
        yield c

def register(c,handle='criador'):
    r=c.post('/api/auth/register',json={'name':'Criador de teste','handle':handle,'password':'test-password-2026','email':handle.lower()+'@example.com','terms_accepted':True})
    assert r.status_code==200,r.text
    c.headers['X-CSRF-Token']=r.json()['csrf']
    assert c.patch('/api/preferences',json={'dm_policy':'everyone'}).status_code==200  # Explicit consent in legacy messaging fixtures.
    return c.get('/api/state').json()['me']

def post(c,**data):
    r=c.post('/api/posts',json={'body':'Minha descoberta sobre tecnologia.',**data})
    assert r.status_code==200,r.text
    return r.json()['id']

def create_image():
    b=io.BytesIO();Image.new('RGB',(600,400),(100,150,120)).save(b,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()

def test_state_no_agents_and_no_secret_paths(client):
    s=client.get('/api/state').json()
    assert len(s['posts'])==2 and all(a['kind']=='human' for a in s['actors'])
    assert s['me'] is None and 'password_hash' not in json.dumps(s)
    for path in ['/server.py','/.env','/schema.sql','/data/synapse.db']:
        assert client.get(path).status_code==404
    assert client.get('/api/state').headers['cache-control']=='no-store'
    assert client.get('/').headers['x-frame-options']=='DENY'
    assert "frame-src 'none'" in client.get('/').headers['content-security-policy']

def test_register_login_session_and_hash(client):
    me=register(client)
    with server.db() as con:
        row=con.execute('SELECT password_hash FROM actors WHERE id=?',(me['id'],)).fetchone()
        assert row[0].startswith('pbkdf2_sha256$600000$')
        assert 'test-password' not in row[0]
    assert client.post('/api/auth/logout',json={}).status_code==200
    assert client.get('/api/state').json()['me'] is None
    r=client.post('/api/auth/login',json={'handle':'CRIADOR','password':'test-password-2026'})
    assert r.status_code==200
    assert 'HttpOnly' in r.headers['set-cookie']
    assert 'SameSite=strict' in r.headers['set-cookie']

def test_auth_invalid_credentials_and_duplicate(client):
    register(client)
    assert client.post('/api/auth/register',json={'name':'Outro','handle':'CRIADOR','password':'test-password-2026','email':'test@example.com','terms_accepted':True}).status_code==409
    assert client.post('/api/auth/login',json={'handle':'criador','password':'errada'}).status_code==401
    assert client.post('/api/auth/login',json={'handle':'synapse','password':'test-password-2026'}).status_code==401
    assert client.post('/api/auth/register',json={'name':'Outro','handle':'outro','password':'curta'}).status_code==422

def test_authorization_csrf_and_origin(client):
    assert client.post('/api/posts',json={'body':'X'}).status_code==401
    register(client)
    for header in [{'X-CSRF-Token':'wrong'},{'Origin':'https://evil.example'},{'X-Synapse-Client':'bad'},{'Sec-Fetch-Site':'cross-site'}]:
        assert client.post('/api/posts',json={'body':'X'},headers=header).status_code==403
    assert client.post('/api/posts',json={'body':'X','author_id':'synapse'}).status_code==422

def test_post_link_like_comment_bookmark_delete(client):
    register(client)
    pid=post(client,link_url='https://example.com',link_title='Referência')
    assert client.post(f'/api/posts/{pid}/like',json={}).json()['active']
    assert client.post(f'/api/posts/{pid}/save',json={}).json()['active']
    assert client.post(f'/api/posts/{pid}/comments',json={'body':'Gostei!'}).status_code==200
    s=client.get('/api/state').json();p=next(p for p in s['posts'] if p['id']==pid)
    assert p['link_url']=='https://example.com/' and p['likes']==1 and p['liked']
    assert p['comments'][0]['body']=='Gostei!' and pid in s['saved']
    assert client.request('DELETE',f'/api/posts/{pid}',json={}).status_code==200
    assert pid not in client.get('/api/state').json()['saved']

def test_image_reencoding_and_deletion(client):
    register(client)
    pid=post(client,image_data=create_image(),image_alt='Uma cor de teste')
    p=next(p for p in client.get('/api/state').json()['posts'] if p['id']==pid)
    path=server.MEDIA_DIR/p['image_path'].split('/')[-1]
    assert path.exists()
    with Image.open(path) as im:
        assert im.format=='JPEG' and im.size==(600,400)
    assert client.request('DELETE',f'/api/posts/{pid}',json={}).status_code==200
    assert not path.exists()

@pytest.mark.parametrize('image',['data:image/svg+xml;base64,PHN2Zz4=','data:image/png;base64,notAnImage','https://evil.example/image.png'])
def test_bad_images_rejected(client,image):
    register(client)
    assert client.post('/api/posts',json={'body':'Teste','image_data':image}).status_code==422

@pytest.mark.parametrize('url',['javascript:alert(1)','file:///etc/passwd','https://user:password@example.com','http://localhost/','http://127.0.0.1/','http://192.168.1.1/','https://example.com/with space','https://example.com\\evil'])
def test_unsafe_urls_rejected(client,url):
    register(client)
    assert client.post('/api/posts',json={'body':'Teste','link_url':url}).status_code==422
    assert client.post('/api/links',json={'url':url,'title':'Teste'}).status_code==422

def test_private_collections_isolation_update_and_delete(client):
    register(client)
    r=client.post('/api/links',json={'url':'https://example.com','title':'Estudo','collection':'Pesquisa','note':'Nota privada'})
    assert r.status_code==200
    lid=r.json()['id']
    r=client.post('/api/links',json={'url':'https://example.com/','title':'Estudo atualizado','collection':'Escola','note':'Privado'})
    assert r.json()['updated']
    assert len(client.get('/api/state').json()['links'])==1
    with TestClient(server.app,headers=HEADERS) as other:
        register(other,'outro')
        assert other.get('/api/state').json()['links']==[]
        assert other.request('DELETE',f'/api/links/{lid}',json={}).status_code==404
    assert client.request('DELETE',f'/api/links/{lid}',json={}).status_code==200
    assert client.get('/api/state').json()['links']==[]

def test_social_search_accents_literal_and_block(client):
    register(client)
    pid=post(client,body='Ciência e fotografia do céu.',link_title='Galáxias')
    s=client.get('/api/search',params={'q':'ciencia','scope':'social'}).json()
    assert any(p['id']==pid for p in s['posts'])
    assert client.get('/api/search',params={'q':'%','scope':'social'}).json()['posts']==[]
    assert client.get('/api/search',params={'q':'Lia','scope':'people'}).json()['people'][0]['id']=='lia'
    client.post('/api/actors/lia/block',json={})
    assert client.get('/api/search',params={'q':'Lia','scope':'people'}).json()['people']==[]

def test_external_search_without_key_returns_no_fake_results(client):
    r=client.get('/api/search',params={'q':'notícias de tecnologia','scope':'web'})
    assert r.status_code==200
    data=r.json();assert data['provider']=='external' and data['results']==[]
    assert 'google.com/search?q=' in data['shortcuts'][0]['url']
    assert client.get('/api/search',params={'q':' ','scope':'web'}).status_code==422
    assert client.get('/api/search',params={'q':'x'*201,'scope':'web'}).status_code==422
    assert client.get('/api/search',params={'q':'x','scope':'unknown'}).status_code==422

def fake_provider(monkeypatch,payload,status=200):
    seen={}
    class Fake:
        def __init__(self,**kwargs):seen['config']=kwargs
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def get(self,url,**kwargs):
            seen['url']=url;seen.update(kwargs)
            return httpx.Response(status,json=payload,request=httpx.Request('GET',url))
    monkeypatch.setattr(server.httpx,'Client',Fake)
    return seen

def test_wikipedia_adapter_parses_real_format_mocked(client,monkeypatch):
    seen=fake_provider(monkeypatch,{'query':{'search':[{'title':'Ciência','pageid':42,'snippet':'<span>Estudo</span> &amp; observação.'}]}})
    r=client.get('/api/search',params={'q':'ciencia','scope':'wiki'})
    assert r.status_code==200
    result=r.json()['results'][0]
    assert result['description']=='Estudo & observação.' and result['url']=='https://pt.wikipedia.org/?curid=42'
    assert seen['url']=='https://pt.wikipedia.org/w/api.php' and not seen['config']['follow_redirects']

def test_brave_adapter_secrets_bad_links_and_daily_limit(client,monkeypatch):
    register(client)
    monkeypatch.setattr(server,'SEARCH_PROVIDER','brave')
    monkeypatch.setattr(server,'BRAVE_SEARCH_API_KEY','SECRET-test-only')
    monkeypatch.setattr(server,'SEARCH_DAILY_LIMIT',1)
    seen=fake_provider(monkeypatch,{'web':{'results':[{'title':'<b>Pesquisa</b>','url':'https://example.com','description':'Uma fonte.'},{'title':'Perigo','url':'javascript:alert(1)'}]}})
    r=client.get('/api/search',params={'q':'pesquisa','scope':'web'})
    assert r.status_code==200 and len(r.json()['results'])==1
    assert seen['headers']['X-Subscription-Token']=='SECRET-test-only' and seen['params']['safesearch']=='strict'
    assert 'SECRET' not in r.text
    assert client.get('/api/search',params={'q':'x','scope':'web'}).status_code==429
    with server.db() as con:
        columns=[r[1] for r in con.execute('PRAGMA table_info(search_usage)')]
        assert 'query' not in columns

def test_provider_failure_explicit_no_fake_fallback(client,monkeypatch):
    fake_provider(monkeypatch,{'error':'quota'},status=429)
    r=client.get('/api/search',params={'q':'ciencia','scope':'wiki'})
    assert r.status_code==502 and 'provedor' in r.json()['detail']

def test_follow_block_and_post_ownership(client):
    register(client);pid=post(client)
    assert client.post('/api/actors/lia/follow',json={}).json()['active']
    assert client.post('/api/actors/lia/block',json={}).json()['active']
    s=client.get('/api/state').json()
    assert 'lia' not in s['following'] and all(p['author_id']!='lia' for p in s['posts'])
    with TestClient(server.app,headers=HEADERS) as other:
        register(other,'outro')
        assert other.request('DELETE',f'/api/posts/{pid}',json={}).status_code==403

def test_human_messages_isolation_and_blocks(client):
    a=register(client)
    with TestClient(server.app,headers=HEADERS) as other:
        b=register(other,'outro')
        assert client.post(f'/api/messages/{b["id"]}',json={'body':'Oi, pessoa real!'}).status_code==200
        assert other.get(f'/api/messages/{a["id"]}').json()['messages'][0]['body']=='Oi, pessoa real!'
        with TestClient(server.app,headers=HEADERS) as third:
            register(third,'terceiro')
            assert third.get(f'/api/messages/{a["id"]}').json()['messages']==[]
        assert other.post(f'/api/actors/{a["id"]}/block',json={}).status_code==200
        assert client.get(f'/api/messages/{b["id"]}').status_code==403
        assert client.post(f'/api/messages/{b["id"]}',json={'body':'bloqueado'}).status_code==403
    assert client.post('/api/messages/lia',json={'body':'Oi'}).status_code==400

def test_export_delete_account_removes_media_and_collections(client):
    me=register(client)
    post(client,image_data=create_image())
    client.post('/api/links',json={'url':'https://example.com','title':'Privado'})
    data=client.get('/api/account/export').json()
    assert len(data['web_links'])==1 and 'password_hash' not in json.dumps(data)
    assert client.request('DELETE','/api/account',json={'password':'errada'}).status_code==401
    assert client.request('DELETE','/api/account',json={'password':'test-password-2026'}).status_code==200
    assert not list(server.MEDIA_DIR.glob('*.jpg'))
    with server.db() as con:
        assert not con.execute('SELECT 1 FROM web_links WHERE owner_id=?',(me['id'],)).fetchone()
    assert client.get('/api/state').json()['me'] is None

def test_ai_routes_removed_and_migration_non_destructive(client):
    register(client)
    for endpoint in ['/api/agents','/api/drafts','/api/missions']:
        assert client.post(endpoint,json={}).status_code in (404,405)
    with server.db() as con:
        con.execute("INSERT INTO actors(id,handle,name,kind,bio,color,created_at) VALUES('old-agent','old.agent','Old Agent','ai','old','blue',?)",(server.now(),))
        con.execute("INSERT INTO posts(id,author_id,body,source,created_at) VALUES('old-post','old-agent','Archived content','demo',?)",(server.now(),))
    server.initialize();s=client.get('/api/state').json()
    assert all(a['kind']=='human' for a in s['actors'])
    assert all(p['id']!='old-post' for p in s['posts'])
    with server.db() as con:
        assert con.execute("SELECT 1 FROM posts WHERE id='old-post'").fetchone()
    assert client.post('/api/actors/old-agent/follow',json={}).status_code==404
    assert client.post('/api/messages/old-agent',json={'body':'hello'}).status_code==404

def test_brave_global_limit_survives_account_deletion(client,monkeypatch):
    register(client)
    monkeypatch.setattr(server,'SEARCH_PROVIDER','brave')
    monkeypatch.setattr(server,'BRAVE_SEARCH_API_KEY','mock-key')
    monkeypatch.setattr(server,'SEARCH_GLOBAL_DAILY_LIMIT',1)
    fake_provider(monkeypatch,{'web':{'results':[]}})
    assert client.get('/api/search',params={'q':'primeira','scope':'web'}).status_code==200
    assert client.request('DELETE','/api/account',json={'password':'test-password-2026'}).status_code==200
    register(client,'nova_conta')
    assert client.get('/api/search',params={'q':'segunda','scope':'web'}).status_code==429

def test_additive_upgrade_from_v02_schema(tmp_path,monkeypatch):
    import sqlite3
    path=tmp_path/'legacy.db'
    monkeypatch.setattr(server,'DB_PATH',path)
    monkeypatch.setattr(server,'MEDIA_DIR',tmp_path/'media')
    # The checked-in base schema still has the original 0.2 posts columns.
    with sqlite3.connect(path) as con:
        con.executescript((server.ROOT/'schema.sql').read_text())
        assert 'link_url' not in [r[1] for r in con.execute('PRAGMA table_info(posts)')]
        con.execute("INSERT INTO actors(id,handle,name,kind,bio,color,created_at) VALUES('legacy','legacy','Pessoa antiga','human','bio','mint',?)",(server.now(),))
        con.execute("INSERT INTO posts(id,author_id,body,source,created_at) VALUES('legacy-post','legacy','Meu post original','human',?)",(server.now(),))
    server.initialize()
    server.initialize()
    with server.db() as con:
        row=con.execute("SELECT * FROM posts WHERE id='legacy-post'").fetchone()
        assert row['body']=='Meu post original' and row['link_url']==''
        assert con.execute("SELECT COUNT(*) FROM posts WHERE id='discover-v03'").fetchone()[0]==1

def test_state_persists_after_application_restart(client):
    register(client)
    pid=post(client,body='Persistência em SQLite, não apenas no navegador.')
    server.initialize()
    assert any(p['id']==pid for p in client.get('/api/state').json()['posts'])
