// k6 load profile for the shop API (test stack, PAYMENTS_SANDBOX=true).
// Scenarios: public catalogue reads, authenticated sync/dashboard, sandbox checkout.
// 429 from the rate limiter is an expected answer, not a failure.
import http from 'k6/http';
import {check, sleep} from 'k6';

const BASE = __ENV.API_BASE || 'http://127.0.0.1:18080';
http.setResponseCallback(http.expectedStatuses({min: 200, max: 299}, 409, 429));

export const options = {
  scenarios: {
    catalogue: {executor: 'ramping-vus', exec: 'catalogue', startVUs: 1,
      stages: [{duration: '20s', target: 20}, {duration: '40s', target: 20}, {duration: '10s', target: 0}]},
    sync: {executor: 'constant-vus', exec: 'sync', vus: 10, duration: '60s', startTime: '5s'},
    checkout: {executor: 'per-vu-iterations', exec: 'checkout', vus: 3, iterations: 5, startTime: '10s', maxDuration: '60s'},
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    'http_req_duration{scenario:catalogue}': ['p(95)<800'],
    'http_req_duration{scenario:sync}': ['p(95)<1000'],
    'http_req_duration{scenario:checkout}': ['p(95)<2500'],
    checks: ['rate>0.98'],
  },
};

function csrfFrom(jar) {
  const c = jar.cookiesForURL(BASE).rw_csrf;
  return c && c.length ? c[0] : '';
}

export function setup() {
  const users = [];
  for (let i = 0; i < 4; i++) {
    const jar = http.cookieJar();
    jar.clear(BASE);
    const csrf = `k6${Date.now()}${i}abcdefghijklmnop`;
    const email = `k6-${Date.now()}-${i}@example.test`;
    const r = http.post(`${BASE}/api/auth/register`, JSON.stringify({email, password: 'LoadTestPass123!'}),
      {headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf, Cookie: `rw_csrf=${csrf}`}});
    check(r, {'register 200': (x) => x.status === 200});
    const cookies = {};
    for (const [k, v] of Object.entries(jar.cookiesForURL(BASE))) cookies[k] = v[0];
    users.push(cookies);
  }
  const plans = http.get(`${BASE}/api/plans`).json() || [];
  return {users, planId: plans.length ? plans[0].id : null};
}

function login(data) {
  const cookies = data.users[(__VU - 1) % data.users.length];
  const jar = http.cookieJar();
  for (const [k, v] of Object.entries(cookies)) jar.set(BASE, k, v);
  return jar;
}

export function catalogue() {
  for (const path of ['/health', '/api/public/config', '/api/plans', '/api/public/servers', '/api/public/cabinet-menu']) {
    const r = http.get(`${BASE}${path}`, {tags: {name: path}});
    check(r, {[`${path} ok`]: (x) => x.status === 200 || x.status === 429});
  }
  sleep(0.5);
}

export function sync(data) {
  login(data);
  for (const path of ['/api/me/sync', '/api/me/dashboard', '/api/me/stats']) {
    const r = http.get(`${BASE}${path}`, {tags: {name: path}});
    check(r, {[`${path} ok`]: (x) => x.status === 200 || x.status === 429});
  }
  sleep(1);
}

export function checkout(data) {
  if (!data.planId) return;
  const jar = login(data);
  const headers = {'Content-Type': 'application/json', 'X-CSRF-Token': csrfFrom(jar),
    'Idempotency-Key': `k6-${__VU}-${__ITER}-${Date.now()}`};
  const r = http.post(`${BASE}/api/payments/create`, JSON.stringify({plan_id: data.planId, provider: 'sandbox'}),
    {headers, tags: {name: '/api/payments/create'}});
  check(r, {'checkout created or open order': (x) => [200, 409, 429].includes(x.status)});
  if (r.status === 200 && r.json('id')) {
    const done = http.post(`${BASE}/api/payments/sandbox/complete`, JSON.stringify({payment_id: r.json('id')}),
      {headers, tags: {name: '/api/payments/sandbox/complete'}});
    check(done, {'sandbox complete': (x) => x.status === 200 || x.status === 429});
  }
  sleep(2);
}
