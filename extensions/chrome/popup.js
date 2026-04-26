const $ = (id) => document.getElementById(id);

async function load() {
  const { baseUrl = "", token = "" } = await chrome.storage.local.get(["baseUrl", "token"]);
  $("baseUrl").value = baseUrl;
  $("token").value = token;
}

function status(msg, cls) {
  const s = $("status");
  s.className = "status " + (cls || "");
  s.textContent = msg;
}

$("save").addEventListener("click", async () => {
  const baseUrl = $("baseUrl").value.trim().replace(/\/+$/, "");
  const token = $("token").value.trim();
  if (!baseUrl || !token) {
    status("Both fields are required.", "err");
    return;
  }
  await chrome.storage.local.set({ baseUrl, token });
  status("Saved.", "ok");
});

$("test").addEventListener("click", async () => {
  const baseUrl = $("baseUrl").value.trim().replace(/\/+$/, "");
  const token = $("token").value.trim();
  if (!baseUrl || !token) {
    status("Fill base URL + token first.", "err");
    return;
  }
  status("Testing…");
  try {
    const r = await fetch(baseUrl + "/api/v2/auth/", {
      method: "GET",
      headers: { "Authorization": `Token ${token}` },
    });
    // FreeWise returns 204 on success, but some reverse proxies / older
    // FastAPI versions normalise to 200 — accept any 2xx.
    if (r.status >= 200 && r.status < 300) {
      status(`OK (${r.status}).`, "ok");
    } else if (r.status === 401) {
      status("Auth rejected (401). Check token.", "err");
    } else {
      status(`Unexpected ${r.status}.`, "err");
    }
  } catch (e) {
    status(`Error: ${e.message || e}`, "err");
  }
});

function fmtTime(iso) {
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch (_) { return iso; }
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, function (c) {
    return ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c];
  });
}

async function renderRecents() {
  const list = $("recent-list");
  if (!list) return;
  const { lastSaves = [] } = await chrome.storage.local.get(["lastSaves"]);
  if (!lastSaves.length) {
    list.innerHTML = '<li class="empty">no saves yet</li>';
    return;
  }
  list.innerHTML = lastSaves.map(function (s) {
    const pill = s.ok
      ? '<span class="pill ok">OK</span>'
      : '<span class="pill err">ERR</span>';
    const titleHtml = s.title
      ? '<span class="title-line" title="' + escapeHtml(s.url || "") + '">'
        + escapeHtml(s.title) + "</span>"
      : '<span class="title-line" title="' + escapeHtml(s.url || "") + '">'
        + escapeHtml(s.url || "(unknown source)") + "</span>";
    const detail = s.ok
      ? `created ${s.created || 1}, ${s.skipped || 0} dupes`
      : (s.error || "unknown error");
    return "<li>"
      + pill + titleHtml
      + '<div class="when">' + fmtTime(s.at) + ' — ' + escapeHtml(detail) + "</div>"
      + "</li>";
  }).join("");
}

$("clear-recents").addEventListener("click", async function () {
  await chrome.storage.local.remove("lastSaves");
  await renderRecents();
});

load();
renderRecents();
