"""Public presentation, pilot invitations and aggregate launch metrics.
No advertising IDs, visitor tracker, public account export or embedded third-party code.
Invitation codes are credentials: only their hashes are stored; signup consumes atomically.
"""
import hashlib
import html
import os
import re
import secrets
import time
from datetime import datetime, timezone, timedelta
from typing import Annotated
from urllib.parse import urlsplit
from xml.sax.saxutils import escape as xml_escape
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import Field, StringConstraints

PAGES = {
    '/bem-vindo': ('Synapse — descubra, guarde e compartilhe', 'Uma rede social para transformar descobertas da internet em conversas. Compartilhe fotos e links e organize suas referências em coleções privadas.'),
    '/como-funciona': ('Como funciona o Synapse', 'Conheça o feed, a pesquisa, as coleções privadas e os controles da comunidade Synapse.'),
    '/ajuda': ('Ajuda e segurança · Synapse', 'Como criar sua conta, confirmar o e-mail, denunciar conteúdo, bloquear perfis e excluir seus dados no Synapse.'),
}


def public_origin(value: str) -> str:
    """Only a configured HTTPS origin is used in canonical URLs; never trust Host."""
    try:
        u = urlsplit(value)
        if (u.scheme == 'https' and u.hostname and not u.username and not u.password
                and u.path in ('', '/') and not u.query and not u.fragment):
            return value.rstrip('/')
    except ValueError:
        pass
    return ''


