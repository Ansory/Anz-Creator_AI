/* ================================================================
   ANZ-CREATOR — Frontend
   Vanilla JS, no framework. Single-file app logic.
   ================================================================ */

/* -------------------- Security Utilities -------------------- */
// Mencegah DOM XSS saat merender data dari AI/Backend ke innerHTML
function escapeHtml(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

/* -------------------- API -------------------- */
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
  el.className = `toast ${type === 'err' ? 'err' : type === 'ok' ? 'ok' : type === 'warn' ? 'warn' : ''}`;
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

/* -------------------- Nav -------------------- */
const NAV_TITLES = {
  'short-maker': 'SHORT MAKER',
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
        toast(`Mode rotation: ${escapeHtml(item.dataset.mode)}`);
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

/* -------------------- SHORT MAKER: Mode cards -------------------- */
function getTransformMode() {
  const active = document.querySelector('#sm-mode-grid .mode-card.active, #sm-mode-normal.active');
  return active ? active.dataset.mode : 'blur';
}

document.getElementById('sm-mode-grid').addEventListener('click', (e) => {
  const card = e.target.closest('.mode-card');
  if (!card) return;
  document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('active'));
  card.classList.add('active');
  document.getElementById('sm-aspect-field').classList.toggle('hidden', card.dataset.mode === 'original');
});

document.getElementById('sm-mode-normal').addEventListener('click', () => {
  document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('active'));
  document.getElementById('sm-mode-normal').classList.add('active');
  document.getElementById('sm-aspect-field').classList.add('hidden');
});

/* -------------------- SHORT MAKER: Caption toggle -------------------- */
document.getElementById('sm-caption').addEventListener('change', (e) => {
  document.getElementById('sm-caption-opts').classList.toggle('hidden', !e.target.checked);
});

/* -------------------- SHORT MAKER: Word density slider -------------------- */
document.getElementById('sm-word-density').addEventListener('input', (e) => {
  document.getElementById('sm-density-badge').textContent = e.target.value + ' Kata';
});

/* -------------------- SHORT MAKER: Time input helpers -------------------- */
function getTimeSeconds(prefix) {
  const hh = parseInt(document.getElementById(prefix + '-hh').value || '0', 10) || 0;
  const mm = parseInt(document.getElementById(prefix + '-mm').value || '0', 10) || 0;
  const ss = parseInt(document.getElementById(prefix + '-ss').value || '0', 10) || 0;
  return hh * 3600 + mm * 60 + ss;
}

function setTimeBoxes(prefix, totalSeconds) {
  totalSeconds = Math.max(0, Math.floor(totalSeconds));
  document.getElementById(prefix + '-hh').value = String(Math.floor(totalSeconds / 3600)).padStart(2, '0');
  document.getElementById(prefix + '-mm').value = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, '0');
  document.getElementById(prefix + '-ss').value = String(totalSeconds % 60).padStart(2, '0');
}

function updateDurationBadge() {
  const start = getTimeSeconds('sm-start');
  const end = getTimeSeconds('sm-end');
  const badge = document.getElementById('sm-duration-badge');
  if (end > start) {
    const dur = end - start;
    badge.textContent = String(Math.floor(dur / 60)).padStart(2, '0') + ':' + String(dur % 60).padStart(2, '0');
    badge.style.color = 'var(--green)';
  } else {
    badge.textContent = '00:00';
    badge.style.color = '';
  }
}

['sm-start-hh','sm-start-mm','sm-start-ss','sm-end-hh','sm-end-mm','sm-end-ss'].forEach(id => {
  const el = document.getElementById(id);
  el.addEventListener('input', () => {
    if (el.value.length >= 2) {
      const next = el.nextElementSibling?.nextElementSibling;
      if (next && next.tagName === 'INPUT') next.focus();
    }
    updateDurationBadge();
  });
});

document.getElementById('sm-start-set').addEventListener('click', () => {
  updateDurationBadge();
  toast('Waktu mulai: ' + fmtTime(getTimeSeconds('sm-start')));
});

