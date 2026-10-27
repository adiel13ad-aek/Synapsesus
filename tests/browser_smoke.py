"""UI tests using real Chromium and a real local API through a Python transport bridge.
Managed-browser policy blocks navigation to localhost here. HTML/CSS/JS are inlined;
fetch and public images are bridged to the actual HTTP server, not mocked application logic.
Not a native Android/iOS/Windows install test. Run against a disposable empty database.
"""
from pathlib import Path
import os,time,json
import httpx
from PIL import Image
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
BASE=os.getenv('SYNAPSE_TEST_URL','http://127.0.0.1:8776')
checks=[];errors=[]
def record(s):checks.append(s);print('PASS',s,flush=True)
def page_for(browser,mode='demo',width=1440,client=None):
    page=browser.new_page(viewport={'width':width,'height':1000})
    page.on('pageerror',lambda error:errors.append(str(error)))
    html=(ROOT/'Synapse-Discovery-demo.html').read_text().replace('data-mode="demo"',f'data-mode="{mode}"')
    if client:
        def transport(url,options):
            r=client.request(options.get('method','GET'),BASE+url,headers=options.get('headers',{}),content=options.get('body'))
            return {'body':r.text,'status':r.status_code}
        page.expose_function('__transport',transport)
        page.evaluate('''() => {window.fetch=async(url,options={})=>{const r=await window.__transport(String(url),options);return new Response(r.body,{status:r.status,headers:{'Content-Type':'application/json'}})}}''')
        html=html.replace('<head>','<head><base href="https://synapse-test.invalid/">')
        def asset(route):
            r=client.get(BASE+route.request.url.split('synapse-test.invalid',1)[1])
            route.fulfill(status=r.status_code,body=r.content,headers={'Content-Type':r.headers.get('content-type','application/octet-stream')})
        page.route('https://synapse-test.invalid/**',asset)
    page.set_content(html,wait_until='domcontentloaded')
    page.wait_for_selector('.hero')
    return page

def go(page,name):
    if page.viewport_size['width']<=580:
        # Messages/settings are accessible through the header/profile on mobile.
        if name=='messages':page.locator('.topbar [data-go="messages"]').click();return
        if name=='settings':
            page.locator('.bottom-nav [data-go="profile"]').click()
            page.locator('.profile-hero [data-go="settings"]').click();return
        page.locator(f'.bottom-nav [data-go="{name}"]').click()
    else:page.locator(f'.sidebar [data-go="{name}"]').first.click()

def submit(page,form):page.locator(f'[data-form="{form}"] [type="submit"]').click()
def register_ui(page,handle):
    page.locator('[data-action="auth"]').first.click()
    form=page.locator('[data-form="auth"]')
    form.locator('[name="name"]').fill('Explorador de teste')
    form.locator('[name="handle"]').fill(handle)
    form.locator('[name="password"]').fill('browser-password-2026')
    submit(page,'auth');expect(page.locator('#dialog')).not_to_be_visible()

