"""Restore an authenticated backup into a separate directory, never the live database.
Keep BACKUP_ENCRYPTION_KEY private. This command never downloads a backup or starts
or stops the application. Supply a copy retrieved through your storage console.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.exceptions import InvalidTag
from operations import decrypt_archive,encryption_key
from manage import restore


def restore_encrypted(source:Path,destination:Path) -> None:
    source=source.resolve();destination=destination.resolve()
    if not source.is_file():raise ValueError('Arquivo de backup não encontrado.')
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError('Escolha uma pasta nova e vazia. Os dados existentes não serão substituídos.')
    key=encryption_key()
    # Plaintext is private, transient and never published as a downloadable artifact.
    with tempfile.TemporaryDirectory(prefix='synapse-restore-') as directory:
        os.chmod(directory,0o700);archive=Path(directory)/'authenticated.zip'
        try:decrypt_archive(source,archive,key)
        except InvalidTag:raise ValueError('Falha de autenticação: chave incorreta ou arquivo alterado.') from None
        restore(archive,destination)
    destination.chmod(0o700)


def main():
    parser=argparse.ArgumentParser(description='Restaurar backup criptografado do Synapse 0.9 em uma pasta separada.')
    parser.add_argument('file',type=Path)
    parser.add_argument('--into',type=Path,required=True)
    args=parser.parse_args()
    try:restore_encrypted(args.file,args.into)
    except (OSError,ValueError) as exc:parser.exit(1,'Restauração não concluída: '+str(exc)+'\n')
    print('Cópia restaurada em:',args.into.resolve())
    print('Cadastro fechado e manutenção ativada. Sessões, links e filas antigas foram invalidados.')
    print('Teste esta cópia isoladamente. Não substitua o banco ativo com o servidor em funcionamento.')
    print('ADMIN_ENCRYPTION_KEY é guardada separadamente e deve corresponder à instalação original.')

if __name__=='__main__':main()
