const {test} = require('node:test');
const assert = require('node:assert/strict');
require('./parser.js');
const {pageKey, postUrl, extract} = globalThis.FBMonitor;
const target = {page_id: '123', url: 'https://www.facebook.com/example'};
test('normalizes profile and vanity Page URLs; rejects foreign hosts', () => {
  assert.equal(pageKey(target.url + '/?locale=zh_TW'), 'example');
  assert.equal(pageKey('https://www.facebook.com/profile.php?id=123'), '123');
  assert.equal(pageKey('https://facebook.com.evil.test/example'), null);
});
test('accepts own permalinks and removes trackers', () => {
  assert.equal(postUrl('/example/posts/pfbidABC?__cft__=track', target), 'https://www.facebook.com/example/posts/pfbidABC');
  assert.equal(postUrl('/story.php?id=123&story_fbid=456&tracking=1', target), 'https://www.facebook.com/permalink.php?story_fbid=456&id=123');
});
test('rejects wrong author, unsupported media and foreign links', () => {
  for (const url of ['/other/posts/456', '/permalink.php?id=999&story_fbid=456', '/reel/123', 'https://evil.test/example/posts/1']) {
    assert.equal(postUrl(url, target), null);
  }
});
test('extracts a post once and excludes nested articles and message links', () => {
  const article = {
    parentElement: {closest: () => null},
    querySelector: () => ({innerText: 'Visible post text'}),
    querySelectorAll: () => [
      {href: '/example/posts/wrong', closest: selector => selector.includes('message') ? {} : article},
      {href: '/example/posts/right', closest: selector => selector.includes('message') ? null : article}
    ]
  };
  const nested = {parentElement: {closest: () => article}};
  assert.deepEqual(extract({querySelectorAll: () => [article, nested, article]}, target),
    [{url: 'https://www.facebook.com/example/posts/right', summary: 'Visible post text'}]);
});
