/* ================================================================
   ANZ-CREATOR — Frontend
   Vanilla JS, no framework. Single-file app logic.
   ================================================================ */

const API = {
  health: () => fetch('/api/health').then(r => r.json()),
  resources: () => fetch('/api/system/resources').then(r => r.json()),

  // Keys
  listKeys: () => fetch('/api/keys').then(r => r.json()),
  addKeys: (keys) => fetch('/api/keys/add', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ keys }),
  }).then(r => r.json()),
  importKeys: (file) => {
    const fd = new FormData(); fd.append('file', file);
    return fetch('/api/keys/import', { method: 'POST', body: fd }).then(r => r.json());
  },
  removeKey: (masked) => fetch(`/api/keys/${encodeURIComponent(masked)}`, { method: 'DELETE' }).then(r => r.json()),
  clearKeys: () => fetch('/api/keys/clear', { method: 'POST' }).then(r => r.json()),
  setMode: (mode) => fetch('/api/keys/mode', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ mode }),
  }).then(r => r.json()),

  // Upload
  upload: (file) => {
    const fd = new FormData(); fd.append('file', file);
    return fetch('/api/upload', { method: 'POST', body: fd }).then(r => r.json());
  },

  // Short Maker
  smFindViral: (body) => fetch('/api/short-maker/find-viral', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  }),
  smStart: (body) => fetch('/api/short-maker/start', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  }).then(r => r.json()),

  // Story Teller
  stPreview: (body) => fetch('/api/story-teller/preview', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  }),
  stStart: (body) => fetch('/api/story-teller/start', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  }).then(r => r.json()),

  // Job
  jobStatus: (jid) => fetch(`/api/job/${jid}`).then(r => r.json()),

  // Outputs
  listOutputs: () => fetch('/api/outputs').then(r => r.json()),

  // System
  shutdown: () => fetch('/api/system/shutdown', { method: 'POST' }).then(r => r.json()),
  restart: () => fetch('/api/system/restart', { method: 'POST' }).then(r => r.json()),
};

