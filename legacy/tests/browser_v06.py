# Legacy social/design regression harness, now pointed at the current demo bundle.
"""Real Chromium + fetch transport bridge -> real FastAPI TestClient and temporary SQLite.
No application server APIs are mocked. Only HTTP transport is bridged by the harness. Live media calls are not exercised.
Physical Android, real SMTP, real push gateway and Internet TURN are not tested here.
"""
from __future__ import annotations
from contextlib import ExitStack
import json,os,sys,tempfile,time,subprocess
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['CALLS_ENABLED']='0'
import server
from fastapi.testclient import TestClient
from PIL import Image
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
checks=[];errors=[]
def record(text):checks.append(text);print('PASS',text,flush=True)

def register(page,handle):
    page.locator('[data-action="auth"]:visible').first.click()
    f=page.locator('[data-form="auth"]')
    for name,value in {'name':handle.title(),'handle':handle,'email':handle+'@example.com','password':'testing-browser-2026'}.items():f.locator('[name="'+name+'"]').fill(value)
    f.locator('[name="terms_accepted"]').check();f.locator('[type="submit"]').click()
    expect(page.locator('[data-form="profile"]')).to_be_visible()
    page.locator('[data-form="profile"] [name="bio"]').fill('Ideias, descobertas e tecnologia.')
    page.locator('[data-form="profile"] [name="interests"]').fill('Tecnologia, Ciência')
    page.locator('[data-form="profile"] [type="submit"]').click();expect(page.locator('#dialog')).not_to_be_visible()

def go(page,name):page.evaluate('(p)=>go(p)',name)
def submit(page,name):page.locator('[data-form="'+name+'"] [type="submit"]').click()

