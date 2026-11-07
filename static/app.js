// Bakery Copilot — the UI layer. It displays what the backend sends; it remembers nothing itself.
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { user: null, conversations: [], current: null, image: null, streaming: false };

  // ---------- helpers ----------
  async function api(path, options = {}) {
    const res = await fetch(path, { headers: { "Content-Type": "application/json" }, credentials: "same-origin", ...options });
    if (res.status === 401) { showLogin(); throw new Error("Please sign in."); }
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    return res.status === 204 ? null : res.json();
  }
  function render(md) {
    if (window.marked) { try { return marked.parse(md, { breaks: true }); } catch (_) {} }
    const div = document.createElement("div"); div.textContent = md; return div.innerHTML.replace(/\n/g, "<br>");
  }
  function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
  function setStatus(text) { $("status").textContent = text || ""; }
  function scrollDown() { const m = $("messages"); m.scrollTop = m.scrollHeight; }

  // ---------- auth ----------
  function showLogin() { $("login").classList.remove("hidden"); $("app").classList.add("hidden"); }
  function showApp() { $("login").classList.add("hidden"); $("app").classList.remove("hidden"); $("who").textContent = state.user ? `signed in as ${state.user.name}` : ""; }

  $("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("login-error").textContent = "";
    try {
      state.user = await api("/api/login", { method: "POST", body: JSON.stringify({ name: $("login-name").value.trim(), password: $("login-password").value }) });
      $("login-password").value = "";
      showApp();
      await loadConversations();
    } catch (err) { $("login-error").textContent = err.message; }
  });
  $("logout").addEventListener("click", async () => { await api("/api/logout", { method: "POST" }).catch(() => {}); state.user = null; state.current = null; showLogin(); });

  // ---------- conversations ----------
  async function loadConversations() {
    state.conversations = await api("/api/conversations");
    renderConversations();
    if (state.current) await openConversation(state.current); else renderEmpty();
  }
  function renderConversations() {
    const nav = $("conversations"); nav.innerHTML = "";
    for (const c of state.conversations) {
      const b = document.createElement("button");
      b.textContent = c.title; b.title = c.title;
      if (c.id === state.current) b.classList.add("active");
      b.addEventListener("click", () => openConversation(c.id));
      nav.appendChild(b);
    }
  }
  async function openConversation(id) {
    setComposer(true);
    state.current = id;
    const conv = state.conversations.find((c) => c.id === id);
    $("conv-title").textContent = conv ? conv.title : "Chat";
    renderConversations();
    const messages = await api(`/api/conversations/${id}/messages`);
    const box = $("messages"); box.innerHTML = "";
    for (const m of messages) addBubble(m.role, m.content, { hasImage: m.has_image, time: m.created_at });
    if (!messages.length) renderEmpty();
    scrollDown();
  }
  function renderEmpty() {
    setComposer(true);
    $("messages").innerHTML = `<div class="empty"><p>Ask about sales, or attach an invoice photo.</p>
      <span class="hint" data-q="How many chocolate cakes were sold in 2026?">How many chocolate cakes were sold in 2026?</span>
      <span class="hint" data-q="How many cheesecakes were sold in 2026?">How many cheesecakes were sold in 2026?</span>
      <span class="hint" data-q="How many babkas did we sell in each month?">How many babkas did we sell in each month?</span>
      <span class="hint recipe-card" role="button" tabindex="0" data-q="${RECIPE_QUESTION}">${RECIPE_QUESTION}</span></div>`;
    $("messages").querySelectorAll(".hint").forEach((h) => h.addEventListener("click", () => {
      if (isRecipeQuestion(h.dataset.q)) { showRecipe(); return; }  // straight to the recipe page
      $("input").value = h.dataset.q; $("input").focus();
    }));
    const card = $("messages").querySelector(".recipe-card");
    if (card) card.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); showRecipe(); } });
  }

  // ---------- recipe hint ----------
  // The hint puts the question in the text box like the others; sending exactly that question
  // shows this fixed answer in the browser: no model call, no cost, not saved to the conversation.
  const RECIPE_QUESTION = "Do you want a chocolate cake recipe?";
  const RECIPE = `**Simple chocolate cake** (one 24 cm round pan, about 10 slices)

**Ingredients**
- 2 cups (250 g) flour
- 2 cups (400 g) sugar
- ¾ cup (75 g) cocoa powder
- 2 tsp baking powder
- 1 tsp baking soda
- ½ tsp salt
- 2 eggs
- 1 cup (240 ml) milk
- ½ cup (120 ml) vegetable oil
- 2 tsp vanilla extract
- 1 cup (240 ml) hot water or hot coffee

**Steps**
1. Heat the oven to 180 °C. Grease the pan and line the bottom with baking paper.
2. In a large bowl, mix the flour, sugar, cocoa, baking powder, baking soda and salt.
3. Add the eggs, milk, oil and vanilla. Whisk for 2 minutes until smooth.
4. Stir in the hot water. The batter will be thin; that is right.
5. Pour into the pan and bake 35–40 minutes, until a toothpick in the centre comes out clean.
6. Cool 10 minutes in the pan, then turn out onto a rack and cool completely.

**Quick chocolate glaze (optional):** melt 100 g dark chocolate with ½ cup (120 ml) cream, stir until smooth, and pour over the cooled cake.`;
  const isRecipeQuestion = (text) => text.trim().toLowerCase() === RECIPE_QUESTION.toLowerCase();
  // The recipe gets a page of its own with no text box or Send button (they are not needed
  // there); New chat or picking a saved chat brings them back.
  function setComposer(visible) {
    $("composer").classList.toggle("hidden", !visible);
    if (!visible) $("attachment").classList.add("hidden");
  }
  function showRecipe() {
    $("input").value = ""; $("input").style.height = "auto";
    state.current = null; renderConversations();
    $("conv-title").textContent = "Chocolate cake recipe";
    $("messages").innerHTML = "";
    addBubble("user", RECIPE_QUESTION);
    addBubble("assistant", RECIPE);
    setComposer(false);
  }
  $("new-chat").addEventListener("click", () => { state.current = null; $("conv-title").textContent = "New chat"; renderConversations(); renderEmpty(); $("input").focus(); });

  // ---------- messages ----------
  function addBubble(role, text, { hasImage = false, imageDataUrl = null, time = null } = {}) {
    const div = document.createElement("div");
    div.className = `msg ${role}`;
    const who = role === "user" ? (state.user ? state.user.name : "You") : "Bakery Copilot";
    const initial = role === "user" ? who.trim().charAt(0).toUpperCase() : "🥐";
    const when = time ? new Date(time) : new Date();
    const stamp = when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    let inner = "";
    if (imageDataUrl) inner += `<img class="img" src="${imageDataUrl}" alt="attached invoice">`;
    else if (hasImage) inner += `<span class="chip">📎 image</span><br>`;
    inner += role === "user" ? `<p>${escapeHtml(text).replace(/\n/g, "<br>")}</p>` : render(text);
    div.innerHTML = `<div class="avatar ${role}">${initial}</div><div class="msg-body"><div class="msg-head"><span class="author">${escapeHtml(who)}</span>${role === "assistant" ? '<span class="tag">BOT</span>' : ""}<span class="time">${stamp}</span></div><div class="body">${inner}</div></div>`;
    $("messages").appendChild(div);
    scrollDown();
    return div;
  }

  // ---------- image attach ----------
  $("image").addEventListener("change", () => {
    const file = $("image").files[0];
    if (!file) { state.image = null; $("attachment").classList.add("hidden"); return; }
    if (file.size > 5 * 1024 * 1024) { alert("Image is larger than 5 MB."); $("image").value = ""; return; }
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result;
      state.image = { media_type: file.type, data: dataUrl.split(",")[1], dataUrl, name: file.name };
      $("attachment").textContent = `Attached: ${file.name}`; $("attachment").classList.remove("hidden");
    };
    reader.readAsDataURL(file);
  });

  // ---------- send + stream ----------
  $("input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("composer").requestSubmit(); } });
  $("input").addEventListener("input", () => { const t = $("input"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 160) + "px"; });

  $("composer").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (state.streaming) return;
    const text = $("input").value.trim();
    if (!text && !state.image) return;
    if (!state.image && isRecipeQuestion(text)) { showRecipe(); return; }
    const image = state.image;
    $("input").value = ""; $("input").style.height = "auto"; state.image = null; $("image").value = ""; $("attachment").classList.add("hidden");
    if ($("messages").querySelector(".empty")) $("messages").innerHTML = "";
    addBubble("user", text || "(invoice photo)", { imageDataUrl: image ? image.dataUrl : null });

    const bot = addBubble("assistant", "");
    const body = bot.querySelector(".body"); body.classList.add("cursor");
    const meta = document.createElement("div"); meta.className = "meta"; bot.querySelector(".msg-body").appendChild(meta);
    state.streaming = true; $("send").disabled = true; setStatus("thinking…");
    let full = "";
    try {
      const res = await fetch("/api/chat", {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: state.current, message: text, image: image ? { media_type: image.media_type, data: image.data } : null }),
      });
      if (!res.ok) { let d = res.statusText; try { d = (await res.json()).detail || d; } catch (_) {} throw new Error(d); }
      const reader = res.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf("\n\n")) >= 0) {
          const raw = buffer.slice(0, idx); buffer = buffer.slice(idx + 2);
          const line = raw.split("\n").find((l) => l.startsWith("data: ")); if (!line) continue;
          const ev = JSON.parse(line.slice(6));
          if (ev.type === "meta") { state.current = ev.conversation_id; if (ev.title) $("conv-title").textContent = ev.title; }
          else if (ev.type === "text") { full += ev.text; body.innerHTML = render(full); scrollDown(); }
          else if (ev.type === "tool") { const c = document.createElement("span"); c.className = `chip tool ${ev.status}`; c.textContent = `${ev.status === "start" ? "⚙" : "✓"} ${ev.name}${ev.summary ? ": " + ev.summary : ""}`; meta.appendChild(c); setStatus(`using ${ev.name}…`); }
          else if (ev.type === "done") { const u = ev.usage || {}; const c = document.createElement("span"); c.className = "chip"; c.textContent = `${u.input_tokens || 0} in · ${u.output_tokens || 0} out · $${(ev.cost_usd || 0).toFixed(4)}`; meta.appendChild(c); }
          else if (ev.type === "error") { full += `\n\n**Error:** ${ev.message}`; body.innerHTML = render(full); }
        }
      }
    } catch (err) {
      full += `\n\n**Error:** ${err.message}`; body.innerHTML = render(full);
    } finally {
      body.classList.remove("cursor"); state.streaming = false; $("send").disabled = false; setStatus("");
      await loadConversationsQuiet();
    }
  });
  async function loadConversationsQuiet() { try { state.conversations = await api("/api/conversations"); renderConversations(); } catch (_) {} }

  // ---------- invoices panel ----------
  async function loadInvoices() {
    const rows = await api("/api/invoices");
    $("invoice-rows").innerHTML = rows.map((r) => `<tr><td>${r.invoice_date || (r.created_at || "").slice(0, 10)}</td><td>${escapeHtml(r.supplier)}<br><small>${escapeHtml(r.invoice_number || "")}</small></td><td>${r.amount == null ? "—" : r.amount.toLocaleString() + " " + r.currency}</td><td><span class="badge ${r.status}">${r.status.replace(/_/g, " ")}</span>${r.flagged ? '<span class="badge flag">flag</span>' : ""}</td></tr>`).join("") || `<tr><td colspan="4"><small>No invoices yet.</small></td></tr>`;
  }
  $("toggle-invoices").addEventListener("click", async () => { $("invoices").classList.toggle("hidden"); if (!$("invoices").classList.contains("hidden")) await loadInvoices(); });
  $("close-invoices").addEventListener("click", () => $("invoices").classList.add("hidden"));

  // ---------- boot ----------
  (async () => {
    try { state.user = await api("/api/me"); showApp(); await loadConversations(); }
    catch (_) { showLogin(); }
  })();
})();