document.getElementById('sm-end-set').addEventListener('click', () => {
  const s = getTimeSeconds('sm-start');
  const e = getTimeSeconds('sm-end');
  updateDurationBadge();
  if (e > 0 && e <= s) toast('⚠ Waktu selesai harus lebih besar dari waktu mulai', 'warn');
  else toast('Waktu selesai: ' + fmtTime(e));
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
  document.getElementById('api-mode').textContent = escapeHtml(data.mode);
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
      <div class="key-row__masked">${escapeHtml(k.masked)}</div>
      <div class="key-row__status ${escapeHtml(k.status)}">${escapeHtml(k.status.replace('_', ' '))}</div>
      <div class="key-row__usage">used: ${k.usage_count} · last: ${last}</div>
      <button class="btn btn--sm btn--danger" data-masked="${escapeHtml(k.masked)}">✕</button>
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
  toast(`${r.added} key diimport dari ${escapeHtml(f.name)}`);
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
    document.getElementById('sm-file-info').textContent = `✓ ${escapeHtml(r.name)} uploaded (${(r.size/1024/1024).toFixed(1)} MB)`;
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
    const vid = escapeHtml(m[1]);
    document.getElementById('sm-preview').innerHTML =
      `<iframe width="100%" height="100%" src="https://www.youtube.com/embed/${vid}" frameborder="0" allowfullscreen></iframe>`;
  }
});

function fmtTime(sec) {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
}

/* -------------------- SHORT MAKER: Viral moments -------------------- */
let _viralMoments = [];
let _selectedMoments = new Set();

const SCORE_LABEL_COLORS = {
  'HOOK KUAT': 'var(--pink)',
  'PLOT TWIST': 'var(--purple)',
  'FAKTA MENGEJUTKAN': 'var(--amber)',
  'EMOSI TINGGI': 'var(--cyan)',
  'VIRAL POTENTIAL': 'var(--green)',
};

function updateSelectedCount() {
  document.getElementById('sm-selected-count').textContent = _selectedMoments.size;
}

function syncSelectAll() {
  const allChecked = _viralMoments.length > 0 && _viralMoments.every((_, i) => _selectedMoments.has(i));
  document.getElementById('sm-select-all').checked = allChecked;
}

function renderViralMoments(moments) {
  _viralMoments = moments || [];
  _selectedMoments = new Set();
  updateSelectedCount();

  document.getElementById('sm-viral-panel').classList.remove('hidden');
  document.getElementById('sm-viral-empty').classList.add('hidden');

  const list = document.getElementById('sm-viral-list');

  if (!_viralMoments.length) {
    list.innerHTML = '<div class="empty-state">Tidak ada momen viral terdeteksi.</div>';
    return;
  }

  list.innerHTML = _viralMoments.map((m, i) => {
    const scoreColor = SCORE_LABEL_COLORS[m.score_label] || 'var(--cyan)';
    const dur = Math.round((m.end_seconds || 0) - (m.start_seconds || 0));
    return '<div class="viral-card" data-index="' + i + '">'
      + '<div class="viral-card__head">'
      + '<label class="check check--sm" style="flex-shrink:0"><input type="checkbox" class="viral-check" data-index="' + i + '"><span class="check__box"></span></label>'
      + '<span class="viral-card__num">#' + String(i + 1).padStart(2, '0') + '</span>'
      + '<span class="viral-card__title">' + escapeHtml(m.title || '—') + '</span>'
      + '<span class="score-badge" style="color:' + scoreColor + ';border-color:' + scoreColor + '">' + escapeHtml(m.score_label || 'VIRAL') + '</span>'
      + '<span class="duration-pill">' + fmtTime(m.start_seconds || 0) + ' · ' + dur + 's</span>'
      + '</div>'
      + (m.hook_quote ? '<div class="viral-card__quote">"' + escapeHtml(m.hook_quote) + '"</div>' : '')
      + (m.description ? '<div class="viral-card__desc">' + escapeHtml(m.description) + '</div>' : '')
      + (m.caption_suggestion ? '<details class="viral-card__caption-detail"><summary class="viral-card__caption-toggle">📝 Saran Caption</summary><div class="viral-card__caption">' + escapeHtml(m.caption_suggestion) + '</div></details>' : '')
      + '<div class="viral-card__actions">'
      + '<button class="btn btn--sm btn--ghost" data-action="set-time" data-index="' + i + '">⊙ Set Waktu</button>'
      + '<button class="btn btn--sm" data-action="convert" data-index="' + i + '">◈ Convert</button>'
      + '<button class="btn btn--sm btn--ghost" data-action="copy" data-index="' + i + '">📋 Salin</button>'
      + '</div></div>';
  }).join('');

  list.querySelectorAll('.viral-check').forEach(cb => {
    cb.addEventListener('change', () => {
      const idx = parseInt(cb.dataset.index, 10);
      cb.checked ? _selectedMoments.add(idx) : _selectedMoments.delete(idx);
      updateSelectedCount();
      syncSelectAll();
    });
  });

  list.querySelectorAll('[data-action]').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.dataset.index, 10);
      const m = _viralMoments[idx];
      if (!m) return;
      if (btn.dataset.action === 'set-time') {
        setTimeBoxes('sm-start', m.start_seconds || 0);
        setTimeBoxes('sm-end', m.end_seconds || 0);
        updateDurationBadge();
        toast('Momen #' + (idx + 1) + ' → ' + fmtTime(m.start_seconds || 0) + ' – ' + fmtTime(m.end_seconds || 0));
      } else if (btn.dataset.action === 'convert') {
        setTimeBoxes('sm-start', m.start_seconds || 0);
        setTimeBoxes('sm-end', m.end_seconds || 0);
        updateDurationBadge();
        startConversion();
      } else if (btn.dataset.action === 'copy') {
        const text = m.caption_suggestion || m.description || m.title || '';
        navigator.clipboard.writeText(text).then(() => toast('Caption disalin!')).catch(() => toast('Gagal salin', 'err'));
      }
    });
  });

  document.getElementById('sm-select-all').checked = false;
}

