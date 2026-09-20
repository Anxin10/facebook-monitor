/* Read-only DOM parser evaluated inside the dedicated background browser. */
globalThis.FBMonitor = (() => {
  function pageKey(value) {
    try {
      const u = new URL(value);
      if (u.origin !== "https://www.facebook.com") return null;
      const path = u.pathname.replace(/^\/|\/$/g, "");
      if (path === "profile.php") return /^\d+$/.test(u.searchParams.get("id") || "") ? u.searchParams.get("id") : null;
      return /^[A-Za-z0-9.]+$/.test(path) ? path.toLowerCase() : null;
    } catch { return null; }
  }
  function postUrl(value, target) {
    try {
      const u = new URL(value, "https://www.facebook.com");
      if (u.origin !== "https://www.facebook.com") return null;
      const m = u.pathname.match(/^\/([A-Za-z0-9.]+)\/posts\/([A-Za-z0-9]+)\/?$/);
      if (m && [pageKey(target.url), String(target.page_id)].includes(m[1].toLowerCase())) {
        return `https://www.facebook.com/${m[1]}/posts/${m[2]}`;
      }
      const id = u.searchParams.get("story_fbid");
      if (["/permalink.php", "/story.php"].includes(u.pathname) &&
          u.searchParams.get("id") === String(target.page_id) && /^[A-Za-z0-9]+$/.test(id || "")) {
        return `https://www.facebook.com/permalink.php?story_fbid=${id}&id=${target.page_id}`;
      }
    } catch { /* Not a supported permalink. */ }
    return null;
  }
  function extract(root, target) {
    const posts = new Map();
    for (const article of root.querySelectorAll('[role="article"]')) {
      if (article.parentElement?.closest('[role="article"]')) continue;
      for (const anchor of article.querySelectorAll('a[href]')) {
        if (anchor.closest('[role="article"]') !== article) continue;
        if (anchor.closest('[data-ad-preview="message"], [data-ad-comet-preview="message"]')) continue;
        const url = postUrl(anchor.href, target);
        if (!url) continue;
        const text = article.querySelector('[data-ad-preview="message"], [data-ad-comet-preview="message"]');
        posts.set(url, {url, summary: (text?.innerText || "").slice(0, 4000)});
        break;
      }
    }
    if (posts.size === 0) {
      for (const anchor of root.querySelectorAll('a[href]')) {
        const url = postUrl(anchor.href, target);
        if (!url || posts.has(url)) continue;
        let container = anchor.parentElement;
        let text = "";
        for (let i = 0; i < 10 && container; i++) {
          const msg = container.querySelector('[data-ad-preview="message"], [data-ad-comet-preview="message"]');
          if (msg && msg.innerText && msg.innerText.trim().length > 10) {
            text = msg.innerText;
            break;
          }
          const textBlocks = [...container.querySelectorAll('div[dir="auto"]')].map(d => d.innerText.trim()).filter(t => t.length > 20);
          if (textBlocks.length > 0) {
            text = textBlocks[0];
            break;
          }
          container = container.parentElement;
        }
        posts.set(url, {url, summary: (text || "").slice(0, 4000)});
      }
    }
    return [...posts.values()].slice(0, 50);
  }
  return {pageKey, postUrl, extract};
})();
