"""Chromium via request-routing bridge to real local Uvicorn, temporary DB and synthetic accounts only.
No public deploy, production HTTPS, real SMTP or physical device tests.
"""
from pathlib import Path
import os, sys, subprocess, tempfile, time, json, socket
import httpx
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'test-results/v08';OUT.mkdir(parents=True,exist_ok=True)
checks=[];errors=[];width_checks=[]
def record(msg):checks.append(msg);print('PASS',msg,flush=True)
PASSWORD='local-browser-test-2026'
with tempfile.TemporaryDirectory(prefix='synapse-v08-browser-') as temp:
    temp=Path(temp);env=os.environ.copy();env.update(SYNAPSE_DB=str(temp/'test.db'),SYNAPSE_MEDIA=str(temp/'media'),SEED_DEMO_DATA='0',SYNAPSE_ENV='development',MAIL_MODE='file',PUBLIC_ORIGIN='',ADMIN_ENCRYPTION_KEY='',PUBLIC_INDEXING='0')
    setup="import server;server.initialize();from manage import create_operator;create_operator('gestor.teste','gestor@example.test','Gestor de teste',%r)\nwith server.db() as c:c.execute(\"UPDATE actors SET email_verified=1 WHERE handle=?\",('gestor.teste',))"%PASSWORD
    subprocess.run([sys.executable,'-c',setup],cwd=ROOT,env=env,check=True)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base='http://127.0.0.1:'+str(port)
    log=(OUT/'server.log').open('w')
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','server:app','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try:
                if httpx.get(base+'/api/health',timeout=.5).status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.1)
        else:raise RuntimeError('Local server not ready')
        admin=httpx.Client(base_url=base,headers={'X-Synapse-Client':'web-v07','Content-Type':'application/json'})
        login=admin.post('/api/auth/login',json={'handle':'gestor.teste','password':PASSWORD});assert login.status_code==200,login.text
        admin.headers['X-CSRF-Token']=login.json()['csrf']
        assert admin.post('/api/manage/unlock',json={'password':PASSWORD}).status_code==200
        assert admin.patch('/api/manage/settings',json={'registration_open':False,'maintenance':False,'uploads_enabled':True,'announcement':'Teste local da apresentação pública.','reason':'Preparar teste local por convites.'}).status_code==200
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
            web='https://synapse-test.invalid'
            def setup_page(page, transport_client):
                import base64
                from urllib.parse import urlsplit
                def transport(url,options):
                    u=urlsplit(url);path=u.path+('?' + u.query if u.query else '')
                    body=base64.b64decode(options['body']) if options.get('body') is not None else None
                    res=transport_client.request(options.get('method','GET'),path,headers=options.get('headers',{}),content=body)
                    return {'body':base64.b64encode(res.content).decode(),'status':res.status_code,'headers':{'content-type':res.headers.get('content-type','application/json')}}
                page.expose_function('__transport',transport)
                page.evaluate("""() => { window.fetch=async(url,options={})=>{
                    let encoded=null;if(options.body!==undefined){let a=new TextEncoder().encode(options.body);let s='';for(let i=0;i<a.length;i+=16384)s+=String.fromCharCode(...a.subarray(i,i+16384));encoded=btoa(s);}
                    const r=await window.__transport(String(url),{method:options.method||'GET',headers:{...(options.headers||{})},body:encoded});
                    return new Response(Uint8Array.from(atob(r.body),c=>c.charCodeAt(0)),{status:r.status,headers:r.headers});
                }; }""")
                def asset(route):
                    res=transport_client.get(urlsplit(route.request.url).path)
                    route.fulfill(status=res.status_code,headers={'content-type':res.headers.get('content-type','application/octet-stream')},body=res.content)
                page.route(web+'/**',asset)
                page.on('pageerror',lambda e:errors.append(str(e)))
            def load_page(page,client,path):
                import re
                markup=client.get(path).text
                scripts=[]
                def inline_script(m):
                    scripts.append('<script>'+client.get('/'+m.group(1)).text.replace('</script','<\\/script')+'</script>');return ''
                markup=re.sub(r'<script src="/([^"<>]+)" defer></script>',inline_script,markup)
                markup=re.sub(r'<link rel="stylesheet" href="/([^"<>]+)">',lambda m:'<style>'+client.get('/'+m.group(1)).text+'</style>',markup)
                markup=markup.replace('<head>','<head><base href="'+web+'/">').replace('</body>',''.join(scripts)+'</body>')
                page.set_content(markup,wait_until='domcontentloaded')
            context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce',service_workers='block')
            page=context.new_page();setup_page(page,admin)
            for width in (320,390,768,1440):
                page.set_viewport_size({'width':width,'height':920})
                for path in ('/bem-vindo','/como-funciona','/ajuda'):
                    load_page(page,admin,path)
                    expect(page.locator('h1')).to_be_visible()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(path,width)
                    width_checks.append([path,width])
                    if path=='/bem-vindo' and width in (390,1440):page.screenshot(path=str(OUT/('landing-'+str(width)+'.png')),full_page=True)
            record('12 verificações responsivas das páginas públicas, sem rolagem horizontal')
            load_page(page,admin,'/ajuda');page.get_by_text('Como excluo minha conta?',exact=True).click();expect(page.get_by_text('Na comunidade, abra Configurações',exact=False)).to_be_visible();record('Ajuda e perguntas expansíveis')
            page.set_viewport_size({'width':1440,'height':1000});load_page(page,admin,'/admin')
            page.get_by_role('button',name='Convites',exact=True).click()
            page.get_by_label('Nome interno do grupo').fill('Grupo inicial de teste')
            page.get_by_label('Quantidade de contas').fill('1');page.get_by_label('Validade em dias').fill('7')
            page.get_by_role('button',name='Gerar convite privado',exact=True).click()
            expect(page.get_by_text('Convite criado — guarde agora')).to_be_visible()
            invite=page.locator('#action-dialog textarea').input_value();code=page.locator('#action-dialog input').input_value()
            assert '#convite=' in invite and code in invite
            page.get_by_role('button',name='Fechar',exact=True).last.click();record('Responsável cria convite pela interface e recebe o link uma única vez')
            for width in (390,1440):
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),('invites',width)
                width_checks.append(['admin/invites',width]);page.screenshot(path=str(OUT/('invites-'+str(width)+'.png')),full_page=True)
            guest_context=browser.new_context(viewport={'width':390,'height':900},reduced_motion='reduce',service_workers='block');guest_client=httpx.Client(base_url=base,timeout=20);guest=guest_context.new_page();setup_page(guest,guest_client)
            guest.evaluate("history.replaceState=()=>{}");load_page(guest,guest_client,'/');guest.wait_for_function("typeof S!=='undefined' && S.site");guest.evaluate('(code)=>{invitationCode=code;authDialog(\"register\");}',code)
            expect(guest.get_by_text('Seu mundo começa aqui.',exact=True)).to_be_visible()
            guest.locator('input[name="name"]').fill('Pessoa de teste');guest.locator('input[name="handle"]').fill('beta.ux')
            guest.locator('input[name="email"]').fill('beta.ux@example.test');guest.locator('input[name="password"]').fill(PASSWORD)
            assert guest.locator('input[name="invite_code"]').input_value()==code
            guest.locator('input[name="terms_accepted"]').check();guest.get_by_role('button',name='Criar minha conta',exact=False).click()
            guest.wait_for_function("S.me && S.me.handle==='beta.ux'")
            record('Formulário de cadastro com código de convite funciona com inscrições gerais fechadas; parâmetro inserido pela ponte de teste')
            state=guest.evaluate("fetch('/api/state').then(r=>r.json())")
            assert state['preferences']['dm_policy']=='following';record('Conta nova inicia mensagens restritas a perfis seguidos')
            response=guest.evaluate("async (csrf)=>{const r=await fetch('/api/posts',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Synapse-Client':'web-v07','X-CSRF-Token':csrf},body:JSON.stringify({body:'Minha primeira descoberta de teste, em um servidor local.'})});return {status:r.status,body:await r.json()};}",state['csrf'])
            assert response['status']==200,response
            record('Conta convidada publica no backend local autenticado')
            page.set_viewport_size({'width':1440,'height':1000});page.get_by_role('button',name='Crescimento',exact=True).click()
            expect(page.get_by_role('heading',name='Primeiros usuários. Dados reais.',exact=True)).to_be_visible()
            expect(page.get_by_text('100%',exact=True)).to_be_visible()
            for width in (390,1440):
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),('growth',width)
                width_checks.append(['admin/growth',width]);page.screenshot(path=str(OUT/('growth-'+str(width)+'.png')),full_page=True)
            record('Painel de crescimento reflete a conta e a publicação de teste')
            page.get_by_role('button',name='Convites',exact=True).click();page.get_by_role('button',name='Revogar',exact=True).click()
            page.locator('#action-reason').fill('Encerrar convite usado no teste local.')
            page.get_by_role('button',name='Confirmar ação',exact=True).click()
            expect(page.get_by_text('Revogado',exact=True)).to_be_visible();record('Revogação de convite pela interface')
            assert not errors,errors
            record('Nenhum erro JavaScript não tratado')
            guest_context.close();context.close();browser.close()
        (OUT/'browser-report.json').write_text(json.dumps({'checks':checks,'width_checks':width_checks,'errors':errors,'method':'Chromium headless com HTML/CSS/JS reais inseridos e ponte HTTP para Uvicorn/SQLite temporário. Navegação direta bloqueada pelo ambiente; código do convite inserido em memória, cookies mantidos no cliente da ponte. Não valida CSP no navegador, HTTPS, navegação direta de convite, cookies reais, SMTP ou hospedagem.'},ensure_ascii=False,indent=2))
    finally:
        proc.terminate()
        try:proc.wait(timeout=8)
        except subprocess.TimeoutExpired:proc.kill()
        log.close()