def no_overflow(page):return page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
    demo=page_for(browser)
    demo.locator('[data-action="new-post"]').first.click()
    demo.locator('[data-form="post"] [name="body"]').fill('Descoberta da demo #teste')
    submit(demo,'post');expect(demo.locator('.post').first).to_contain_text('Descoberta da demo')
    demo.locator('.post').first.locator('[data-action="like"]').click()
    expect(demo.locator('.post').first.locator('[data-action="like"]')).to_have_attribute('aria-pressed','true')
    demo.locator('.post').first.locator('[data-action="save-post"]').click()
    demo.locator('.post').first.locator('[data-action="comments"]').click()
    demo.locator('.post').first.locator('[name="body"]').fill('Um comentário local.')
    submit(demo,'comment');expect(demo.locator('.post').first).to_contain_text('Um comentário local.')
    record('Demo: publicar, curtir, salvar e comentar')
    go(demo,'explore');demo.locator('#explore-query').fill('design');demo.locator('.search-large button').click()
    expect(demo.locator('.main')).to_contain_text('referências')
    demo.locator('[data-action="scope"][data-id="web"]').click()
    expect(demo.locator('.main')).to_contain_text('Não há resultados inventados')
    link=demo.locator('.external-options a').first
    expect(link).to_have_attribute('href','https://www.google.com/search?q=design')
    expect(link).to_have_attribute('rel','noopener noreferrer')
    record('Demo: busca local e atalhos externos sem resultados falsos')
    demo.locator('#explore-query').fill('https://example.com');demo.locator('.search-large button').click()
    demo.locator('.result [data-action="collect"]').first.click()
    demo.locator('[data-form="collect"] [name="title"]').fill('Fonte para meu projeto')
    demo.locator('[data-form="collect"] [name="collection"]').fill('Projeto')
    demo.locator('[data-form="collect"] [name="note"]').fill('Nota só minha')
    submit(demo,'collect');expect(demo.locator('#dialog')).not_to_be_visible()
    go(demo,'collections');expect(demo.locator('.main')).to_contain_text('Fonte para meu projeto')
    demo.locator('[data-action="share-link"]').first.click()
    demo.locator('[data-form="post"] [name="body"]').fill('Minha descoberta compartilhada.')
    submit(demo,'post');expect(demo.locator('.post').first).to_contain_text('Minha descoberta compartilhada.')
    expect(demo.locator('.post').first.locator('.link-card')).to_have_attribute('href','https://example.com/')
    record('Demo: endereço → coleção privada → publicação com link')
    # Real server through transport bridge.
    client=httpx.Client(timeout=20)
    real=page_for(browser,mode='server',client=client)
    handle='browser'+str(int(time.time()))
    register_ui(real,handle)
    record('Servidor: cadastro e sessão pela interface')
    image=OUT/'upload.png';Image.new('RGB',(480,320),(70,110,90)).save(image)
    real.locator('[data-action="new-post"]').first.click()
    form=real.locator('[data-form="post"]')
    form.locator('[name="body"]').fill('Foto real de teste com link de pesquisa.')
    form.locator('[name="link_url"]').fill('https://example.com/fonte')
    form.locator('[name="link_title"]').fill('Uma fonte original')
    form.locator('[name="image_alt"]').fill('Retângulo de teste')
    form.locator('#image-file').set_input_files(image)
    expect(real.locator('.preview')).to_be_visible()
    submit(real,'post');expect(real.locator('#dialog')).not_to_be_visible()
    expect(real.locator('.post').first).to_contain_text('Foto real de teste')
    img=real.locator('.post').first.locator('.post-media')
    expect(img).to_be_visible();assert img.evaluate('(img)=>img.complete && img.naturalWidth===480')
    record('Servidor: upload de imagem, reencodificação e exibição de post com fonte')
    real.locator('.post').first.locator('[data-action="like"]').click()
    expect(real.locator('.post').first.locator('[data-action="like"]')).to_have_attribute('aria-pressed','true')
    real.locator('.post').first.locator('[data-action="comments"]').click()
    real.locator('.post').first.locator('[name="body"]').fill('Comentário persistido no servidor.')
    submit(real,'comment');expect(real.locator('.post').first).to_contain_text('Comentário persistido')
    record('Servidor: curtir e comentar pela interface')
    real.locator('.post').first.locator('[data-action="collect"]').click()
    real.locator('[data-form="collect"] [name="collection"]').fill('Estudos')
    real.locator('[data-form="collect"] [name="note"]').fill('Nota privada persistente')
    submit(real,'collect');expect(real.locator('#dialog')).not_to_be_visible()
    go(real,'collections');expect(real.locator('.main')).to_contain_text('Nota privada persistente')
    state=client.get(BASE+'/api/state').json()
    assert state['links'][0]['collection']=='Estudos'
    record('Servidor: coleções persistidas no banco')
    # A second account sends a message; read/send back from the UI.
    other=httpx.Client(headers={'X-Synapse-Client':'web-v03','Content-Type':'application/json'})
    r=other.post(BASE+'/api/auth/register',json={'name':'Outra pessoa','handle':'other'+str(int(time.time())),'password':'browser-password-2026'})
    assert r.status_code==200,r.text
    other.headers['X-CSRF-Token']=r.json()['csrf']
    other_id=other.get(BASE+'/api/state').json()['me']['id']
    me_id=state['me']['id']
    assert other.post(BASE+'/api/messages/'+me_id,json={'body':'Olá, duas contas reais!'}).status_code==200
    go(real,'feed');real.locator('[data-action="refresh"]').click()
    go(real,'messages');real.locator('#chat-target').select_option(other_id)
    expect(real.locator('#chat-messages')).to_contain_text('Olá, duas contas reais!')
    real.locator('[data-form="message"] [name="body"]').fill('Resposta pelo navegador.')
    submit(real,'message');expect(real.locator('#chat-messages')).to_contain_text('Resposta pelo navegador.')
    record('Servidor: mensagens privadas entre duas contas')
    go(real,'profile');real.locator('[data-action="edit-profile"]').click()
    real.locator('[data-form="profile"] [name="name"]').fill('Explorador atualizado')
    submit(real,'profile');expect(real.locator('.profile-hero h2')).to_have_text('Explorador atualizado')
    record('Servidor: edição de perfil')
    go(real,'feed');real.locator('[data-action="new-post"]').first.click()
    real.locator('[data-form="post"] [name="body"]').fill('<img src=x onerror="window.__xss=1"> <script>window.__xss=2</script>')
    submit(real,'post');expect(real.locator('#dialog')).not_to_be_visible()
    assert real.evaluate('window.__xss') is None
    expect(real.locator('.post').first.locator('.post-body')).to_contain_text('<script>')
    record('Servidor: conteúdo HTML malicioso exibido como texto')
    # Reconnect with same HTTP cookie jar; state must survive new UI instance.
    again=page_for(browser,mode='server',client=client)
    expect(again.locator('.account-button')).to_contain_text('Explorador atualizado')
    go(again,'collections');expect(again.locator('.main')).to_contain_text('Nota privada persistente')
    record('Servidor: sessão e dados preservados em nova instância da interface')
    for width in (320,390,768,1440):
        screen=page_for(browser,width=width)
        for view in ('feed','explore','collections','profile','messages'):
            go(screen,view)
            assert no_overflow(screen),f'Overflow {width}px {view}'
        record(f'Layout: cinco telas sem rolagem horizontal em {width}px')
        if width in (390,1440):
            go(screen,'feed');screen.evaluate("document.getElementById('toast').style.display='none'")
            screen.screenshot(path=str(OUT/('preview-mobile.png' if width==390 else 'preview-desktop.png')),full_page=False)
            if width==1440:
                go(screen,'explore');screen.screenshot(path=str(OUT/'preview-explore.png'),full_page=False)
        screen.close()
    assert not errors,errors
    record('JavaScript: nenhuma exceção não tratada nas telas testadas')
    browser.close();client.close();other.close()
(OUT/'browser-results.json').write_text(json.dumps({'checks':checks,'count':len(checks),'errors':errors,'method':'Chromium real + bridge HTTP; localhost navigation blocked by managed policy','external_providers':'not live-tested'},ensure_ascii=False,indent=2))
print('TOTAL',len(checks))
