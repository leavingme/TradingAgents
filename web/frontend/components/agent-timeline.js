const TEAMS = [
  { key: 'analystTeam', agents: ['Market Analyst', 'Sentiment Analyst', 'News Analyst', 'Fundamentals Analyst'] },
  { key: 'researchTeam', agents: ['Bull Researcher', 'Bear Researcher', 'Research Manager'] },
  { key: 'tradingTeam', agents: ['Trader'] },
  { key: 'riskManagement', agents: ['Aggressive Analyst', 'Neutral Analyst', 'Conservative Analyst'] },
  { key: 'portfolioManagement', agents: ['Portfolio Manager'] },
];

const DISPLAY_NAMES = {
  en: {},
  zh: {
    'Market Analyst': '市场分析师', 'Sentiment Analyst': '情绪分析师',
    'News Analyst': '新闻分析师', 'Fundamentals Analyst': '基本面分析师',
    'Bull Researcher': '看多研究员', 'Bear Researcher': '看空研究员',
    'Research Manager': '研究经理', Trader: '交易员',
    'Aggressive Analyst': '激进风险分析师', 'Neutral Analyst': '中性风险分析师',
    'Conservative Analyst': '保守风险分析师', 'Portfolio Manager': '组合经理',
  },
};

export function formatAgentName(name, locale = 'en') {
  const displayName = DISPLAY_NAMES[locale]?.[name];
  if (displayName) return displayName;
  return String(name || '').replace(/_/g, ' ').replace(/\b\w/g, character => character.toUpperCase());
}

export function createAgentTimeline({ element, t, locale, formatStatus, statusClassName }) {
  const agents = new Map();

  function update(name, status) {
    agents.set(name, status);
    render();
  }

  function clear() {
    agents.clear();
    element.replaceChildren();
  }

  function render() {
    const rows = [headerRow()];
    const rendered = new Set();
    TEAMS.forEach(team => {
      const active = team.agents.filter(agent => agents.has(agent));
      active.forEach((agent, index) => {
        rendered.add(agent);
        rows.push(agentRow(index === 0 ? t(team.key) : '', agent, agents.get(agent)));
      });
    });
    Array.from(agents.keys()).filter(agent => !rendered.has(agent)).forEach((agent, index) => {
      rows.push(agentRow(index === 0 ? t('otherTeam') : '', agent, agents.get(agent)));
    });
    element.replaceChildren(...rows);
  }

  function headerRow() {
    const item = document.createElement('li');
    item.className = 'agent-row agent-row-header';
    item.append(cell(t('teamColumn'), 'agent-team'), cell(t('agentColumn'), 'agent-name'), cell(t('statusColumn'), 'agent-status'));
    return item;
  }

  function agentRow(teamName, agent, status) {
    const item = document.createElement('li');
    item.className = `agent-row status-${statusClassName(status)}`;
    const name = cell('', 'agent-name');
    const dot = document.createElement('span');
    dot.className = 'dot';
    const label = document.createElement('span');
    label.textContent = formatAgentName(agent, locale());
    name.append(dot, label);
    item.append(cell(teamName, 'agent-team'), name, cell(formatStatus(status), 'agent-status'));
    return item;
  }

  return { update, clear, render };
}

function cell(text, className) {
  const element = document.createElement('span');
  element.className = className;
  element.textContent = text;
  return element;
}
