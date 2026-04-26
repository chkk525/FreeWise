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

load();
