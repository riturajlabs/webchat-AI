// WebChat AI - Phase 12.1 baseline load test (chat streaming pipeline).
//
// Hammers POST /api/chat/stream on the isolated perf API (:8001, native Mongo,
// mock AI providers) and records SSE stream latency (TTFB + full duration) and
// completion/error rates. A fresh owner token is minted in setup() so a 15-min
// access-token lifetime never cuts the run short.
//
// Run:
//   k6 run scripts/perf/load-test.js
// Overrides (defaults match scripts/perf/seed.py):
//   PERF_API, PERF_EMAIL, PERF_PASSWORD, PERF_WEBSITE, PERF_QUESTION_POOL
// Set PERF_SCENARIO=baseline|sustained10vu to run one scenario in isolation.
import http from 'k6/http';
import { check } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const API_BASE = __ENV.PERF_API || 'http://127.0.0.1:8001';
const EMAIL = __ENV.PERF_EMAIL || 'perf@example.com';
const PASSWORD = __ENV.PERF_PASSWORD || 'perf-password-123';
const WEBSITE = __ENV.PERF_WEBSITE || '5705a2ac-124e-472d-b747-ce8783acaff1';

function uniqueId(prefix) {
  return `${prefix}-${__VU}-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
}
const QUESTIONS = __ENV.PERF_QUESTION_POOL
  ? __ENV.PERF_QUESTION_POOL.split('|')
  : [
      'What pricing plans do you offer?',
      'How does the free trial work?',
      'What are the API rate limits?',
      'How do I upgrade my account?',
      'Is there a team plan?',
    ];

const chatDone = new Counter('chat_done_events');
const chatError = new Counter('chat_error_events');
const chatStreamDuration = new Trend('chat_stream_duration_ms', true);
const chatTtfb = new Trend('chat_ttfb_ms', true);
const chatErrorRate = new Rate('chat_error_rate');
const scenarios = {
  // Baseline ramp: warm-up -> peak -> soak -> ramp-down.
  baseline: {
    executor: 'ramping-vus',
    stages: [
      { duration: '30s', target: 5 },
      { duration: '30s', target: 20 },
      { duration: '60s', target: 50 },
      { duration: '60s', target: 50 },
      { duration: '30s', target: 0 },
    ],
    gracefulRampDown: '10s',
  },
  // Phase 12.6 latency target: 10 concurrent users, steady state.
  sustained10vu: {
    executor: 'constant-vus',
    vus: 10,
    duration: '3m',
  },
};

const selectedScenario = __ENV.PERF_SCENARIO;
export const options = {
  scenarios: selectedScenario ? { [selectedScenario]: scenarios[selectedScenario] } : scenarios,
  thresholds: {
    chat_error_rate: ['rate < 0.01'],
  },
};

export function setup() {
  const res = http.post(
    `${API_BASE}/api/auth/login`,
    JSON.stringify({ email: EMAIL, password: PASSWORD }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  check(res, { 'login 200': (r) => r.status === 200 });
  return { token: res.json('access_token'), website: WEBSITE };
}

// Per-VU conversation state: the first turn creates the session, later turns
// reuse it so the run exercises the resume + history path, not the error path.
let sessionId = null;

export default async function chatScenario(data) {
  const visitorId = uniqueId('vis');
  const question = QUESTIONS[Math.floor(Math.random() * QUESTIONS.length)];
  const payload = {
    website_id: data.website,
    question,
    visitor_id: visitorId,
  };
  if (sessionId) {
    payload.session_id = sessionId;
  }
  const body = JSON.stringify(payload);
  const headers = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${data.token}`,
  };

  const res = await http.asyncRequest('POST', `${API_BASE}/api/chat/stream`, body, {
    headers,
    timeout: '60s',
  });

  if (res.status !== 200) {
    chatError.add(1);
    chatErrorRate.add(true);
    return;
  }
  chatTtfb.add(res.timings.waiting);
  chatStreamDuration.add(res.timings.duration);

  const streamed = typeof res.body === 'string' ? res.body : '';
  const ok = streamed.includes('event: done');
  if (ok) {
    chatDone.add(1);
    chatErrorRate.add(false);
    if (!sessionId) {
      const match = /"session_id": "([a-f0-9-]{36})"/.exec(streamed);
      if (match) {
        sessionId = match[1];
      }
    }
  } else {
    chatError.add(1);
    chatErrorRate.add(true);
  }
}
