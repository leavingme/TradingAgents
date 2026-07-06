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
const tickerSelect  = document.querySelector('#ticker');
const customTicker  = document.querySelector('#customTicker');
const runControls   = document.querySelector('#runControls');
const runView       = document.querySelector('#runView');
const settingsView  = document.querySelector('#settingsView');
const runViewButton = document.querySelector('#runViewButton');
const settingsViewButton = document.querySelector('#settingsViewButton');
const settingsForm  = document.querySelector('#settingsForm');
const resetSettings = document.querySelector('#resetSettings');
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
const reportSectionSelect = document.querySelector('#reportSectionSelect');
const refreshHistory= document.querySelector('#refreshHistory');
const historyList   = document.querySelector('#historyList');
const llmProvider   = document.querySelector('#llmProvider');
const quickThinkLlm = document.querySelector('#quickThinkLlm');
const deepThinkLlm  = document.querySelector('#deepThinkLlm');
const backendUrl    = document.querySelector('#backendUrl');
const outputLanguage= document.querySelector('#outputLanguage');
const researchDepth = document.querySelector('#researchDepth');
const uiLanguage    = document.querySelector('#uiLanguage');
const googleThinkingLevel = document.querySelector('#googleThinkingLevel');
const openaiReasoningEffort = document.querySelector('#openaiReasoningEffort');
const anthropicEffort = document.querySelector('#anthropicEffort');

