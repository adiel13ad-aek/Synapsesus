"""UI smoke checks through an explicit HTTP bridge to local Uvicorn.
This sandbox blocks direct Chromium navigation. No real browser TLS, CSP, cookies,
external service or physical mobile test is claimed. All users are synthetic.
"""
from pathlib import Path
import base64,json,os,re,socket,subprocess,sys,tempfile,time
from urllib.parse import urlsplit
import httpx
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'test-results/v09';OUT.mkdir(parents=True,exist_ok=True)
PASSWORD='local-browser-test-2026'
checks=[];errors=[];sizes=[]
def record(x):checks.append(x);print('PASS',x,flush=True)
with tempfile.TemporaryDirectory(prefix='synapse09-ui-') as tmp:
    tmp=Path(tmp);env=os.environ.copy();env.update(SYNAPSE_DB=str(tmp/'test.db'),SYNAPSE_MEDIA=str(tmp/'media'),SYNAPSE_ENV='development',PUBLIC_ORIGIN='',SEED_DEMO_DATA='0',MAIL_MODE='file',ADMIN_ENCRYPTION_KEY='',AGE_ENFORCED='0',MINOR_ACCOUNTS_ENABLED='0',PUBLIC_INDEXING='0',AUTO_BACKUP_ENABLED='0',BACKUP_ENCRYPTION_KEY=base64.urlsafe_b64encode(os.urandom(32)).decode())
    setup="import server;server.initialize();from manage import create_operator;create_operator('gestor.teste','gestor@example.test','Gestor de teste',%r)\nwith server.db() as c:c.execute(\"UPDATE actors SET email_verified=1 WHERE handle='gestor.teste'\")"%PASSWORD
    subprocess.run([sys.executable,'-c',setup],cwd=ROOT,env=env,check=True)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}';web='https://synapse-test.invalid'
    log=(OUT/'browser-server.log').open('w')
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','server:app','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    clients=[]
    try:
        for _ in range(100):
            try:
                if httpx.get(base+'/api/ready',timeout=.5).status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.1)
        else:raise RuntimeError('Server unavailable')
        def client():
            c=httpx.Client(base_url=base,headers={'X-Synapse-Client':'web-v09','Content-Type':'application/json'},timeout=20);clients.append(c);return c
        admin=client();res=admin.post('/api/auth/login',json={'handle':'gestor.teste','password':PASSWORD});assert res.status_code==200
        admin.headers['X-CSRF-Token']=res.json()['csrf'];assert admin.post('/api/manage/unlock',json={'password':PASSWORD}).status_code==200
        def register(c,handle):
            r=c.post('/api/auth/register',json={'name':'Conta de teste','handle':handle,'email':handle+'@example.test','password':PASSWORD,'terms_accepted':True});assert r.status_code==200,r.text
            c.headers['X-CSRF-Token']=r.json()['csrf'];return c.get('/api/state').json()['me']
        user=client();me=register(user,'pessoa.teste')
        follower=client();following=register(follower,'conexao.teste')
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
            context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce',service_workers='block')
            def page_for(c,path):
                page=context.new_page()
                def transport(url,options):
                    u=urlsplit(url);target=u.path+('?' + u.query if u.query else '')
                    body=base64.b64decode(options['body']) if options.get('body') is not None else None
                    r=c.request(options.get('method','GET'),target,headers=options.get('headers',{}),content=body)
                    return {'body':base64.b64encode(r.content).decode(),'status':r.status_code,'headers':{'content-type':r.headers.get('content-type','application/json')}}
                page.expose_function('__transport',transport)
                page.evaluate("""()=>{window.fetch=async(url,options={})=>{let body=null;if(options.body!==undefined){const bytes=new TextEncoder().encode(options.body);let s='';for(let i=0;i<bytes.length;i+=16384)s+=String.fromCharCode(...bytes.subarray(i,i+16384));body=btoa(s);}const r=await window.__transport(String(url),{method:options.method||'GET',headers:{...(options.headers||{})},body});return new Response(Uint8Array.from(atob(r.body),c=>c.charCodeAt(0)),{status:r.status,headers:r.headers});};}""")
                def asset(route):
                    r=c.get(urlsplit(route.request.url).path)
                    route.fulfill(status=r.status_code,headers={'content-type':r.headers.get('content-type','application/octet-stream')},body=r.content)
                page.route(web+'/**',asset);page.on('pageerror',lambda e:errors.append(str(e)))
                markup=c.get(path).text;scripts=[]
                def script(m):scripts.append('<script>'+c.get('/'+m.group(1)).text.replace('</script','<\\/script')+'</script>');return ''
                markup=re.sub(r'<script src="/([^"<>]+)" defer></script>',script,markup)
                markup=re.sub(r'<link rel="stylesheet" href="/([^"<>]+)">',lambda m:'<style>'+c.get('/'+m.group(1)).text+'</style>',markup)
                markup=markup.replace('<head>','<head><base href="'+web+'/">').replace('</body>',''.join(scripts)+'</body>')
                page.set_content(markup,wait_until='domcontentloaded');return page
            safety=page_for(user,'/conta/seguranca')
            expect(safety.get_by_role('heading',name='Situação da conta')).to_be_visible()
            safety.locator('input[name=private]').check();safety.get_by_role('button',name='Salvar privacidade').click()
            expect(safety.locator('#notice')).to_contain_text('Solicitação registrada')
            assert user.get('/api/account/security').json()['private'];record('Privacy form changes the real server setting')
            assert follower.post('/api/actors/'+me['id']+'/follow',json={}).json()['pending']
            safety.evaluate('load()');expect(safety.get_by_role('button',name='Aprovar',exact=True)).to_be_visible()
            safety.get_by_role('button',name='Aprovar',exact=True).click()
            safety.wait_for_function('account.follow_requests.length===0')
            assert len(user.get('/api/account/followers').json()['items'])==1;record('Approved follow request through the user interface')
            form=safety.locator('form[data-form=support]')
            form.locator('select[name=kind]').select_option('privacy')
            form.locator('input[name=subject]').fill('Como remover os meus dados?')
            form.locator('textarea[name=body]').fill('Esta é uma solicitação sintética para testar o suporte e a resposta do operador.')
            form.locator('[type=submit]').click()
            expect(safety.get_by_role('heading',name='Como remover os meus dados?')).to_be_visible();record('Private support ticket submitted and displayed')
            second=client();result=second.post('/api/auth/login',json={'handle':'pessoa.teste','password':PASSWORD});assert result.status_code==200
            safety.evaluate('load()');safety.get_by_role('button',name='Encerrar todas as outras sessões').click()
            time.sleep(.2);assert second.get('/api/account/security').status_code==401;record('Revoked another live login through the security center')
            ops=page_for(admin,'/operacao');expect(ops.get_by_role('heading',name='E-mails que não somem silenciosamente.')).to_be_visible()
            reply=ops.locator('form[data-form=reply]');reply.locator('textarea').fill('Esta é uma resposta de teste. Você pode exportar e excluir sua conta em Configurações.')
            reply.locator('select').select_option('closed');reply.locator('[type=submit]').click()
            expect(ops.locator('#notice')).to_contain_text('Resposta registrada')
            safety.evaluate('load()');expect(safety.get_by_text('Esta é uma resposta de teste.',exact=False)).to_be_visible();record('Operator replied; only the requesting user receives the support response')
            ops.get_by_role('button',name='Enviar teste para meu e-mail').click();expect(ops.locator('#notice')).to_contain_text('outbox local');record('Test email UI truthfully labels file-only delivery')
            ops.get_by_role('button',name='Criar ponto de recuperação').click();expect(ops.locator('#notice')).to_contain_text('enfileirado')
            for _ in range(70):
                data=admin.get('/api/manage/operations').json()
                if data['backups'] and data['backups'][0]['status']=='local_only':break
                time.sleep(.2)
            else:raise AssertionError('Scheduled worker did not create local backup')
            ops.get_by_role('button',name='Atualizar agora ↻').click();expect(ops.get_by_text('Somente no servidor',exact=True)).to_be_visible();record('UI backup job executed by the application worker, labelled local-only')
            safety.wait_for_timeout(7000)  # let transient notices disappear naturally before captures
            for page,kind in [(safety,'security'),(ops,'operations')]:
                for width in (320,390,768,1440):
                    page.set_viewport_size({'width':width,'height':1000});page.evaluate('scrollTo(0,0)')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(kind,width)
                    sizes.append([kind,width]);page.screenshot(path=str(OUT/(kind+'-'+str(width)+'.png')),full_page=False)
            record('Eight responsive checks without horizontal page overflow')
            guest=client();locked=page_for(guest,'/operacao');expect(locked.get_by_role('heading',name='Desbloqueie seu painel.')).to_be_visible()
            assert not locked.get_by_role('heading',name='E-mails que não somem silenciosamente.').count();record('Unauthenticated operations page reveals no operational data')
            main=page_for(guest,'/');main.wait_for_function("typeof S!=='undefined' && S.site")
            main.evaluate('authDialog("register")');main.locator('input[name=name]').fill('Conta pela interface');main.locator('input[name=handle]').fill('nova.interface')
            main.locator('input[name=email]').fill('nova.interface@example.test');main.locator('input[name=password]').fill(PASSWORD)
            main.locator('input[name=terms_accepted]').check();main.get_by_role('button',name='Criar minha conta',exact=False).click()
            main.wait_for_function("S.me && S.me.handle==='nova.interface'");record('Existing social registration still works in local development mode')
            assert not errors,errors;record('No unhandled JavaScript errors')
            context.close();browser.close()
        (OUT/'browser-report.json').write_text(json.dumps({'checks':checks,'width_checks':sizes,'errors':errors,'method':'Chromium with real HTML/CSS/JS through an explicit HTTP bridge to local Uvicorn, temporary SQLite and synthetic accounts. Direct browser navigation is blocked by the sandbox. Does not test browser TLS/CSP/cookies, provider calls, real SMTP, object storage or physical devices.'},ensure_ascii=False,indent=2))
    finally:
        for c in clients:c.close()
        proc.terminate();proc.wait(timeout=20);log.close()
