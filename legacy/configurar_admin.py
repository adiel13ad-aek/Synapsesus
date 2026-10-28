"""Interactive local operator creation. No default password and no public promotion endpoint."""
from pathlib import Path
import getpass
import os
import sys

ROOT=Path(__file__).resolve().parent

def main():
    print('\nSynapse 0.8 — criar sua conta responsável\n')
    print('Execute apenas no computador/servidor sob seu controle. Não compartilhe sua senha.')
    # Create only a missing development configuration. Never overwrite an existing deployment.
    env=ROOT/'.env'
    if not env.exists():
        with env.open('x',encoding='utf-8') as f:
            env.chmod(0o600)
            f.write('SYNAPSE_ENV=development\nSEED_DEMO_DATA=0\nMAIL_MODE=file\n')
        print('Configuração local criada, sem perfis fictícios. A implantação pública é uma etapa separada.')
    import server
    from manage import create_operator
    server.initialize()
    with server.db() as con:
        count=con.execute('SELECT COUNT(*) FROM operators').fetchone()[0]
    if count:
        print('Já há conta(s) administrativa(s). Este assistente não modifica as permissões delas.')
        if input('Criar outro responsável? Digite CRIAR para continuar: ').strip()!='CRIAR':
            print('Nenhuma conta criada.');return
    name=input('Seu nome de exibição: ').strip()
    handle=input('Seu usuário, sem @ (3 a 24 caracteres): ').strip().lower().lstrip('@')
    email=input('Seu e-mail: ').strip()
    if not 2<=len(name)<=50:raise ValueError('Use um nome de 2 a 50 caracteres.')
    password=getpass.getpass('Crie uma senha exclusiva de pelo menos 16 caracteres: ')
    if password!=getpass.getpass('Repita a senha: '):raise ValueError('As senhas não coincidem.')
    create_operator(handle,email,name,password)
    print('\nConta criada. Nenhuma senha foi gravada em texto puro nem exibida aqui.')
    print('Inicie o site e acesse http://localhost:8000/admin. Entre e configure o autenticador.')
    if server.MAIL_MODE=='file':
        print('Modo local: o link de confirmação está em data/outbox (arquivo .eml privado). Não houve envio de e-mail.')
    else:print('Confirme seu e-mail. O envio depende da configuração e entrega do provedor SMTP.')
    print('O site ainda NÃO está publicado. Consulte docs/OPERACAO.md para a implantação.')

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyboardInterrupt) as exc:
        print('Configuração não concluída:',str(exc),file=sys.stderr);sys.exit(1)
    except Exception:
        print('Não foi possível criar a conta. Verifique os campos e a disponibilidade do usuário/e-mail. Nenhuma conta existente foi alterada.',file=sys.stderr);sys.exit(1)
