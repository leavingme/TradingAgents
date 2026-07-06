/**
 * TradingAgents Web UI — Enhanced Application Script
 *
 * Preserves all original behaviour (SSE, form submit, history, cancel) while
 * adding:
 *  - Markdown rendering via marked.js for the report viewer
 *  - Animated status dot in the header
 *  - Color-coded event types in the live stream
 *  - Styled history status badges
 *  - Empty-state placeholder for the report panel
 */

// ── DOM references ──────────────────────────────────────────────────────────
const form          = document.querySelector('#runForm');
const statusEl      = document.querySelector('#runStatus');
const statusDot     = document.querySelector('#statusDot');
const runIdEl       = document.querySelector('#runId');
const eventCountEl  = document.querySelector('#eventCount');
const agentList     = document.querySelector('#agentList');
const eventLog      = document.querySelector('#eventLog');
const reportViewer  = document.querySelector('#reportViewer');
const startButton   = document.querySelector('#startButton');
const cancelButton  = document.querySelector('#cancelButton');
const clearLog      = document.querySelector('#clearLog');
const loadReport    = document.querySelector('#loadReport');
const refreshHistory= document.querySelector('#refreshHistory');
const historyList   = document.querySelector('#historyList');

// ── State ───────────────────────────────────────────────────────────────────
let currentRunId = null;
let source       = null;
let eventCount   = 0;
const agents     = new Map();

// ── Initialise date field ────────────────────────────────────────────────────
document.querySelector('#analysisDate').value = new Date().toISOString().slice(0, 10);

// Show empty-state placeholder in the report panel on load
showReportPlaceholder();