/* -------------------- Toast -------------------- */
function toast(msg, type = 'ok') {
  const container = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = `toast ${type === 'err' ? 'err' : type === 'ok' ? 'ok' : ''}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transform = 'translateX(100%)'; }, 3500);
  setTimeout(() => el.remove(), 4000);
}

/* -------------------- Error parser -------------------- */
async function parseApiError(response) {
  let payload;
  try { payload = await response.json(); } catch { payload = {}; }
  const d = payload.detail;
  if (!d) return { message: `HTTP ${response.status}`, hint: null, code: null };
  if (typeof d === 'string') return { message: d, hint: null, code: null };
  return {
    message: d.message || 'Error tidak diketahui',
    hint: d.hint || null,
    code: d.code || null,
    traceback: d.traceback || null,
  };
}

function renderError(container, err) {
  let html = `<div class="empty-state" style="color:var(--pink); text-align:left; padding:16px">
    <div style="font-weight:600; margin-bottom:6px">❌ ${escapeHtml(err.message)}</div>`;
  if (err.hint) html += `<div style="font-size:12px; opacity:0.75; margin-bottom:6px">💡 ${escapeHtml(err.hint)}</div>`;
  if (err.code) html += `<div style="font-size:11px; opacity:0.5; font-family:monospace">code: ${escapeHtml(err.code)}</div>`;
  if (err.traceback && err.traceback.length) {
    html += `<details style="margin-top:8px; font-size:11px; opacity:0.6">
      <summary style="cursor:pointer">Technical details</summary>
      <pre style="white-space:pre-wrap; margin-top:6px; font-size:10px">${escapeHtml(err.traceback.join('\n'))}</pre>
    </details>`;
  }
  html += `</div>`;
  container.innerHTML = html;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

/* -------------------- Nav -------------------- */
const NAV_TITLES = {
  'short-maker': 'SHORT MAKER',
  'story-teller': 'TEXT TO STORY TELLING',
  'api-manager': 'API KEY MANAGER',
  'outputs': 'GENERATED OUTPUTS',
  'settings': 'SETTINGS',
};

function switchView(viewName) {
  document.querySelectorAll('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.view === viewName));
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.dataset.view === viewName));
  document.querySelectorAll('.panel-content').forEach(p => p.classList.toggle('hidden', p.dataset.panel !== viewName));
  document.getElementById('topbar-title').textContent = NAV_TITLES[viewName] || viewName.toUpperCase();
  const hasPanel = document.querySelector(`.panel-content[data-panel="${viewName}"]`);
  document.getElementById('app').classList.toggle('no-right', !hasPanel);
  if (viewName === 'api-manager') loadKeys();
  if (viewName === 'outputs') loadOutputs();
}

document.querySelectorAll('.nav-item').forEach(n => {
  n.addEventListener('click', () => switchView(n.dataset.view));
});

/* -------------------- Segmented control -------------------- */
function segValue(id) {
  const el = document.getElementById(id);
  const active = el?.querySelector('.seg__item.active');
  return active ? active.dataset.v : null;
}

document.querySelectorAll('.seg').forEach(seg => {
  seg.addEventListener('click', (e) => {
    const item = e.target.closest('.seg__item');
    if (!item) return;
    seg.querySelectorAll('.seg__item').forEach(i => i.classList.remove('active'));
    item.classList.add('active');
    if (seg.id === 'keys-mode') {
      API.setMode(item.dataset.mode).then(() => {
        toast(`Mode rotation: ${item.dataset.mode}`);
        loadKeys();
      });
    }
  });
});

/* -------------------- Tab handler -------------------- */
document.querySelectorAll('.tabs').forEach(tabs => {
  tabs.addEventListener('click', (e) => {
    const tab = e.target.closest('.tabs__tab');
    if (!tab) return;
    const targetContent = tabs.parentElement.querySelectorAll(':scope > .tab-content');
    tabs.querySelectorAll('.tabs__tab').forEach(t => t.classList.toggle('active', t === tab));
    targetContent.forEach(c => c.classList.toggle('active', c.dataset.tab === tab.dataset.tab));
  });
});

/* -------------------- Duration preset -------------------- */
document.getElementById('sm-duration').addEventListener('change', (e) => {
  document.getElementById('sm-custom-time').classList.toggle('hidden', e.target.value !== 'custom');
});

/* -------------------- Resource monitor -------------------- */
async function updateResources() {
  try {
    const d = await API.resources();
    const cpuBar = document.getElementById('cpu-bar');
    const ramBar = document.getElementById('ram-bar');
    cpuBar.style.width = d.cpu_percent + '%';
    ramBar.style.width = d.ram_percent + '%';
    cpuBar.className = 'monitor-bar__fill' + (d.cpu_percent > 85 ? ' crit' : d.cpu_percent > 60 ? ' warn' : '');
    ramBar.className = 'monitor-bar__fill' + (d.ram_percent > 85 ? ' crit' : d.ram_percent > 60 ? ' warn' : '');
    document.getElementById('cpu-val').textContent = Math.round(d.cpu_percent) + '%';
    document.getElementById('ram-val').textContent = Math.round(d.ram_percent) + '%';
  } catch (e) { /* silent */ }
}
setInterval(updateResources, 3000);
updateResources();

/* -------------------- API KEY MANAGER -------------------- */
async function loadKeys() {
  const data = await API.listKeys();
  const stats = data.stats;
  document.getElementById('keys-count').textContent = stats.total;
  document.getElementById('keys-active').textContent = stats.active;
  document.getElementById('keys-quota').textContent = stats.quota_exceeded;
  document.getElementById('keys-invalid').textContent = stats.invalid;
  document.getElementById('api-active').textContent = stats.active;
  document.getElementById('api-total').textContent = stats.total;
  document.getElementById('api-mode').textContent = data.mode;
  document.getElementById('badge-keys').textContent = `${stats.active}/${stats.total} KEYS`;
  const rpTotal = document.getElementById('rp-total');
  if (rpTotal) {
    rpTotal.textContent = stats.total;
    document.getElementById('rp-active').textContent = stats.active;
    document.getElementById('rp-quota').textContent = stats.quota_exceeded;
    document.getElementById('rp-invalid').textContent = stats.invalid;
  }
  document.querySelectorAll('#keys-mode .seg__item').forEach(i => {
    i.classList.toggle('active', i.dataset.mode === data.mode);
  });
  const list = document.getElementById('keys-list');
  if (!data.keys || !data.keys.length) {
    list.innerHTML = '<div class="empty-state">Belum ada API key. Tambah di atas.</div>';
    return;
  }
  list.innerHTML = data.keys.map((k, i) => {
    const last = k.last_used ? new Date(k.last_used * 1000).toLocaleTimeString() : '—';
    return `<div class="key-row">
      <div class="key-row__num">#${String(i + 1).padStart(2, '0')}</div>
      <div class="key-row__masked">${k.masked}</div>
      <div class="key-row__status ${k.status}">${k.status.replace('_', ' ')}</div>
      <div class="key-row__usage">used: ${k.usage_count} · last: ${last}</div>
      <button class="btn btn--sm btn--danger" data-masked="${k.masked}">✕</button>
    </div>`;
  }).join('');
  list.querySelectorAll('[data-masked]').forEach(btn => {
    btn.addEventListener('click', async () => {
      await API.removeKey(btn.dataset.masked);
      toast('Key dihapus');
      loadKeys();
    });
  });
}

document.getElementById('keys-add').addEventListener('click', async () => {
  const ta = document.getElementById('keys-textarea');
  const lines = ta.value.split('\n').map(l => l.trim()).filter(Boolean);
  if (!lines.length) return toast('Kosong', 'err');
  const r = await API.addKeys(lines);
  ta.value = '';
  toast(`${r.added} key ditambahkan`);
  loadKeys();
});

document.getElementById('keys-file').addEventListener('change', async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const r = await API.importKeys(f);
  toast(`${r.added} key diimport dari ${f.name}`);
  e.target.value = '';
  loadKeys();
});

document.getElementById('keys-clear').addEventListener('click', async () => {
  if (!confirm('Hapus SEMUA API key?')) return;
  const r = await API.clearKeys();
  toast(`${r.cleared} key dihapus`);
  loadKeys();
});

/* -------------------- SHORT MAKER: File preview -------------------- */
let uploadedFilePath = null;

document.getElementById('sm-file').addEventListener('change', async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  document.getElementById('sm-file-info').textContent = `Uploading: ${f.name} (${(f.size/1024/1024).toFixed(1)} MB)`;
  try {
    const r = await API.upload(f);
    uploadedFilePath = r.path;
    document.getElementById('sm-file-info').textContent = `✓ ${r.name} uploaded (${(r.size/1024/1024).toFixed(1)} MB)`;
    const preview = document.getElementById('sm-preview');
    const url = URL.createObjectURL(f);
    preview.innerHTML = `<video src="${url}" controls></video>`;
    toast('File uploaded');
  } catch (err) {
    toast('Upload gagal', 'err');
  }
});

document.getElementById('sm-url').addEventListener('input', (e) => {
  const url = e.target.value.trim();
  if (!url) return;
  const m = url.match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|embed\/|shorts\/))([^?&]+)/);
  if (m) {
    const vid = m[1];
    document.getElementById('sm-preview').innerHTML =
      `<iframe width="100%" height="100%" src="https://www.youtube.com/embed/${vid}" frameborder="0" allowfullscreen></iframe>`;
  }
});

/* -------------------- SHORT MAKER: Find Viral -------------------- */
document.getElementById('sm-find-viral').addEventListener('click', async () => {
  const sourceType = document.querySelector('.tabs__tab.active').dataset.tab;
  const source = sourceType === 'url' ? document.getElementById('sm-url').value.trim() : uploadedFilePath;
  if (!source) return toast('Masukkan URL atau upload file dulu', 'err');
  const btn = document.getElementById('sm-find-viral');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> Scanning...';
  const list = document.getElementById('sm-viral-list');
  list.innerHTML = '<div class="text-sm text-muted">AI sedang menganalisis video...</div>';
  try {
    const r = await API.smFindViral({
      source, source_type: sourceType,
      topic: document.getElementById('sm-topic').value,
      language: 'id',
    });
    if (!r.ok) {
      const err = await parseApiError(r);
      renderError(list, err);
      toast(err.message, 'err');
      return;
    }
    const data = await r.json();
    const moments = data.data?.moments || [];
    if (!moments.length) {
      list.innerHTML = '<div class="empty-state">Tidak ada momen terdeteksi.</div>';
    } else {
      list.innerHTML = moments.map(m => `
        <div class="viral-moment" data-start="${m.start_seconds}" data-end="${m.end_seconds}">
          <div class="viral-moment__score">${m.score || '—'}</div>
          <div class="viral-moment__body">
            <h4>${m.title}</h4>
            <p>${m.hook || ''}</p>
          </div>
          <div class="viral-moment__time">${fmtTime(m.start_seconds)} → ${fmtTime(m.end_seconds)}</div>
        </div>
      `).join('');
      list.querySelectorAll('.viral-moment').forEach(el => {
        el.addEventListener('click', () => {
          document.getElementById('sm-duration').value = 'custom';
          document.getElementById('sm-custom-time').classList.remove('hidden');
          document.getElementById('sm-start').value = fmtTime(+el.dataset.start);
          document.getElementById('sm-end').value = fmtTime(+el.dataset.end);
          toast('Momen dipilih ke Custom Time');
        });
      });
    }
  } catch (e) {
    renderError(list, { message: e.message || 'Network error', hint: 'Cek koneksi dan coba lagi.' });
    toast(e.message, 'err');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '◎ Cari Momen Viral (AI)';
  }
});

function fmtTime(sec) {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

function parseTime(str) {
  if (!str) return 0;
  const parts = str.split(':').map(Number);
  if (parts.length === 3) return parts[0]*3600 + parts[1]*60 + parts[2];
  if (parts.length === 2) return parts[0]*60 + parts[1];
  return Number(parts[0]) || 0;
}

/* -------------------- SHORT MAKER: Start -------------------- */
document.getElementById('sm-start').addEventListener('click', async () => {
  const sourceType = document.querySelector('.tabs__tab.active').dataset.tab;
  const source = sourceType === 'url' ?
    document.getElementById('sm-url').value.trim() : uploadedFilePath;
  if (!source) return toast('Masukkan URL atau upload file', 'err');
  const durPreset = document.getElementById('sm-duration').value;
  const body = {
    source, source_type: sourceType,
    transform_mode: document.getElementById('sm-mode').value,
    aspect: segValue('sm-aspect'),
    quality: segValue('sm-quality'),
    caption_ai: document.getElementById('sm-caption').checked,
    topic: document.getElementById('sm-topic').value,
    duration_preset: durPreset,
    custom_start: durPreset === 'custom' ? parseTime(document.getElementById('sm-start').value) : 0,
    custom_end: durPreset === 'custom' ? parseTime(document.getElementById('sm-end').value) : 0,
    encoding: segValue('sm-encoding'),
    use_gpu: document.getElementById('sm-gpu').checked,
    bypass_copyright: document.getElementById('sm-bypass').checked,
    language: 'id',
  };
  const btn = document.getElementById('sm-start');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> PROCESSING...';
  document.getElementById('sm-log').innerHTML = '';
  document.getElementById('sm-result').innerHTML = '';
  try {
    const r = await API.smStart(body);
    await pollJob(r.job_id, 'sm-log', (result) => renderShortResult(result));
  } catch (e) {
    toast(e.message, 'err');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '◈ INITIALIZE CONVERSION ◈';
  }
});

function renderShortResult(result) {
  document.getElementById('sm-result').innerHTML = `
    <div class="result-card">
      <h3>✓ CONVERSION COMPLETE</h3>
      <video src="${result.output_url}" controls style="width:100%;max-height:300px;border:1px solid var(--border-glow)"></video>
      <div class="divider"></div>
      <div class="meta-row"><span class="meta-row__label">JUDUL</span><span class="meta-row__value">${result.title}</span></div>
      <div class="meta-row"><span class="meta-row__label">DURASI</span><span class="meta-row__value">${result.duration.toFixed(1)} detik</span></div>
      <div class="meta-row"><span class="meta-row__label">SEGMEN</span><span class="meta-row__value">${fmtTime(result.start_seconds)} → ${fmtTime(result.end_seconds)}</span></div>
      <div class="meta-row"><span class="meta-row__label">DESKRIPSI</span><span class="meta-row__value">${result.description}</span></div>
      <div class="meta-row"><span class="meta-row__label">TAGS</span><span class="meta-row__value">${(result.tags||[]).map(t=>`<span class="tag-chip">#${t}</span>`).join('')}</span></div>
      ${result.pinned_comment ? `<div class="meta-row"><span class="meta-row__label">PIN COMMENT</span><span class="meta-row__value">${result.pinned_comment}</span></div>` : ''}
      <div class="divider"></div>
      <a class="btn" href="${result.output_url}" download>⤓ DOWNLOAD VIDEO</a>
    </div>`;
}

/* -------------------- STORY TELLER -------------------- */
function collectStoryOpts() {
  return {
    title: document.getElementById('st-title').value.trim(),
    genre: document.getElementById('st-genre').value,
    style: document.getElementById('st-style').value,
    length: document.getElementById('st-length').value,
    language: document.getElementById('st-language').value,
    tts_voice: segValue('st-voice'),
    tts_speed: segValue('st-speed'),
    bgm_mood: document.getElementById('st-bgm').value,
    aspect: segValue('st-aspect'),
    quality: segValue('st-quality'),
    use_footage: document.getElementById('st-footage').checked,
  };
}

document.getElementById('st-preview').addEventListener('click', async () => {
  const opts = collectStoryOpts();
  if (!opts.title) return toast('Isi judul/topik dulu', 'err');
  const btn = document.getElementById('st-preview');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> Generating...';
  document.getElementById('st-script-list').innerHTML = '<div class="text-sm text-muted">AI sedang menulis naskah...</div>';
  try {
    const r = await API.stPreview(opts);
    if (!r.ok) {
      const err = await parseApiError(r);
      renderError(document.getElementById('st-script-list'), err);
      toast(err.message, 'err');
      return;
    }
    const data = await r.json();
    const scenes = data.scenes || [];
    const list = document.getElementById('st-script-list');
    if (!scenes.length) {
      list.innerHTML = '<div class="empty-state">Naskah kosong, coba generate ulang.</div>';
    } else {
      list.innerHTML = scenes.map((s, i) => `
        <div class="scene-card">
          <div class="scene-card__num">SCENE ${String(i+1).padStart(2,'0')}</div>
          <div>${s.text}</div>
          <div class="scene-card__keyword">🎬 ${s.keyword}</div>
        </div>`).join('');
    }
    toast(`${scenes.length} scene dibuat`);
  } catch (e) {
    renderError(document.getElementById('st-script-list'), { message: e.message || 'Network error', hint: 'Cek koneksi dan coba lagi.' });
    toast(e.message, 'err');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '◎ Preview Naskah';
  }
});

document.getElementById('st-start').addEventListener('click', async () => {
  const opts = collectStoryOpts();
  if (!opts.title) return toast('Isi judul/topik dulu', 'err');
  const btn = document.getElementById('st-start');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> RENDERING...';
  document.getElementById('st-log').innerHTML = '';
  document.getElementById('st-result').innerHTML = '';
  try {
    const r = await API.stStart(opts);
    await pollJob(r.job_id, 'st-log', (result) => renderStoryResult(result));
  } catch (e) {
    toast(e.message, 'err');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '◈ GENERATE STORY VIDEO ◈';
  }
});

function renderStoryResult(result) {
  document.getElementById('st-result').innerHTML = `
    <div class="result-card">
      <h3>✓ STORY GENERATED</h3>
      <video src="${result.output_url}" controls style="width:100%;max-height:300px;border:1px solid var(--border-glow)"></video>
      <div class="divider"></div>
      <div class="meta-row"><span class="meta-row__label">DURASI</span><span class="meta-row__value">${result.duration.toFixed(1)} detik</span></div>
      <div class="meta-row"><span class="meta-row__label">SCENES</span><span class="meta-row__value">${result.scenes?.length || 0}</span></div>
      <div class="divider"></div>
      <a class="btn" href="${result.output_url}" download>⤓ DOWNLOAD VIDEO</a>
    </div>`;
}

/* -------------------- Job polling -------------------- */
async function pollJob(jid, logElId, onDone) {
  const logEl = document.getElementById(logElId);
  const ws = tryOpenWebSocket(jid);
  return new Promise((resolve, reject) => {
    if (ws) {
      ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        (data.logs || []).forEach(l => appendLog(logEl, l.msg));
        if (data.status === 'done') {
          appendLog(logEl, '✓ JOB COMPLETE', 'ok');
          onDone?.(data.result);
          resolve(data);
        } else if (data.status === 'error') {
          appendLog(logEl, '✗ ' + (data.error || 'Unknown error'), 'err');
          toast(data.error, 'err');
          reject(new Error(data.error || 'job failed'));
        }
      };
      ws.onerror = () => fallbackPoll();
    } else {
      fallbackPoll();
    }
    function fallbackPoll() {
      let seen = 0;
      const interval = setInterval(async () => {
        try {
          const data = await API.jobStatus(jid);
          const newLogs = data.progress.slice(seen);
          seen = data.progress.length;
          newLogs.forEach(l => appendLog(logEl, l.msg));
          if (data.status === 'done') {
            clearInterval(interval);
            appendLog(logEl, '✓ JOB COMPLETE', 'ok');
            onDone?.(data.result);
            resolve(data);
          } else if (data.status === 'error') {
            clearInterval(interval);
            appendLog(logEl, '✗ ' + (data.error || 'error'), 'err');
            toast(data.error, 'err');
            reject(new Error(data.error));
          }
        } catch (e) {
          clearInterval(interval);
          reject(e);
        }
      }, 1200);
    }
  });
}

function tryOpenWebSocket(jid) {
  try {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    return new WebSocket(`${proto}://${location.host}/ws/job/${jid}`);
  } catch (e) { return null; }
}