// ── State ───────────────────────────────────────────────────────────────────
let currentRunId = null;
let source       = null;
let eventCount   = 0;
let currentStatus = 'ready';
const agents     = new Map();
const reportSections = new Map();
let selectedReportSection = 'all';
let configDefaults = null;
const settingsStorageKey = 'tradingagents.web.settings';
const uiLanguageStorageKey = 'tradingagents.web.uiLanguage';
let activeLocale = 'en';
const translations = {
  en: {
    pageTitle: 'TradingAgents — AI Market Intelligence',
    brandTagline: 'AI-powered market intelligence',
    navRun: 'Run',
    navSettings: 'Settings',
    statusReady: 'Ready',
    noRun: 'No run',
    ticker: 'Ticker',
    tickerCustom: 'Custom ticker...',
    tickerPlaceholder: 'e.g. SPY, 0700.HK, BTC-USD',
    analysisDate: 'Analysis Date',
    assetType: 'Asset Type',
    assetStock: 'Stock',
    assetCrypto: 'Crypto',
    analysts: 'Analysts',
    analystMarket: 'Market',
    analystSocial: 'Social',
    analystNews: 'News',
    analystFundamentals: 'Fundamentals',
    startAnalysis: 'Start Analysis',
    cancel: 'Cancel',
    settingsTitle: 'Run Settings',
    settingsSubtitle: 'Defaults used when starting a new analysis run.',
    resetDefaults: 'Reset Defaults',
    uiLanguage: 'UI Language',
    uiLanguageAuto: 'Auto',
    reportLanguage: 'Report Language',
    analysisDepth: 'Analysis Depth',
    depthShallow: 'Shallow · quick research',
    depthMedium: 'Medium · moderate debate',
    depthDeep: 'Deep · comprehensive research',
    llmProvider: 'LLM Provider',
    quickModel: 'Quick Model',
    deepModel: 'Deep Model',
    backendUrl: 'Backend URL',
    providerDefault: 'Provider default',
    googleThinking: 'Gemini Thinking',
    openaiReasoning: 'OpenAI Reasoning',
    anthropicEffort: 'Claude Effort',
    agentTimeline: 'Agent Timeline',
    teamColumn: 'Team',
    agentColumn: 'Agent',
    statusColumn: 'Status',
    analystTeam: 'Analyst Team',
    researchTeam: 'Research Team',
    tradingTeam: 'Trading Team',
    riskManagement: 'Risk Management',
    portfolioManagement: 'Portfolio Management',
    otherTeam: 'Other',
    runHistory: 'Run History',
    liveStream: 'Live Stream',
    analysisReport: 'Analysis Report',
    reportSection: 'Report section',
    reportAll: 'All',
    refreshHistory: 'Refresh history',
    clearLog: 'Clear log',
    loadReport: 'Load report',
    events: 'events',
    event: 'event',
    system: 'system',
    starting: 'Starting...',
    failedToStart: 'Failed to start',
    cancelRequested: 'Cancel requested',
    runCompleted: 'Run completed',
    runCancelled: 'Run cancelled',
    runFailed: 'Run failed',
    reportUnavailable: 'Report is not available yet.',
    reportPlaceholder: 'Run an analysis to see the report here.',
    statusPending: 'pending',
    statusRunning: 'running',
    statusCompleted: 'completed',
    statusFailed: 'failed',
    statusCancelled: 'cancelled',
    eventRunStarted: 'run started',
    eventMessage: 'message',
    eventToolCall: 'tool call',
    eventAgentStatus: 'agent status',
    eventReportSection: 'report section',
    eventRunCompleted: 'run completed',
    eventRunCancelled: 'run cancelled',
    eventError: 'error',
    reportUpdated: 'updated',
    liveReportTitle: 'Live Analysis Report',
  },
  zh: {
    pageTitle: 'TradingAgents — AI 市场情报',
    brandTagline: 'AI 驱动的市场情报',
    navRun: '运行',
    navSettings: '配置',
    statusReady: '就绪',
    noRun: '无运行',
    ticker: '标的',
    tickerCustom: '自定义标的...',
    tickerPlaceholder: '例如 SPY, 0700.HK, BTC-USD',
    analysisDate: '分析日期',
    assetType: '资产类型',
    assetStock: '股票',
    assetCrypto: '加密货币',
    analysts: '分析师',
    analystMarket: '市场',
    analystSocial: '情绪',
    analystNews: '新闻',
    analystFundamentals: '基本面',
    startAnalysis: '开始分析',
    cancel: '取消',
    settingsTitle: '运行配置',
    settingsSubtitle: '启动新分析时使用的默认配置。',
    resetDefaults: '恢复默认',
    uiLanguage: '界面语言',
    uiLanguageAuto: '自动',
    reportLanguage: '报告语言',
    analysisDepth: '分析深度',
    depthShallow: '浅层 · 快速研究',
    depthMedium: '中等 · 适度辩论',
    depthDeep: '深度 · 全面研究',
    llmProvider: 'LLM 提供商',
    quickModel: '快速模型',
    deepModel: '深度模型',
    backendUrl: '后端地址',
    providerDefault: '使用提供商默认值',
    googleThinking: 'Gemini 思考模式',
    openaiReasoning: 'OpenAI 推理强度',
    anthropicEffort: 'Claude 强度',
    agentTimeline: 'Agent 时间线',
    teamColumn: '团队',
    agentColumn: 'Agent',
    statusColumn: '状态',
    analystTeam: '分析师团队',
    researchTeam: '研究团队',
    tradingTeam: '交易团队',
    riskManagement: '风险管理',
    portfolioManagement: '组合管理',
    otherTeam: '其他',
    runHistory: '运行历史',
    liveStream: '实时流',
    analysisReport: '分析报告',
    reportSection: '报告章节',
    reportAll: '全部',
    refreshHistory: '刷新历史',
    clearLog: '清空日志',
    loadReport: '加载报告',
    events: '个事件',
    event: '个事件',
    system: '系统',
    starting: '启动中...',
    failedToStart: '启动失败',
    cancelRequested: '已请求取消',
    runCompleted: '运行完成',
    runCancelled: '运行已取消',
    runFailed: '运行失败',
    reportUnavailable: '报告尚不可用。',
    reportPlaceholder: '运行一次分析后会在这里显示报告。',
    statusPending: '等待中',
    statusRunning: '运行中',
    statusCompleted: '已完成',
    statusFailed: '失败',
    statusCancelled: '已取消',
    eventRunStarted: '运行开始',
    eventMessage: '消息',
    eventToolCall: '工具调用',
    eventAgentStatus: 'Agent 状态',
    eventReportSection: '报告章节',
    eventRunCompleted: '运行完成',
    eventRunCancelled: '运行取消',
    eventError: '错误',
    reportUpdated: '已更新',
    liveReportTitle: '实时分析报告',
  },
};
const modelPresets = {
  'minimax-cn': {
    quick: 'MiniMax-M3',
    deep: 'MiniMax-M3',
  },
  minimax: {
    quick: 'MiniMax-M3',
    deep: 'MiniMax-M3',
  },
  openai: {
    quick: 'gpt-5.4-mini',
    deep: 'gpt-5.5',
  },
  anthropic: {
    quick: 'claude-4-haiku',
    deep: 'claude-4.5-sonnet',
  },
  google: {
    quick: 'gemini-3-flash-preview',
    deep: 'gemini-3-pro-preview',
  },
  'qwen-cn': {
    quick: 'qwen-plus',
    deep: 'qwen-max',
  },
  openrouter: {
    quick: 'openai/gpt-5.4-mini',
    deep: 'openai/gpt-5.5',
  },
  openai_compatible: {
    quick: 'MiniMax-M3',
    deep: 'MiniMax-M3',
  },
};
const agentTeams = [
  {
    key: 'analystTeam',
    agents: ['Market Analyst', 'Sentiment Analyst', 'News Analyst', 'Fundamentals Analyst'],
  },
  {
    key: 'researchTeam',
    agents: ['Bull Researcher', 'Bear Researcher', 'Research Manager'],
  },
  {
    key: 'tradingTeam',
    agents: ['Trader'],
  },
  {
    key: 'riskManagement',
    agents: ['Aggressive Analyst', 'Neutral Analyst', 'Conservative Analyst'],
  },
  {
    key: 'portfolioManagement',
    agents: ['Portfolio Manager'],
  },
];
const reportSectionOrder = [
  'market_report',
  'sentiment_report',
  'news_report',
  'fundamentals_report',
  'bull_researcher',
  'bear_researcher',
  'investment_plan',
  'trader_investment_plan',
  'aggressive_analyst',
  'conservative_analyst',
  'neutral_analyst',
  'final_trade_decision',
];
const reportSectionTitles = {
  market_report: 'Market Analyst',
  sentiment_report: 'Sentiment Analyst',
  news_report: 'News Analyst',
  fundamentals_report: 'Fundamentals Analyst',
  bull_researcher: 'Bull Researcher',
  bear_researcher: 'Bear Researcher',
  investment_plan: 'Research Team Decision',
  trader_investment_plan: 'Trader',
  aggressive_analyst: 'Aggressive Analyst',
  conservative_analyst: 'Conservative Analyst',
  neutral_analyst: 'Neutral Analyst',
  final_trade_decision: 'Portfolio Manager',
};

