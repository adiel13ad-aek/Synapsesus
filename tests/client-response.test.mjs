import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const source = readFileSync(new URL('../web/api-client.js', import.meta.url), 'utf8');
const lists = ['actors', 'posts', 'following', 'saved', 'blocked', 'links', 'stories', 'notifications'];
const state = () => ({mode: 'server', me: null, ...Object.fromEntries(lists.map(key => [key, []]))});
function client(fetch) {
  const window = {};
  runInNewContext(source, {window, fetch});
  return window.SynapseAPI;
}
const hasCode = code => error => error.code === code;

test('HTML with HTTP 200 is rejected before it can replace feed state', async () => {
  const api = client(async () => new Response('<!doctype html><h1>Synapse</h1>', {headers: {'Content-Type': 'text/html'}}));
  await assert.rejects(api.request('/api/state'), hasCode('api_not_json'));
});

test('JSON without its content type is not mistaken for a working API', async () => {
  const api = client(async () => new Response(JSON.stringify(state())));
  await assert.rejects(api.request('/api/state'), hasCode('api_not_json'));
});

test('malformed JSON with HTTP 200 is rejected', async () => {
  const api = client(async () => new Response('{"stories":', {headers: {'Content-Type': 'application/json'}}));
  await assert.rejects(api.request('/api/state'), hasCode('api_invalid_json'));
});

test('null, array and scalar JSON responses are rejected', async () => {
  for (const payload of [null, [], 'ok', 1, true]) {
    const api = client(async () => Response.json(payload));
    await assert.rejects(api.request('/api/state'), hasCode('api_invalid_json'));
  }
});

test('successful JSON is returned intact and GET bypasses cache', async () => {
  let sent;
  const expected = state();
  const api = client(async (...args) => { sent = args; return Response.json(expected); });
  assert.deepEqual(await api.request('/api/state'), expected);
  assert.equal(sent[0], '/api/state');
  assert.equal(sent[1].method, 'GET');
  assert.equal(sent[1].credentials, 'same-origin');
  assert.equal(sent[1].cache, 'no-store');
  assert.equal(sent[1].headers['X-Synapse-Client'], 'web-v10');
  assert.equal(sent[1].body, undefined);
  assert.equal(sent[1].headers['X-CSRF-Token'], undefined);
});

test('JSON media types with charset and vendor suffix are accepted', async () => {
  for (const type of ['application/json; charset=utf-8', 'Application/JSON', 'application/vnd.synapse+json']) {
    const api = client(async () => new Response('{"ok":true}', {headers: {'Content-Type': type}}));
    assert.equal((await api.request('/api/health')).ok, true);
  }
});

test('write requests retain JSON body and CSRF protections', async () => {
  let sent;
  const api = client(async (...args) => { sent = args; return Response.json({ok: true}); });
  await api.request('/api/posts', 'POST', {body: 'Minha descoberta'}, 'session-csrf');
  assert.equal(sent[1].method, 'POST');
  assert.equal(sent[1].headers['Content-Type'], 'application/json');
  assert.equal(sent[1].headers['X-CSRF-Token'], 'session-csrf');
  assert.equal(sent[1].headers['X-Synapse-Client'], 'web-v10');
  assert.equal(sent[1].credentials, 'same-origin');
  assert.equal(sent[1].body, JSON.stringify({body: 'Minha descoberta'}));
});

test('JSON HTTP errors preserve their support reference and message', async () => {
  const api = client(async () => Response.json({detail: 'Cadastro fechado.', request_id: 'test-reference'}, {status: 403}));
  await assert.rejects(api.request('/api/auth/register', 'POST', {}), error => {
    assert.equal(error.code, 'http_error');
    assert.equal(error.status, 403);
    assert.equal(error.message, 'Cadastro fechado.');
    assert.equal(error.requestId, 'test-reference');
    return true;
  });
});

test('HTML HTTP failures are identified as server errors', async () => {
  const api = client(async () => new Response('<h1>Bad Gateway</h1>', {status: 502, headers: {'Content-Type': 'text/html'}}));
  await assert.rejects(api.request('/api/state'), error => error.code === 'http_error' && error.message.includes('502'));
});

test('network failure remains distinct from incompatible server data', async () => {
  const api = client(async () => { throw new TypeError('Failed to fetch'); });
  await assert.rejects(api.request('/api/state'), hasCode('network_error'));
});

test('a valid state keeps its original identity, including populated content', () => {
  const api = client();
  const expected = state();
  expected.posts.push({id: 'post-1', body: 'Uma descoberta'});
  expected.me = {id: 'user-1', name: 'Pessoa'};
  assert.equal(api.validateState(expected), expected);
  expected.mode = 'demo';
  assert.equal(api.validateState(expected), expected);
});

test('every missing or invalid feed list is rejected instead of defaulting to empty', () => {
  const api = client();
  for (const key of lists) {
    const missing = state();
    delete missing[key];
    assert.throws(() => api.validateState(missing), hasCode('state_invalid'), key);
    for (const value of [null, {}, '', 1]) {
      assert.throws(() => api.validateState({...state(), [key]: value}), hasCode('state_invalid'), key);
    }
  }
});

test('wrong state envelopes and identities cannot enter rendering', () => {
  const api = client();
  for (const value of [null, [], {}, {detail: 'Resposta inválida.'}, {...state(), mode: 'unknown'}, {...state(), me: []}, {...state(), me: 'user'}, {...state(), me: undefined}]) {
    assert.throws(() => api.validateState(value), hasCode('state_invalid'));
  }
});

test('rejected state preserves the last good state and a retry can recover', async () => {
  const previous = state();
  previous.posts.push({id: 'already-visible'});
  const restored = state();
  restored.posts.push({id: 'after-recovery'});
  let attempts = 0;
  const api = client(async () => Response.json(++attempts === 1 ? {detail: 'Incomplete'} : restored));
  let current = previous;
  const refresh = async () => { current = api.validateState(await api.request('/api/state')); };
  await assert.rejects(refresh(), hasCode('state_invalid'));
  assert.equal(current, previous);
  await refresh();
  assert.deepEqual(current, restored);
});
