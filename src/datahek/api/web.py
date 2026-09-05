"""Basic web UI — single-page chat consuming /ask/stream (SSE).

Zero external dependencies: inline CSS/JS, dark theme, no build step.
"""
from fastapi.responses import HTMLResponse

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DataHek OSS</title>
<style>
  :root { --bg:#0F172A; --panel:#1E293B; --border:#334155; --text:#F8FAFC; --muted:#94A3B8;
          --accent:#22C55E; --info:#38BDF8; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: system-ui, sans-serif; height: 100vh; display: flex; }
  aside { width: 260px; background: var(--panel); border-right: 1px solid var(--border); padding: 16px; display: flex; flex-direction: column; gap: 12px; }
  main { flex: 1; display: flex; flex-direction: column; }
  h1 { font-size: 18px; }
  h1 span { color: var(--accent); }
  select, input, button { width: 100%; padding: 8px; border-radius: 6px; border: 1px solid var(--border); background: #0B1220; color: var(--text); font-size: 13px; }
  button { background: var(--accent); color: #052E16; font-weight: 600; cursor: pointer; border: none; }
  button:hover { filter: brightness(1.1); }
  label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
  #chat { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 10px; }
  .msg { max-width: 75%; padding: 10px 14px; border-radius: 10px; font-size: 14px; line-height: 1.55; white-space: pre-wrap; }
  .msg.user { align-self: flex-end; background: var(--info); color: #082F49; }
  .msg.assistant { align-self: flex-start; background: var(--panel); border: 1px solid var(--border); }
  .msg.err { align-self: flex-start; background: #450A0A; border: 1px solid #B91C1C; color: #FECACA; }
  table { border-collapse: collapse; font-size: 12px; margin-top: 8px; }
  th, td { border: 1px solid var(--border); padding: 4px 10px; text-align: left; }
  th { color: var(--accent); }
  #composer { display: flex; gap: 8px; padding: 14px; border-top: 1px solid var(--border); }
  #composer input { flex: 1; }
  #status { font-size: 11px; color: var(--muted); }
  #add-conn { margin-top: auto; display: flex; flex-direction: column; gap: 6px; }
  .hide { display: none !important; }
</style>
</head>
<body>
<aside>
  <h1>Data<span>Hek</span> OSS</h1>
  <div>
    <label>Connection</label>
    <select id="conn-select"><option value="">— none —</option></select>
  </div>
  <div id="add-conn">
    <label>Add connection</label>
    <input id="nc-name" placeholder="name">
    <input id="nc-host" placeholder="host (e.g. localhost)">
    <input id="nc-db" placeholder="database">
    <button id="nc-save">Save connection</button>
  </div>
  <div id="status"></div>
</aside>
<main>
  <div id="chat"><div class="msg assistant">Ask anything about your connected data.</div></div>
  <div id="composer">
    <input id="chat-input" placeholder="Ask a question..." autocomplete="off">
    <button id="send">Send</button>
  </div>
</main>
<script>
const chat = document.getElementById('chat');
const input = document.getElementById('chat-input');
const status = document.getElementById('status');
const connSelect = document.getElementById('conn-select');
let conversationId = null;

async function refreshConnections() {
  const res = await fetch('/connections');
  const conns = await res.json();
  connSelect.innerHTML = '<option value="">— none —</option>' +
    conns.map(c => `<option value="${c.id}">${c.name} (${c.provider})</option>`).join('');
  status.textContent = `${conns.length} connection(s)`;
}
async function ensureConversation() {
  if (!conversationId) {
    const res = await fetch('/conversations', { method: 'POST', headers: {'content-type':'application/json'}, body: JSON.stringify({title:'web'}) });
    conversationId = (await res.json()).id;
  }
  return conversationId;
}
function addMsg(role, text) {
  const el = document.createElement('div');
  el.className = 'msg ' + role;
  el.textContent = text;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}
function renderRows(rows, columns) {
  if (!rows || !rows.length) return;
  const table = document.createElement('table');
  const head = '<tr>' + columns.map(c => `<th>${c}</th>`).join('') + '</tr>';
  const body = rows.map(r => '<tr>' + columns.map(c => `<td>${r[c]}</td>`).join('') + '</tr>').join('');
  table.innerHTML = head + body;
  chat.appendChild(table);
}
async function ask(question) {
  if (!connSelect.value) { addMsg('err', 'Select a connection first.'); return; }
  addMsg('user', question);
  const answerEl = addMsg('assistant', '');
  const connId = connSelect.value;
  const convId = await ensureConversation();
  const res = await fetch('/ask/stream', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ question, connection_id: connId, conversation_id: convId }),
  });
  if (!res.ok) {
    const err = await res.json();
    answerEl.textContent = `Error: ${err.message || err.code}`;
    answerEl.className = 'msg err';
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let explanation = '';
  const consume = async () => {
    const { done, value } = await reader.read();
    if (done) { answerEl.textContent = explanation || '…'; return; }
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split('\\n\\n');
    buf = parts.pop();
    for (const part of parts) {
      const line = part.split('\\n').find(l => l.startsWith('data: '));
      if (!line) continue;
      let ev; try { ev = JSON.parse(line.slice(6)); } catch { continue; }
      if (ev.type === 'clarification') { explanation = ev.text; answerEl.textContent = ev.text; }
      else if (ev.type === 'token') { explanation += ev.content; answerEl.textContent = explanation; }
      else if (ev.type === 'rows') renderRows(ev.rows, ev.columns);
    }
    consume();
  };
  consume();
}
document.getElementById('send').addEventListener('click', () => {
  const q = input.value.trim(); if (!q) return;
  input.value = '';
  ask(q);
});
input.addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('send').click(); });
document.getElementById('nc-save').addEventListener('click', async () => {
  const name = document.getElementById('nc-name').value.trim();
  const host = document.getElementById('nc-host').value.trim();
  const db = document.getElementById('nc-db').value.trim();
  if (!name) return;
  const res = await fetch('/connections', { method: 'POST', headers: {'content-type':'application/json'},
    body: JSON.stringify({ name, provider: 'clickhouse', host: host || 'localhost', port: 8123, database: db || 'default' }) });
  if (!res.ok) { status.textContent = 'add failed: ' + (await res.text()); return; }
  await refreshConnections();
  status.textContent = 'connection saved';
});
refreshConnections();
</script>
</body>
</html>"""


def index_html() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)