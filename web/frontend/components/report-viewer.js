const SECTION_ORDER = [
  'market_report', 'sentiment_report', 'news_report', 'fundamentals_report',
  'bull_researcher', 'bear_researcher', 'investment_plan', 'trader_investment_plan',
  'aggressive_analyst', 'conservative_analyst', 'neutral_analyst', 'final_trade_decision',
];

const SECTION_TITLES = {
  en: {
    market_report: 'Market Analyst', sentiment_report: 'Sentiment Analyst', news_report: 'News Analyst',
    fundamentals_report: 'Fundamentals Analyst', bull_researcher: 'Bull Researcher',
    bear_researcher: 'Bear Researcher', investment_plan: 'Research Team Decision',
    trader_investment_plan: 'Trader', aggressive_analyst: 'Aggressive Analyst',
    conservative_analyst: 'Conservative Analyst', neutral_analyst: 'Neutral Analyst',
    final_trade_decision: 'Portfolio Manager',
  },
  zh: {
    market_report: '市场分析师', sentiment_report: '情绪分析师', news_report: '新闻分析师',
    fundamentals_report: '基本面分析师', bull_researcher: '看多研究员',
    bear_researcher: '看空研究员', investment_plan: '研究团队决策',
    trader_investment_plan: '交易员计划', aggressive_analyst: '激进风险分析师',
    conservative_analyst: '保守风险分析师', neutral_analyst: '中性风险分析师',
    final_trade_decision: '组合经理决策',
  },
};

export function createReportViewer({
  api, element, sectionSelect, readingModeToggle, newReportsNotice, t, locale, formatAgentName,
}) {
  const sections = new Map();
  let selected = 'all';
  let latestSection = null;
  let readingMode = false;
  let unreadCount = 0;
  let pendingReportRunId = null;

  sectionSelect.addEventListener('change', () => {
    selected = sectionSelect.value;
    renderLive();
  });
  readingModeToggle.addEventListener('click', () => { void setReadingMode(!readingMode); });
  newReportsNotice.addEventListener('click', () => { void setReadingMode(false); });

  function updateSection(content) {
    if (!content || typeof content !== 'object' || !content.section || !content.text) return;
    sections.set(content.section, content.text);
    latestSection = content.section;
    if (readingMode) {
      unreadCount += 1;
      renderOptions();
      renderReadingControls();
      return;
    }
    selected = content.section;
    renderOptions();
    renderLive();
  }

  function renderLive() {
    const available = orderedSections();
    if (!available.length) {
      placeholder();
      return;
    }
    const visible = selected === 'all' ? available : available.filter(([section]) => section === selected);
    const markdown = selected === 'all'
      ? [`# ${t('liveReportTitle')}`, ...visible.map(([section, text]) => `\n\n## ${title(section)}\n\n${text}`)].join('')
      : visible.map(([section, text]) => `# ${title(section)}\n\n${text}`).join('');
    renderMarkdown(markdown);
  }

  function renderOptions() {
    const options = [option('all', t('reportAll')), ...orderedSections().map(([section]) => option(section, title(section)))];
    sectionSelect.replaceChildren(...options);
    sectionSelect.disabled = sections.size === 0;
    sectionSelect.value = sections.has(selected) || selected === 'all' ? selected : 'all';
  }

  function orderedSections() {
    const ordered = SECTION_ORDER.filter(section => sections.has(section)).map(section => [section, sections.get(section)]);
    const known = new Set(SECTION_ORDER);
    return ordered.concat(Array.from(sections.entries()).filter(([section]) => !known.has(section)));
  }

  function title(section) {
    return SECTION_TITLES[locale()]?.[section] || SECTION_TITLES.en[section] || formatAgentName(section, locale());
  }

  async function load(runId) {
    if (!runId) return;
    if (readingMode) {
      pendingReportRunId = runId;
      renderReadingControls();
      return;
    }
    try {
      renderMarkdown(await api.getReport(runId));
    } catch {
      placeholder(t('reportUnavailable'));
    }
  }

  function renderMarkdown(text) {
    if (typeof globalThis.marked !== 'undefined') {
      element.innerHTML = globalThis.marked.parse(text);
      return;
    }
    const pre = document.createElement('pre');
    pre.textContent = text;
    element.replaceChildren(pre);
  }

  function placeholder(message = t('reportPlaceholder')) {
    element.innerHTML = `
      <div class="report-empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
          <polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line>
          <line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline>
        </svg><p></p>
      </div>`;
    element.querySelector('p').textContent = message;
  }

  function reset({ showPlaceholder = true } = {}) {
    sections.clear();
    selected = 'all';
    latestSection = null;
    readingMode = false;
    unreadCount = 0;
    pendingReportRunId = null;
    renderOptions();
    renderReadingControls();
    if (showPlaceholder) placeholder(); else element.replaceChildren();
  }

  function refresh() {
    renderOptions();
    renderReadingControls();
    if (sections.size) renderLive();
    else if (element.querySelector('.report-empty')) placeholder();
  }

  async function setReadingMode(enabled) {
    if (readingMode === enabled) return;
    readingMode = enabled;
    if (!readingMode) {
      const pendingRunId = pendingReportRunId;
      pendingReportRunId = null;
      unreadCount = 0;
      if (pendingRunId) {
        renderReadingControls();
        await load(pendingRunId);
        return;
      }
      if (latestSection) selected = latestSection;
      renderOptions();
      renderLive();
    }
    renderReadingControls();
  }

  function renderReadingControls() {
    readingModeToggle.classList.toggle('active', readingMode);
    readingModeToggle.setAttribute('aria-pressed', String(readingMode));
    readingModeToggle.title = t(readingMode ? 'readingModeOn' : 'readingModeOff');
    newReportsNotice.hidden = unreadCount === 0;
    newReportsNotice.textContent = t('newReportsLabel').replace('{count}', String(unreadCount));
  }

  renderReadingControls();
  return { updateSection, load, reset, refresh, placeholder };
}

function option(value, label) {
  const element = document.createElement('option');
  element.value = value;
  element.textContent = label;
  return element;
}
