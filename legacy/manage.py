"""Local operator commands. No network publishing or billing is performed by this tool."""
from __future__ import annotations
import argparse
import base64
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile

import server


def sha256_file(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def backup(destination: Path) -> Path:
    """Run with the application stopped so DB + media are one coherent snapshot."""
    server.initialize()
    destination=destination.resolve()
    if destination.exists(): raise ValueError('O destino já existe; não será sobrescrito.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        dbcopy=Path(folder)/'database.sqlite3'
        with sqlite3.connect(dbcopy) as target,server.db() as source: source.backup(target)
        entries=[('database.sqlite3',dbcopy)]
        entries += [('media/'+p.name,p) for p in sorted(server.MEDIA_DIR.glob('*')) if p.is_file() and re.fullmatch(r'[a-f0-9]{32}\.(jpg|mp4)',p.name)]
        manifest={'version':'0.9.0','created_at':server.now(),'files':{name:sha256_file(path) for name,path in entries}}
        with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED) as z:
            for name,path in entries:z.write(path,name)
            z.writestr('manifest.json',json.dumps(manifest,indent=2))
    destination.chmod(0o600)
    return destination


def restore(archive: Path, destination: Path) -> None:
    """Restore only validated known paths into a NEW directory. Existing data is untouched."""
    destination=destination.resolve()
    if destination.exists() and any(destination.iterdir()):raise ValueError('Escolha uma pasta nova e vazia. Restauração não sobrescreve dados existentes.')
    destination.mkdir(parents=True,exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as z:
            infos=z.infolist()
            if len(infos)>100000 or sum(i.file_size for i in infos)>20*1024**3:raise ValueError('Backup excede o limite de restauração.')
            names=[i.filename for i in infos]
            if len(names)!=len(set(names)):raise ValueError('Entradas duplicadas no backup.')
            for n in names:
                if n not in ('manifest.json','database.sqlite3') and not re.fullmatch(r'media/[a-f0-9]{32}\.(jpg|mp4)',n):raise ValueError('Caminho não permitido no backup.')
            manifest=json.loads(z.read('manifest.json'))
            if set(manifest['files'])!=set(names)-{'manifest.json'}:raise ValueError('Manifesto inconsistente.')
            if 'database.sqlite3' not in names:raise ValueError('Banco ausente.')
            for name,digest in manifest['files'].items():
                target=destination/('synapse.db' if name=='database.sqlite3' else name)
                target.parent.mkdir(parents=True,exist_ok=True)
                check=hashlib.sha256()
                with z.open(name) as src,target.open('xb') as out:
                    while chunk:=src.read(1024*1024):check.update(chunk);out.write(chunk)
                if check.hexdigest()!=digest:raise ValueError('Checksum incorreto no backup.')
                target.chmod(0o600)
        with sqlite3.connect(destination/'synapse.db') as con:
            if con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Banco inválido.')
            if con.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Banco com referências inconsistentes.')
            for table in ('sessions','auth_tokens','push_subscriptions','call_signals','calls','admin_grants','durable_rates','session_devices','age_challenges','guardian_invites','mail_jobs','integration_checks'):
                if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():con.execute('DELETE FROM '+table)
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='site_settings'").fetchone():
                con.execute('UPDATE site_settings SET registration_open=0,maintenance=1 WHERE id=1')
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='backup_jobs'").fetchone():
                con.execute("UPDATE backup_jobs SET status='failed',error_code='restored_database' WHERE status IN ('queued','running')")
    except Exception:
        # This directory was empty and created solely for restoration; never remove user input elsewhere.
        for p in list(destination.iterdir()):
            if p.is_dir():shutil.rmtree(p)
            else:p.unlink()
        raise


def cleanup() -> dict:
    server.initialize();cutoff=time.time()-86400
    with server.db() as con:
        assets=[dict(r) for r in con.execute('SELECT * FROM media_assets WHERE post_id IS NULL AND created_at<?',(server.datetime.fromtimestamp(cutoff,server.timezone.utc).isoformat(),))]
        for row in assets:con.execute('DELETE FROM media_assets WHERE id=?',(row['id'],))
        stories=[dict(r) for r in con.execute('SELECT * FROM stories WHERE expires<?',(time.time(),))]
        con.execute('DELETE FROM stories WHERE expires<?',(time.time(),))
        con.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
        con.execute('DELETE FROM auth_tokens WHERE expires<?',(time.time(),))
        con.execute('DELETE FROM calls WHERE expires<?',(time.time(),))
    server.delete_media_files(assets)
    for story in stories:server.remove_image(story['image_path'])
    for folder in (server.DB_PATH.parent/'outbox',server.MEDIA_DIR/'.staging'):
        for p in folder.glob('*'):
            if p.is_file() and p.stat().st_mtime<cutoff:p.unlink(missing_ok=True)
    return {'unused_uploads_removed':len(assets),'expired_stories_removed':len(stories)}


def create_operator(handle: str, email: str, name: str, password: str) -> str:
    if not re.fullmatch(r'[a-zA-Z0-9_.]{3,24}',handle):raise ValueError('Nome de usuário inválido.')
    email=server.validate_email(email)
    if len(password)<16 or len(password)>128:raise ValueError('Use uma senha exclusiva entre 16 e 128 caracteres.')
    uid=server.uid()
    with server.db() as con:
        # Never promote or replace a pre-existing account based solely on its public handle.
        if con.execute('SELECT 1 FROM actors WHERE handle=? OR email=?',(handle,email)).fetchone():raise ValueError('Conta já existe. Use o comando admin no servidor de confiança para promover a identidade correta.')
        con.execute("INSERT INTO actors(id,handle,name,kind,bio,color,password_hash,created_at,email,terms_version) VALUES(?,?,?,'human','','violet',?,?,?,'operator-bootstrap')",(uid,handle.lower(),name,server.password_hash(password),server.now(),email))
        con.execute('INSERT INTO operators VALUES(?,?)',(uid,server.now()))
    server.send_token(uid,email,'verify')
    return uid


def main():
    parser=argparse.ArgumentParser(description='Manutenção local do Synapse 0.9')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('check')
    p=sub.add_parser('backup');p.add_argument('file',type=Path);p.add_argument('--server-stopped',action='store_true',required=True)
    p=sub.add_parser('restore');p.add_argument('file',type=Path);p.add_argument('--into',type=Path,required=True);p.add_argument('--server-stopped',action='store_true',required=True)
    sub.add_parser('cleanup')
    p=sub.add_parser('admin');p.add_argument('handle')
    p=sub.add_parser('reset-admin-mfa');p.add_argument('handle')
    sub.add_parser('admin-key')
    p=sub.add_parser('create-operator');p.add_argument('--handle',required=True);p.add_argument('--email',required=True);p.add_argument('--name',default='Operador Synapse')
    p=sub.add_parser('vapid');p.add_argument('--output',type=Path,default=Path('data/push-private.pem'))
    args=parser.parse_args()
    if args.command=='restore':restore(args.file,args.into);print('Restaurado. Sessões, tokens e assinaturas push antigas foram invalidados.');return
    server.initialize()
    if args.command=='check':print(json.dumps({'configuration':server.deployment_checks(),'capabilities':server.capabilities()},ensure_ascii=False,indent=2))
    elif args.command=='backup':print('Backup privado criado:',backup(args.file))
    elif args.command=='cleanup':print(json.dumps(cleanup()))
    elif args.command=='admin-key':
        from cryptography.fernet import Fernet
        print('Guarde em ADMIN_ENCRYPTION_KEY no ambiente privado de produção. Nunca envie ao repositório:')
        print(Fernet.generate_key().decode())
    elif args.command=='reset-admin-mfa':
        with server.db() as con:
            user=con.execute('SELECT a.id,a.handle FROM actors a JOIN operators o ON o.user_id=a.id WHERE a.handle=?',(args.handle,)).fetchone()
            if not user:raise ValueError('Operador não encontrado.')
            if input('Confirme o @usuário para redefinir MFA e revogar suas sessões: ').strip().lower().lstrip('@')!=user['handle']:raise ValueError('Cancelado.')
            con.execute('DELETE FROM operator_security WHERE user_id=?',(user['id'],))
            con.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
            server.admin_event(con,user,'mfa_reset_from_console','operator',user['id'],'Recuperação pelo console de confiança.')
        print('MFA removido e sessões revogadas. Reconfigure o autenticador antes de administrar em produção.')
    elif args.command=='admin':
        with server.db() as con:
            user=con.execute('SELECT id,name,email,handle FROM actors WHERE handle=? AND seeded=0 AND active=1',(args.handle,)).fetchone()
            if not user:raise ValueError('Conta real não encontrada.')
            print('Conta a promover:',user['name'],user['handle'],user['email'])
            if input('Digite o nome de usuário para confirmar: ').strip()!=user['handle']:raise ValueError('Confirmação incorreta.')
            con.execute('INSERT OR IGNORE INTO operators VALUES(?,?)',(user['id'],server.now()))
            con.execute("INSERT OR REPLACE INTO operator_roles(user_id,role) VALUES(?,'owner')",(user['id'],))
            server.admin_event(con,user,'owner_promoted_from_console','operator',user['id'],'Promoção confirmada no console de confiança.')
        print('Administrador vinculado à identidade da conta, não a um nome reutilizável.')
    elif args.command=='create-operator':
        password=getpass.getpass('Senha exclusiva de administrador (mínimo 16 caracteres): ')
        if password!=getpass.getpass('Repita a senha: '):raise ValueError('Senhas diferentes.')
        print('Conta criada:',create_operator(args.handle,args.email,args.name,password));print('Confirme o e-mail e guarde sua senha fora do repositório.')
    elif args.command=='vapid':
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        key=ec.generate_private_key(ec.SECP256R1());args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('xb') as out:out.write(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        args.output.chmod(0o600)
        public=key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
        print('VAPID_PUBLIC_KEY='+base64.urlsafe_b64encode(public).decode().rstrip('='))
        print('VAPID_PRIVATE_KEY='+str(args.output.resolve()));print('A chave privada não deve ir para o GitHub nem para o aplicativo.')

if __name__=='__main__':
    try:main()
    except Exception as exc:print('Erro:',exc,file=sys.stderr);sys.exit(1)
