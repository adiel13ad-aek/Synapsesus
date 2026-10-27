"""Start Synapse on this computer. --lan explicitly exposes it to the local network."""
import argparse
import sys
import threading
import webbrowser
from pathlib import Path

if sys.version_info < (3, 10):
    raise SystemExit('Instale Python 3.10 ou superior.')

parser=argparse.ArgumentParser(description='Synapse: protótipo para testes privados.')
parser.add_argument('--lan',action='store_true',help='Escutar em 0.0.0.0 para testar na mesma rede Wi-Fi.')
parser.add_argument('--port',type=int,default=8000)
parser.add_argument('--no-browser',action='store_true')
args=parser.parse_args()
if not 1024<=args.port<=65535:
    parser.error('Use uma porta entre 1024 e 65535.')
try:
    import uvicorn
except ImportError:
    raise SystemExit('Faltam dependências. Execute: python -m pip install -r requirements.txt')

if __name__=='__main__':
    print('\nSynapse 0.4 — teste privado, não exponha diretamente à internet.\n')
    print(f'Neste computador: http://localhost:{args.port}')
    print('Rede social + pesquisa. Agentes de IA desativados.')
    if args.lan:
        print(f'Na mesma rede: http://IP-DO-COMPUTADOR:{args.port}')
        print('Use apenas rede privada confiável. HTTP de rede não protege senhas em trânsito.')
        print('Use contas e senhas de teste. Para instalar PWA no celular, configure HTTPS.')
    print('O banco persistente fica em data/synapse.db (ou SYNAPSE_DB).\n')
    if not args.no_browser:
        timer=threading.Timer(1.5,lambda:webbrowser.open(f'http://localhost:{args.port}'))
        timer.daemon=True
        timer.start()
    uvicorn.run('server:app',app_dir=str(Path(__file__).resolve().parent),host='0.0.0.0' if args.lan else '127.0.0.1',port=args.port,proxy_headers=False,access_log=False)
