#!/usr/bin/env python3
"""Interactive LOCAL generator; never uploads settings or prints secrets.
Run after dependencies are installed. Reuse existing production keys on upgrades.
"""
from __future__ import annotations
import getpass
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from cryptography.fernet import Fernet
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.env.production.local'

def ask(label, validator=lambda v:bool(v), *, secret=False, default=''):
    while True:
        value=(getpass.getpass if secret else input)(label+(' ['+default+']' if default else '')+': ').strip() or default
        if '\n' not in value and '\r' not in value and not value.startswith(('"',"'")) and not value.endswith(('"',"'")) and validator(value):return value
        print('Valor inválido. Revise o campo, sem aspas ou quebras de linha.')
def valid_origin(v):
    try:
        u=urlsplit(v);return u.scheme=='https' and bool(u.hostname) and not u.username and not u.password and u.path in ('','/') and not u.query and not u.fragment
    except ValueError:return False

def main():
    if OUT.exists():raise SystemExit('O arquivo já existe. Não será sobrescrito. Em atualização, preserve ADMIN_ENCRYPTION_KEY e dados existentes.')
    print('Configuração privada da PRIMEIRA implantação. Nada será enviado à internet.\nNão envie o arquivo gerado ao GitHub, ao chat ou à pasta web.\nPara uma instalação existente, cancele e mantenha sua chave atual.\n')
    if input('É a primeira implantação, sem chave administrativa anterior? Digite SIM: ').strip()!='SIM':return
    email=lambda v:bool(re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',v))
    values={'SYNAPSE_ENV':'production','SEED_DEMO_DATA':'0','PUBLIC_ORIGIN':ask('Endereço HTTPS real do serviço',valid_origin).rstrip('/'),
            'SYNAPSE_DB':'/app/data/synapse.db','SYNAPSE_MEDIA':'/app/data/media',
            'OPERATOR_NAME':ask('Nome do responsável pela operação'),
            'SUPPORT_EMAIL':ask('E-mail monitorado de suporte',email),
            'CHILD_SAFETY_EMAIL':ask('E-mail monitorado de segurança infantil',email),
            'MAIL_MODE':'smtp','SMTP_HOST':ask('Servidor SMTP',lambda v:bool(re.fullmatch(r'[A-Za-z0-9.-]+',v))),
            'SMTP_PORT':ask('Porta SMTP (465 ou 587)',lambda v:v in ('465','587'),default='587'),
            'SMTP_FROM':ask('E-mail remetente autorizado no provedor',email),
            'SMTP_USER':ask('Usuário SMTP'),'SMTP_PASSWORD':ask('Senha/chave SMTP',secret=True),
            'BOOTSTRAP_HANDLE':ask('Seu nome de usuário administrador',lambda v:bool(re.fullmatch(r'[a-zA-Z0-9_.]{3,24}',v))),
            'BOOTSTRAP_EMAIL':ask('Seu e-mail administrador',email),
            'ADMIN_ENCRYPTION_KEY':Fernet.generate_key().decode(),'BACKUP_ENCRYPTION_KEY':Fernet.generate_key().decode(),'AUTO_BACKUP_ENABLED':'0','MINOR_ACCOUNTS_ENABLED':'0','PUBLIC_INDEXING':'0','GOOGLE_SITE_VERIFICATION':'',
            'SEARCH_PROVIDER':'external','CALLS_ENABLED':'0','FORWARDED_ALLOW_IPS':'127.0.0.1'}
    while True:
        password=ask('Senha NOVA de administrador (16 a 128 caracteres)',lambda v:16<=len(v)<=128,secret=True)
        if password==getpass.getpass('Confirme a senha: '):break
        print('As senhas não coincidem.')
    values['BOOTSTRAP_PASSWORD']=password
    fd=os.open(OUT,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as f:
        f.write('# SEGREDOS DE PRODUÇÃO. Não compartilhar. Não incluir no GitHub.\n')
        for k,v in values.items():f.write(k+'='+v+'\n')
    print('Arquivo privado criado:',OUT.name)
    print('Importe as variáveis no painel privado da hospedagem. Não substitua seu .env local com os caminhos /app/data.')
    print('Guarde ADMIN_ENCRYPTION_KEY em local seguro. Após criar a conta, remova BOOTSTRAP_PASSWORD do ambiente hospedado e da cópia local.')
    print('Guarde também BACKUP_ENCRYPTION_KEY fora do servidor. Turnstile, aferição externa e destino de backup ainda precisam ser configurados conforme docs/ABERTURA-0.9.md.')
    print('Nenhuma hospedagem, assinatura paga ou publicação foi criada.')
if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:print('\nCancelado.');sys.exit(1)
