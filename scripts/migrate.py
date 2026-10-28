#!/usr/bin/env python3
"""Offline, explicit migration from 0.9 SQLite to a NEW empty D1 + private R2.
Never calls a cloud API. Never alters the source. Outputs contain private data.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
SKIP={'sessions','session_devices','auth_tokens','admin_grants','age_challenges','guardian_invites',
      'mail_jobs','calls','call_signals','push_subscriptions','durable_rates','integration_checks',
      'launch_attestations','policy_reviews','backup_jobs','setup_locks'}
NAME=re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
MEDIA_NAME=re.compile(r'^[a-f0-9]{32}\.(?:jpg|jpeg|png|webp|mp4)$')

def quoted(name):
    if not NAME.fullmatch(name):raise ValueError('Identificador SQL inesperado.')
    return '"'+name+'"'

def sql_value(value):
    if value is None:return 'NULL'
    if isinstance(value,bytes):return "X'"+value.hex()+"'"
    if isinstance(value,(int,float)):return str(value)
    # SQLite/D1 SQL literal; hex avoids NUL/control chars and protects dump parsing.
    return "CAST(X'"+value.encode('utf-8').hex()+"' AS TEXT)"

def encode64(value):return base64.urlsafe_b64encode(value).rstrip(b'=').decode()

def read_key(path):
    value=Path(path).read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}',value):raise ValueError('Arquivo de chave inválido; deve conter apenas a chave.')
    raw=base64.urlsafe_b64decode(value+'='*(-len(value)%4))
    if len(raw)!=32:raise ValueError('A chave deve conter 32 bytes.')
    return value,raw

def migrate(args):
    if not args.server_stopped:raise ValueError('Pare o servidor 0.9 e use --server-stopped. O parâmetro apenas declara a parada; não a executa.')
    source=Path(args.database).resolve(strict=True)
    media=Path(args.media).resolve(strict=True)
    output=Path(args.output).resolve()
    if not source.is_file() or not media.is_dir():raise ValueError('Banco e pasta de mídias inválidos.')
    if output==media or media in output.parents or output==source.parent:raise ValueError('Use uma pasta de saída separada da instalação antiga.')
    output.mkdir(parents=True,exist_ok=False,mode=0o700)
    os.chmod(output,0o700)
    created=[]
    try:
        src=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
        src.row_factory=sqlite3.Row
        if src.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Falha de integridade no banco original.')
        if src.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Banco original tem referências inválidas; corrija antes de migrar.')
        dest=sqlite3.connect(':memory:')
        dest.row_factory=sqlite3.Row
        # D1 schema exactly as shipped, with fresh closed registration defaults.
        dest.executescript((ROOT/'migrations/0001_initial.sql').read_text())
        triggers=[(r['name'],r['sql']) for r in dest.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'")]
        for name,_ in triggers:dest.execute('DROP TRIGGER '+quoted(name))
        dest.commit();dest.execute('PRAGMA foreign_keys=OFF')
        target_tables={r[0] for r in dest.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        source_tables=[r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        unknown=set(source_tables)-target_tables
        if unknown:raise ValueError('Tabelas desconhecidas na origem; migração interrompida para evitar perda: '+', '.join(sorted(unknown)))
        old_key=new_key=None
        security_exists='operator_security' in source_tables
        enabled=src.execute('SELECT COUNT(*) FROM operator_security WHERE enabled=1').fetchone()[0] if security_exists else 0
        if enabled:
            if not args.legacy_admin_key_file or not args.new_admin_key_file:
                raise ValueError('Há 2FA ativo. Forneça --legacy-admin-key-file e --new-admin-key-file para preservar o autenticador.')
            try:
                from cryptography.fernet import Fernet
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            except ImportError:raise ValueError('Instale cryptography==46.0.4 no ambiente local para converter a proteção do 2FA.')
            old_value,_=read_key(args.legacy_admin_key_file)
            old_key=Fernet(old_value.encode())
            _,new_key=read_key(args.new_admin_key_file)
        counts={};skipped={}
        for table in source_tables:
            total=src.execute('SELECT COUNT(*) FROM '+quoted(table)).fetchone()[0]
            if table in SKIP:skipped[table]=total;continue
            target_cols=[r['name'] for r in dest.execute('PRAGMA table_info('+quoted(table)+')')]
            source_cols=[r['name'] for r in src.execute('PRAGMA table_info('+quoted(table)+')')]
            unknown_cols=set(source_cols)-set(target_cols)
            if unknown_cols:raise ValueError('Colunas desconhecidas em '+table+'; nada será descartado automaticamente.')
            columns=[c for c in target_cols if c in source_cols]
            dest.execute('DELETE FROM '+quoted(table))
            for row in src.execute('SELECT * FROM '+quoted(table)):
                value=dict(row)
                if table=='actors':value.update(terms_version='',age_band='unknown',age_verified_until=0,age_provider='')
                if table=='site_settings':value['registration_open']=0;value['maintenance']=1
                if table=='pilot_invites':value['revoked']=1
                if table=='site_policies':value['reviewed_by']=None;value['reviewed_at']=''
                if table=='operator_security':
                    value.update(pending='',pending_expires=0)
                    if value['enabled']:
                        plaintext=old_key.decrypt(value['secret'].encode())
                        iv=os.urandom(12)
                        encrypted=AESGCM(new_key).encrypt(iv,plaintext,None)
                        value['secret']='v1:'+encode64(iv)+':'+encode64(encrypted)
                    else:value['secret']=''
                dest.execute('INSERT INTO '+quoted(table)+'('+','.join(map(quoted,columns))+') VALUES('+','.join('?' for _ in columns)+')',[value[c] for c in columns])
            counts[table]=total
        dest.commit();dest.execute('PRAGMA foreign_keys=ON')
        if dest.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('A transformação resultou em referências inválidas; saída não utilizável.')
        # Preserve file keys. Existing MP4s are copied, but runtime parity may be limited.
        required=set()
        for table,columns in [('actors',['avatar_path','cover_path']),('posts',['image_path']),('stories',['image_path']),('media_assets',['path','thumbnail'])]:
            for row in dest.execute('SELECT '+','.join(columns)+' FROM '+quoted(table)):
                for value in row:
                    if not value:continue
                    if not isinstance(value,str) or not value.startswith('/media/') or not MEDIA_NAME.fullmatch(value[7:]):raise ValueError('Referência de mídia inválida no banco; revise os dados antes de migrar.')
                    required.add(value[7:])
        media_out=output/'media';media_out.mkdir(mode=0o700)
        files=[]
        for name in sorted(required):
            path=media/name
            if path.is_symlink() or not path.is_file():raise ValueError('Uma mídia referenciada está ausente ou é link simbólico: '+name)
            destination=media_out/name
            shutil.copyfile(path,destination);os.chmod(destination,0o600)
            digest=hashlib.sha256(destination.read_bytes()).hexdigest()
            files.append({'key':name,'file':'media/'+name,'bytes':destination.stat().st_size,'sha256':digest,
                          'content_type':mimetypes.guess_type(name)[0] or 'application/octet-stream'})
        # Import only into a fresh database after migrations. Guard executes first.
        lines=['-- DADOS PRIVADOS. NÃO ENVIAR AO GITHUB. Destino: banco NOVO, com migrations aplicadas.',
               'PRAGMA defer_foreign_keys=ON;',
               "INSERT INTO setup_locks(id,user_id,consumed_at) SELECT 2,'refuse-nonempty','' WHERE EXISTS(SELECT 1 FROM actors);",
               *['DROP TRIGGER '+quoted(name)+';' for name,_ in triggers],
               'DELETE FROM site_settings;']
        # SQLite schema order has parents first. Actor self-reference rows explicitly sorted.
        for table in [r[0] for r in dest.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]:
            if table in SKIP:continue
            cols=[r['name'] for r in dest.execute('PRAGMA table_info('+quoted(table)+')')]
            rows=list(dest.execute('SELECT * FROM '+quoted(table)))
            if table=='actors':
                pending=rows;rows=[];seen=set()
                while pending:
                    ready=[r for r in pending if not r['owner_id'] or r['owner_id'] in seen]
                    if not ready:raise ValueError('Ciclo de propriedade de contas na origem.')
                    for r in ready:rows.append(r);seen.add(r['id'])
                    pending=[r for r in pending if r['id'] not in seen]
            for row in rows:lines.append('INSERT INTO '+quoted(table)+'('+','.join(map(quoted,cols))+') VALUES('+','.join(sql_value(row[c]) for c in cols)+');')
        lines += [ddl+';' for _,ddl in triggers]
        lines += ['PRAGMA defer_foreign_keys=OFF;']
        sql='\n'.join(lines)+'\n'
        # Replay the generated SQL into another fresh DB to verify actual artifact.
        verify=sqlite3.connect(':memory:')
        verify.executescript((ROOT/'migrations/0001_initial.sql').read_text())
        verify.executescript(sql)
        if verify.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Falha de integridade no SQL exportado.')
        for table,count in counts.items():
            if verify.execute('SELECT COUNT(*) FROM '+quoted(table)).fetchone()[0]!=count:raise ValueError('Contagem divergente no SQL exportado: '+table)
        sql_path=output/'import.sql';sql_path.write_text(sql,encoding='utf-8');os.chmod(sql_path,0o600)
        manifest={'format':'synapse-cloudflare-migration-v1','created_at':datetime.now(timezone.utc).isoformat(),
                  'database_sha256':hashlib.sha256(sql.encode()).hexdigest(),'counts':counts,'discarded_ephemeral_records':skipped,
                  'two_factor_accounts_preserved':enabled,'media':files,'registration_open':False,'maintenance':True,
                  'warning':'SQL, mídias e relatório são privados. Importar somente em D1 novo e R2 privado. Nenhum recurso remoto foi alterado.'}
        manifest_path=output/'manifest.json';manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');os.chmod(manifest_path,0o600)
        print('Migração offline preparada e reproduzida em banco temporário. Nenhum upload realizado.')
        print('Saída privada:',output)
        print('Contas:',counts.get('actors',0),'| Publicações:',counts.get('posts',0),'| Mídias:',len(files),'| 2FA preservados:',enabled)
    except Exception:
        # Do not leave an incomplete bundle that could be mistaken for a usable export.
        shutil.rmtree(output)
        raise

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',required=True);p.add_argument('--media',required=True)
    p.add_argument('--output',default='migration-output')
    p.add_argument('--server-stopped',action='store_true')
    p.add_argument('--legacy-admin-key-file');p.add_argument('--new-admin-key-file')
    args=p.parse_args()
    try:migrate(args)
    except Exception as exc:
        print('Migração interrompida:',type(exc).__name__+':',str(exc),file=sys.stderr);return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
