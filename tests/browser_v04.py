"""Real Chromium UI + httpx transport to a real server (no mocked application endpoints).
This bridge is used because the managed browser blocks localhost navigation.
Not native device, SMTP, HTTPS deployment, or search-provider certification.
"""
from pathlib import Path
import json,time,os,httpx
from PIL import Image
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
BASE='http://127.0.0.1:8777';checks=[];errors=[]
def record(text):checks.append(text);print('PASS',text,flush=True)
def page_for(browser,mode='server',client=None,width=1440):
    page=browser.new_page(viewport={'width':width,'height':950 if width>700 else 844})
    page.set_default_timeout(8000)
    page.on('pageerror',lambda e:errors.append(str(e)))
    html=(ROOT/'Synapse-Discovery-v0.4-demo.html').read_text().replace('data-mode="demo"',f'data-mode="{mode}"')
    if client:
        def transport(url,options):
            r=client.request(options.get('method','GET'),BASE+url,headers=options.get('headers',{}),content=options.get('body'))
            return {'body':r.text,'status':r.status_code}
        page.expose_function('__transport',transport)
        page.evaluate("""() => {window.fetch=async(url,options={})=>{const r=await window.__transport(String(url),options);return new Response(r.body,{status:r.status,headers:{'Content-Type':'application/json'}})}}""")
        html=html.replace('<head>','<head><base href="https://synapse-test.invalid/">')
        def asset(route):
            r=client.get(BASE+route.request.url.split('synapse-test.invalid',1)[1])
            route.fulfill(status=r.status_code,body=r.content,headers={'Content-Type':r.headers.get('content-type','application/octet-stream')})
        page.route('https://synapse-test.invalid/**',asset)
    page.set_content(html,wait_until='domcontentloaded');page.wait_for_selector('.welcome');page.wait_for_timeout(400)
    return page

def go(page,name):
    if page.viewport_size['width']<=700:
        if name in ['messages','notifications']:page.locator(f'.topbar [data-go="{name}"]').click();return
        if name=='settings':
            page.locator('.bottom-nav [data-go="profile"]').click()
            page.locator('.profile-toolbar [data-go="settings"]').click();return
        page.locator(f'.bottom-nav [data-go="{name}"]').click()
    else:page.locator(f'.sidebar [data-go="{name}"]').first.click()
