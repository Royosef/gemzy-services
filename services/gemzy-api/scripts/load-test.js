import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 10 },
    { duration: '1m', target: 20 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p95<500'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:5050';

export default function () {
  const res = http.get(`${BASE_URL}/`);
  check(res, { 'status was 200': (r) => r.status == 200 });

  // TODO: Add authenticated scenarios here
  // const loginRes = http.post(`${BASE_URL}/auth/login`, ...);

  sleep(1);
}
