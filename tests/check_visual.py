from pathlib import Path
import json,sys,httpx
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1512,'height':1080})
    errs=[];page.on('pageerror',lambda e:errs.append(str(e)))
    page.set_content((ROOT/'Synapse-Discovery-v0.4-demo.html').read_text(),wait_until='domcontentloaded')
    page.wait_for_selector('.welcome');page.screenshot(path=str(OUT/'desktop-first.png'))
    page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(OUT/'mobile-first.png'))
    print('errors',errs)
    print('overflow',page.evaluate('document.documentElement.scrollWidth > innerWidth'))
    browser.close()
