"""Build a self-contained HTML demo; never include secrets or server data."""
from pathlib import Path
root=Path(__file__).resolve().parent
html=(root/'web/index.html').read_text().replace('data-mode="server"','data-mode="demo"')
html=html.replace('<link rel="icon" href="/icon.svg" type="image/svg+xml">','').replace('<link rel="manifest" href="/manifest.webmanifest">','')
html=html.replace('<link rel="stylesheet" href="/style.css">','<style>'+(root/'web/style.css').read_text()+'</style>')
for name in ('demo-adapter.js','app.js'):
    js=(root/'web'/name).read_text().replace('</script','<\\/script')
    html=html.replace(f'<script src="/{name}" defer></script>','<script>'+js+'</script>')
(root/'Synapse-Discovery-demo.html').write_text(html,encoding='utf-8')
print('Created',root/'Synapse-Discovery-demo.html')
