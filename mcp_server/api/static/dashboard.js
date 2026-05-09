(function () {
  const tabs = document.querySelectorAll('.tab');
  const panels = document.querySelectorAll('.panel');
  const search = document.getElementById('q');

  function show(name) {
    tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === name));
    panels.forEach(p => p.classList.toggle('active', p.dataset.panel === name));
    if (history.replaceState) history.replaceState(null, '', '#' + name);
    applyFilter();
  }
  tabs.forEach(t => t.addEventListener('click', () => show(t.dataset.tab)));

  // Sortable headers — click toggles asc/desc
  document.querySelectorAll('table.dt thead th').forEach(th => {
    th.addEventListener('click', () => {
      const tbl = th.closest('table');
      const idx = parseInt(th.dataset.col);
      const type = th.dataset.sortType;
      const cur = th.dataset.dir;
      const next = cur === 'asc' ? 'desc' : 'asc';
      tbl.querySelectorAll('thead th').forEach(h => (h.dataset.dir = ''));
      th.dataset.dir = next;
      const rows = Array.from(tbl.tBodies[0].rows);
      rows.sort((a, b) => {
        let av = a.cells[idx].textContent.trim();
        let bv = b.cells[idx].textContent.trim();
        if (type === 'num') {
          av = parseFloat(av.replace(/[^0-9.\-+]/g, '')) || 0;
          bv = parseFloat(bv.replace(/[^0-9.\-+]/g, '')) || 0;
          return next === 'asc' ? av - bv : bv - av;
        }
        return next === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      });
      rows.forEach(r => tbl.tBodies[0].appendChild(r));
    });
  });

  // Search across the active panel only
  function applyFilter() {
    const q = (search.value || '').toLowerCase();
    const tbl = document.querySelector('.panel.active table.dt');
    if (!tbl) return;
    for (const tr of tbl.tBodies[0].rows) {
      tr.style.display =
        q && !tr.textContent.toLowerCase().includes(q) ? 'none' : '';
    }
  }
  search.addEventListener('input', applyFilter);

  // Open from URL hash (#theses, #leadlag, etc.)
  const hash = (location.hash || '').replace(/^#/, '');
  if (hash && document.querySelector('.panel[data-panel="' + hash + '"]')) {
    show(hash);
  }
})();