document.getElementById('sm-select-all').addEventListener('change', (e) => {
  _viralMoments.forEach((_, i) => e.target.checked ? _selectedMoments.add(i) : _selectedMoments.delete(i));
  document.querySelectorAll('.viral-check').forEach(cb => { cb.checked = e.target.checked; });
  updateSelectedCount();
});

document.getElementById('sm-bulk-copy').addEventListener('click', () => {
  if (!_selectedMoments.size) return toast('Pilih momen dulu', 'warn');
  const text = [..._selectedMoments].sort().map(i => {
    const m = _viralMoments[i];
    return '#' + (i + 1) + ' ' + m.title + '\n' + fmtTime(m.start_seconds || 0) + ' → ' + fmtTime(m.end_seconds || 0) + '\n' + (m.caption_suggestion || m.description || '');
  }).join('\n\n---\n\n');
  navigator.clipboard.writeText(text).then(() => toast(_selectedMoments.size + ' caption disalin!')).catch(() => toast('Gagal salin', 'err'));
});

document.getElementById('sm-bulk-convert').addEventListener('click', async () => {
  if (!_selectedMoments.size) return toast('Pilih momen dulu', 'warn');
  toast('Memulai convert ' + _selectedMoments.size + ' video...');
  for (const idx of [..._selectedMoments].sort()) {
    const m = _viralMoments[idx];
    setTimeBoxes('sm-start', m.start_seconds || 0);
    setTimeBoxes('sm-end', m.end_seconds || 0);
    updateDurationBadge();
    await startConversion();
  }
});

document.getElementById('sm-viral-close').addEventListener('click', () => {
  document.getElementById('sm-viral-panel').classList.add('hidden');
  document.getElementById('sm-viral-empty').classList.remove('hidden');
});

document.getElementById('sm-viral-refresh').addEventListener('click', () => {
  document.getElementById('sm-find-viral').click();
});

/* -------------------- SHORT MAKER: Find Viral -------------------- */
document.getElementById('sm-find-viral').addEventListener('click', async () => {
  const sourceType = document.querySelector('.tabs__tab.active').dataset.tab;
  const source = sourceType === 'url' ? document.getElementById('sm-url').value.trim() : uploadedFilePath;
  if (!source) return toast('Masukkan URL atau upload file dulu', 'err');

  const btn = document.getElementById('sm-find-viral');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> Scanning...';

  try {
    const r = await API.smFindViral({
      source, source_type: sourceType,
      topic: document.getElementById('sm-topic').value,
      duration_preset: document.getElementById('sm-duration').value,
      language: document.getElementById('sm-caption-language').value,
    });

    if (!r.ok) {
      const err = await parseApiError(r);
      toast(err.message, 'err');
      renderViralMoments([]);
      renderError(document.getElementById('sm-viral-list'), err);
      return;
    }

    const data = await r.json();
    const moments = data.data?.moments || [];
    renderViralMoments(moments);
    if (moments.length) toast(moments.length + ' momen viral ditemukan!', 'ok');
    else toast('Tidak ada momen terdeteksi', 'warn');
  } catch (e) {
    toast(e.message || 'Network error', 'err');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '✨ Cari Momen Viral (AI)';
  }
});

