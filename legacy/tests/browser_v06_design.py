# Legacy social/design regression harness, now pointed at the current demo bundle.
"""Visual/interaction regression of the self-contained v0.6 demo.
Chromium's container navigation/storage restrictions require set_content.
No fake server calls; local persistence is not asserted in this harness.
"""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
checks=[];errors=[]
def record(label):checks.append(label);print('PASS',label,flush=True)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
 page=browser.new_page(viewport={'width':1440,'height':1000})
 page.set_default_timeout(7000);page.on('pageerror',lambda e:errors.append(str(e)))
 page.set_content((ROOT/'demos'/'Synapse-Discovery-v0.8-demo.html').read_text(),wait_until='load')
 expect(page.locator('.post')).to_have_count(6)
 assert page.locator('.post-media img').count()==0 # image itself carries post-media class
 assert page.locator('img.post-media').first.evaluate('(e)=>e.complete && e.naturalWidth>0')
 assert page.locator('.image-caption').first.evaluate('(e)=>e.getBoundingClientRect().height < 45')
 record('Demo opens with six labelled sample posts and intact local images')
 post='#post-discover-v06'
 page.locator(post+' [data-action="like"]').click();expect(page.locator(post+' [data-action="like"]')).to_have_attribute('aria-pressed','true')
 page.locator(post+' [data-action="save-post"]').click();page.locator('[data-action="feed-filter"][data-id="saved"]').click();expect(page.locator('.post')).to_have_count(1)
 page.locator('[data-action="feed-filter"][data-id="all"]').click();page.locator(post+' [data-action="comments"]').first.click()
 page.locator(post+' [data-form="comment"] input').fill('Teste do novo visual.')
 page.locator(post+' [data-form="comment"] button[type="submit"]').click();expect(page.locator(post+' .comments')).to_contain_text('Teste do novo visual.')
 record('Like, save/filter and comment work after the redesign')
 page.locator('.rail [data-action="follow"][data-id="lia"]').click();expect(page.locator('.rail [data-action="follow"][data-id="lia"]')).to_have_text('Seguindo')
 page.locator('[data-action="feed-filter"][data-id="following"]').click();expect(page.locator('.post')).to_have_count(2)
 page.locator('[data-action="feed-filter"][data-id="all"]').click()
 record('Following a sample profile updates the following feed')
 page.locator('[data-action="story"][data-id="lia"]').click();expect(page.locator('.story-view')).to_be_visible()
 assert page.locator('.story-view>img').evaluate('(im)=>im.complete&&im.naturalWidth>0')
 page.locator('[data-action="pause-story"]').click();expect(page.locator('.story-view')).to_have_class('story-view violet story-paused')
 page.locator('[data-action="next-story"]').click();page.locator('[data-action="close"]').click();expect(page.locator('#dialog')).not_to_be_visible()
 record('Stories open, display local images, pause, advance and close')
 page.locator('[data-action="new-post"]').first.click();form=page.locator('[data-form="post"]')
 form.locator('[name="body"]').fill('Publicação local criada na interface redesenhada. #teste')
 form.locator('[type="submit"]').click();expect(page.locator('.post').first).to_contain_text('Publicação local criada')
 page.evaluate("go('profile')");expect(page.locator('.discovery-card')).to_have_count(1)
 page.locator('[data-action="edit-profile"]').click();profile=page.locator('[data-form="profile"]')
 profile.locator('[name="bio"]').fill('Meu perfil com o novo visual.');profile.locator('[type="submit"]').click();expect(page.locator('.profile-bio')).to_have_text('Meu perfil com o novo visual.')
 record('Create post, profile gallery and profile editing preserve existing actions')
 page.locator('.rail [data-ui="web-search"]').click();expect(page.locator('[data-action="scope"][data-id="web"]')).to_have_attribute('aria-pressed','true')
 page.locator('#explore-query').fill('astronomia');page.locator('.search-large [type="submit"]').click()
 expect(page.locator('.external-options')).to_contain_text('Google');expect(page.locator('.notice')).to_contain_text('não possui um índice próprio')
 page.locator('[data-action="scope"][data-id="social"]').click();page.locator('#explore-query').fill('teste');page.locator('.search-large [type="submit"]').click();expect(page.locator('.post')).to_have_count(1)
 record('Integrated search switches between actual local results and clearly labelled external shortcuts')
 page.evaluate("go('feed')");page.locator('[data-ui="credits"]').first.click();expect(page.locator('.credits-list article')).to_have_count(5);page.locator('[data-action="close"]').click()
 page.locator('[data-ui="theme"]').click();expect(page.locator('html')).to_have_attribute('data-theme','dark')
 page.evaluate("go('settings')");page.locator('[name="reduce_motion"]').check();page.locator('[data-form="preferences"] [type="submit"]').click();expect(page.locator('html')).to_have_attribute('data-motion','reduced')
 assert page.locator('.btn').first.evaluate('(e)=>getComputedStyle(e).transitionDuration')=='0s'
 record('Image credits, dark mode and reduced-motion setting work')
 # 7 widths x 7 routes x 2 themes, no off-canvas page overflow.
 layout_count=0
 for theme in ('light','dark'):
  page.evaluate('(t)=>{S.preferences.theme=t;applyPreferences();draw()}',theme)
  for width in (320,390,430,768,1024,1440,1920):
   page.set_viewport_size({'width':width,'height':900 if width<701 else 1000})
   for route in ('feed','explore','profile','collections','messages','notifications','settings'):
    page.evaluate('(r)=>go(r)',route)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),(theme,width,route)
    layout_count+=1
 record(f'{layout_count} route/width/theme combinations without horizontal page overflow')
 page.set_viewport_size({'width':390,'height':900});page.evaluate("go('feed')")
 page.locator('.bottom-nav [data-plus="videos"]').click();expect(page.locator('.empty')).to_contain_text('Vídeos reais estão disponíveis')
 page.locator('.bottom-nav [data-go="explore"]').click();expect(page.locator('#explore-query')).to_be_visible()
 page.locator('.bottom-nav [data-action="new-post"]').click();expect(page.locator('[data-form="post"]')).to_be_visible();page.keyboard.press('Escape');expect(page.locator('#dialog')).not_to_be_visible()
 record('Mobile bottom navigation, video entry and modal keyboard dismissal work')
 assert not errors,errors
 record('No unhandled JavaScript errors in exercised routes')
 (OUT/'browser-v06-design.json').write_text(json.dumps({'checks':checks,'layout_combinations':layout_count,'page_errors':errors,'environment':'Chromium desktop engine, emulated viewport sizes, set_content; no physical phone or file-localStorage persistence assertion'},indent=2,ensure_ascii=False))
 browser.close()
print('DESIGN CHECKS:',len(checks))
