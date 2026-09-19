(() => {
  let busy = false;
  let retryBatch = null;
  async function scan() {
    if (busy) return;
    busy = true;
    try {
      const pageUrl = location.href;
      if (retryBatch && retryBatch.pageUrl !== pageUrl) retryBatch = null;
      const result = await chrome.runtime.sendMessage({type: "target"});
      if (!result.ok || !result.target) return;
      const posts = retryBatch?.posts || FBMonitor.extract(document, result.target);
      if (!posts.length || location.href !== pageUrl) return;
      retryBatch = {pageUrl, posts};
      const response = await chrome.runtime.sendMessage({type: "observe", posts});
      if (response.ok) retryBatch = null;
    } catch { /* Retry while this tab remains open. */ }
    finally { busy = false; }
  }
  setInterval(scan, 15000);
  scan();
})();
