let state = { q: '', page: 1, page_size: 20, sort: 'relevance' };

async function search() {
  const params = new URLSearchParams();
  params.set('q', document.getElementById('q').value);
  params.set('page', state.page);
  params.set('page_size', state.page_size);
  params.set('sort', document.getElementById('sort').value);
  const speaker = document.getElementById('speaker').value.trim();
  const start = document.getElementById('start').value;
  const end = document.getElementById('end').value;
  const min_duration = document.getElementById('min_duration').value;
  if (speaker) params.set('speaker', speaker);
  if (start) params.set('start', start);
  if (end) params.set('end', end);
  if (min_duration) params.set('min_duration', min_duration);
  const res = await fetch('/api/search?' + params.toString());
  const data = await res.json();
  renderResults(data);
}

function renderResults(data) {
  const el = document.getElementById('results');
  el.innerHTML = '';
  data.items.forEach(item => {
    const d = document.createElement('div');
    d.className = 'result';
    d.innerHTML = `<h3><a href="#" data-id="${item.id}" class="open">${item.title || item.id}</a></h3>
      <div class="meta">${item.date || ''} — ${(item.top_speakers||[]).join(', ')}</div>
      <div class="snippet">${item.snippet || ''}</div>`;
    el.appendChild(d);
  });
  document.getElementById('pageinfo').textContent = `Page ${data.page} of ${Math.ceil(data.total / data.page_size) || 1}`;
  el.querySelectorAll('a.open').forEach(a => a.addEventListener('click', async (e) => {
    e.preventDefault();
    const id = e.target.getAttribute('data-id');
    await openDetail(id);
  }));
}

async function openDetail(id) {
  const res = await fetch('/api/transcript/' + id);
  const data = await res.json();
  const el = document.getElementById('detail');
  const dl = `/api/transcript/${id}.txt`;
  const dj = `/api/transcript/${id}`;
  el.innerHTML = `<div class="detail-head"><h2>${data.title || id}</h2>
    <div class="d-actions"><a href="${dl}" target="_blank">Download .txt</a> | <a href="${dj}" target="_blank">Download .json</a></div>
    <div class="d-meta">${data.date || ''}</div></div>`;
  const list = document.createElement('div');
  list.className = 'segments';
  data.segments.forEach(s => {
    const div = document.createElement('div');
    div.className = 'segment';
    const st = fmt(s.start_time), et = fmt(s.end_time || s.start_time);
    div.innerHTML = `<div class="seg-meta">${st} - ${et} <span class="speaker">${s.speaker_name || ''}</span></div><div class="seg-text">${escapeHtml(s.text)}</div>`;
    list.appendChild(div);
  });
  el.appendChild(list);
  el.classList.remove('hidden');
  window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'});
}

function fmt(s) {
  s = s || 0; const h = Math.floor(s/3600), m=Math.floor((s%3600)/60), sec=s%60;
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
}

function escapeHtml(str) {
  return (str || '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

document.getElementById('searchBtn').addEventListener('click', () => { state.page = 1; search(); });
document.getElementById('q').addEventListener('keydown', (e) => { if (e.key === 'Enter') { state.page=1; search(); }});
document.getElementById('prev').addEventListener('click', () => { if (state.page>1) { state.page--; search(); }});
document.getElementById('next').addEventListener('click', () => { state.page++; search(); });

// initial
search();