function appendLog(el, msg, cls = '') {
  const time = new Date().toLocaleTimeString();
  const div = document.createElement('div');
  div.className = 'log-entry ' + cls;
  div.innerHTML = `<span class="log-entry__time">${time}</span><span class="log-entry__msg">${msg}</span>`;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
}

/* -------------------- OUTPUTS -------------------- */
async function loadOutputs() {
  const data = await API.listOutputs();
  const list = document.getElementById('outputs-list');
  if (!data.items || !data.items.length) {
    list.innerHTML = '<div class="empty-state">Belum ada output.</div>';
    return;
  }
  list.innerHTML = data.items.map(item => `
    <div class="key-row" style="grid-template-columns: 1fr auto auto">
      <div>
        <div class="key-row__masked">${item.name}</div>
        <div class="text-xs text-muted">${item.size_mb} MB · ${new Date(item.modified*1000).toLocaleString()}</div>
      </div>
      <a class="btn btn--sm" href="${item.url}" target="_blank">▶ OPEN</a>
      <a class="btn btn--sm btn--ghost" href="${item.url}" download>⤓ DOWNLOAD</a>
    </div>`).join('');
}

/* -------------------- Restart/Shutdown Handlers -------------------- */
const overlay = document.getElementById('sys-overlay');
const overlayIcon = document.getElementById('overlay-icon');
const overlayTitle = document.getElementById('overlay-title');
const overlayMsg = document.getElementById('overlay-msg');
const overlaySpinner = document.getElementById('overlay-spinner');