def render_page(path: str, origin: str, *, registration_open: bool = False,
                announcement: str = '', support_email: str = '', indexing: bool = False,
                verification: str = '', app_url: str = '/', static: bool = False) -> str:
    title, description = PAGES[path]
    origin = public_origin(origin)
    indexing = indexing and bool(origin)
    e = html.escape
    canonical = origin + path if origin else ''
    meta = (f'<link rel="canonical" href="{e(canonical, quote=True)}">'
            f'<meta property="og:url" content="{e(canonical, quote=True)}">'
            f'<meta property="og:image" content="{e(origin)}/icon-512.png">') if origin else ''
    if re.fullmatch(r'[A-Za-z0-9_-]{10,200}', verification or ''):
        meta += f'<meta name="google-site-verification" content="{e(verification)}">'
    app = e(app_url, quote=True)
    signup_url = app + ('&amp;' if '?' in app else '?') + 'signup=1'
    cta_url = signup_url if registration_open and not static else app
    cta = 'Criar minha conta' if registration_open and not static else 'Abrir a comunidade'
    status = 'Cadastros abertos' if registration_open and not static else 'Lançamento em preparação'
    notice = e(announcement) if announcement else ('A comunidade está começando. Entre, publique uma descoberta e ajude a construir este espaço.' if registration_open and not static else 'Estamos preparando a abertura. Os testes são por convite; quem já tem uma conta pode entrar.')
    contact = (f'<a href="mailto:{e(support_email, quote=True)}">{e(support_email)}</a>'
               if re.fullmatch(r'[^\s@<>"\r\n]+@[^\s@<>"\r\n]+\.[^\s@<>"\r\n]+', support_email or '')
               else 'O contato oficial será publicado aqui antes da abertura dos cadastros.')
    if path == '/bem-vindo':
        content = f'''<section class="hero"><div class="hero-copy"><p class="eyebrow"><span class="live-dot"></span> SUA CURIOSIDADE ENCONTRA COMPANHIA</p><h1>O que você descobre<br>merece <em>ser compartilhado.</em></h1><p class="lead">Encontre uma ideia. Guarde a referência. Comece uma conversa. Sua rede social, conectada ao melhor que você encontra na web.</p><div class="actions"><a class="button primary" href="{cta_url}">{cta}<span aria-hidden="true"> ↗</span></a><a class="button secondary" href="/como-funciona">Conheça o Synapse</a></div><p class="small">Fotos, links e pessoas. Sem agentes de IA nesta versão.</p></div><div class="preview" aria-label="Exemplo ilustrativo de uma descoberta, não uma publicação de usuário"><div class="preview-top"><span class="mini-logo">✦</span><div><strong>Uma descoberta muda a conversa.</strong><small>Exemplo ilustrativo · Synapse</small></div><span aria-hidden="true">•••</span></div><div class="preview-art"><span class="orbit o1"></span><span class="orbit o2"></span><span class="orbit o3"></span><span class="big-star">✦</span><span class="art-label">SIGA A CURIOSIDADE.</span></div><div class="preview-copy"><p class="preview-icons" aria-hidden="true">♡ &nbsp; ↗ &nbsp; ◇</p><strong>Encontrei algo que vale a conversa.</strong><p>Um tutorial, uma fotografia, uma ideia. Compartilhe sua descoberta e conte por que ela importa.</p><span class="topic">#descobertas</span> <span class="topic">#criatividade</span></div><span class="floating-note">↗ Encontre. Guarde. Conecte.</span></div></section>
<section class="status-strip" role="status"><span class="status-pill">{status}</span><p>{notice}</p></section>
<section class="section"><div class="section-heading"><p class="eyebrow">MENOS LINKS PERDIDOS. MAIS CONVERSAS.</p><h2>Da descoberta à conexão.</h2></div><div class="steps"><article><span class="step-number">01</span><h3>Descubra</h3><p>Explore pessoas e publicações. Use os atalhos de pesquisa para continuar sua curiosidade na web.</p></article><article><span class="step-number">02</span><h3>Guarde</h3><p>Organize links em coleções privadas, com suas próprias anotações e referências.</p></article><article><span class="step-number">03</span><h3>Compartilhe</h3><p>Publique uma foto ou um link, acrescente seu ponto de vista e encontre outras perspectivas.</p></article></div></section>
<section class="closing"><p class="eyebrow">UMA COMUNIDADE EM CONSTRUÇÃO</p><h2>Não precisa postar mais.<br>Precisa ter algo para trocar.</h2><p>Comece com uma descoberta útil e uma pergunta de verdade.</p><a class="button primary" href="{cta_url}">{cta} ↗</a></section>'''
    elif path == '/como-funciona':
        content = f'''<section class="text-page"><p class="eyebrow">SEU PRIMEIRO ENCONTRO COM O SYNAPSE</p><h1>Descubra junto.</h1><p class="lead">Uma rede social de pessoas, ideias e referências.</p><div class="info-grid"><article><h2>Um feed para conversar</h2><p>Publique textos, imagens e links. Siga perfis, curta e comente. Galerias e vídeos dependem dos recursos habilitados no servidor.</p></article><article><h2>Uma pesquisa honesta</h2><p>A pesquisa interna encontra perfis e publicações. A busca web abre um buscador externo por padrão. Resultados gerais dentro do Synapse dependem de um provedor configurado; não temos um índice próprio de toda a internet.</p></article><article><h2>Coleções que são suas</h2><p>Guarde links e notas privadas. Compartilhar uma descoberta no feed é uma escolha separada: sua anotação privada não é publicada automaticamente.</p></article><article><h2>No celular e no computador</h2><p>O site adapta sua interface à tela. Navegadores compatíveis podem oferecer instalação como aplicativo web. Não é necessário baixar um APK para começar.</p></article><article><h2>Controle e transparência</h2><p>Bloqueie perfis, denuncie conteúdo e exporte ou exclua sua conta. Mensagens não possuem criptografia de ponta a ponta. Publicações do feed podem ser vistas por visitantes.</p></article><article><h2>Lançamento responsável</h2><p>Estamos em fase inicial. Disponibilidade, moderação, privacidade e proteções para menores precisam ser verificadas pelo responsável antes da abertura ampla.</p></article></div><a class="button primary" href="{app}">Abrir a comunidade ↗</a></section>'''
    else:
        content = f'''<section class="text-page"><p class="eyebrow">CENTRAL DE AJUDA</p><h1>Um lugar para<br>suas perguntas.</h1><div class="faq"><details open><summary>Como entro no Synapse?</summary><p>Abra a comunidade, escolha Entrar e use seu usuário ou e-mail. Quando o cadastro estiver aberto, escolha Criar conta. Durante os testes fechados, use o convite enviado pelo responsável. Nunca reutilize uma senha importante.</p></details><details><summary>Não recebi o e-mail de confirmação.</summary><p>Confira o spam e use Reenviar confirmação nas configurações da conta. Se continuar sem receber, procure o contato oficial abaixo. Não envie sua senha nem o link de recuperação a ninguém.</p></details><details><summary>Como denuncio ou bloqueio?</summary><p>Use o menu da publicação ou do perfil para denunciar. No perfil, use o controle de bloqueio. As denúncias são revisadas pelo responsável da comunidade; não são uma chamada de emergência.</p></details><details><summary>Minhas coleções e mensagens são públicas?</summary><p>Coleções e notas são restritas à sua conta. Mensagens são restritas aos participantes na aplicação, mas não possuem criptografia de ponta a ponta. Quem opera a infraestrutura pode ter acesso ao banco. Publicações e perfis do feed são públicos.</p></details><details><summary>Como excluo minha conta?</summary><p>Na comunidade, abra Configurações → Conta e segurança → Excluir conta e confirme sua senha. Consulte também a página de exclusão. Backups e registros operacionais seguem a política publicada pelo responsável.</p></details><details><summary>O site funciona como navegador irrestrito?</summary><p>Não. Links externos abrem no navegador. Sites externos podem exigir conta, pagamento ou permissão e têm suas próprias regras.</p></details><details><summary>Qual é o cuidado com crianças e adolescentes?</summary><p>A abertura a esse público exige avaliação específica, aferição de idade e proteções adequadas, inclusive supervisão parental quando aplicável. O projeto não anuncia essas funções como prontas. A liberação depende de implementação e revisão do responsável.</p></details></div><section class="support"><h2>Contato oficial</h2><p>{contact}</p><p>Use este canal para suporte, privacidade, segurança e pedidos sobre conteúdo. Nunca envie senhas ou documentos sem necessidade e orientação adequada.</p></section><a class="button secondary" href="{app}">Voltar à comunidade</a></section>'''
    footer_base = app_url.rstrip('/') if static else ''
    return f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title><meta name="description" content="{e(description, quote=True)}"><meta name="robots" content="{'index,follow' if indexing else 'noindex,follow'}"><meta name="theme-color" content="#faf9fd"><meta property="og:type" content="website"><meta property="og:locale" content="pt_BR"><meta property="og:site_name" content="Synapse"><meta property="og:title" content="{e(title, quote=True)}"><meta property="og:description" content="{e(description, quote=True)}"><meta name="twitter:card" content="summary">{meta}<link rel="icon" href="/icon.svg" type="image/svg+xml"><link rel="stylesheet" href="/launch.css"></head><body><a class="skip" href="#conteudo">Ir para o conteúdo</a><header class="header"><a class="brand" href="/bem-vindo"><span aria-hidden="true">✦</span>synapse<span class="brand-dot">.</span></a><nav aria-label="Navegação principal"><a href="/como-funciona">Como funciona</a><a href="/ajuda">Ajuda</a><a class="button nav-button" href="{app}">Entrar ↗</a></nav></header><main id="conteudo">{content}</main><footer><a class="brand" href="/bem-vindo">synapse.</a><p>Descobertas que conectam.</p><nav aria-label="Documentos"><a href="{e(footer_base)}/terms.html">Termos</a><a href="{e(footer_base)}/privacy.html">Privacidade</a><a href="{e(footer_base)}/safety.html">Segurança</a><a href="{e(footer_base)}/delete-account.html">Excluir conta</a><a href="/ajuda">Ajuda</a></nav><small>Projeto em lançamento. Sem contadores de usuários fictícios.</small></footer></body></html>'''


def install(app, s):
    old_initialize = s.initialize
    def initialize():
        old_initialize()
        with s.db() as con:
            con.executescript('''CREATE TABLE IF NOT EXISTS pilot_invites (
              id TEXT PRIMARY KEY, code_hash TEXT UNIQUE NOT NULL,
              label TEXT NOT NULL, created_by TEXT REFERENCES actors(id) ON DELETE SET NULL,
              max_uses INTEGER NOT NULL, uses INTEGER NOT NULL DEFAULT 0,
              expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS pilot_invites_expiry ON pilot_invites(expires);''')
    s.initialize = initialize

    def invite_hash(code):
        return hashlib.sha256(code.encode()).hexdigest()
    def eligible_invite(con, code):
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', code or ''):
            return None
        return con.execute('SELECT * FROM pilot_invites WHERE code_hash=? AND revoked=0 AND expires>? AND uses<max_uses', (invite_hash(code), time.time())).fetchone()
    s.eligible_invite = eligible_invite
    def consume_invite(con, code):
        row = eligible_invite(con, code)
        if not row:
            raise HTTPException(403, 'Convite inválido, expirado, revogado ou sem vagas.')
        changed = con.execute('UPDATE pilot_invites SET uses=uses+1 WHERE id=? AND revoked=0 AND expires>? AND uses<max_uses', (row['id'],time.time())).rowcount
        if changed != 1:
            raise HTTPException(403, 'Este convite não está mais disponível.')
        return row['id']
    s.consume_invite = consume_invite

    def owner(request: Request, user=Depends(s.member)):
        if s.operator_role(user) != 'owner':
            raise HTTPException(403, 'Somente o responsável pode gerenciar o lançamento.')
        if os.getenv('SYNAPSE_ENV') == 'production' and not user['email_verified']:
            raise HTTPException(403, 'Confirme o e-mail do responsável.')
        s.require_admin_elevation(request, user)
        return user

    class NewInvite(s.Data):
        label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=80)]
        max_uses: Annotated[int, Field(strict=True, ge=1, le=50)] = 1
        days: Annotated[int, Field(strict=True, ge=1, le=30)] = 7
    class Revoke(s.Data):
        reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8,max_length=600)]

    @app.get('/api/manage/invites')
    def invites(user=Depends(owner)):
        with s.db() as con:
            rows=[dict(r) for r in con.execute('SELECT id,label,max_uses,uses,expires,revoked,created_at FROM pilot_invites ORDER BY created_at DESC LIMIT 100')]
        for r in rows:
            r['available'] = not r['revoked'] and r['expires'] > time.time() and r['uses'] < r['max_uses']
        return {'items':rows,'notice':'Convites autorizam cadastro limitado mesmo com inscrições gerais fechadas. Não substituem avaliação de público, proteções de menores ou revisão de privacidade.'}

    @app.post('/api/manage/invites')
    def create_invite(data:NewInvite,user=Depends(owner)):
        s.rate_limit('invite-create:'+user['id'],20,3600)
        code=secrets.token_urlsafe(32);iid=s.uid();expires=time.time()+data.days*86400
        with s.db() as con:
            con.execute('INSERT INTO pilot_invites VALUES(?,?,?,?,?,?,?,0,?)',(iid,invite_hash(code),data.label,user['id'],data.max_uses,0,expires,s.now()))
            s.admin_event(con,user,'invite_created','invite',iid,'Convite: '+data.label)
        origin=public_origin(s.PUBLIC_ORIGIN)
        return {'id':iid,'code':code,'url':origin+'/?signup=1#convite='+code,'expires':expires,
                'notice':'Guarde agora. O código só aparece nesta resposta; revogue e gere outro caso o perca. Não publique convites privados em redes abertas.'}

    @app.post('/api/manage/invites/{invite_id}/revoke')
    def revoke(invite_id:str,data:Revoke,user=Depends(owner)):
        with s.db() as con:
            if not con.execute('SELECT 1 FROM pilot_invites WHERE id=?',(invite_id,)).fetchone():raise HTTPException(404,'Convite não encontrado.')
            con.execute('UPDATE pilot_invites SET revoked=1 WHERE id=?',(invite_id,))
            s.admin_event(con,user,'invite_revoked','invite',invite_id,data.reason)
        return {'ok':True}

    @app.get('/api/manage/growth')
    def growth(user=Depends(owner)):
        cutoff=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat(timespec='milliseconds')
        with s.db() as con:
            def n(sql,args=()):return con.execute(sql,args).fetchone()[0]
            members="a.seeded=0 AND a.kind='human' AND NOT EXISTS(SELECT 1 FROM operators o WHERE o.user_id=a.id)"
            counts={
                'members':n('SELECT COUNT(*) FROM actors a WHERE '+members),
                'verified':n('SELECT COUNT(*) FROM actors a WHERE '+members+' AND a.email_verified=1'),
                'creators':n('SELECT COUNT(*) FROM actors a WHERE '+members+' AND EXISTS(SELECT 1 FROM posts p WHERE p.author_id=a.id AND p.hidden=0)'),
                'new_7d':n('SELECT COUNT(*) FROM actors a WHERE '+members+' AND a.created_at>=?',(cutoff,)),
                'posting_7d':n('SELECT COUNT(DISTINCT p.author_id) FROM posts p JOIN actors a ON a.id=p.author_id WHERE '+members+' AND p.created_at>=? AND p.hidden=0',(cutoff,)),
                'posts_7d':n('SELECT COUNT(*) FROM posts p JOIN actors a ON a.id=p.author_id WHERE '+members+' AND p.created_at>=? AND p.hidden=0',(cutoff,)),
                'invited_signups':n('SELECT COALESCE(SUM(uses),0) FROM pilot_invites'),
            }
            daily=[dict(r) for r in con.execute('SELECT substr(a.created_at,1,10) day,COUNT(*) total FROM actors a WHERE '+members+' AND a.created_at>=? GROUP BY day ORDER BY day',(cutoff,))]
        counts['activation_percent']=round(100*counts['creators']/counts['members'],1) if counts['members'] else 0
        return {'counts':counts,'daily':daily,'notice':'Agregados do banco atual, excluindo exemplos e administradores. Ativação = conta com publicação visível / contas de membros. Não mede visitantes únicos, retenção, leitores ou origem de tráfego. Exclusões e moderação podem alterar os totais.'}

    def enabled_indexing():
        return os.getenv('PUBLIC_INDEXING','0')=='1' and bool(public_origin(s.PUBLIC_ORIGIN))

    def page(path):
        st=s.public_site_settings()
        return HTMLResponse(render_page(path,s.PUBLIC_ORIGIN,registration_open=bool(st['registration_open'] and not st['maintenance']),
          announcement=st['announcement'],support_email=os.getenv('SUPPORT_EMAIL',''),indexing=enabled_indexing(),verification=os.getenv('GOOGLE_SITE_VERIFICATION','')),
          headers={'Cache-Control':'no-store'})
    @app.get('/', include_in_schema=False)
    def app_home():
        # Search Console's URL-prefix verification fetches the root page, not just
        # the marketing page. Do not index the social app or expose any secrets.
        document=(s.ROOT/'web'/'index.html').read_text(encoding='utf-8')
        token=os.getenv('GOOGLE_SITE_VERIFICATION','')
        if re.fullmatch(r'[A-Za-z0-9_-]{10,200}',token):
            document=document.replace('</head>',f'<meta name="google-site-verification" content="{html.escape(token)}"></head>',1)
        return HTMLResponse(document,headers={'Cache-Control':'no-store'})

    @app.get('/bem-vindo',include_in_schema=False)
    def welcome():return page('/bem-vindo')
    @app.get('/como-funciona',include_in_schema=False)
    def how_it_works():return page('/como-funciona')
    @app.get('/ajuda',include_in_schema=False)
    def help_page():return page('/ajuda')

    @app.get('/robots.txt',include_in_schema=False)
    def robots():
        # Crawl is allowed so crawlers can actually read noindex on private shells.
        # Authentication, not robots.txt, protects private data. Exclude only duplicate query URLs.
        origin=public_origin(s.PUBLIC_ORIGIN)
        body='User-agent: *\nAllow: /\nDisallow: /*?\n'
        if origin and enabled_indexing():body+='Sitemap: '+origin+'/sitemap.xml\n'
        return Response(body,media_type='text/plain',headers={'Cache-Control':'no-cache'})
    @app.get('/sitemap.xml',include_in_schema=False)
    def sitemap():
        origin=public_origin(s.PUBLIC_ORIGIN)
        items=''.join('<url><loc>'+xml_escape(origin+p)+'</loc></url>' for p in PAGES) if enabled_indexing() else ''
        return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+items+'</urlset>',media_type='application/xml',headers={'Cache-Control':'no-cache'})
