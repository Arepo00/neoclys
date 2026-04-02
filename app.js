let token = localStorage.getItem('token') || '';
const logEl = document.getElementById('log');
const authStatus = document.getElementById('authStatus');
const adminOut = document.getElementById('adminOut');
const kpiEl = document.getElementById('kpi');

function log(x) { logEl.textContent = typeof x === 'string' ? x : JSON.stringify(x, null, 2); }
function setAuth(x) { authStatus.textContent = typeof x === 'string' ? x : JSON.stringify(x, null, 2); }

async function api(path, method='GET', body, idem=false) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (idem) headers['Idempotency-Key'] = crypto.randomUUID();
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json();
  if (!res.ok) throw new Error(JSON.stringify(data));
  return data;
}

function renderKpi(r) {
  const rows = Object.entries(r || {}).filter(([k]) => ['outreaches','replies','qualified_bookings','calls_held','wins','revenue','close_rate','f2a_actions'].includes(k));
  kpiEl.innerHTML = rows.map(([k,v]) => `<div class='k'><strong>${k}</strong><span>${v}</span></div>`).join('');
}

document.getElementById('signupBtn').onclick = async () => {
  try {
    const data = await api('/api/auth/signup', 'POST', {
      org_name: document.getElementById('orgName').value,
      email: document.getElementById('email').value,
      password: document.getElementById('password').value,
    });
    setAuth(data); log('Signup successful. Now login.');
  } catch (e) { log(String(e)); }
};

document.getElementById('loginBtn').onclick = async () => {
  try {
    const data = await api('/api/auth/login', 'POST', {
      email: document.getElementById('email').value,
      password: document.getElementById('password').value,
    });
    token = data.token; localStorage.setItem('token', token);
    setAuth('Authenticated.'); log('Login success.');
  } catch (e) { log(String(e)); }
};

document.getElementById('seedBtn').onclick = async () => {
  try { log(await api('/api/org/seed', 'POST', { count: Number(document.getElementById('seedCount').value) }, true)); }
  catch (e) { log(String(e)); }
};

document.getElementById('runBtn').onclick = async () => {
  try {
    const x = await api('/api/org/run', 'POST', { days: Number(document.getElementById('runDays').value) }, true);
    log({ message: 'Run complete', records: x.results.length });
  } catch (e) { log(String(e)); }
};

document.getElementById('reportBtn').onclick = async () => {
  try { const r = await api('/api/org/report'); renderKpi(r); log(r); }
  catch (e) { log(String(e)); }
};

document.getElementById('orgsBtn').onclick = async () => {
  try { adminOut.textContent = JSON.stringify(await api('/api/admin/orgs'), null, 2); }
  catch (e) { adminOut.textContent = String(e); }
};

document.getElementById('subscribeBtn').onclick = async () => {
  try { adminOut.textContent = JSON.stringify(await api('/api/billing/subscribe', 'POST', { plan: 'pro' }), null, 2); }
  catch (e) { adminOut.textContent = String(e); }
};

document.getElementById('integBtn').onclick = async () => {
  try { adminOut.textContent = JSON.stringify(await api('/api/integrations/status'), null, 2); }
  catch (e) { adminOut.textContent = String(e); }
};
