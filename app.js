const statusEl = document.getElementById('status');
const kpiEl = document.getElementById('kpi');
const checksEl = document.getElementById('checks');

function setStatus(msg) {
  statusEl.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
}

function renderKpi(report) {
  if (!report) return;
  const rows = [
    ['Outreaches', report.outreaches],
    ['Replies', report.replies],
    ['Qualified Bookings', report.qualified_bookings],
    ['Calls Held', report.calls_held],
    ['Wins', report.wins],
    ['Revenue', report.revenue],
    ['Avg Qualified Calls / Day', report.avg_qualified_calls_per_day],
    ['Close Rate', report.close_rate],
    ['F2A Actions', report.f2a_actions],
    ['Top Template', report.top_template],
    ['Top Playbook', report.top_playbook],
  ];
  kpiEl.innerHTML = rows.map(([k, v]) => `<div class="k"><strong>${k}</strong><span>${v}</span></div>`).join('');
}

function renderChecks(checks) {
  if (!checks) return;
  checksEl.innerHTML = Object.entries(checks)
    .map(([k, v]) => `<li>${v ? '✅' : '❌'} <code>${k}</code></li>`)
    .join('');
}

async function api(path, method = 'GET', body) {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function refreshReport() {
  const report = await api('/api/report');
  renderKpi(report);
}

document.getElementById('initBtn').onclick = async () => {
  const data = await api('/api/init', 'POST', {});
  setStatus(data);
  await refreshReport();
};

document.getElementById('seedBtn').onclick = async () => {
  const count = Number(document.getElementById('seedCount').value || 3000);
  const data = await api('/api/seed', 'POST', { count });
  setStatus(data);
  await refreshReport();
};

document.getElementById('runBtn').onclick = async () => {
  const days = Number(document.getElementById('runDays').value || 60);
  const data = await api('/api/run', 'POST', { days });
  setStatus({ message: 'Run complete', days, daily_records: data.results.length });
  await refreshReport();
};

document.getElementById('verifyBtn').onclick = async () => {
  const data = await api('/api/verify');
  setStatus(data.report);
  renderChecks(data.checks);
};

document.getElementById('refreshBtn').onclick = refreshReport;
refreshReport().catch((e) => setStatus(String(e)));
