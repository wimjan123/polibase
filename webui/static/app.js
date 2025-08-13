const state = { q: '', page: 1, page_size: 20, selected: null, s: { q: '', start: '', end: '', speaker: '', page: 1, page_size: 20 } };

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error('Request failed');
  return await res.json();
}

function qs(id){ return document.getElementById(id); }

function fmt(t){
  t = t || 0; const h = Math.floor(t/3600), m = Math.floor((t%3600)/60), s = t%60;
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

async function loadList() {
  const params = new URLSearchParams({ page: state.page, page_size: state.page_size });
  if (state.q) params.set('q', state.q);
  const data = await fetchJSON('/api/transcripts?' + params.toString());
  renderList(data);
}

function renderList(data){
  const list = qs('list');
  list.innerHTML = '';
  data.items.forEach(item => {
    const el = document.createElement('div');
    el.className = 'item';
    el.innerHTML = `
      <div class="t">${escapeHtml(item.title || item.id)}</div>
      <div class="m">${item.date || ''} • ${item.segments || 0} segments</div>
      <div class="chips">${(item.top_speakers||[]).map(s => `<span class="chip">${escapeHtml(s)}</span>`).join('')}</div>
    `;
    el.addEventListener('click', () => openDetail(item.id));
    list.appendChild(el);
  });
  qs('pageinfo').textContent = `Page ${data.page} / ${Math.max(1, Math.ceil(data.total / data.page_size))}`;
}

async function openDetail(id){
  state.selected = id;
  const data = await fetchJSON('/api/transcripts/' + encodeURIComponent(id));
  qs('title').textContent = data.title || id;
  const meta = [];
  if (data.date) meta.push(data.date);
  if (data.url) meta.push(`<a href="${data.url}" target="_blank">Source</a>`);
  qs('meta').innerHTML = meta.join(' • ');
  const chips = (data.speakers||[]).slice(0,5).map(s => `<span class="chip" title="${s.seconds||0}s">${escapeHtml(s.name || '')}</span>`).join('');
  qs('chips').innerHTML = chips;
  // actions
  qs('actions').hidden = false;
  qs('dlTxt').href = `/api/transcripts/${encodeURIComponent(id)}.txt`;
  qs('dlJson').href = `/api/transcripts/${encodeURIComponent(id)}`;

  const wrap = qs('segments');
  wrap.innerHTML = '';
  (data.segments||[]).forEach(seg => {
    const el = document.createElement('div');
    el.className = 'seg';
    const st = fmt(seg.start_time), et = fmt(seg.end_time || seg.start_time);
    el.innerHTML = `
      <div class="time">${st} – ${et}</div>
      <div>
        <div class="speaker">${escapeHtml(seg.speaker_name || '')}</div>
        <div class="text">${escapeHtml(seg.text || '')}</div>
      </div>
    `;
    wrap.appendChild(el);
  });
  // Scroll main content to top on selection
  document.querySelector('.content').scrollTo({ top: 0, behavior: 'smooth' });
}

function escapeHtml(s){
  return (s||'').replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

// Events
qs('q').addEventListener('input', (e)=>{
  state.q = e.target.value.trim();
  state.page = 1;
  loadList();
});
qs('prev').addEventListener('click', ()=>{ if(state.page>1){ state.page--; loadList(); }});
qs('next').addEventListener('click', ()=>{ state.page++; loadList(); });

// Init
loadList();

// --- Segment FTS search ---
async function searchSegments(){
  const params = new URLSearchParams();
  if (state.s.q) params.set('q', state.s.q);
  if (state.s.speaker) params.set('speaker', state.s.speaker);
  if (state.s.start) params.set('start', state.s.start);
  if (state.s.end) params.set('end', state.s.end);
  params.set('page', state.s.page);
  params.set('page_size', state.s.page_size);
  const data = await fetchJSON('/api/search?' + params.toString());
  renderSearchResults(data);
}

function renderSearchResults(data){
  const wrap = document.getElementById('sresults');
  const list = document.getElementById('sitems');
  list.innerHTML = '';
  data.items.forEach(it => {
    const el = document.createElement('div');
    el.className = 'result';
    el.innerHTML = `
      <h3><a href="#" data-id="${it.id}" class="open">${escapeHtml(it.title || it.id)}</a></h3>
      <div class="meta">${it.date || ''} • ${(it.top_speakers||[]).join(', ')}</div>
      <div class="snippet">${it.snippet || ''}</div>
    `;
    list.appendChild(el);
  });
  document.getElementById('spageinfo').textContent = `Page ${data.page} / ${Math.max(1, Math.ceil(data.total / data.page_size))}`;
  wrap.classList.toggle('hidden', (data.items||[]).length === 0 && !state.s.q);
  list.querySelectorAll('a.open').forEach(a => a.addEventListener('click', (e)=>{
    e.preventDefault();
    const id = e.currentTarget.getAttribute('data-id');
    openDetail(id);
  }));
}

document.getElementById('sgo').addEventListener('click', ()=>{ state.s.page = 1; applySearchInputs(); searchSegments(); });
document.getElementById('sq').addEventListener('keydown', (e)=>{ if(e.key==='Enter'){ state.s.page=1; applySearchInputs(); searchSegments(); }});
document.getElementById('sprev').addEventListener('click', ()=>{ if(state.s.page>1){ state.s.page--; searchSegments(); }});
document.getElementById('snext').addEventListener('click', ()=>{ state.s.page++; searchSegments(); });

function applySearchInputs(){
  state.s.q = document.getElementById('sq').value.trim();
  state.s.start = document.getElementById('sstart').value;
  state.s.end = document.getElementById('send').value;
  state.s.speaker = document.getElementById('sspeaker').value.trim();
}
