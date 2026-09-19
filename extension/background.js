importScripts("parser.js");
const ready = chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});

async function request(path, body) {
  await ready;
  const {token} = await chrome.storage.local.get("token");
  if (!token) throw new Error("請先貼上 browser-token.local 的配對碼");
  const response = await fetch(`http://127.0.0.1:8765${path}`, {
    method: body ? "POST" : "GET",
    headers: {Authorization: `Bearer ${token}`, "Content-Type": "application/json"},
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(5000)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  (async () => {
    const popup = !sender.tab && sender.url === chrome.runtime.getURL("popup.html");
    if (popup && message.type === "status") return request("/status");
    if (popup && message.type === "arm") return request("/arm", message.payload);
    const pageUrl = sender.url;
    if (!sender.tab || sender.frameId !== 0 || !FBMonitor.pageKey(pageUrl)) throw new Error("Unsupported page");
    const {targets} = await request("/status");
    const target = targets.find(t => FBMonitor.pageKey(t.url) === FBMonitor.pageKey(pageUrl));
    if (message.type === "target") return {target: target || null};
    if (message.type !== "observe" || !target) throw new Error("Unconfigured page");
    return request("/observations", {page_id: target.page_id, page_url: pageUrl, posts: message.posts});
  })().then(result => respond({ok: true, ...result}))
    .catch(error => respond({ok: false, error: error.message}));
  return true;
});