def submit(page,kind):page.locator(f'[data-form="{kind}"] [type="submit"]').click()
def no_overflow(page):return page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    client=httpx.Client(timeout=20);page=page_for(browser,client=client)
    handle='ui'+str(int(time.time()))
    page.locator('[data-action="auth"]').first.click()
    form=page.locator('[data-form="auth"]')
    form.locator('[name="name"]').fill('Pessoa Criativa')
    form.locator('[name="handle"]').fill(handle)
    form.locator('[name="email"]').fill(handle+'@example.com')
    form.locator('[name="password"]').fill('ui-password-2026')
    form.locator('[name="terms_accepted"]').check()
    submit(page,'auth')
    expect(page.locator('[data-form="profile"]')).to_be_visible()
    record('Cadastro com e-mail e aceite de termos abre personalização')
    image=OUT/'upload-test.png';Image.new('RGB',(640,400),(117,91,181)).save(image)
    profile=page.locator('[data-form="profile"]')
    profile.locator('[name="bio"]').fill('Fotografia, ciência e referências que conectam.')
    profile.locator('[name="website"]').fill('https://example.com')
    profile.locator('[name="interests"]').fill('Ciência, Fotografia, Design')
    profile.locator('[data-upload="avatar"]').set_input_files(image)
    expect(page.locator('#avatar-preview img')).to_be_visible()
    profile.locator('[data-upload="cover"]').set_input_files(image)
    expect(page.locator('#cover-preview img')).to_be_visible()
    submit(page,'profile');expect(page.locator('#dialog')).not_to_be_visible()
    go(page,'profile');expect(page.locator('.profile-bio')).to_contain_text('Fotografia, ciência')
    assert page.locator('.profile-cover img').evaluate('(i)=>i.complete&&i.naturalWidth===640')
    record('Foto, capa, bio, site e interesses salvos no perfil real')
    page.locator('[data-action="new-post"]').first.click()
    form=page.locator('[data-form="post"]')
    form.locator('[name="body"]').fill('Publicação real com imagem #fotografia')
    form.locator('[name="link_url"]').fill('https://example.com/referencia')
    form.locator('[name="link_title"]').fill('Fonte original')
    form.locator('[name="image_alt"]').fill('Imagem de teste violeta')
    form.locator('#image-file').set_input_files(image);expect(page.locator('#image-preview img')).to_be_visible()
    submit(page,'post');expect(page.locator('#dialog')).not_to_be_visible()
    expect(page.locator('.post').first).to_contain_text('Publicação real')
    assert page.locator('.post-media').first.evaluate('(i)=>i.complete&&i.naturalWidth===640')
    record('Publicação de imagem e link real com legenda acessível')
    page.locator('.post').first.locator('[data-action="like"]').click()
    expect(page.locator('.post').first.locator('[data-action="like"]')).to_have_attribute('aria-pressed','true')
    page.locator('.post').first.locator('[data-action="save-post"]').click()
    page.locator('.post').first.locator('[data-action="comments"]').first.click()
    page.locator('.post').first.locator('[name="body"]').fill('Um comentário de verdade.')
    submit(page,'comment');expect(page.locator('.comments')).to_contain_text('Um comentário de verdade.')
    record('Curtida, salvar publicação e comentário persistidos')
    page.locator('.post').first.locator('[data-action="post-menu"]').click()
    page.locator('[data-action="edit-post"]').click()
    page.locator('[data-form="edit-post"] [name="body"]').fill('Legenda editada #fotografia')
    submit(page,'edit-post');expect(page.locator('#dialog')).not_to_be_visible()
    expect(page.locator('.post').first).to_contain_text('Legenda editada')
    record('Edição da própria legenda pela interface')
    page.locator('.post').first.locator('[data-action="collect"]').click()
    page.locator('[data-form="collect"] [name="collection"]').fill('Projeto criativo')
    page.locator('[data-form="collect"] [name="note"]').fill('Nota privada — não publicar.')
    submit(page,'collect');expect(page.locator('#dialog')).not_to_be_visible()
    go(page,'collections');expect(page.locator('.main')).to_contain_text('Nota privada — não publicar.')
    page.locator('.main [data-action="share-link"]').first.click()
    assert page.locator('[data-form="post"] [name="body"]').input_value()==''
    page.locator('[data-action="close"]').first.click()
    record('Coleção privada e compartilhamento sem vazamento da anotação')
    go(page,'feed');page.locator('[data-action="new-story"]').click()
    page.locator('[data-form="story"] [name="body"]').fill('Um momento compartilhado por 24 horas.')
    submit(page,'story');expect(page.locator('#dialog')).not_to_be_visible()
    page.locator('[data-action="story"]').first.click()
    expect(page.locator('.story-view')).to_contain_text('24 horas')
    page.locator('[data-action="pause-story"]').click();expect(page.locator('.story-view')).to_have_class('story-view violet story-paused')
    page.locator('[data-action="close"]').first.click()
    record('Criar, abrir e pausar story real')
    go(page,'settings')
    page.locator('[name="theme"]').select_option('dark');page.locator('[name="accent"]').select_option('mint')
    page.locator('[name="reduce_motion"]').check();submit(page,'preferences')
    expect(page.locator('html')).to_have_attribute('data-theme','dark')
    expect(page.locator('html')).to_have_attribute('data-accent','mint')
    expect(page.locator('html')).to_have_attribute('data-motion','reduced')
    record('Tema escuro, cor e movimento reduzido com persistência na conta')
    state=client.get(BASE+'/api/state').json();me_id=state['me']['id']
    other=httpx.Client(headers={'X-Synapse-Client':'web-v04','Content-Type':'application/json'},timeout=20)
    r=other.post(BASE+'/api/auth/register',json={'name':'Pessoa de teste','handle':handle+'b','email':handle+'b@example.com','password':'ui-password-2026','terms_accepted':True})
    assert r.status_code==200,r.text;other.headers['X-CSRF-Token']=r.json()['csrf']
    oid=other.get(BASE+'/api/state').json()['me']['id']
    assert other.post(BASE+'/api/messages/'+me_id,json={'body':'Mensagem entre duas contas reais.'}).status_code==200
    assert other.post(BASE+'/api/actors/'+me_id+'/follow',json={}).status_code==200
    go(page,'feed');page.locator('[data-action="refresh"]').click()
    expect(page.locator('.sidebar .badge')).to_be_visible()
    go(page,'notifications');expect(page.locator('.main')).to_contain_text('enviou uma mensagem')
    page.locator('[data-action="read-notifications"]').click()
    expect(page.locator('.notification.unread')).to_have_count(0)
    record('Notificações reais de outra conta e marcação como lidas')
    go(page,'messages');page.locator('#chat-target').select_option(oid)
    expect(page.locator('#chat-messages')).to_contain_text('Mensagem entre duas contas reais.')
    page.locator('[data-form="message"] [name="body"]').fill('Resposta escrita na interface.')
    submit(page,'message');expect(page.locator('#chat-messages')).to_contain_text('Resposta escrita na interface.')
    record('Mensagens bidirecionais entre contas reais')
    go(page,'explore');page.locator('#explore-query').fill('fotografia');submit(page,'search')
    expect(page.locator('.main')).to_contain_text('Legenda editada')
    page.locator('[data-action="scope"][data-id="web"]').click()
    expect(page.locator('.external-options a').first).to_have_attribute('href','https://www.google.com/search?q=fotografia')
    expect(page.locator('.main')).to_contain_text('Nenhum resultado é inventado')
    record('Busca social real e atalhos web identificados sem resultados fictícios')
    go(page,'feed');page.locator('[data-action="new-post"]').first.click()
    page.locator('[data-form="post"] [name="body"]').fill('<img src=x onerror="window.__xss=1"><script>window.__xss=2</script>')
    submit(page,'post');expect(page.locator('#dialog')).not_to_be_visible()
    assert page.evaluate('window.__xss') is None
    expect(page.locator('.post').first.locator('.post-body')).to_contain_text('<script>')
    record('HTML inserido em publicações aparece como texto sem executar')
    page2=page_for(browser,client=client)
    expect(page2.locator('html')).to_have_attribute('data-theme','dark')
    go(page2,'collections');expect(page2.locator('.main')).to_contain_text('Nota privada — não publicar.')
    record('Sessão, preferências e coleções preservadas ao reabrir a interface')
    # Screenshots use an untouched demo rather than real/test user data.
    for width in (320,390,768,1440):
        demo=page_for(browser,mode='demo',width=width)
        for name in ('feed','explore','collections','profile','messages','notifications','settings'):
            go(demo,name);demo.wait_for_timeout(100)
            assert no_overflow(demo),f'Overflow {width} {name}'
        record(f'Sete telas sem rolagem horizontal em {width}px')
        if width in (390,1440):
            go(demo,'feed');demo.wait_for_timeout(450);demo.evaluate("document.getElementById('toast').style.visibility='hidden'")
            demo.screenshot(path=str(OUT/('Synapse-v04-mobile.png' if width==390 else 'Synapse-v04-desktop.png')))
            if width==1440:
                go(demo,'explore');demo.wait_for_timeout(450);demo.screenshot(path=str(OUT/'Synapse-v04-explorar.png'))
                go(demo,'settings');demo.locator('[name="theme"]').select_option('dark');submit(demo,'preferences')
                go(demo,'feed');demo.wait_for_timeout(450);demo.evaluate("document.getElementById('toast').style.visibility='hidden'")
                demo.screenshot(path=str(OUT/'Synapse-v04-dark.png'))
        demo.close()
    # Demo mutations are explicitly local.
    demo=page_for(browser,mode='demo',width=390)
    demo.locator('.bottom-nav [data-action="new-post"]').click()
    demo.locator('[data-form="post"] [name="body"]').fill('Uma descoberta apenas local.')
    submit(demo,'post');expect(demo.locator('#dialog')).not_to_be_visible()
    expect(demo.locator('.post').first).to_contain_text('Uma descoberta apenas local.')
    demo.locator('.post').first.locator('[data-action="like"]').click()
    expect(demo.locator('.post').first.locator('[data-action="like"]')).to_have_attribute('aria-pressed','true')
    record('Demonstração móvel: publicar e curtir localmente')
    assert not errors,errors
    record('Nenhuma exceção JavaScript não tratada nos fluxos exercitados')
    browser.close();client.close();other.close()
(OUT/'browser-results-v04.json').write_text(json.dumps({'count':len(checks),'checks':checks,'errors':errors,'method':'Chromium with real HTTP API bridge, not native device testing'},ensure_ascii=False,indent=2))
print('TOTAL',len(checks))
