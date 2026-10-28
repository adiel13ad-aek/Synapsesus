"""Regression coverage for the v0.6 presentation bundle and client protocol."""
from pathlib import Path
from test_api import client, register
ROOT=Path(__file__).resolve().parents[1]

def test_v06_client_registration_and_preferences(client):
    client.headers['X-Synapse-Client']='web-v06'
    register(client,'novo_visual')
    r=client.patch('/api/preferences',json={'theme':'dark','accent':'violet','reduce_motion':True,'dm_policy':'everyone'})
    assert r.status_code==200,r.text
    state=client.get('/api/state').json()
    assert state['preferences']['theme']=='dark'
    assert state['preferences']['reduce_motion']
    assert client.post('/api/posts',json={'body':'Interface v0.6 conectada ao servidor.'}).status_code==200

def test_v06_static_bundle_served_with_csp(client):
    for path in ('/','/style.css','/visual-assets.js','/app.js','/features.js','/icon.svg'):
        response=client.get(path)
        assert response.status_code==200,path
        assert "script-src 'self'" in response.headers['content-security-policy']
    assert '/visual-assets.js' in client.get('/').text
    assert 'synapse-ui-v09' in client.get('/sw.js').text

def test_demo_and_android_asset_are_identical():
    demo=(ROOT/'demos'/'Synapse-Discovery-v0.8-demo.html').read_bytes()
    assert demo==(ROOT/'android/app/src/main/assets/index.html').read_bytes()
    assert b'data-mode="demo"' in demo
    assert b'<script src=' not in demo
    assert b'data:image/jpeg;base64,' in demo

def test_css_bundle_is_reproducible():
    assert (ROOT/'web/style.css').read_text()==(ROOT/'web/base.css').read_text()+'\n'+(ROOT/'web/redesign.css').read_text()