function showOverlay(mode) {
  if (mode === 'restart') {
    overlayIcon.textContent = '⟳';
    overlayTitle.textContent = 'RESTARTING...';
    overlayMsg.textContent = 'Menunggu server kembali online...';
    overlaySpinner.style.display = 'block';
  } else {
    overlayIcon.textContent = '⏻';
    overlayTitle.textContent = 'SERVER OFF';
    overlayMsg.textContent = 'Server telah dimatikan. Tutup tab ini atau jalankan ulang manual.';
    overlaySpinner.style.display = 'none';
  }
  overlay.classList.add('show');
}

async function doRestart() {
  if (!confirm('Restart server sekarang?')) return;
  showOverlay('restart');
  try {
    await API.restart();
  } catch (_) {}
  let attempts = 0;
  const poll = setInterval(async () => {
    attempts++;
    try {
      const r = await fetch('/api/health');
      if (r.ok) {
        clearInterval(poll);
        overlay.classList.remove('show');
        toast('✓ Server berhasil restart', 'ok');
        loadKeys();
      }
    } catch (_) {}
    if (attempts > 40) {
      clearInterval(poll);
      overlayMsg.textContent = 'Server tidak merespons. Coba refresh halaman manual.';
    }
  }, 1000);
}

async function doShutdown() {
  if (!confirm('Matikan server? Kamu perlu jalankan ulang manual dari terminal.')) return;
  try {
    await API.shutdown();
  } catch (_) {}
  showOverlay('shutdown');
}

// Bind restart/shutdown buttons
['btn-restart', 'settings-restart', 'rp-restart'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('click', doRestart);
});
['btn-shutdown', 'settings-shutdown', 'rp-shutdown'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('click', doShutdown);
});

/* -------------------- INIT -------------------- */
(async function init() {
  try {
    const h = await API.health();
    if (h.version) {
      document.getElementById('badge-version').textContent = 'v' + h.version;
      const sv = document.getElementById('s-version');
      if (sv) sv.textContent = h.version;
    }
    const actualPort = location.port || (location.protocol === 'https:' ? '443' : '80');
    const serverPort = h.port ? String(h.port) : actualPort;
    ['server-port', 's-port'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = serverPort;
    });
  } catch (e) {
    console.error('Init health check failed:', e);
  }
  try {
    await loadKeys();
  } catch (e) {
    console.error(e);
  }
})();
