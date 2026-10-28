"""Chromium UI + an HTTP transport bridge -> Uvicorn -> temporary SQLite.
The managed browser blocks localhost navigation; fetch and media are bridged, not server APIs.
Test accounts only. Email verification is fixture setup, not an SMTP delivery test.
"""
from pathlib import Path
import os,sys,subprocess,tempfile,time,json,socket,base64
import httpx
from playwright.sync_api import sync_playwright,expect
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from administration import totp
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
checks=[];errors=[]
def record(msg):checks.append(msg);print('PASS',msg,flush=True)
PASSWORD='testing-browser-2026' # throwaway local fixture, never deployed
with tempfile.TemporaryDirectory(prefix='synapse-browser-v07-') as temp:
    temp=Path(temp)
    env=os.environ.copy();env.update(SYNAPSE_DB=str(temp/'test.db'),SYNAPSE_MEDIA=str(temp/'media'),SEED_DEMO_DATA='0',SYNAPSE_ENV='development',MAIL_MODE='file',PUBLIC_ORIGIN='',ADMIN_ENCRYPTION_KEY='')
    setup="import server;server.initialize();from manage import create_operator;create_operator('gestor.teste','gestor@example.test','Gestor de teste',%r)\nwith server.db() as c:c.execute(\"UPDATE actors SET email_verified=1 WHERE handle=?\",('gestor.teste',))"%PASSWORD
    subprocess.run([sys.executable,'-c',setup],cwd=ROOT,env=env,check=True)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base='http://127.0.0.1:'+str(port)
    log=(OUT/'browser-http-server.log').open('w')
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','server:app','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    try:
        for attempt in range(60):
            try:
                if httpx.get(base+'/api/health',timeout=1).status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.1)
        else:raise RuntimeError('Local server did not start')
        clients=[]
        for handle,name in [('marina.teste','Marina (teste)'),('rafael.teste','Rafael (teste)'),('camila.teste','Camila (teste)')]:
            c=httpx.Client(base_url=base,headers={'X-Synapse-Client':'web-v07'},timeout=15)
            r=c.post('/api/auth/register',json={'handle':handle,'name':name,'email':handle+'@example.test','password':PASSWORD,'terms_accepted':True});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];clients.append(c)
        photo='data:image/jpeg;base64,'+base64.b64encode((ROOT/'web/assets/mountain.jpg').read_bytes()).decode()
        p1=clients[0].post('/api/posts',json={'body':'Boas descobertas merecem uma comunidade. Publicação de teste para revisão.','image_data':photo}).json()['id']
        p2=clients[1].post('/api/posts',json={'body':'Uma referência nova para o meu projeto. Publicação de teste.','link_url':'https://example.com/'}).json()['id']
        clients[2].post('/api/posts/'+p2+'/report',json={'reason':'Denúncia fictícia para verificar o fluxo de moderação.'}).raise_for_status()
        clients[0].post('/api/links',json={'url':'https://example.com/private','title':'Referência privada de teste','note':'SEGREDO_DE_COLECAO_PRIVADA'}).raise_for_status()
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
            def make_page(mode='admin',width=1440,client=None):
                transport_client=client or httpx.Client(base_url=base,timeout=20)
                context=browser.new_context(viewport={'width':width,'height':1000 if width>700 else 844},service_workers='block')
                page=context.new_page();page.set_default_timeout(12000);page.on('pageerror',lambda e:errors.append(str(e)))
                def transport(url,options):
                    from urllib.parse import urlsplit
                    u=urlsplit(url);path=u.path+('?' + u.query if u.query else '')
                    body=base64.b64decode(options['body']) if options.get('body') is not None else None
                    r=transport_client.request(options.get('method','GET'),path,headers=options.get('headers',{}),content=body)
                    return {'body':base64.b64encode(r.content).decode(),'status':r.status_code,'headers':{'content-type':r.headers.get('content-type','application/json')}}
                page.expose_function('__transport',transport)
                page.evaluate("""() => { window.fetch=async(url,options={})=>{
                    const headers={...(options.headers||{})};let encoded=null;
                    if(options.body!==undefined){let a=new TextEncoder().encode(options.body);let s='';for(let i=0;i<a.length;i+=16384)s+=String.fromCharCode(...a.subarray(i,i+16384));encoded=btoa(s);}
                    const r=await window.__transport(String(url),{method:options.method||'GET',headers,body:encoded});
                    return new Response(Uint8Array.from(atob(r.body),c=>c.charCodeAt(0)),{status:r.status,headers:r.headers});
                }; }""")
                def asset(route):
                    from urllib.parse import urlsplit
                    r=transport_client.get(urlsplit(route.request.url).path)
                    route.fulfill(status=r.status_code,headers={'Content-Type':r.headers.get('content-type','application/octet-stream')},body=r.content)
                page.route('https://synapse-test.invalid/**',asset)
                if mode=='admin':
                    markup=(ROOT/'web/admin.html').read_text().replace('<link rel="stylesheet" href="/admin.css">','<style>'+(ROOT/'web/admin.css').read_text()+'</style>')
                    markup=markup.replace('<script src="/admin.js" defer></script>','').replace('</body>','<script>'+(ROOT/'web/admin.js').read_text().replace('</script','<\\/script')+'</script></body>')
                else:markup=(ROOT/'demos'/'Synapse-Discovery-v0.8-demo.html').read_text().replace('data-mode="demo"','data-mode="server"')
                markup=markup.replace('<head>','<head><base href="https://synapse-test.invalid/">')
                page.set_content(markup,wait_until='domcontentloaded')
                return page,transport_client
            page,operator_client=make_page()
            expect(page.locator('[data-form="login"]')).to_be_visible()
            page.locator('[name="handle"]').fill('gestor.teste');page.locator('[name="password"]').fill(PASSWORD)
            page.locator('[data-form="login"] [type="submit"]').click()
            expect(page.locator('[data-form="enroll"]')).to_be_visible();page.locator('[name="password"]').fill(PASSWORD)
            page.locator('[data-form="enroll"] [type="submit"]').click()
            secret=page.locator('.secret').inner_text();code=totp(secret,int(time.time()//30))
            page.locator('[name="code"]').fill(code);page.locator('[data-form="confirm-mfa"] [type="submit"]').click()
            expect(page.locator('.recovery code')).to_have_count(8)
            page.locator('[data-action="continue"]').click();expect(page.locator('#main.main h1')).to_have_text('Sua comunidade, em perspectiva.')
            record('Login administrativo, configuração TOTP e códigos de recuperação na interface + ponte HTTP ao servidor real')
            page.screenshot(path=str(OUT/'admin-desktop.png'),full_page=False)
            def go(view):
                page.locator('[data-nav="'+view+'"]').first.click()
                expect(page.locator('#main')).not_to_contain_text('Carregando dados do servidor…')
            go('users');expect(page.locator('tbody tr')).to_have_count(4)
            row=page.locator('tbody tr').filter(has_text='rafael.teste');row.locator('[data-user-action="suspend"]').click()
            page.locator('#action-reason').fill('Conta suspensa em um teste temporário de segurança.')
            page.locator('[data-form="action"] [type="submit"]').click();expect(page.locator('#action-dialog')).not_to_be_visible()
            expect(page.locator('tbody tr').filter(has_text='rafael.teste')).to_contain_text('Suspensa')
            assert clients[1].get('/api/state').json()['me'] is None
            record('Suspensão pelo painel revogou a sessão HTTP da conta alvo')
            go('posts');page.locator('[data-post="'+p1+'"]').click();page.locator('#action-reason').fill('Teste de ocultação da publicação pública.')
            page.locator('[data-form="action"] [type="submit"]').click();expect(page.locator('#action-dialog')).not_to_be_visible()
            assert not any(p['id']==p1 for p in httpx.get(base+'/api/feed').json()['posts'])
            page.locator('[data-post="'+p1+'"]').click();page.locator('#action-reason').fill('Teste de restauração da publicação pública.')
            page.locator('[data-form="action"] [type="submit"]').click();expect(page.locator('#action-dialog')).not_to_be_visible()
            assert any(p['id']==p1 for p in httpx.get(base+'/api/feed').json()['posts'])
            record('Ocultar e restaurar publicação refletiu no feed público')
            go('reports');expect(page.locator('.content-card')).to_have_count(1)
            page.locator('[data-decision="dismiss"]').click();page.locator('#action-reason').fill('Denúncia de teste analisada sem infração real.')
            page.locator('[data-form="action"] [type="submit"]').click();expect(page.locator('#main')).to_contain_text('Fila em dia.')
            record('Denúncia revisada com justificativa e encerramento da fila')
            go('settings');page.locator('[name="registration_open"]').uncheck();page.locator('[name="announcement"]').fill('Estamos preparando a abertura da comunidade. Obrigado por acompanhar!')
            page.locator('[name="reason"]').fill('Preparação do lançamento em ambiente de teste.')
            page.locator('[data-form="settings"] [type="submit"]').click();expect(page.locator('#notice')).to_contain_text('Configurações aplicadas')
            assert not httpx.get(base+'/api/site').json()['registration_open']
            visitor,visitor_client=make_page('public',390)
            expect(visitor.locator('.site-notice')).to_contain_text('preparando a abertura')
            visitor.locator('[data-action="auth"]:visible').first.click();expect(visitor.locator('[data-form="auth"] [name="password"]')).to_be_visible()
            assert visitor.locator('[data-form="auth"] [name="email"]').count()==0
            record('Cadastros fechados no servidor e aviso público exibido na rede')
            go('policies');page.locator('#policy-select').select_option('privacy')
            text='Política temporária de teste automatizado, não utilizável no lançamento.\n\n'+('Informações fictícias sobre a operação. '*15)
            page.locator('#policy-body').fill(text);page.locator('[name="reason"]').fill('Teste do editor de documentos públicos.')
            page.locator('[name="reviewed"]').check();page.locator('[data-form="policy"] [type="submit"]').click()
            expect(page.locator('#notice')).to_contain_text('Documento publicado')
            assert 'Política temporária' in httpx.get(base+'/privacy.html').text
            record('Editor publicou texto revisado na página pública, sem HTML executável')
            go('launch');page.locator('[data-attest="browser_test"]').click();page.locator('[name="note"]').fill('Teste local automatizado por HTTP, sem domínio público real.')
            page.locator('[name="confirmed"]').check();page.locator('[data-form="attest"] [type="submit"]').click()
            expect(page.locator('#action-dialog')).not_to_be_visible();expect(page.locator('#main')).to_contain_text('declarações do responsável')
            record('Checklist distingue configuração de verificação declarada pelo responsável')
            page.screenshot(path=str(OUT/'admin-launch.png'),full_page=True)
            go('audit');expect(page.locator('tbody')).to_contain_text('Conta suspensa');expect(page.locator('tbody')).to_contain_text('Configurações atualizadas')
            assert 'SEGREDO_DE_COLECAO_PRIVADA' not in page.content()
            record('Histórico exibiu responsável e ações, sem expor coleções privadas')
            layout_count=0
            for width in (320,390,768,1440,1920):
                page.set_viewport_size({'width':width,'height':844 if width<700 else 1000})
                for view in ('overview','users','posts','reports','settings','policies','launch','audit','health'):
                    go(view)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),(width,view)
                    layout_count+=1
                    if width==390 and view=='overview':
                        expect(page.locator('#notice')).not_to_have_class('show')
                        page.screenshot(path=str(OUT/'admin-mobile.png'),full_page=True)
                    if width==1440 and view=='users':page.screenshot(path=str(OUT/'admin-users.png'),full_page=False)
            record(str(layout_count)+' combinações de tela administrativa e largura sem rolagem horizontal da página')
            page.close();page,_=make_page('public',client=operator_client);expect(page.locator('#app .layout')).to_be_visible()
            layout_public=0
            for width in (320,390,768,1440):
                page.set_viewport_size({'width':width,'height':844 if width<700 else 1000})
                for section in ('feed','explore','collections','profile','messages','notifications','settings'):
                    page.evaluate('(s)=>go(s)',section);page.wait_for_timeout(50)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),(width,section)
                    layout_public+=1
            record(str(layout_public)+' combinações de tela pública e largura preservadas')
            page.evaluate("() => { window.open=(url)=>{window.__policyURL=url;}; legal('privacy'); }")
            assert page.evaluate('window.__policyURL')=='/privacy.html'
            record('Link de privacidade da interface aponta ao documento publicado pelo responsável')
            page.close();page,_=make_page('admin',client=operator_client);expect(page.locator('#main.main h1')).to_have_text('Sua comunidade, em perspectiva.')
            page.locator('[data-action="lock"]').click();expect(page.locator('[data-form="unlock"]')).to_be_visible()
            record('Bloqueio manual removeu o acesso administrativo sem sair da conta social')
            assert not errors,errors
            record('Nenhum erro JavaScript não tratado nas telas exercitadas')
            (OUT/'browser-v07.json').write_text(json.dumps({'checks':checks,'layout_admin':layout_count,'layout_public':layout_public,'page_errors':errors,'transport':'Chromium fetch/media bridge -> real HTTP -> Uvicorn -> SQLite temporary. Browser localhost navigation is blocked by environment policy; server API is not mocked.','fixture':'Temporary test accounts, mock email verification only; MFA TOTP computed by test authenticator','not_tested':['Public hosting','Real SMTP delivery','Real HTTPS/proxy at hosting provider','Physical phones','Independent security audit','Load/capacity test']},ensure_ascii=False,indent=2))
            browser.close()
    finally:
        proc.terminate()
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
        log.close()
