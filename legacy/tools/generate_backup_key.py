"""Creates a new private key file without replacing existing keys or changing server configuration."""
import argparse
import base64
import os
from pathlib import Path
import secrets

parser=argparse.ArgumentParser(description='Gerar chave de backup apenas na primeira configuração.')
parser.add_argument('--output',type=Path,default=Path('.backup-key.local'))
args=parser.parse_args()
try:
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as file:
        file.write('BACKUP_ENCRYPTION_KEY='+base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()+'\n')
except FileExistsError:parser.exit(1,'Arquivo já existe: não será sobrescrito. Preserve a chave original.\n')
print('Chave criada no arquivo privado:',args.output)
print('Guarde uma cópia fora do servidor. Não envie ao GitHub nem ao chat.')
print('Em atualizações, preserve a chave anterior: trocá-la impede abrir os backups antigos.')