// ── Initialise date field ────────────────────────────────────────────────────
document.querySelector('#analysisDate').value = new Date().toISOString().slice(0, 10);

// Show empty-state placeholder in the report panel on load
initializeLocale();
showReportPlaceholder();
loadConfigDefaults();

runViewButton.addEventListener('click', () => showView('run'));
settingsViewButton.addEventListener('click', () => showView('settings'));
window.addEventListener('hashchange', handleHashRoute);
handleHashRoute();

settingsForm.addEventListener('input', saveSettings);
settingsForm.addEventListener('change', saveSettings);

tickerSelect.addEventListener('change', updateTickerMode);

uiLanguage.addEventListener('change', () => {
  saveUiLanguage(uiLanguage.value);
  initializeLocale();
  renderDynamicLabels();
});

resetSettings.addEventListener('click', () => {
  try {
    window.localStorage.removeItem(settingsStorageKey);
  } catch {
    // Ignore storage failures; resetting the visible form is still useful.
  }
  if (configDefaults) {
    applyConfigDefaults(configDefaults);
    saveSettings();
  }
});

llmProvider.addEventListener('change', () => {
  const preset = modelPresets[llmProvider.value];
  if (preset) {
    quickThinkLlm.value = preset.quick;
    deepThinkLlm.value = preset.deep;
  }
  updateProviderOptions();
  saveSettings();
});

// ── Form submit ──────────────────────────────────────────────────────────────
form.addEventListener('submit', async event => {
  event.preventDefault();
  resetRun();

  const payload = buildPayload(new FormData(form));
  setBusy(true);
  setStatus('starting', 'running');

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
    setRunHash(run.run_id, true);
    refreshRunHistory();
    connectEvents(run.run_id);
  } catch (error) {
    setStatus('failed_to_start', 'error');
    appendEvent('error', null, error.message);
    setBusy(false);
  }
});