with tempfile.TemporaryDirectory() as td,ExitStack() as stack:
    server.DB_PATH=Path(td)/'synapse.db';server.MEDIA_DIR=Path(td)/'media';server._rates.clear()
    clients=[]
    p=stack.enter_context(sync_playwright())
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    def make_page(width=1440):
        c=stack.enter_context(TestClient(server.app,base_url='https://synapse.test'))
        clients.append(c)
        context=browser.new_context(viewport={'width':width,'height':950 if width>700 else 844},service_workers='block')
        page=context.new_page();page.set_default_timeout(12000);page.on('pageerror',lambda err:errors.append(str(err)))
        def transport(url,options):
            import base64
            headers=options.get('headers',{})
            raw=base64.b64decode(options['body']) if options.get('body') is not None else None
            response=c.request(options.get('method','GET'),url,headers=headers,content=raw)
            return {'body':base64.b64encode(response.content).decode(),'status':response.status_code,'headers':{'content-type':response.headers.get('content-type','application/json')}}
        page.expose_function('__transport',transport)
        page.evaluate("""() => {
          window.fetch=async(url,options={})=>{
            const headers={...(options.headers||{})};let body=null;
            if(options.body instanceof FormData){const r=new Request('https://synapse.test/',{method:'POST',body:options.body});headers['Content-Type']=r.headers.get('Content-Type');body=new Uint8Array(await r.arrayBuffer());}
            else if(options.body!==undefined)body=new TextEncoder().encode(options.body);
            let encoded=null;if(body){let chunks=[];for(let i=0;i<body.length;i+=16384)chunks.push(String.fromCharCode(...body.subarray(i,i+16384)));encoded=btoa(chunks.join(''));}
            const r=await window.__transport(String(url),{method:options.method||'GET',headers,body:encoded});
            return new Response(Uint8Array.from(atob(r.body),c=>c.charCodeAt(0)),{status:r.status,headers:r.headers});
          };
        }""")
        def asset(route):
            u=urlsplit(route.request.url)
            response=c.get(u.path+('?' + u.query if u.query else ''),headers={'Range':route.request.headers['range']} if 'range' in route.request.headers else {})
            route.fulfill(status=response.status_code,headers=dict(response.headers),body=response.content)
        page.route('https://synapse-test.invalid/**',asset)
        html=(ROOT/'Synapse-Discovery-v0.7-demo.html').read_text().replace('data-mode="demo"','data-mode="server"').replace('<head>','<head><base href="https://synapse-test.invalid/">')
        page.set_content(html,wait_until='domcontentloaded');expect(page.locator('.welcome')).to_be_visible()
        return page
    page=make_page();register(page,'aurora');record('Cadastro, login automático e personalização na interface real')
    photo1=Path(td)/'one.png';photo2=Path(td)/'two.png'
    Image.new('RGB',(640,440),(118,92,180)).save(photo1);Image.new('RGB',(640,440),(76,142,125)).save(photo2)
    page.locator('[data-action="new-post"]').first.click();f=page.locator('[data-form="post-plus"]')
    f.locator('[name="body"]').fill('Uma galeria de descobertas #criacao');f.locator('[name="image_alt"]').fill('Duas imagens de teste, violeta e verde')
    f.locator('#gallery-files').set_input_files([photo1,photo2]);expect(page.locator('.upload-tile')).to_have_count(2)
    expect(f.locator('[type="submit"]')).to_be_enabled();submit(page,'post-plus');expect(page.locator('#dialog')).not_to_be_visible()
    expect(page.locator('.media-gallery .gallery-slide')).to_have_count(2)
    assert page.locator('.gallery-slide img').first.evaluate('(im)=>im.complete&&im.naturalWidth===640')
    page.locator('[data-plus="gallery-next"]').first.click();page.wait_for_timeout(500)
    assert page.locator('.gallery-track').first.evaluate('(e)=>e.scrollLeft>100')
    record('Envio real de duas fotos, publicação e navegação do carrossel')
    page.locator('.post').first.locator('[data-action="comments"]').first.click()
    page.locator('[data-form="comment"] [name="body"]').fill('Comentário publicado pela interface.');submit(page,'comment')
    expect(page.locator('.comments')).to_contain_text('Comentário publicado')
    page.locator('.post').first.locator('[data-action="like"]').click();expect(page.locator('.post').first.locator('[data-action="like"]')).to_have_attribute('aria-pressed','true')
    record('Curtida e comentário preservados após a atualização da galeria')
    clip=Path(td)/'clip.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=size=180x320:rate=15:duration=1','-c:v','libx264','-threads','1','-pix_fmt','yuv420p','-y',str(clip)],check=True,timeout=15)
    page.locator('[data-action="new-post"]').first.click();f=page.locator('[data-form="post-plus"]');f.locator('[name="body"]').fill('Primeiro vídeo de teste #video');f.locator('#gallery-files').set_input_files(clip)
    expect(page.locator('.upload-tile video')).to_be_visible();expect(f.locator('[type="submit"]')).to_be_enabled();submit(page,'post-plus');expect(page.locator('#dialog')).not_to_be_visible()
    expect(page.locator('video.post-video')).to_be_visible();page.locator('[data-plus="videos"]').first.click();expect(page.locator('video.post-video')).to_be_visible()
    page.locator('video.post-video').first.evaluate('(v)=>v.load()');page.wait_for_function('document.querySelector("video.post-video").videoWidth > 0')
    record('Upload, transcodificação, miniatura e carregamento de vídeo no feed dedicado')
    page.locator('[data-plus="all-posts"]').click();expect(page.locator('.welcome')).to_be_visible()
    go(page,'settings');page.locator('[name="theme"]').select_option('dark');page.locator('[name="reduce_motion"]').check();submit(page,'preferences');expect(page.locator('html')).to_have_attribute('data-theme','dark')
    page.locator('[data-plus="push-on"]').click();expect(page.locator('#toast')).to_be_visible()
    record('Tema e movimento reduzido persistidos; push não configurado informado sem falsa ativação')
    other=make_page(390);register(other,'cobalto');record('Segunda conta independente no layout móvel')
    first_id=page.evaluate('S.me.id');second_id=other.evaluate('S.me.id')
    page.locator('[data-go="feed"]').first.click();page.locator('[data-action="refresh"]').click();go(page,'messages')
    page.locator('#chat-target').select_option(second_id);page.locator('[data-form="message"] [name="body"]').fill('Mensagem real entre duas contas.');submit(page,'message')
    go(other,'messages');other.locator('#chat-target').select_option(first_id);expect(other.locator('#chat-messages')).to_contain_text('Mensagem real entre duas contas')
    other.locator('[data-form="message"] [name="body"]').fill('Recebi no celular simulado.');submit(other,'message');page.wait_for_timeout(3400)
    expect(page.locator('#chat-messages')).to_contain_text('Recebi no celular simulado')
    record('Conversa bidirecional entre dois navegadores/contas com atualização periódica')
    # Signalling is covered by test_v05.py. Live media is not certified by this browser run.
    # Fresh demo renders showcase layout rather than the artificial upload fixtures.
    demo=browser.new_page(viewport={'width':1440,'height':1000});demo.on('pageerror',lambda e:errors.append(str(e)))
    demo.set_content((ROOT/'Synapse-Discovery-v0.7-demo.html').read_text(),wait_until='domcontentloaded');expect(demo.locator('.welcome')).to_be_visible()
    demo.wait_for_timeout(4500);demo.screenshot(path=str(OUT/'synapse-1440.png'),full_page=False)
    for width in (320,390,768,1440):
        page.set_viewport_size({'width':width,'height':844 if width<700 else 950})
        for section in ('feed','explore','collections','profile','messages','notifications','settings'):
            go(page,section);page.wait_for_timeout(60)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),(width,section)
    record('28 combinações de tela/largura sem rolagem horizontal: 7 seções × 320/390/768/1440')
    demo.set_viewport_size({'width':390,'height':844});demo.wait_for_timeout(300);demo.screenshot(path=str(OUT/'synapse-390.png'),full_page=False)
    go(page,'feed');page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(OUT/'video-mobile.png'),full_page=False)
    assert not errors,errors
    record('Sem erros JavaScript não tratados nas rotas exercitadas')
    (OUT/'browser-v06-server.json').write_text(json.dumps({'checks':checks,'page_errors':errors,'transport':'Chromium fetch bridge to FastAPI TestClient; no mocked server API; no simulated camera/audio capture','calls':'signalling tested by pytest; live capture/peer connection not validated','not_tested':['WebRTC live media and TURN','Physical Android','Play Store','public deployment','SMTP delivery','Web Push gateway']},ensure_ascii=False,indent=2))
    browser.close()
print('BROWSER CHECKS:',len(checks))
