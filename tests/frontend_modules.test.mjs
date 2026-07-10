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
  instances[0].onerror();
  instances[0].onerror();
  stream.connect('next');
  assert.equal(instances[0].closed, true);
  assert.equal(instances[0].url, '/api/runs/run%20id/events');
  assert.deepEqual(events, [{ type: 'message', payload: { content: { text: 'hello' } } }]);
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
    runButton: element(), settingsButton: element(), providersButton: element(),
  };
  const { createRouter } = await importSource('router.js');
  const router = createRouter({ elements, getCurrentRunId: () => null, onSelectRun() {} });
  router.handleHash();
  assert.equal(elements.runView.hidden, true);
  assert.equal(elements.settingsView.hidden, false);
  assert.equal(elements.providersView.hidden, true);
  assert.deepEqual(scrollCalls, [[0, 0], [0, 0]]);
  assert.equal(typeof listeners.get('hashchange'), 'function');
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
