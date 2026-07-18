import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const frontendUrl = new URL('../web/frontend/', import.meta.url);

async function importSource(relativePath) {
  const source = await readFile(new URL(relativePath, frontendUrl), 'utf8');
  return import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}#${Date.now()}`);
}

test('API client serializes run creation and parses the response', { concurrency: false }, async () => {
  const calls = [];
  globalThis.fetch = async (path, options) => {
    calls.push({ path, options });
    return new Response(JSON.stringify({ run_id: 'NVDA-test' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  const { api } = await importSource('api-client.js');
  const result = await api.startRun({ ticker: 'NVDA' });
  assert.deepEqual(result, { run_id: 'NVDA-test' });
  assert.equal(calls[0].path, '/api/runs');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.body, JSON.stringify({ ticker: 'NVDA' }));
});

test('API client preserves server error details and encodes run ids', { concurrency: false }, async () => {
  const paths = [];
  globalThis.fetch = async path => {
    paths.push(path);
    return new Response('report unavailable', { status: 404 });
  };
  const { api } = await importSource('api-client.js');
  await assert.rejects(api.getReport('run id/one'), /report unavailable/);
  assert.equal(paths[0], '/api/runs/run%20id%2Fone/report');
});

test('API client encodes evaluation cohort selectors', { concurrency: false }, async () => {
  const paths = [];
  globalThis.fetch = async path => {
    paths.push(path);
    return new Response(JSON.stringify({ evaluations: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  const { api } = await importSource('api-client.js');
  await api.getEvaluations({
    ticker: '0700.HK',
    baseline: 'baseline v1',
    challenger: 'candidate/v2',
    baselineFingerprint: 'base+fp',
    challengerFingerprint: 'candidate fp',
  });
  assert.equal(
    paths[0],
    '/api/evaluations?ticker=0700.HK&baseline=baseline+v1&challenger=candidate%2Fv2&baseline_fingerprint=base%2Bfp&challenger_fingerprint=candidate+fp',
  );
});

test('event stream dispatches typed events, closes old connections, and reports reconnect once', { concurrency: false }, async () => {
  const instances = [];
  class FakeEventSource {
    constructor(url) {
      this.url = url;
      this.listeners = new Map();
      this.closed = false;
      instances.push(this);
    }
    addEventListener(type, callback) { this.listeners.set(type, callback); }
    close() { this.closed = true; }
    emit(type, payload) { this.listeners.get(type)?.({ data: JSON.stringify(payload) }); }
  }
  globalThis.EventSource = FakeEventSource;
  const events = [];
  let reconnects = 0;
  const { createEventStream } = await importSource('event-stream.js');
  const stream = createEventStream({
    onEvent: (type, payload) => events.push({ type, payload }),
    onReconnect: () => { reconnects += 1; },
  });
  stream.connect('run id');
  instances[0].emit('message', { content: { text: 'hello' } });
  instances[0].emit('longitudinal_context_status', {
    content: { status: 'loaded', same_symbol_included_count: 1 },
  });
  instances[0].emit('architecture_evaluation_status', {
    content: {
      status: 'loaded',
      current_architecture: {
        sample_count: 20,
        readiness_status: 'ready_for_controlled_experiment_design',
      },
    },
  });
  instances[0].onerror();
  instances[0].onerror();
  stream.connect('next');
  assert.equal(instances[0].closed, true);
  assert.equal(instances[0].url, '/api/runs/run%20id/events');
  assert.deepEqual(events, [
    { type: 'message', payload: { content: { text: 'hello' } } },
    {
      type: 'longitudinal_context_status',
      payload: { content: { status: 'loaded', same_symbol_included_count: 1 } },
    },
    {
      type: 'architecture_evaluation_status',
      payload: {
        content: {
          status: 'loaded',
          current_architecture: {
            sample_count: 20,
            readiness_status: 'ready_for_controlled_experiment_design',
          },
        },
      },
    },
  ]);
  assert.equal(reconnects, 1);
  stream.close();
  assert.equal(instances[1].closed, true);
});

test('router restores settings deep links without native anchor scrolling', { concurrency: false }, async () => {
  const listeners = new Map();
  const scrollCalls = [];
  globalThis.window = {
    location: { hash: '#settings', pathname: '/' },
    history: { replaceState() {} },
    addEventListener: (type, callback) => listeners.set(type, callback),
    scrollTo: (...args) => scrollCalls.push(args),
    requestAnimationFrame: callback => callback(),
  };
  const element = () => ({
    hidden: false,
    classList: { toggle() {} },
  });
  const elements = {
    runControls: element(), runView: element(), settingsView: element(), providersView: element(),
    evaluationsView: element(), runButton: element(), settingsButton: element(),
    providersButton: element(), evaluationsButton: element(),
  };
  const { createRouter } = await importSource('router.js');
  const router = createRouter({ elements, getCurrentRunId: () => null, onSelectRun() {} });
  router.handleHash();
  assert.equal(elements.runView.hidden, true);
  assert.equal(elements.settingsView.hidden, false);
  assert.equal(elements.providersView.hidden, true);
  assert.equal(elements.evaluationsView.hidden, true);
  assert.deepEqual(scrollCalls, [[0, 0], [0, 0]]);
  assert.equal(typeof listeners.get('hashchange'), 'function');
});

test('router restores evaluation deep links and invokes the loader', { concurrency: false }, async () => {
  let evaluationLoads = 0;
  globalThis.window = {
    location: { hash: '#evaluations', pathname: '/' },
    history: { replaceState() {} },
    addEventListener() {},
    scrollTo() {},
    requestAnimationFrame: callback => callback(),
  };
  const element = () => ({
    hidden: false,
    classList: { toggle() {} },
  });
  const elements = {
    runControls: element(), runView: element(), settingsView: element(), providersView: element(),
    evaluationsView: element(), runButton: element(), settingsButton: element(),
    providersButton: element(), evaluationsButton: element(),
  };
  const { createRouter } = await importSource('router.js');
  const router = createRouter({
    elements,
    getCurrentRunId: () => null,
    onSelectRun() {},
    onShowEvaluations: () => { evaluationLoads += 1; },
  });
  router.handleHash();
  assert.equal(elements.evaluationsView.hidden, false);
  assert.equal(elements.runView.hidden, true);
  assert.equal(evaluationLoads, 1);
});

test('evaluation view model exposes rolling and pending evidence', { concurrency: false }, async () => {
  const { buildEvaluationViewModel } = await importSource('components/evaluation-dashboard.js');
  const view = buildEvaluationViewModel({
    evaluations: [{ run_id: 'evaluated' }],
    pending_evaluation_count: 1,
    pending_evaluations: [{ run_id: 'pending' }],
    rollups: [{
      architecture_version: 'candidate',
      architecture_fingerprint: 'fingerprint',
      sample_count: 20,
      directional_hit_rate: 0.6,
      mean_alpha_return: 0.01,
      mean_score: 0.008,
      outcome_assessment: {
        status: 'uncertainty_ready',
        rolling_monitoring: {
          tickers: {
            NVDA: {
              windows: {
                5: {
                  status: 'comparison_ready',
                  current: { sample_count: 5, mean_score: -0.01 },
                  previous: { mean_score: 0.02 },
                  current_minus_previous: {
                    mean_score: -0.03,
                    mean_alpha_return: -0.02,
                  },
                },
              },
            },
          },
        },
      },
      optimization_assessment: {
        readiness_status: 'ready_for_controlled_experiment_design',
        recommended_action: 'investigate_recent_deterioration',
        controlled_experiment_ready: true,
        cost_hotspots: [{
          agent: 'Research Manager',
          mean_tokens_in: 1200,
          sample_count: 20,
        }],
        tool_context_hotspots: [{
          tool: 'get_financial_evidence',
          mean_output_chars: 42000,
          sample_count: 20,
        }],
        weakest_rating: {
          rating: 'hold',
          mean_score: -0.01,
          sample_count: 5,
        },
      },
    }],
  });
  assert.equal(view.evaluationCount, 1);
  assert.equal(view.pendingCount, 1);
  assert.equal(view.cohortCount, 1);
  assert.deepEqual(view.cohorts[0].rolling[0], {
    ticker: 'NVDA',
    windowSize: 5,
    status: 'comparison_ready',
    currentCount: 5,
    currentMeanScore: -0.01,
    previousMeanScore: 0.02,
    scoreDelta: -0.03,
    alphaDelta: -0.02,
  });
  assert.deepEqual(view.cohorts[0].optimization, {
    readinessStatus: 'ready_for_controlled_experiment_design',
    recommendedAction: 'investigate_recent_deterioration',
    controlledExperimentReady: true,
    costHotspots: [{
      agent: 'Research Manager',
      meanTokensIn: 1200,
      sampleCount: 20,
    }],
    toolContextHotspots: [{
      tool: 'get_financial_evidence',
      meanOutputChars: 42000,
      sampleCount: 20,
    }],
    weakestRating: {
      rating: 'hold',
      meanScore: -0.01,
      sampleCount: 5,
    },
  });
});

test('event log localizes architecture evaluation readiness', { concurrency: false }, async () => {
  const labels = {
    samples: '样本',
    evaluationCodeReadyForExperiment: '可以设计受控实验',
    evaluationCodeInvestigateRecent: '调查近期退化',
    toolOutputHotspots: '工具输出',
  };
  const { createEventLog } = await importSource('components/event-log.js');
  const log = createEventLog({
    element: { replaceChildren() {} },
    t: key => labels[key] || key,
    locale: () => 'zh',
    formatAgentName: value => value,
    formatStatus: value => value,
    formatStats: () => 'stats',
  });
  assert.equal(
    log.text('architecture_evaluation_status', {
      status: 'loaded',
      current_architecture: {
        sample_count: 20,
        readiness_status: 'ready_for_controlled_experiment_design',
        recommended_action: 'investigate_recent_deterioration',
      },
      context_cost_diagnostic: {
        top_tools: [
          { tool: 'get_news', output_chars: 80000 },
          { tool: 'get_financial_evidence', output_chars: 42468 },
        ],
      },
    }),
    'loaded · 20 样本 · 可以设计受控实验 · 调查近期退化 · '
      + '工具输出: get_news 80.0K, get_financial_evidence 42.5K',
  );
  assert.equal(
    log.text('stats', {
      by_tool: {
        get_indicators: { output_chars: 12000 },
        get_news: { output_chars: 80000 },
        get_financial_evidence: { output_chars: 42468 },
        get_verified_market_snapshot: { output_chars: 2000 },
      },
    }),
    'stats · 工具输出: get_news 80.0K, '
      + 'get_financial_evidence 42.5K, get_indicators 12.0K',
  );
});

test('report reading mode preserves content until the user resumes live updates', { concurrency: false }, async () => {
  class FakeControl {
    constructor() {
      this.listeners = new Map();
      this.classList = { toggle() {} };
      this.hidden = false;
      this.value = 'all';
    }
    addEventListener(type, callback) { this.listeners.set(type, callback); }
    setAttribute(name, value) { this[name] = value; }
    replaceChildren(...children) { this.children = children; }
    click() { this.listeners.get('click')?.(); }
  }
  const reportElement = {
    innerHTML: '',
    replaceChildren() {},
    querySelector() { return null; },
  };
  const sectionSelect = new FakeControl();
  const readingModeToggle = new FakeControl();
  const newReportsNotice = new FakeControl();
  globalThis.document = {
    createElement() { return { value: '', textContent: '' }; },
  };
  globalThis.marked = { parse: markdown => markdown };
  const labels = {
    reportAll: 'All', liveReportTitle: 'Live report', reportPlaceholder: 'Empty',
    reportUnavailable: 'Unavailable', readingMode: 'Reading mode', readingModeOn: 'On',
    readingModeOff: 'Off', newReportsLabel: '{count} new reports',
  };
  const { createReportViewer } = await importSource('components/report-viewer.js');
  const viewer = createReportViewer({
    api: { getReport: async () => '# final' },
    element: reportElement,
    sectionSelect,
    readingModeToggle,
    newReportsNotice,
    t: key => labels[key] || key,
    locale: () => 'en',
    formatAgentName: name => name,
  });
  viewer.updateSection({ section: 'market_report', text: 'first report' });
  assert.match(reportElement.innerHTML, /first report/);
  readingModeToggle.click();
  viewer.updateSection({ section: 'news_report', text: 'new report' });
  assert.match(reportElement.innerHTML, /first report/);
  assert.doesNotMatch(reportElement.innerHTML, /new report/);
  assert.equal(newReportsNotice.hidden, false);
  assert.equal(newReportsNotice.textContent, '1 new reports');
  newReportsNotice.click();
  assert.match(reportElement.innerHTML, /new report/);
  assert.equal(newReportsNotice.hidden, true);
});
