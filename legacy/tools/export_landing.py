#!/usr/bin/env python3
"""Optional static PRESENTATION export for Pages; never exports accounts or backend.
The primary recommended deployment serves both application and presentation from Docker.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import sys
from xml.sax.saxutils import escape
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from launch import PAGES, public_origin, render_page
ROOT=Path(__file__).resolve().parents[1]

def export(output:Path,origin:str,app_origin:str,*,indexing=False,verification='',support_email=''):
    if not public_origin(origin) or not public_origin(app_origin):raise ValueError('Use origens HTTPS sem caminho, consulta ou credenciais.')
    if output.exists():raise ValueError('Destino já existe. Escolha uma pasta nova; nenhum arquivo será sobrescrito.')
    output.mkdir(parents=True)
    for route in PAGES:
        (output/(route.lstrip('/')+'.html')).write_text(render_page(route,origin,app_url=app_origin+'/',static=True,indexing=indexing,verification=verification,support_email=support_email),encoding='utf-8')
    for name in ('launch.css','icon.svg','icon-192.png','icon-512.png'):shutil.copyfile(ROOT/'web'/name,output/name)
    (output/'_redirects').write_text('/ /bem-vindo 302\n',encoding='utf-8')
    (output/'404.html').write_text('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="robots" content="noindex"><title>Página não encontrada</title><h1>Somente a apresentação está neste endereço.</h1><p>A rede social usa o servidor indicado no botão Entrar.</p><a href="/bem-vindo">Conhecer o Synapse</a></html>',encoding='utf-8')
    (output/'robots.txt').write_text('User-agent: *\nAllow: /\n'+('Sitemap: '+origin+'/sitemap.xml\n' if indexing else ''),encoding='utf-8')
    items=''.join('<url><loc>'+escape(origin+p)+'</loc></url>' for p in PAGES) if indexing else ''
    (output/'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+items+'</urlset>',encoding='utf-8')
    (output/'_headers').write_text('/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: no-referrer\n  X-Frame-Options: DENY\n  Content-Security-Policy: default-src \'self\'; script-src \'none\'; style-src \'self\'; img-src \'self\'; frame-ancestors \'none\'; form-action \'none\'; base-uri \'none\'\n',encoding='utf-8')
    return output

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--origin',required=True);p.add_argument('--app-origin',required=True);p.add_argument('--output',type=Path,default=Path('public-site'));p.add_argument('--index',action='store_true');p.add_argument('--google-verification',default='');p.add_argument('--support-email',default='');a=p.parse_args()
    print('Somente apresentação exportada:',export(a.output,a.origin.rstrip('/'),a.app_origin.rstrip('/'),indexing=a.index,verification=a.google_verification,support_email=a.support_email))
    print('Nenhum cadastro, API, banco, mensagem ou servidor foi publicado.')
if __name__=='__main__':main()
