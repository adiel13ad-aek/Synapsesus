from pathlib import Path
import subprocess,os,tempfile,sys
root=Path(__file__).resolve().parents[1]
temp=Path(tempfile.mkdtemp(prefix='synapse-v04-ui-'))
env=os.environ.copy();env.update(SYNAPSE_DB=str(temp/'test.db'),SYNAPSE_MEDIA=str(temp/'media'),MAIL_MODE='file',ADMIN_HANDLES='moderador')
log=(root/'test-server.log').open('w')
p=subprocess.Popen([sys.executable,'-m','uvicorn','server:app','--host','127.0.0.1','--port','8777'],cwd=root,env=env,stdout=log,stderr=log,start_new_session=True)
print('PID',p.pid,'TEST DATA',temp)
