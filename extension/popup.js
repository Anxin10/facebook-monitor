const status = document.getElementById("status");
async function refresh() {
  const result = await chrome.runtime.sendMessage({type: "status"});
  status.textContent = result.ok ? "本機服務已連線" : result.error;
  const container = document.getElementById("targets");
  container.replaceChildren();
  for (const target of result.targets || []) {
    const section = document.createElement("section");
    const link = document.createElement("a");
    link.href = target.url; link.target = "_blank"; link.rel = "noopener";
    link.textContent = target.page_id;
    const info = document.createElement("p");
    info.textContent = `${target.armed ? "通知啟用" : "記錄基準（不通知）"} · 已記錄 ${target.observed_count} 篇 · 最近收到：${target.last_seen_at || "尚未收到可辨識貼文"}`;
    const button = document.createElement("button");
    button.textContent = target.armed ? "暫停通知" : "基準確認，開始通知";
    button.disabled = !target.observed_count;
    button.onclick = async () => {
      const response = await chrome.runtime.sendMessage({type: "arm", payload: {page_id: target.page_id, armed: !target.armed}});
      if (!response.ok) status.textContent = response.error;
      else await refresh();
    };
    section.append(link, info, button); container.append(section);
  }
}
document.getElementById("save").onclick = async () => {
  const token = document.getElementById("token").value.trim();
  if (token.length < 32) {status.textContent = "配對碼至少 32 字元"; return;}
  await chrome.storage.local.set({token});
  document.getElementById("token").value = "";
  await refresh();
};
document.getElementById("refresh").onclick = refresh;
refresh();
