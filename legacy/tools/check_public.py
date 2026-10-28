#!/usr/bin/env python3
"""Read-only smoke check of ONE operator-controlled Synapse origin.
No login, password guessing, writes, load test or certification. SSL stays enabled.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
import httpx


def check(client, origin: str) -> dict:
    results=[]
    def record(name, ok, note):results.append({'check':name,'ok':bool(ok),'note':note})
    def get(path):
        try:return client.get(path)
        except (httpx.HTTPError,OSError):return None
    def is_json(r):
        if r is None:return {}
        try:return r.json()
        except (ValueError,TypeError):return {}
    record('https',urlsplit(origin).scheme=='https','HTTPS deve estar ativo no endereço público.')
    r=get('/api/health');data=is_json(r)
    record('backend',r is not None and r.status_code==200 and isinstance(data,dict) and data.get('ok') is True and isinstance(data.get('version'),str),'A rota deve retornar JSON do servidor, não uma página HTML de hospedagem estática.')
    ready=get('/api/ready');rd=is_json(ready)
    record('readiness',ready is not None and ready.status_code==200 and isinstance(rd,dict) and rd.get('ready') is True,'Banco acessível e reserva mínima de espaço. Não testa serviços externos.')
    site=get('/api/site');sd=is_json(site)
    record('production',isinstance(sd,dict) and sd.get('production') is True,'Modo production. Este diagnóstico não altera o ambiente.')
    home=get('/')
    record('real_app',home is not None and home.status_code==200 and 'data-mode="server"' in home.text and 'data-mode="demo"' not in home.text,'A interface precisa usar o servidor real.')
    landing=get('/bem-vindo')
    record('public_page',landing is not None and landing.status_code==200 and '<h1>' in landing.text and 'rel="canonical"' in landing.text,'Página de apresentação e endereço canônico.')
    record('indexing_enabled',landing is not None and 'content="index,follow"' in landing.text,'Ativar PUBLIC_INDEXING somente depois de revisar a página e o domínio.')
    record('security_headers',home is not None and home.headers.get('x-content-type-options')=='nosniff' and 'frame-ancestors' in home.headers.get('content-security-policy','') and 'max-age=' in home.headers.get('strict-transport-security',''),'Verificação parcial de cabeçalhos. Não é auditoria de segurança.')
    state=get('/api/state');st=is_json(state)
    record('anonymous_state',state is not None and state.status_code==200 and isinstance(st,dict) and 'me' in st and st['me'] is None,'Visitante não deve receber sessão de outra pessoa.')
    record('no_demo_records',isinstance(st,dict) and 'actors' in st and not any(a.get('seeded') for a in st.get('actors',[])),'Não divulgar exemplos como usuários reais.')
    record('guest_content_hidden',isinstance(st,dict) and st.get('posts')==[] and st.get('actors')==[],'Visitantes não recebem conteúdo social antes da ativação de uma conta.')
    checks=[get(p) for p in ('/api/account/security','/api/manage/operations','/api/account/sessions')]
    record('security_center_protected',all(p is not None and p.status_code==401 for p in checks),'Central de segurança, sessões e operação exigem autenticação.')
    contact=get('/.well-known/security.txt')
    record('security_contact',contact is not None and contact.status_code==200 and contact.text.startswith('Contact: mailto:'),'Canal público de comunicação de incidentes configurado.')
    admin=get('/api/manage/overview')
    record('admin_protected',admin is not None and admin.status_code==401,'A administração deve exigir autenticação.')
    probes=[get(p) for p in ('/.env','/data/synapse.db','/server.py')]
    record('private_files',all(p is not None and p.status_code in (403,404) for p in probes),'Segredos e banco não devem ser servidos pela web.')
    robot=get('/robots.txt')
    record('robots',robot is not None and robot.status_code==200 and origin.rstrip('/')+'/sitemap.xml' in robot.text,'Endereço do sitemap no robots.txt.')
    sitemap=get('/sitemap.xml');locs=[]
    try:
        if sitemap is not None and sitemap.status_code==200:
            locs=[i.text for i in ET.fromstring(sitemap.content).iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
    except ET.ParseError:pass
    expected={origin.rstrip('/')+p for p in ('/bem-vindo','/como-funciona','/ajuda')}
    record('sitemap',set(locs)==expected,'Somente páginas públicas revisadas; perfis, conversas e painel não entram no sitemap.')
    return {'origin':origin,'ok':all(r['ok'] for r in results),'checks':results,'limitations':['Não envia e-mail nem verifica entrega SMTP.','Não cria contas nem testa pagamentos.','Não verifica backup externo, proteção de menores, conformidade jurídica ou capacidade de tráfego.','Uma aprovação aqui não significa serviço 100% seguro nem cadastro geral liberado.']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('origin');p.add_argument('--output',type=Path);args=p.parse_args()
    u=urlsplit(args.origin)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.path not in ('','/') or u.query or u.fragment:
        p.error('Use apenas a origem HTTPS do seu site, sem usuário, senha, caminho ou parâmetros.')
    origin=args.origin.rstrip('/')
    with httpx.Client(base_url=origin,timeout=15,follow_redirects=False,headers={'User-Agent':'Synapse-Launch-Check/0.9'}) as c:
        report=check(c,origin)
    text=json.dumps(report,ensure_ascii=False,indent=2)
    print(text)
    if args.output:
        # Never overwrite an existing report or config accidentally.
        with args.output.open('x',encoding='utf-8') as f:f.write(text+'\n')
    return 0 if report['ok'] else 1

if __name__=='__main__':sys.exit(main())
