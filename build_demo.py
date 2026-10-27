"""Self-contained demo. Never include keys, database contents or mail files."""
from pathlib import Path
root=Path(__file__).resolve().parent
html=(root/'web/index.html').read_text().replace('data-mode="server"','data-mode="demo"')
html=html.replace('<link rel="icon" href="/icon.svg" type="image/svg+xml">','').replace('<link rel="manifest" href="/manifest.webmanifest">','')
html=html.replace('<link rel="stylesheet" href="/style.css">','<style>'+(root/'web/style.css').read_text()+'</style>')
scripts=''
for name in ('demo-adapter.js','app.js'):
    js=(root/'web'/name).read_text().replace('</script','<\\/script')
    html=html.replace(f'<script src="/{name}" defer></script>','')
    scripts+='<script>'+js+'</script>'
# Inline scripts must run after DOM construction (inline defer has no effect).
html=html.replace('</body>',scripts+'</body>')
output=root/'Synapse-Discovery-v0.4-demo.html';output.write_text(html,encoding='utf-8')
(root/'android/app/src/main/assets/index.html').write_text(html,encoding='utf-8')
print('Created self-contained demo and Android asset:',output)