// ── Form submit ──────────────────────────────────────────────────────────────
form.addEventListener('submit', async event => {
  event.preventDefault();
  resetRun();

  const payload = buildPayload(new FormData(form));
  setBusy(true);
  setStatus('Starting…', 'running');

  try {
    const response = await fetch('/api/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(await response.text());

    const run      = await response.json();
    currentRunId   = run.run_id;
    runIdEl.textContent = shortId(run.run_id);
    setStatus(run.status, 'running');
    cancelButton.disabled = false;
    refreshRunHistory();
    connectEvents(run.run_id);
  } catch (error) {
    setStatus('Failed to start', 'error');
    appendEvent('error', null, error.message);
    setBusy(false);
  }
});

// ── Cancel button ────────────────────────────────────────────────────────────
cancelButton.addEventListener('click', async () => {
  if (!currentRunId) return;
  await fetch(`/api/runs/${currentRunId}/cancel`, { method: 'POST' });
  setStatus('Cancel requested', 'running');
  cancelButton.disabled = true;
});

// ── Clear log ────────────────────────────────────────────────────────────────
clearLog.addEventListener('click', () => {
  eventLog.replaceChildren();
});

// ── Refresh history ──────────────────────────────────────────────────────────
refreshHistory.addEventListener('click', refreshRunHistory);

// ── Load report ──────────────────────────────────────────────────────────────
loadReport.addEventListener('click', async () => {
  if (!currentRunId) return;
  await loadRunReport(currentRunId);
});

// Load run history on startup
refreshRunHistory();

// ── Helpers ──────────────────────────────────────────────────────────────────

function buildPayload(data) {
  const selectedAnalysts = data.getAll('analysts');
  const depth = Number(data.get('researchDepth'));
  return {
    ticker: String(data.get('ticker')).trim().toUpperCase(),
    analysis_date: data.get('analysisDate'),
    asset_type: data.get('assetType'),
    selected_analysts: selectedAnalysts.length ? selectedAnalysts : ['market'],
    research_depth: Number.isFinite(depth) && depth > 0 ? depth : null,
  };
}

/** Return a short, displayable run ID (last 8 chars). */
function shortId(id) {
  if (!id || id === 'No run') return id;
  return id.length > 12 ? '…' + id.slice(-8) : id;
}

function resetRun() {
  if (source) source.close();
  source       = null;
  currentRunId = null;
  eventCount   = 0;
  agents.clear();
  eventLog.replaceChildren();
  agentList.replaceChildren();
  showReportPlaceholder();
  runIdEl.textContent       = 'No run';
  eventCountEl.textContent  = '0 events';
  loadReport.disabled       = true;
}

// ── SSE connection ────────────────────────────────────────────────────────────
function connectEvents(runId) {
  if (source) source.close();
  source = new EventSource(`/api/runs/${runId}/events`);

  const eventTypes = [
    'run_started',
    'message',
    'tool_call',
    'agent_status',
    'report_section',
    'run_completed',
    'error',
  ];

  for (const type of eventTypes) {
    source.addEventListener(type, ev =>
      handleRuntimeEvent(type, JSON.parse(ev.data))
    );
  }

  source.onerror = () => {
    appendEvent('error', null, 'Event stream disconnected');
    closeStream();
  };
}

function handleRuntimeEvent(type, event) {
  eventCount += 1;
  eventCountEl.textContent = `${eventCount} event${eventCount !== 1 ? 's' : ''}`;

  if (type === 'agent_status' && event.agent) {
    updateAgent(event.agent, event.content?.status ?? 'pending');
  }

  if (type === 'run_completed') {
    setStatus('completed', 'done');
    loadReport.disabled = false;
    cancelButton.disabled = true;
    appendEvent(type, event.agent, event.content?.decision ?? 'Run completed');
    loadRunReport(currentRunId);
    refreshRunHistory();
    closeStream();
    return;
  }

  if (type === 'error') {
    setStatus('failed', 'error');
    cancelButton.disabled = true;
    appendEvent(type, event.agent, event.content?.error ?? 'Run failed');
    refreshRunHistory();
    closeStream();
    return;
  }

  if (type === 'run_started') setStatus('running', 'running');
  appendEvent(type, event.agent, eventText(type, event.content));
}

// ── Agent timeline ────────────────────────────────────────────────────────────
function updateAgent(name, status) {
  agents.set(name, status);
  agentList.replaceChildren(
    ...Array.from(agents.entries()).map(([agent, agentStatus]) => {
      const item = document.createElement('li');
      item.className = `status-${agentStatus}`;

      const dot = document.createElement('span');
      dot.className = 'dot';

      const label = document.createElement('span');
      label.textContent = formatAgentName(agent);

      const state = document.createElement('span');
      state.className = 'agent-status';
      state.textContent = agentStatus.replace('_', ' ');

      item.append(dot, label, state);
      return item;
    }),
  );
}

/** Convert snake_case agent names to Title Case for display. */
function formatAgentName(name) {
  return name
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
}

// ── Run history ───────────────────────────────────────────────────────────────
async function refreshRunHistory() {
  const response = await fetch('/api/runs');
  if (!response.ok) return;
  const runs = await response.json();
  historyList.replaceChildren(...runs.slice(0, 20).map(renderHistoryItem));
}

function renderHistoryItem(run) {
  const item = document.createElement('li');

  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = `${run.ticker}  ·  ${run.analysis_date}`;
  button.addEventListener('click', () => selectHistoryRun(run.run_id));

  const meta = document.createElement('div');
  meta.className = 'history-meta';

  const statusBadge = document.createElement('span');
  statusBadge.className = `history-status ${run.status}`;
  statusBadge.textContent = run.status;

  const count = document.createElement('span');
  count.textContent = `${run.event_count} events`;

  meta.append(statusBadge, count);
  item.append(button, meta);
  return item;
}

async function selectHistoryRun(runId) {
  if (source) source.close();
  source = null;

  const response = await fetch(`/api/runs/${runId}`);
  if (!response.ok) return;
  const run = await response.json();

  currentRunId   = run.run_id;
  runIdEl.textContent      = shortId(run.run_id);
  setStatus(run.status, statusClass(run.status));
  eventCount     = 0;
  eventCountEl.textContent = '0 events';
  loadReport.disabled      = !run.report_path;
  cancelButton.disabled    = !['pending', 'running'].includes(run.status);
  eventLog.replaceChildren();

  connectEvents(run.run_id);
  if (run.report_path) await loadRunReport(run.run_id);
}

// ── Event log ─────────────────────────────────────────────────────────────────
function appendEvent(type, agent, text) {
  const item = document.createElement('article');
  item.className = 'event';

  const head = document.createElement('div');
  head.className = 'event-head';

  const badge = document.createElement('span');
  badge.className = `event-type event-type-${type}`;
  badge.textContent = type.replace(/_/g, ' ');

  const agentSpan = document.createElement('span');
  agentSpan.className = 'event-agent';
  agentSpan.textContent = agent ? formatAgentName(agent) : 'system';

  const time = document.createElement('span');
  time.className = 'event-time';
  time.textContent = new Date().toLocaleTimeString();

  const body = document.createElement('div');
  body.className = 'event-text';
  body.textContent = text || '';

  head.append(badge, agentSpan, time);
  item.append(head, body);
  eventLog.append(item);
  eventLog.scrollTop = eventLog.scrollHeight;
}

function eventText(type, content) {
  if (!content) return '';
  if (typeof content === 'string') return content;
  if (type === 'message')        return content.text || '';
  if (type === 'tool_call')      return `${content.name || 'tool'}  ${JSON.stringify(content.args || {})}`;
  if (type === 'report_section') return `${content.section || 'report'} updated`;
  if (type === 'agent_status')   return content.status || '';
  if (type === 'run_started')    return `${content.ticker} · ${content.analysis_date}`;
  return JSON.stringify(content);
}

// ── Report viewer ─────────────────────────────────────────────────────────────
async function loadRunReport(runId) {
  if (!runId) return;
  const response = await fetch(`/api/runs/${runId}/report`);
  if (!response.ok) {
    reportViewer.innerHTML = '';
    showReportPlaceholder('Report is not available yet.');
    return;
  }
  const text = await response.text();

  // Render Markdown if marked.js is available, otherwise fall back to pre-text
  if (typeof marked !== 'undefined') {
    reportViewer.innerHTML = marked.parse(text);
  } else {
    const pre = document.createElement('pre');
    pre.textContent = text;
    reportViewer.innerHTML = '';
    reportViewer.appendChild(pre);
  }
}

function showReportPlaceholder(message = 'Run an analysis to see the report here.') {
  reportViewer.innerHTML = `
    <div class="report-empty">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
        <polyline points="14 2 14 8 20 8"></polyline>
        <line x1="16" y1="13" x2="8" y2="13"></line>
        <line x1="16" y1="17" x2="8" y2="17"></line>
        <polyline points="10 9 9 9 8 9"></polyline>
      </svg>
      <p>${message}</p>
    </div>
  `;
}

// ── Stream management ─────────────────────────────────────────────────────────
function closeStream() {
  if (source) source.close();
  source = null;
  setBusy(false);
}

function setBusy(isBusy) {
  startButton.disabled   = isBusy;
  cancelButton.disabled  = !isBusy || !currentRunId;
}

// ── Status dot helper ─────────────────────────────────────────────────────────
function setStatus(text, state) {
  statusEl.textContent = text;
  statusDot.className  = `status-dot ${state ?? ''}`;
}

function statusClass(status) {
  if (status === 'completed') return 'done';
  if (status === 'running')   return 'running';
  if (status === 'failed' || status === 'cancelled') return 'error';
  return 'ready';
}