// ── Cancel button ────────────────────────────────────────────────────────────
cancelButton.addEventListener('click', async () => {
  if (!currentRunId) return;
  await fetch(`/api/runs/${currentRunId}/cancel`, { method: 'POST' });
  setStatus('cancel_requested', 'running');
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

reportSectionSelect.addEventListener('change', () => {
  selectedReportSection = reportSectionSelect.value;
  renderLiveReport();
});

// Load run history on startup
refreshRunHistory();

// ── Helpers ──────────────────────────────────────────────────────────────────

async function loadConfigDefaults() {
  try {
    const response = await fetch('/api/config/defaults');
    if (!response.ok) return;
    configDefaults = await response.json();
    applyConfigDefaults(configDefaults);
    applySavedSettings();
  } catch {
    // Keep the static HTML defaults when the API is unavailable.
    applySavedSettings();
  }
}

function applyConfigDefaults(defaults) {
  setFieldValue(llmProvider, defaults.llm_provider);
  setFieldValue(quickThinkLlm, defaults.quick_think_llm);
  setFieldValue(deepThinkLlm, defaults.deep_think_llm);
  setFieldValue(backendUrl, defaults.backend_url);
  setFieldValue(outputLanguage, defaults.output_language);
  setFieldValue(researchDepth, defaults.research_depth);
  setFieldValue(googleThinkingLevel, defaults.google_thinking_level);
  setFieldValue(openaiReasoningEffort, defaults.openai_reasoning_effort);
  setFieldValue(anthropicEffort, defaults.anthropic_effort);
  updateProviderOptions();
}

function setFieldValue(field, value) {
  if (!field || value === undefined || value === null || value === '') return;
  field.value = String(value);
}

function applySavedSettings() {
  let saved;
  try {
    saved = JSON.parse(window.localStorage.getItem(settingsStorageKey) || 'null');
  } catch {
    return;
  }
  if (!saved) return;
  setFieldValue(llmProvider, saved.llm_provider);
  setFieldValue(quickThinkLlm, saved.quick_think_llm);
  setFieldValue(deepThinkLlm, saved.deep_think_llm);
  setFieldValue(backendUrl, saved.backend_url);
  setFieldValue(outputLanguage, saved.output_language);
  setFieldValue(researchDepth, saved.research_depth);
  setFieldValue(googleThinkingLevel, saved.google_thinking_level);
  setFieldValue(openaiReasoningEffort, saved.openai_reasoning_effort);
  setFieldValue(anthropicEffort, saved.anthropic_effort);
  updateProviderOptions();
}

function initializeLocale() {
  const selected = savedUiLanguage();
  setFieldValue(uiLanguage, selected);
  activeLocale = resolveLocale(selected);
  applyTranslations();
}

function savedUiLanguage() {
  try {
    return window.localStorage.getItem(uiLanguageStorageKey) || 'auto';
  } catch {
    return 'auto';
  }
}

function saveUiLanguage(value) {
  try {
    window.localStorage.setItem(uiLanguageStorageKey, value);
  } catch {
    // UI language persistence is optional.
  }
}

function resolveLocale(value) {
  if (value === 'zh' || value === 'en') return value;
  return navigator.language?.toLowerCase().startsWith('zh') ? 'zh' : 'en';
}

function t(key) {
  return translations[activeLocale]?.[key] ?? translations.en[key] ?? key;
}

function applyTranslations() {
  document.documentElement.lang = activeLocale === 'zh' ? 'zh-CN' : 'en';
  document.title = t('pageTitle');

  document.querySelectorAll('[data-i18n]').forEach(element => {
    element.textContent = t(element.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-title]').forEach(element => {
    element.title = t(element.dataset.i18nTitle);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(element => {
    element.placeholder = t(element.dataset.i18nPlaceholder);
  });

  if (!currentRunId) runIdEl.textContent = t('noRun');
  statusEl.textContent = formatStatus(currentStatus);
  updateEventCount();
  if (reportViewer.querySelector('.report-empty')) showReportPlaceholder();
}

function renderDynamicLabels() {
  updateEventCount();
  updateAgentList();
  updateReportSectionOptions();
  if (reportSections.size) renderLiveReport();
  refreshRunHistory();
}

function updateEventCount() {
  eventCountEl.textContent = formatEventCount(eventCount);
}

function formatEventCount(count) {
  if (activeLocale === 'zh') return `${count} ${t(count === 1 ? 'event' : 'events')}`;
  return `${count} ${t(count === 1 ? 'event' : 'events')}`;
}

function formatStatus(status) {
  const key = {
    pending: 'statusPending',
    running: 'statusRunning',
    completed: 'statusCompleted',
    failed: 'statusFailed',
    cancelled: 'statusCancelled',
    ready: 'statusReady',
    starting: 'starting',
    failed_to_start: 'failedToStart',
    cancel_requested: 'cancelRequested',
  }[statusClassName(status)];
  if (key) return t(key);
  return status;
}

function formatEventType(type) {
  const key = {
    run_started: 'eventRunStarted',
    message: 'eventMessage',
    tool_call: 'eventToolCall',
    agent_status: 'eventAgentStatus',
    report_section: 'eventReportSection',
    run_completed: 'eventRunCompleted',
    run_cancelled: 'eventRunCancelled',
    error: 'eventError',
  }[type];
  return key ? t(key) : type.replace(/_/g, ' ');
}

function statusClassName(status) {
  return String(status || 'pending')
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_')
    .replace(/[^a-z0-9_]/g, '');
}

function currentSettings() {
  return {
    research_depth: Number.isFinite(Number(researchDepth.value)) && Number(researchDepth.value) > 0
      ? Number(researchDepth.value)
      : null,
    llm_provider: llmProvider.value,
    quick_think_llm: quickThinkLlm.value.trim() || null,
    deep_think_llm: deepThinkLlm.value.trim() || null,
    backend_url: backendUrl.value.trim() || null,
    output_language: outputLanguage.value,
    google_thinking_level: googleThinkingLevel.value || null,
    openai_reasoning_effort: openaiReasoningEffort.value || null,
    anthropic_effort: anthropicEffort.value || null,
  };
}

function updateProviderOptions() {
  const provider = llmProvider.value;
  document.querySelectorAll('.provider-option').forEach(element => {
    element.hidden = true;
  });
  const activeClass = {
    google: '.provider-google',
    openai: '.provider-openai',
    anthropic: '.provider-anthropic',
  }[provider];
  if (!activeClass) return;
  document.querySelectorAll(activeClass).forEach(element => {
    element.hidden = false;
  });
}

function saveSettings() {
  try {
    window.localStorage.setItem(settingsStorageKey, JSON.stringify(currentSettings()));
  } catch {
    // Local persistence is optional; the visible form remains the source for this run.
  }
}

function showView(view, updateHash = true) {
  const settingsActive = view === 'settings';
  runControls.classList.toggle('hidden', settingsActive);
  runView.classList.toggle('hidden', settingsActive);
  settingsView.classList.toggle('hidden', !settingsActive);
  runControls.hidden = settingsActive;
  runView.hidden = settingsActive;
  settingsView.hidden = !settingsActive;
  runViewButton.classList.toggle('active', !settingsActive);
  settingsViewButton.classList.toggle('active', settingsActive);
  if (updateHash) {
    if (settingsActive) {
      window.location.hash = 'settings';
    } else if (currentRunId) {
      setRunHash(currentRunId);
    } else {
      window.history.replaceState(null, '', window.location.pathname);
    }
  }
}

function handleHashRoute() {
  const hash = window.location.hash.slice(1);
  if (hash === 'settings') {
    showView('settings', false);
    return;
  }

  if (hash.startsWith('run=')) {
    const runId = decodeURIComponent(hash.slice(4));
    showView('run', false);
    if (runId && runId !== currentRunId) {
      selectHistoryRun(runId, { updateHash: false });
    }
    return;
  }

  showView('run', false);
}

function setRunHash(runId, replace = false) {
  const target = `#run=${encodeURIComponent(runId)}`;
  if (window.location.hash === target) return;
  if (replace) {
    window.history.replaceState(null, '', target);
  } else {
    window.location.hash = target;
  }
}

function buildPayload(data) {
  const selectedAnalysts = data.getAll('analysts');
  const settings = currentSettings();
  return {
    ticker: selectedTicker(data),
    analysis_date: data.get('analysisDate'),
    asset_type: data.get('assetType'),
    selected_analysts: selectedAnalysts.length ? selectedAnalysts : ['market'],
    ...settings,
  };
}

function selectedTicker(data) {
  const selected = String(data.get('ticker') || '').trim();
  const raw = selected === '__custom'
    ? String(data.get('customTicker') || '').trim()
    : selected;
  return raw.toUpperCase();
}

function updateTickerMode() {
  const custom = tickerSelect.value === '__custom';
  customTicker.hidden = !custom;
  customTicker.required = custom;
  if (custom) customTicker.focus();
}

/** Return a short, displayable run ID (last 8 chars). */
function shortId(id) {
  if (!id || id === t('noRun')) return id;
  return id.length > 12 ? '…' + id.slice(-8) : id;
}

function resetRun() {
  if (source) source.close();
  source       = null;
  currentRunId = null;
  eventCount   = 0;
  agents.clear();
  reportSections.clear();
  selectedReportSection = 'all';
  eventLog.replaceChildren();
  agentList.replaceChildren();
  updateReportSectionOptions();
  showReportPlaceholder();
  runIdEl.textContent       = t('noRun');
  updateEventCount();
  loadReport.disabled       = true;
}

// ── SSE connection ────────────────────────────────────────────────────────────
function connectEvents(runId) {
  if (source) source.close();
  source = new EventSource(`/api/runs/${runId}/events`);
  let streamErrorLogged = false;

  const eventTypes = [
    'run_started',
    'message',
    'tool_call',
    'agent_status',
    'report_section',
    'run_completed',
    'run_cancelled',
    'error',
  ];

  for (const type of eventTypes) {
    source.addEventListener(type, ev =>
      handleRuntimeEvent(type, JSON.parse(ev.data))
    );
  }

  source.onerror = () => {
    if (!streamErrorLogged) {
      appendEvent('error', null, 'Event stream reconnecting');
      streamErrorLogged = true;
    }
  };
}

function handleRuntimeEvent(type, event) {
  eventCount += 1;
  updateEventCount();

  if (type === 'agent_status' && event.agent) {
    updateAgent(event.agent, event.content?.status ?? 'pending');
  }

  if (type === 'report_section') {
    updateReportSection(event.content);
  }

  if (type === 'run_completed') {
    setStatus('completed', 'done');
    loadReport.disabled = false;
    cancelButton.disabled = true;
    appendEvent(type, event.agent, event.content?.decision ?? t('runCompleted'));
    loadRunReport(currentRunId);
    refreshRunHistory();
    closeStream();
    return;
  }

  if (type === 'run_cancelled') {
    setStatus('cancelled', 'error');
    cancelButton.disabled = true;
    appendEvent(type, event.agent, event.content?.message ?? t('runCancelled'));
    refreshRunHistory();
    closeStream();
    return;
  }

  if (type === 'error') {
    setStatus('failed', 'error');
    cancelButton.disabled = true;
    appendEvent(type, event.agent, event.content?.error ?? t('runFailed'));
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
  updateAgentList();
}

function updateAgentList() {
  const rows = [renderAgentHeader()];
  const rendered = new Set();

  for (const team of agentTeams) {
    const activeAgents = team.agents.filter(agent => agents.has(agent));
    activeAgents.forEach((agent, index) => {
      rendered.add(agent);
      rows.push(renderAgentRow(index === 0 ? t(team.key) : '', agent, agents.get(agent)));
    });
  }

  const otherAgents = Array.from(agents.keys()).filter(agent => !rendered.has(agent));
  otherAgents.forEach((agent, index) => {
    rows.push(renderAgentRow(index === 0 ? t('otherTeam') : '', agent, agents.get(agent)));
  });

  agentList.replaceChildren(...rows);
}

function renderAgentHeader() {
  const item = document.createElement('li');
  item.className = 'agent-row agent-row-header';
  item.append(
    agentCell(t('teamColumn'), 'agent-team'),
    agentCell(t('agentColumn'), 'agent-name'),
    agentCell(t('statusColumn'), 'agent-status'),
  );
  return item;
}

function renderAgentRow(teamName, agent, status) {
  const item = document.createElement('li');
  item.className = `agent-row status-${statusClassName(status)}`;

  const team = agentCell(teamName, 'agent-team');
  const name = agentCell('', 'agent-name');
  const dot = document.createElement('span');
  dot.className = 'dot';
  const label = document.createElement('span');
  label.textContent = formatAgentName(agent);
  name.append(dot, label);

  const state = agentCell(formatStatus(status), 'agent-status');
  item.append(team, name, state);
  return item;
}

function agentCell(text, className) {
  const cell = document.createElement('span');
  cell.className = className;
  cell.textContent = text;
  return cell;
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
  statusBadge.textContent = formatStatus(run.status);

  const count = document.createElement('span');
  count.textContent = formatEventCount(run.event_count);

  meta.append(statusBadge, count);
  item.append(button, meta);
  return item;
}

async function selectHistoryRun(runId, options = {}) {
  if (options.updateHash !== false) {
    setRunHash(runId);
    return;
  }

  if (source) source.close();
  source = null;

  const response = await fetch(`/api/runs/${runId}`);
  if (!response.ok) return;
  const run = await response.json();

  currentRunId   = run.run_id;
  runIdEl.textContent      = shortId(run.run_id);
  setStatus(run.status, statusClass(run.status));
  eventCount     = 0;
  updateEventCount();
  reportSections.clear();
  selectedReportSection = 'all';
  updateReportSectionOptions();
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
  badge.textContent = formatEventType(type);

  const agentSpan = document.createElement('span');
  agentSpan.className = 'event-agent';
  agentSpan.textContent = agent ? formatAgentName(agent) : t('system');

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
  if (type === 'report_section') return `${content.section || 'report'} ${t('reportUpdated')}`;
  if (type === 'agent_status')   return formatStatus(content.status || '');
  if (type === 'run_started')    return `${content.ticker} · ${content.analysis_date}`;
  return JSON.stringify(content);
}

// ── Report viewer ─────────────────────────────────────────────────────────────
function updateReportSection(content) {
  if (!content || typeof content !== 'object') return;
  const section = content.section;
  const text = content.text;
  if (!section || !text) return;
  reportSections.set(section, text);
  selectedReportSection = section;
  updateReportSectionOptions();
  renderLiveReport();
}

function renderLiveReport() {
  const sections = orderedReportSections();
  if (!sections.length) {
    showReportPlaceholder();
    return;
  }

  const selectedSections = selectedReportSection === 'all'
    ? sections
    : sections.filter(([section]) => section === selectedReportSection);
  const markdown = selectedReportSection === 'all'
    ? [
        `# ${t('liveReportTitle')}`,
        ...selectedSections.map(([section, text]) => `\n\n## ${reportSectionTitle(section)}\n\n${text}`),
      ].join('')
    : selectedSections.map(([section, text]) => `# ${reportSectionTitle(section)}\n\n${text}`).join('');
  renderMarkdown(markdown);
}

function updateReportSectionOptions() {
  const current = selectedReportSection;
  const options = [
    optionElement('all', t('reportAll')),
    ...orderedReportSections().map(([section]) => optionElement(section, reportSectionTitle(section))),
  ];
  reportSectionSelect.replaceChildren(...options);
  reportSectionSelect.disabled = reportSections.size === 0;
  reportSectionSelect.value = reportSections.has(current) || current === 'all' ? current : 'all';
}

function optionElement(value, label) {
  const option = document.createElement('option');
  option.value = value;
  option.textContent = label;
  return option;
}

function orderedReportSections() {
  const ordered = reportSectionOrder
    .filter(section => reportSections.has(section))
    .map(section => [section, reportSections.get(section)]);
  const known = new Set(reportSectionOrder);
  const extra = Array.from(reportSections.entries()).filter(([section]) => !known.has(section));
  return ordered.concat(extra);
}

function reportSectionTitle(section) {
  return reportSectionTitles[section] || formatAgentName(section);
}

async function loadRunReport(runId) {
  if (!runId) return;
  const response = await fetch(`/api/runs/${runId}/report`);
  if (!response.ok) {
    reportViewer.innerHTML = '';
    showReportPlaceholder(t('reportUnavailable'));
    return;
  }
  const text = await response.text();
  renderMarkdown(text);
}

function renderMarkdown(text) {
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

function showReportPlaceholder(message = t('reportPlaceholder')) {
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
  currentStatus = text;
  statusEl.textContent = formatStatus(text);
  statusDot.className  = `status-dot ${state ?? ''}`;
}

function statusClass(status) {
  if (status === 'completed') return 'done';
  if (status === 'running')   return 'running';
  if (status === 'failed' || status === 'cancelled') return 'error';
  return 'ready';
}
