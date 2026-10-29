// k6 against a real server (workflow «Load live»): read-only public endpoints, a step-up profile to find the
// rate at which the API stops answering in time. No accounts are created and nothing is bought.
// 429 from the rate limiter is reported separately: it means the shop protects itself, not that it broke.
import http from 'k6/http';
import {check} from 'k6';
import {Counter} from 'k6/metrics';

const BASE = (__ENV.TARGET || '').replace(/\/$/, '');
const PEAK = Number(__ENV.PEAK_VUS || 50);
const STEP = __ENV.STEP || '30s';
const limited = new Counter('rate_limited');
http.setResponseCallback(http.expectedStatuses({min: 200, max: 299}, 304, 429));

export const options = {
  scenarios: {
    stepup: {executor: 'ramping-vus', exec: 'reads', startVUs: 1, gracefulRampDown: '10s',
      stages: [{duration: STEP, target: Math.ceil(PEAK / 4)}, {duration: STEP, target: Math.ceil(PEAK / 2)},
               {duration: STEP, target: PEAK}, {duration: STEP, target: PEAK}, {duration: '10s', target: 0}]},
  },
  thresholds: {
    http_req_failed: ['rate<0.02'],
    'http_req_duration{scenario:stepup}': ['p(95)<1500'],
  },
};

const PATHS = ['/health', '/api/plans', '/api/public/config', '/api/public/status-page', '/api/public/service-status'];

export function reads() {
  const path = PATHS[Math.floor(Math.random() * PATHS.length)];
  const r = http.get(`${BASE}${path}`, {tags: {name: path}, headers: {'User-Agent': 'corgi-load-live/1'}});
  if (r.status === 429) limited.add(1);
  check(r, {'answered': (x) => x.status === 200 || x.status === 304 || x.status === 429});
}