/* -------------------- SHORT MAKER: Conversion -------------------- */
async function startConversion() {
  const sourceType = document.querySelector('.tabs__tab.active').dataset.tab;
  const source = sourceType === 'url' ? document.getElementById('sm-url').value.trim() : uploadedFilePath;
  if (!source) { toast('Masukkan URL atau upload file', 'err'); return; }

  const startSec = getTimeSeconds('sm-start');
  const endSec = getTimeSeconds('sm-end');
  if (endSec > 0 && endSec <= startSec) {
    toast('⚠ Waktu selesai harus lebih besar dari waktu mulai', 'warn');
    return;
  }

  const captionOn = document.getElementById('sm-caption').checked;
  const transformMode = getTransformMode();

  const body = {
    source, source_type: sourceType,
    transform_mode: transformMode,
    aspect: transformMode === 'original' ? '9:16' : document.getElementById('sm-aspect').value,
    quality: document.getElementById('sm-quality').value,
    caption_ai: captionOn,
    caption_style: captionOn ? document.getElementById('sm-caption-style').value : 'classic_white',
    caption_language: captionOn ? document.getElementById('sm-caption-language').value : 'original',
    animate_text: captionOn && document.getElementById('sm-animate-text').checked,
    word_density: captionOn ? parseInt(document.getElementById('sm-word-density').value, 10) : 2,
    topic: document.getElementById('sm-topic').value,
    duration_preset: document.getElementById('sm-duration').value,
    custom_start: startSec,
    custom_end: endSec,
    encoding: segValue('sm-encoding'),
    use_gpu: document.getElementById('sm-gpu').checked,
    bypass_copyright: document.getElementById('sm-bypass').checked,
    language: document.getElementById('sm-caption-language').value,
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
}

document.getElementById('sm-start').addEventListener('click', startConversion);

function renderShortResult(result) {
  const tagsHtml = (result.tags || []).map(t => '<span class="tag-chip">#' + escapeHtml(t) + '</span>').join('');
  const captionWarn = (result.caption_applied === false)
    ? '<div style="color:var(--amber);font-size:12px;margin-bottom:8px">⚠ Caption gagal diburn — video tanpa subtitle</div>'
    : '';
  document.getElementById('sm-result').innerHTML = `
    <div class="result-card">
      <h3>✓ CONVERSION COMPLETE</h3>
      ${captionWarn}
      <video src="${escapeHtml(result.output_url)}" controls style="width:100%;max-height:300px;border:1px solid var(--border-glow)"></video>
      <div class="divider"></div>
      <div class="meta-row"><span class="meta-row__label">JUDUL</span><span class="meta-row__value">${escapeHtml(result.title)}</span></div>
      <div class="meta-row"><span class="meta-row__label">DURASI</span><span class="meta-row__value">${result.duration.toFixed(1)} detik</span></div>
      <div class="meta-row"><span class="meta-row__label">SEGMEN</span><span class="meta-row__value">${fmtTime(result.start_seconds)} → ${fmtTime(result.end_seconds)}</span></div>
      <div class="meta-row"><span class="meta-row__label">DESKRIPSI</span><span class="meta-row__value">${escapeHtml(result.description)}</span></div>
      <div class="meta-row"><span class="meta-row__label">TAGS</span><span class="meta-row__value">${tagsHtml}</span></div>
      ${result.pinned_comment ? '<div class="meta-row"><span class="meta-row__label">PIN COMMENT</span><span class="meta-row__value">' + escapeHtml(result.pinned_comment) + '</span></div>' : ''}
      <div class="divider"></div>
      <a class="btn" href="${escapeHtml(result.output_url)}" download>⤓ DOWNLOAD VIDEO</a>
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
          appendLog(logEl, '✗ ' + escapeHtml(data.error || 'Unknown error'), 'err');
          toast(escapeHtml(data.error), 'err');
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
            appendLog(logEl, '✗ ' + escapeHtml(data.error || 'error'), 'err');
            toast(escapeHtml(data.error), 'err');
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
    return new WebSocket(`${proto}://${location.host}/ws/job/${encodeURIComponent(jid)}`);
  } catch (e) { return null; }
}

function appendLog(el, msg, cls = '') {
  const time = new Date().toLocaleTimeString();
  const div = document.createElement('div');
  div.className = 'log-entry ' + escapeHtml(cls);
  div.innerHTML = `<span class="log-entry__time">${escapeHtml(time)}</span><span class="log-entry__msg">${escapeHtml(msg)}</span>`;
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
        <div class="key-row__masked">${escapeHtml(item.name)}</div>
        <div class="text-xs text-muted">${item.size_mb} MB · ${new Date(item.modified*1000).toLocaleString()}</div>
      </div>
      <a class="btn btn--sm" href="${escapeHtml(item.url)}" target="_blank">▶ OPEN</a>
      <a class="btn btn--sm btn--ghost" href="${escapeHtml(item.url)}" download>⤓ DOWNLOAD</a>
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
  try { await API.restart(); } catch (_) {}
  
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
  try { await API.shutdown(); } catch (_) {}
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
      document.getElementById('badge-version').textContent = 'v' + escapeHtml(h.version);
      const sv = document.getElementById('s-version');
      if (sv) sv.textContent = escapeHtml(h.version);
    }
    const actualPort = location.port || (location.protocol === 'https:' ? '443' : '80');
    const serverPort = h.port ? String(h.port) : actualPort;
    ['server-port', 's-port'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = escapeHtml(serverPort);
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
