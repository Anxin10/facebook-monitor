const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function worker() {
  let listener;
  const calls = [];
  const context = vm.createContext({URL, AbortSignal,
    chrome: {
      storage: {local: {setAccessLevel: async () => {}, get: async () => ({token: 'test-pairing-token'})}},
      runtime: {getURL: name => `chrome-extension://test/${name}`, onMessage: {addListener: fn => {listener = fn;}}}
    },
    fetch: async (url, options) => {
      calls.push({url, options});
      return {ok: true, json: async () => url.endsWith('/status')
        ? {targets: [{page_id: '123', url: 'https://www.facebook.com/example'}]}
        : {inserted: 1}};
    }
  });
  context.importScripts = file => vm.runInContext(fs.readFileSync(path.join(__dirname, file), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'background.js'), 'utf8'), context);
  return {calls, send: (message, sender) => new Promise(resolve => listener(message, sender, resolve))};
}
test('worker derives target from sender, not an untrusted claimed page id', async () => {
  const w = worker();
  const result = await w.send({type: 'observe', page_id: 'evil', posts: [{url: 'https://www.facebook.com/example/posts/1'}]},
    {tab: {id: 1}, frameId: 0, url: 'https://www.facebook.com/example'});
  assert.equal(result.ok, true);
  const call = w.calls.find(c => c.url.endsWith('/observations'));
  assert.equal(JSON.parse(call.options.body).page_id, '123');
  assert.equal(call.options.headers.Authorization, 'Bearer test-pairing-token');
});
test('Facebook page cannot enable notifications or select arbitrary endpoints', async () => {
  const w = worker();
  const sender = {tab: {id: 1}, frameId: 0, url: 'https://www.facebook.com/example'};
  assert.equal((await w.send({type: 'arm', payload: {page_id: '123', armed: true}}, sender)).ok, false);
  assert.equal(w.calls.some(c => c.url.endsWith('/arm')), false);
  assert.equal((await w.send({type: 'observe'}, {...sender, url: 'https://evil.test/example'})).ok, false);
});
test('only extension popup may arm a target', async () => {
  const w = worker();
  const result = await w.send({type: 'arm', payload: {page_id: '123', armed: true}},
    {url: 'chrome-extension://test/popup.html'});
  assert.equal(result.ok, true);
  assert.equal(w.calls[0].url, 'http://127.0.0.1:8765/arm');
});
