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
const providersViewButton = document.querySelector('#providersViewButton');
const settingsForm  = document.querySelector('#settingsForm');
const resetSettings = document.querySelector('#resetSettings');
const resetProviders = document.querySelector('#resetProviders');
const ohlcvSettingsBody = document.querySelector('#ohlcvSettingsBody');
const analystPromptList = document.querySelector('#analystPromptList');
const providersView = document.querySelector('#providersView');
const statusEl      = document.querySelector('#runStatus');
const statusDot     = document.querySelector('#statusDot');
const runIdEl       = document.querySelector('#runId');
const eventCountEl  = document.querySelector('#eventCount');
const llmCountEl    = document.querySelector('#llmCount');
const toolCountEl   = document.querySelector('#toolCount');
const tokenCountEl  = document.querySelector('#tokenCount');
const agentList     = document.querySelector('#agentList');
const eventLog      = document.querySelector('#eventLog');
const reportViewer  = document.querySelector('#reportViewer');
const startButton   = document.querySelector('#startButton');
const cancelButton  = document.querySelector('#cancelButton');
const clearLog      = document.querySelector('#clearLog');
const loadReport    = document.querySelector('#loadReport');
const reportSectionSelect = document.querySelector('#reportSectionSelect');
const refreshHistory= document.querySelector('#refreshHistory');
const clearHistory  = document.querySelector('#clearHistory');
const historyList   = document.querySelector('#historyList');
const apiKeyStatusList = document.querySelector('#apiKeyStatusList');
const llmProvider   = document.querySelector('#llmProvider');
const quickThinkLlm = document.querySelector('#quickThinkLlm');
const deepThinkLlm  = document.querySelector('#deepThinkLlm');
const backendUrl    = document.querySelector('#backendUrl');
const outputLanguage= document.querySelector('#outputLanguage');
const customOutputLanguage = document.querySelector('#customOutputLanguage');
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
let currentStats = { llm_calls: 0, tool_calls: 0, tokens_in: 0, tokens_out: 0 };
const agents     = new Map();
const reportSections = new Map();
let selectedReportSection = 'all';
let configDefaults = null;
let envStatus = null;
let analystPrompts = [];
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
    apiKeyStatus: 'API Key Status',
    apiKeyConfigured: 'configured',
    apiKeyMissing: 'missing',
    apiKeyNotRequired: 'not required',
    analystPrompts: 'Analyst Prompts',
    analystPromptsSubtitle: 'Review the read-only prompts used by each analyst.',
    analystPromptTools: 'Tools',
    analystPromptUnavailable: 'Analyst prompts are unavailable.',
    uiLanguage: 'UI Language',
    uiLanguageAuto: 'Auto',
    reportLanguage: 'Report Language',
    customLanguage: 'Custom language...',
    customLanguagePlaceholder: 'e.g. Turkish, Vietnamese, Thai, Indonesian',
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
    eventStats: 'stats',
    eventRunCompleted: 'run completed',
    eventRunCancelled: 'run cancelled',
    eventError: 'error',
    reportUpdated: 'updated',
    liveReportTitle: 'Live Analysis Report',
    llmCalls: 'LLM',
    toolCalls: 'tools',
    tokens: 'Tokens',
    navProviders: 'Providers',
    providersTitle: 'Capability Providers',
    providersSubtitle: 'Select and prioritize data & capability providers for your analysis runs.',
    providersSummaryTitle: 'Provider Data Capability Summary',
    providersSummarySubtitle: 'Verified by real provider requests. This summarizes market coverage, newest available data, and the smallest K-line interval each provider can return.',
    resetProviders: 'Reset Defaults',
    prioritySetting: 'Priority & Enable Settings',
    sideBySideComparison: 'Side-by-Side Comparison',
    summaryProvider: 'Provider',
    summaryMarkets: 'Markets',
    summaryLatest: 'Newest data observed',
    summaryGranularity: 'Smallest K-line interval',
    summaryNotes: 'Notes',
    coverageUsHkCn: 'US stocks / Hong Kong stocks / China A-shares',
    summaryMarketsAll: 'US stocks / China A-shares / Hong Kong stocks',
    summaryWestockLatest: 'Observed latest rows: US stocks 2026-07-07, China A-shares 2026-07-08, Hong Kong stocks 2026-07-08',
    summaryWestockGranularity: '1-minute K-line for China A-shares only',
    summaryWestockNote: 'Works well as the default OHLCV source. Its minute-level K-line data is limited to China A-share stocks.',
    summaryLongbridgeCliLatest: 'Observed current data for US stocks, China A-shares, and Hong Kong stocks',
    summaryLongbridgeGranularity: '1-minute K-line supported',
    summaryLongbridgeCliNote: 'Useful when Westock data is stale, unavailable, or when minute-level data is needed outside China A-shares.',
    summaryLongbridgeMcpLatest: 'Observed current data for US stocks, China A-shares, and Hong Kong stocks',
    summaryLongbridgeMcpNote: 'Provides the same market coverage as Longbridge CLI when the Longbridge MCP credential is valid.',
    providersSummaryFootnote: 'Last real provider verification: 2026-07-08.',
    compProvider: 'Provider',
    compSpeed: 'Speed',
    compQuality: 'Quality',
    compApiKey: 'API Key',
    compRateLimit: 'Rate Limit',
    compCoverage: 'Coverage',
    providerSettings: 'Current Settings',
    providerStatus: 'Status',
    providerEnabled: 'enabled',
    providerDisabled: 'disabled',
    providerPriority: 'priority',
    vendorVerify: 'Verify now',
    vendorVerifying: 'Verifying',
    vendorNeverVerified: 'Not verified yet',
    vendorVerifiedAnalysis: 'Analysis run',
    vendorVerifiedManual: 'Manual check',
    vendorAvailable: 'Available',
    vendorUnavailable: 'Unavailable',
    vendorNoData: 'No data',
    vendorRateLimited: 'Rate limited',
    vendorNotConfigured: 'Not configured',
    compTokenRequired: 'Token Required',
    compKeyRequired: 'Key Required',
    compNone: 'None',
    compHigh: 'High',
    compMedium: 'Medium',
    compTight: 'Tight',
    compGlobal: 'Global',
    compNoLimit: 'No Limit',
    compNewsFallbackCoverage: 'Ticker and global news fallback only',
    compNewsFullCoverage: 'Ticker news / global news / insider transactions',
    catCoreStockTitle: 'Core Stock Price Data (OHLCV)',
    catCoreStockDesc: 'Provides historical and current price bar data for target tickers.',
    catTechIndTitle: 'Technical Indicators',
    catTechIndDesc: 'Provides indicators like SMA, EMA, MACD, RSI, and Bollinger Bands.',
    indicatorSourceTitle: 'Indicator Coverage & Source',
    indicatorSourceDesc: 'Shows whether each technical indicator is directly provided by a vendor, computed by the vendor, or computed locally from OHLCV data.',
    indicatorColumn: 'Indicator',
    indicatorMeaningColumn: 'Meaning',
    indicatorSourceLocal: 'Local calculation',
    indicatorSourceVendor: 'Vendor-side calculation',
    indicatorSourceNative: 'Native API',
    indicatorSourceMissing: 'Not wired',
    indicatorClose10Ema: '10-day EMA',
    indicatorClose50Sma: '50-day SMA',
    indicatorClose200Sma: '200-day SMA',
    indicatorSma: '20-day SMA alias',
    indicatorSma50: '50-day SMA alias',
    indicatorMacd: 'MACD line',
    indicatorMacds: 'MACD signal line',
    indicatorMacdh: 'MACD histogram',
    indicatorRsi: 'RSI',
    indicatorBoll: 'Bollinger middle band',
    indicatorBollUb: 'Bollinger upper band',
    indicatorBollLb: 'Bollinger lower band',
    indicatorAtr: 'ATR volatility',
    indicatorVwma: 'Volume-weighted moving average',
    indicatorMfi: 'Money Flow Index',
    indicatorSourceFootnote: 'Verified capability: Westock passed 13 indicators; Longbridge MCP and CLI passed 14 indicators across US stocks, China A-shares, and Hong Kong stocks. Alpha Vantage is shown for source type comparison and is not in the default technical-indicator chain.',
    catFundamentalsTitle: 'Company Fundamental Data',
    catFundamentalsDesc: 'Financial statements (income statements, balance sheets, cashflow statements).',
    catNewsTitle: 'News & Social Data',
    catNewsDesc: 'Fetches ticker news, global market news, and insider transactions. DuckDuckGo is a configurable fallback for news search.',
    catMacroTitle: 'Macroeconomic Data',
    catMacroDesc: 'Economic metrics like inflation, GDP, central bank interest rates.',
    catPredictionTitle: 'Prediction Markets',
    catPredictionDesc: 'Market-implied probabilities for forward-looking macro events.',
    badgeUltraFast: 'Ultra Fast',
    badgeFast: 'Fast',
    badgeMedium: 'Medium',
    badgeSlower: 'Slower',
    badgeStandard: 'Standard',
    badgePremium: 'Premium',
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
    apiKeyStatus: 'API Key 状态',
    apiKeyConfigured: '已配置',
    apiKeyMissing: '未配置',
    apiKeyNotRequired: '无需配置',
    analystPrompts: '分析师提示词',
    analystPromptsSubtitle: '查看每位分析师实际使用的只读提示词。',
    analystPromptTools: '工具',
    analystPromptUnavailable: '暂时无法加载分析师提示词。',
    uiLanguage: '界面语言',
    uiLanguageAuto: '自动',
    reportLanguage: '报告语言',
    customLanguage: '自定义语言...',
    customLanguagePlaceholder: '例如 Turkish, Vietnamese, Thai, Indonesian',
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
    eventStats: '统计',
    eventRunCompleted: '运行完成',
    eventRunCancelled: '运行取消',
    eventError: '错误',
    reportUpdated: '已更新',
    liveReportTitle: '实时分析报告',
    llmCalls: 'LLM',
    toolCalls: '工具',
    tokens: 'Tokens',
    navProviders: '服务商',
    providersTitle: '服务商配置',
    providersSubtitle: '管理及排列各个底层能力的数服务商优先级及开关。',
    providersSummaryTitle: '数据能力实测摘要',
    providersSummarySubtitle: '基于真实服务商请求验证，汇总各服务商支持的市场、能拿到的最新数据，以及最小 K 线周期。',
    resetProviders: '恢复默认',
    prioritySetting: '优先级及启用设置',
    sideBySideComparison: '服务商横向评测',
    summaryProvider: '服务商',
    summaryMarkets: '市场覆盖',
    summaryLatest: '实测最新数据',
    summaryGranularity: '最小 K 线周期',
    summaryNotes: '说明',
    coverageUsHkCn: '美股 / 港股 / A 股',
    summaryMarketsAll: '美股 / A 股 / 港股',
    summaryWestockLatest: '实测最新数据：美股 2026-07-07，A 股 2026-07-08，港股 2026-07-08',
    summaryWestockGranularity: '仅 A 股支持 1 分钟 K 线',
    summaryWestockNote: '适合做默认 OHLCV 来源，但分钟级 K 线仅覆盖 A 股个股。',
    summaryLongbridgeCliLatest: '实测美股、A 股、港股均可获得当前数据',
    summaryLongbridgeGranularity: '支持 1 分钟 K 线',
    summaryLongbridgeCliNote: '当 Westock 数据过旧、不可用，或需要 A 股之外的分钟级数据时，适合作为备用来源。',
    summaryLongbridgeMcpLatest: '实测美股、A 股、港股均可获得当前数据',
    summaryLongbridgeMcpNote: 'Longbridge MCP 凭证有效时，市场覆盖与 Longbridge CLI 一致。',
    providersSummaryFootnote: '最后一次真实服务商验证：2026-07-08。',
    compProvider: '服务商',
    compSpeed: '速度',
    compQuality: '数据质量',
    compApiKey: 'API 密钥',
    compRateLimit: '频次限制',
    compCoverage: '覆盖范围',
    providerSettings: '当前设置',
    providerStatus: '状态',
    providerEnabled: '已启用',
    providerDisabled: '未启用',
    providerPriority: '优先级',
    vendorVerify: '立即验证',
    vendorVerifying: '验证中',
    vendorNeverVerified: '尚未验证',
    vendorVerifiedAnalysis: '分析运行',
    vendorVerifiedManual: '手动验证',
    vendorAvailable: '可用',
    vendorUnavailable: '不可用',
    vendorNoData: '无数据',
    vendorRateLimited: '达到频率限制',
    vendorNotConfigured: '未配置',
    compTokenRequired: '需要 Token',
    compKeyRequired: '需要 API Key',
    compNone: '无需',
    compHigh: '高频 / 宽裕',
    compMedium: '中等频次',
    compTight: '极其严格',
    compGlobal: '全球',
    compNoLimit: '无限制 (本地计算)',
    compNewsFallbackCoverage: '仅个股新闻和全球新闻 fallback',
    compNewsFullCoverage: '个股新闻 / 全球新闻 / 内幕交易',
    catCoreStockTitle: '核心 K 线股价数据 (OHLCV)',
    catCoreStockDesc: '提供个股的历史和实时K线数据。',
    catTechIndTitle: '技术分析指标',
    catTechIndDesc: '提供 SMA, EMA, MACD, RSI, 布林带等指标。',
    indicatorSourceTitle: '指标覆盖与来源',
    indicatorSourceDesc: '说明每个技术指标是服务商原生提供、服务商侧计算，还是由项目基于 OHLCV 本地计算。',
    indicatorColumn: '指标',
    indicatorMeaningColumn: '含义',
    indicatorSourceLocal: '本地计算',
    indicatorSourceVendor: '服务商侧计算',
    indicatorSourceNative: '原生提供',
    indicatorSourceMissing: '未接入',
    indicatorClose10Ema: '10 日 EMA',
    indicatorClose50Sma: '50 日 SMA',
    indicatorClose200Sma: '200 日 SMA',
    indicatorSma: '20 日 SMA 别名',
    indicatorSma50: '50 日 SMA 别名',
    indicatorMacd: 'MACD 线',
    indicatorMacds: 'MACD 信号线',
    indicatorMacdh: 'MACD 柱状图',
    indicatorRsi: 'RSI',
    indicatorBoll: '布林带中轨',
    indicatorBollUb: '布林带上轨',
    indicatorBollLb: '布林带下轨',
    indicatorAtr: 'ATR 波动率',
    indicatorVwma: '成交量加权均线',
    indicatorMfi: '资金流量指标',
    indicatorSourceFootnote: '能力验证结果：Westock 通过 13 个指标；Longbridge MCP 和 CLI 通过 14 个指标，验证范围覆盖美股、A 股和港股。Alpha Vantage 仅用于说明来源类型，不在默认技术指标链中。',
    catFundamentalsTitle: '公司财务基本面数据',
    catFundamentalsDesc: '利润表、资产负债表、现金流量表等财务数据。',
    catNewsTitle: '新闻与社交动态舆情',
    catNewsDesc: '获取个股新闻、全球宏观新闻和内幕交易信息。DuckDuckGo 是可配置的新闻搜索 fallback。',
    catMacroTitle: '宏观经济数据指标',
    catMacroDesc: '美国和全球通胀、GDP、美联储利率等数据。',
    catPredictionTitle: '预测事件概率市场',
    catPredictionDesc: 'Polymarket 等前瞻性事件市场概率。',
    badgeUltraFast: '极速',
    badgeFast: '快速',
    badgeMedium: '中等',
    badgeSlower: '较慢',
    badgeStandard: '标准',
    badgePremium: '优质',
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
  en: {
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
  },
  zh: {
    market_report: '市场分析师',
    sentiment_report: '情绪分析师',
    news_report: '新闻分析师',
    fundamentals_report: '基本面分析师',
    bull_researcher: '看多研究员',
    bear_researcher: '看空研究员',
    investment_plan: '研究团队决策',
    trader_investment_plan: '交易员计划',
    aggressive_analyst: '激进风险分析师',
    conservative_analyst: '保守风险分析师',
    neutral_analyst: '中性风险分析师',
    final_trade_decision: '组合经理决策',
  },
};
const agentDisplayNames = {
  en: {
    'Market Analyst': 'Market Analyst',
    'Sentiment Analyst': 'Sentiment Analyst',
    'News Analyst': 'News Analyst',
    'Fundamentals Analyst': 'Fundamentals Analyst',
    'Bull Researcher': 'Bull Researcher',
    'Bear Researcher': 'Bear Researcher',
    'Research Manager': 'Research Manager',
    Trader: 'Trader',
    'Aggressive Analyst': 'Aggressive Analyst',
    'Neutral Analyst': 'Neutral Analyst',
    'Conservative Analyst': 'Conservative Analyst',
    'Portfolio Manager': 'Portfolio Manager',
  },
  zh: {
    'Market Analyst': '市场分析师',
    'Sentiment Analyst': '情绪分析师',
    'News Analyst': '新闻分析师',
    'Fundamentals Analyst': '基本面分析师',
    'Bull Researcher': '看多研究员',
    'Bear Researcher': '看空研究员',
    'Research Manager': '研究经理',
    Trader: '交易员',
    'Aggressive Analyst': '激进风险分析师',
    'Neutral Analyst': '中性风险分析师',
    'Conservative Analyst': '保守风险分析师',
    'Portfolio Manager': '组合经理',
  },
};

// ── Initialise date field ────────────────────────────────────────────────────
document.querySelector('#analysisDate').value = new Date().toISOString().slice(0, 10);

// Show empty-state placeholder in the report panel on load
initializeLocale();
showReportPlaceholder();
loadConfigDefaults();
loadEnvStatus();
loadAnalystPrompts();

runViewButton.addEventListener('click', () => showView('run'));
settingsViewButton.addEventListener('click', () => showView('settings'));
providersViewButton.addEventListener('click', () => {
  showView('providers');
  loadEnvStatus();
});
resetProviders.addEventListener('click', () => {
  try {
    window.localStorage.removeItem(providersStorageKey);
  } catch {}
  loadProviders();
});
window.addEventListener('hashchange', handleHashRoute);
handleHashRoute();

settingsForm.addEventListener('input', saveSettings);
settingsForm.addEventListener('change', saveSettings);
researchDepth.addEventListener('input', saveSettings);
researchDepth.addEventListener('change', saveSettings);

tickerSelect.addEventListener('change', updateTickerMode);
outputLanguage.addEventListener('change', updateOutputLanguageMode);

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
  renderApiKeyStatus();
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

clearHistory.addEventListener('click', async () => {
  const confirmMsg = activeLocale === 'zh' ? '您确定要清空所有运行历史数据吗？' : 'Are you sure you want to clear all history?';
  if (!confirm(confirmMsg)) return;
  const res = await fetch('/api/runs', { method: 'DELETE' });
  if (res.ok) {
    window.location.hash = '';
    refreshRunHistory();
    resetToInitialState();
  }
});

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
    loadProviders();
  } catch {
    // Keep the static HTML defaults when the API is unavailable.
    applySavedSettings();
    loadProviders();
  }
}

async function loadEnvStatus() {
  try {
    const response = await fetch('/api/config/env-status');
    if (!response.ok) return;
    envStatus = await response.json();
    renderApiKeyStatus();
    if (providersState && typeof providersState === 'object' && Object.keys(providersState).length > 0) {
      Object.keys(availableCategoryVendors).forEach(cat => {
        renderCategoryProviders(cat);
      });
    }
  } catch {
    // API key status is informational; runs still use server-side env config.
  }
}

async function loadAnalystPrompts() {
  if (!analystPromptList) return;
  try {
    const response = await fetch('/api/config/analyst-prompts');
    if (!response.ok) throw new Error(await response.text());
    const payload = await response.json();
    analystPrompts = Array.isArray(payload.analysts) ? payload.analysts : [];
    renderAnalystPrompts();
  } catch {
    analystPrompts = [];
    renderAnalystPrompts(true);
  }
}

function applyConfigDefaults(defaults) {
  setFieldValue(llmProvider, defaults.llm_provider);
  setFieldValue(quickThinkLlm, defaults.quick_think_llm);
  setFieldValue(deepThinkLlm, defaults.deep_think_llm);
  setFieldValue(backendUrl, defaults.backend_url);
  setFieldValue(researchDepth, defaults.research_depth);
  setFieldValue(googleThinkingLevel, defaults.google_thinking_level);
  setFieldValue(openaiReasoningEffort, defaults.openai_reasoning_effort);
  setFieldValue(anthropicEffort, defaults.anthropic_effort);
  setOutputLanguageValue(defaults.output_language);
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
  setOutputLanguageValue(saved.output_language);
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
  updateStats(currentStats);
  renderApiKeyStatus();
  renderAnalystPrompts();
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
    stats: 'eventStats',
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
    output_language: selectedOutputLanguage(),
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

function renderApiKeyStatus() {
  if (!apiKeyStatusList || !envStatus?.providers) return;
  const providers = envStatus.providers;
  const active = llmProvider.value;
  const rows = [active, 'openai_compatible']
    .concat(Object.keys(providers).filter(provider => provider !== active && provider !== 'openai_compatible'))
    .filter((provider, index, all) => providers[provider] && all.indexOf(provider) === index)
    .slice(0, 8)
    .map(provider => renderApiKeyStatusItem(provider, providers[provider], provider === active));
  apiKeyStatusList.replaceChildren(...rows);
}

function renderApiKeyStatusItem(provider, status, active) {
  const item = document.createElement('div');
  item.className = `env-status-item${active ? ' active' : ''}`;

  const name = document.createElement('span');
  name.className = 'env-status-provider';
  name.textContent = provider;

  const detail = document.createElement('span');
  detail.className = 'env-status-detail';
  detail.textContent = status.env_var || t('apiKeyNotRequired');

  const badge = document.createElement('span');
  const state = status.required
    ? (status.configured ? 'configured' : 'missing')
    : 'optional';
  badge.className = `env-status-badge ${state}`;
  badge.textContent = status.required
    ? (status.configured ? t('apiKeyConfigured') : t('apiKeyMissing'))
    : t('apiKeyNotRequired');

  item.append(name, detail, badge);
  return item;
}

function renderAnalystPrompts(loadFailed = false) {
  if (!analystPromptList) return;
  if (!analystPrompts.length) {
    const empty = document.createElement('div');
    empty.className = 'analyst-prompt-empty';
    empty.textContent = loadFailed ? t('analystPromptUnavailable') : '';
    analystPromptList.replaceChildren(empty);
    return;
  }

  const items = analystPrompts.map(promptInfo => {
    const item = document.createElement('details');
    item.className = 'analyst-prompt-item';

    const summary = document.createElement('summary');
    summary.className = 'analyst-prompt-summary';

    const titleWrap = document.createElement('span');
    titleWrap.className = 'analyst-prompt-heading';

    const title = document.createElement('span');
    title.className = 'analyst-prompt-title';
    title.textContent = analystPromptTitle(promptInfo);

    const description = document.createElement('span');
    description.className = 'analyst-prompt-description';
    description.textContent = String(promptInfo.description || '');

    titleWrap.append(title, description);
    summary.append(titleWrap);

    const body = document.createElement('div');
    body.className = 'analyst-prompt-body';

    const tools = document.createElement('div');
    tools.className = 'analyst-prompt-tools';
    const toolList = Array.isArray(promptInfo.tools) ? promptInfo.tools : [];
    tools.textContent = `${t('analystPromptTools')}: ${toolList.join(', ') || '--'}`;

    const pre = document.createElement('pre');
    pre.className = 'analyst-prompt-text';
    pre.textContent = String(promptInfo.prompt || '');

    body.append(tools, pre);
    item.append(summary, body);
    return item;
  });
  analystPromptList.replaceChildren(...items);
}

function analystPromptTitle(promptInfo) {
  const titleMap = {
    market: 'Market Analyst',
    social: 'Sentiment Analyst',
    news: 'News Analyst',
    fundamentals: 'Fundamentals Analyst',
  };
  const title = titleMap[promptInfo.key] || promptInfo.title;
  return agentDisplayNames[activeLocale]?.[title] ?? title;
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
  const providersActive = view === 'providers';
  const runActive = view === 'run';
  
  runControls.classList.toggle('hidden', settingsActive || providersActive);
  runView.classList.toggle('hidden', settingsActive || providersActive);
  settingsView.classList.toggle('hidden', !settingsActive);
  providersView.classList.toggle('hidden', !providersActive);
  
  runControls.hidden = settingsActive || providersActive;
  runView.hidden = settingsActive || providersActive;
  settingsView.hidden = !settingsActive;
  providersView.hidden = !providersActive;
  
  runViewButton.classList.toggle('active', runActive);
  settingsViewButton.classList.toggle('active', settingsActive);
  providersViewButton.classList.toggle('active', providersActive);

  if (updateHash) {
    if (settingsActive) {
      window.location.hash = 'settings';
    } else if (providersActive) {
      window.location.hash = 'providers';
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
  if (hash === 'providers') {
    showView('providers', false);
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
  const activeVendors = currentProviders();
  return {
    ticker: selectedTicker(data),
    analysis_date: data.get('analysisDate'),
    asset_type: data.get('assetType'),
    selected_analysts: selectedAnalysts.length ? selectedAnalysts : ['market'],
    ...settings,
    config_overrides: {
      data_vendors: activeVendors
    }
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

function selectedOutputLanguage() {
  const selected = outputLanguage.value;
  if (selected !== '__custom') return selected;
  return customOutputLanguage.value.trim() || 'Chinese';
}

function setOutputLanguageValue(value) {
  if (!value) return;
  const known = Array.from(outputLanguage.options).some(option => option.value === value);
  if (known) {
    outputLanguage.value = value;
    customOutputLanguage.value = '';
  } else {
    outputLanguage.value = '__custom';
    customOutputLanguage.value = value;
  }
  updateOutputLanguageMode();
}

function updateOutputLanguageMode() {
  const custom = outputLanguage.value === '__custom';
  customOutputLanguage.hidden = !custom;
  customOutputLanguage.required = custom;
  if (custom) customOutputLanguage.focus();
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
  currentStats = { llm_calls: 0, tool_calls: 0, tokens_in: 0, tokens_out: 0 };
  agents.clear();
  reportSections.clear();
  selectedReportSection = 'all';
  eventLog.replaceChildren();
  agentList.replaceChildren();
  updateReportSectionOptions();
  showReportPlaceholder();
  runIdEl.textContent       = t('noRun');
  updateEventCount();
  updateStats(currentStats);
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
    'stats',
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

  if (type === 'stats') {
    updateStats(event.content);
    return;
  }

  if (type === 'run_completed') {
    setStatus('completed', 'done');
    loadReport.disabled = false;
    cancelButton.disabled = true;
    appendEvent(type, event.agent, event.content?.decision ?? t('runCompleted'));
    loadRunReport(currentRunId);
    refreshRunHistory();
    loadEnvStatus();
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
  const displayName = agentDisplayNames[activeLocale]?.[name] ?? agentDisplayNames.en[name];
  if (displayName) return displayName;
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

  const deleteBtn = document.createElement('button');
  deleteBtn.type = 'button';
  deleteBtn.className = 'btn-icon delete-run-btn';
  deleteBtn.title = activeLocale === 'zh' ? '删除运行记录' : 'Delete run';
  deleteBtn.innerHTML = `
    <svg viewBox="0 0 16 16" fill="currentColor" width="12" height="12">
      <path d="M11 1.5v1h3.5a.5.5 0 0 1 0 1h-.538l-.853 10.66A2 2 0 0 1 11.115 16h-6.23a2 2 0 0 1-1.994-1.84L2.038 3.5H1.5a.5.5 0 0 1 0-1H5v-1A1.5 1.5 0 0 1 6.5 0h3A1.5 1.5 0 0 1 11 1.5Zm-5 0v1h4v-1a.5.5 0 0 0-.5-.5h-3a.5.5 0 0 0-.5.5ZM4.5 5.029l.5 8.5a.5.5 0 1 0 .998-.06l-.5-8.5a.5.5 0 1 0-.998.06Zm6.53-.06a.5.5 0 0 0-.51.49l-.5 8.5a.5.5 0 1 0 .998.06l.5-8.5a.5.5 0 0 0-.488-.55ZM1.962 3.5l.847 10.59a1 1 0 0 0 .997.91h6.23a1 1 0 0 0 .997-.91L11.892 3.5H1.962Z"/>
    </svg>
  `;
  deleteBtn.addEventListener('click', async (e) => {
    e.stopPropagation();
    const confirmMsg = activeLocale === 'zh' ? '您确定要删除此条运行记录吗？' : 'Are you sure you want to delete this run?';
    if (!confirm(confirmMsg)) return;
    const res = await fetch(`/api/runs/${run.run_id}`, { method: 'DELETE' });
    if (res.ok) {
      const currentHashRunId = window.location.hash.slice(1).startsWith('run=')
        ? decodeURIComponent(window.location.hash.slice(5))
        : null;
      if (currentHashRunId === run.run_id) {
        window.location.hash = '';
        resetToInitialState();
      }
      refreshRunHistory();
    }
  });

  meta.append(statusBadge, count, deleteBtn);
  item.append(button, meta);
  return item;
}

function resetToInitialState() {
  currentRunId = null;
  if (source) {
    source.close();
    source = null;
  }
  setStatus('ready', 'ready');
  setBusy(false);
  eventLog.replaceChildren();
  reportViewer.replaceChildren();
  reportSectionSelect.innerHTML = '';
  agentList.replaceChildren();
  llmCountEl.textContent = '--';
  toolCountEl.textContent = '--';
  tokenCountEl.textContent = '--';
  eventCountEl.textContent = '--';
  document.querySelector('#runDuration').textContent = '--';
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
  currentStats = { llm_calls: 0, tool_calls: 0, tokens_in: 0, tokens_out: 0 };
  updateEventCount();
  updateStats(currentStats);
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
  if (type === 'stats')          return formatStats(content);
  return JSON.stringify(content);
}

function updateStats(stats = {}) {
  currentStats = {
    llm_calls: Number(stats.llm_calls) || 0,
    tool_calls: Number(stats.tool_calls) || 0,
    tokens_in: Number(stats.tokens_in) || 0,
    tokens_out: Number(stats.tokens_out) || 0,
  };
  llmCountEl.textContent = `${currentStats.llm_calls} ${t('llmCalls')}`;
  toolCountEl.textContent = `${currentStats.tool_calls} ${t('toolCalls')}`;
  const hasTokens = currentStats.tokens_in > 0 || currentStats.tokens_out > 0;
  tokenCountEl.textContent = hasTokens
    ? `${t('tokens')}: ${formatCompactNumber(currentStats.tokens_in)}↑ ${formatCompactNumber(currentStats.tokens_out)}↓`
    : `${t('tokens')}: --`;
}

function formatStats(stats = {}) {
  const llmCalls = Number(stats.llm_calls) || 0;
  const toolCalls = Number(stats.tool_calls) || 0;
  const tokensIn = Number(stats.tokens_in) || 0;
  const tokensOut = Number(stats.tokens_out) || 0;
  return `${llmCalls} ${t('llmCalls')} · ${toolCalls} ${t('toolCalls')} · ${t('tokens')}: ${formatCompactNumber(tokensIn)}↑ ${formatCompactNumber(tokensOut)}↓`;
}

function formatCompactNumber(value) {
  if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
  return String(value);
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
  return reportSectionTitles[activeLocale]?.[section]
    ?? reportSectionTitles.en[section]
    ?? formatAgentName(section);
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

// ── Capability Providers Management ──────────────────────────────────────────
const providersStorageKey = 'tradingagents.web.providers';
let providersState = {};

const availableCategoryVendors = {
  core_stock_apis: ["westock", "longbridge_mcp", "longbridge", "alpha_vantage"],
  technical_indicators: ["westock", "longbridge_mcp", "longbridge", "alpha_vantage"],
  fundamental_data: ["westock", "longbridge_mcp", "longbridge", "alpha_vantage"],
  news_data: ["westock", "duckduckgo", "alpha_vantage"],
  macro_data: ["fred"],
  prediction_markets: ["polymarket"],
};

const providerMeta = {
  westock: { name: "Westock" },
  longbridge_mcp: { name: "Longbridge MCP" },
  longbridge: { name: "Longbridge CLI" },
  alpha_vantage: { name: "Alpha Vantage" },
  duckduckgo: { name: "DuckDuckGo" },
  fred: { name: "FRED" },
  polymarket: { name: "Polymarket" },
};

function saveProviders() {
  try {
    window.localStorage.setItem(providersStorageKey, JSON.stringify(providersState));
  } catch {
    // Local persistence is optional
  }
}

function parseCategoryDefault(category, defaultStr) {
  const defaultsList = defaultStr ? defaultStr.split(',').map(s => s.trim()).filter(Boolean) : [];
  const result = [];
  
  defaultsList.forEach(v => {
    if (availableCategoryVendors[category].includes(v)) {
      result.push({ id: v, enabled: true });
    }
  });
  
  availableCategoryVendors[category].forEach(v => {
    if (!defaultsList.includes(v)) {
      result.push({ id: v, enabled: false });
    }
  });
  
  return result;
}

function normalizeCategoryProviders(category, rows) {
  const allowed = availableCategoryVendors[category] || [];
  const normalized = [];
  const seen = new Set();

  (Array.isArray(rows) ? rows : []).forEach(row => {
    const id = row?.id;
    if (!allowed.includes(id) || seen.has(id)) return;
    normalized.push({ id, enabled: row.enabled !== false });
    seen.add(id);
  });

  allowed.forEach(id => {
    if (!seen.has(id)) normalized.push({ id, enabled: false });
  });

  return normalized;
}

function loadProviders() {
  let saved = null;
  try {
    saved = JSON.parse(window.localStorage.getItem(providersStorageKey) || 'null');
  } catch {}
  
  if (saved && typeof saved === 'object') {
    providersState = {};
    Object.keys(availableCategoryVendors).forEach(cat => {
      providersState[cat] = normalizeCategoryProviders(cat, saved[cat]);
    });
  } else {
    providersState = {};
    const defaultDataVendors = configDefaults?.data_vendors || {
      core_stock_apis: "westock, longbridge_mcp, longbridge",
      technical_indicators: "westock, longbridge_mcp, longbridge",
      fundamental_data: "westock, longbridge_mcp, longbridge",
      news_data: "westock, duckduckgo, alpha_vantage",
      macro_data: "fred",
      prediction_markets: "polymarket"
    };
    
    Object.keys(availableCategoryVendors).forEach(cat => {
      providersState[cat] = parseCategoryDefault(cat, defaultDataVendors[cat]);
    });
  }
  
  Object.keys(availableCategoryVendors).forEach(cat => {
    renderCategoryProviders(cat);
  });
  renderOhlcvSettingsTable();
}

function renderCategoryProviders(category) {
  const container = document.querySelector(`#list_${category}`);
  if (!container) return;
  
  const vendors = providersState[category];
  container.innerHTML = '';
  
  vendors.forEach((v, index) => {
    const li = document.createElement('li');
    li.className = `provider-item${v.enabled ? '' : ' disabled'}`;
    li.dataset.vendor = v.id;
    li.dataset.index = index;
    
    const meta = providerMeta[v.id] || { name: v.id };
    const verification = envStatus?.vendor_verifications?.[category]?.[v.id];
    const verificationState = verification?.status || 'unverified';
    let badgeText = '';
    let badgeClass = '';
    
    if (envStatus && envStatus.data_vendors && envStatus.data_vendors[v.id]) {
      const status = envStatus.data_vendors[v.id];
      const isConfigured = status.configured;
      if (status.required) {
        badgeText = isConfigured ? t('apiKeyConfigured') : t('apiKeyMissing');
        badgeClass = isConfigured ? 'configured' : 'missing';
      } else {
        badgeText = t('apiKeyNotRequired');
        badgeClass = 'optional';
      }
    } else {
      badgeText = t('apiKeyNotRequired');
      badgeClass = 'optional';
    }
    
    li.innerHTML = `
      <div class="provider-item-left">
        <input type="checkbox" class="provider-enable-checkbox" ${v.enabled ? 'checked' : ''} />
        <span class="provider-identity">
          <span class="provider-name">${meta.name}</span>
          <span class="provider-verification-detail" title="${escapeHtml(verification?.detail || '')}">${escapeHtml(formatVendorVerification(verification))}</span>
        </span>
      </div>
      <div class="provider-item-right">
        <span class="vendor-health-badge ${verificationState}">${escapeHtml(formatVendorHealth(verificationState))}</span>
        <span class="env-status-badge ${badgeClass}">${badgeText}</span>
        <button type="button" class="btn-verify-vendor" title="${t('vendorVerify')}" aria-label="${t('vendorVerify')}">↻</button>
        <div class="provider-order-buttons">
          <button type="button" class="btn-order btn-order-up" title="Move Up" ${index === 0 ? 'disabled' : ''}>▲</button>
          <button type="button" class="btn-order btn-order-down" title="Move Down" ${index === vendors.length - 1 ? 'disabled' : ''}>▼</button>
        </div>
      </div>
    `;
    
    const checkbox = li.querySelector('.provider-enable-checkbox');
    checkbox.addEventListener('change', () => {
      v.enabled = checkbox.checked;
      li.classList.toggle('disabled', !v.enabled);
      saveProviders();
    });

    const verifyButton = li.querySelector('.btn-verify-vendor');
    verifyButton.addEventListener('click', async () => {
      verifyButton.disabled = true;
      verifyButton.classList.add('loading');
      verifyButton.title = t('vendorVerifying');
      try {
        const response = await fetch(`/api/config/data-vendors/${encodeURIComponent(category)}/${encodeURIComponent(v.id)}/verify`, {
          method: 'POST',
        });
        if (!response.ok) throw new Error(await response.text());
        const result = await response.json();
        envStatus = envStatus || {};
        envStatus.vendor_verifications = envStatus.vendor_verifications || {};
        envStatus.vendor_verifications[category] = envStatus.vendor_verifications[category] || {};
        envStatus.vendor_verifications[category][v.id] = result;
      } catch (error) {
        console.error('Vendor verification failed', error);
      } finally {
        renderCategoryProviders(category);
      }
    });
    
    const upBtn = li.querySelector('.btn-order-up');
    upBtn.addEventListener('click', () => {
      if (index > 0) {
        const temp = vendors[index];
        vendors[index] = vendors[index - 1];
        vendors[index - 1] = temp;
        saveProviders();
        renderCategoryProviders(category);
      }
    });
    
    const downBtn = li.querySelector('.btn-order-down');
    downBtn.addEventListener('click', () => {
      if (index < vendors.length - 1) {
        const temp = vendors[index];
        vendors[index] = vendors[index + 1];
        vendors[index + 1] = temp;
        saveProviders();
        renderCategoryProviders(category);
      }
    });
    
    container.appendChild(li);
  });

  if (category === 'core_stock_apis') {
    renderOhlcvSettingsTable();
  }
}

function formatVendorHealth(status) {
  return {
    available: t('vendorAvailable'),
    unavailable: t('vendorUnavailable'),
    no_data: t('vendorNoData'),
    rate_limited: t('vendorRateLimited'),
    not_configured: t('vendorNotConfigured'),
    unverified: t('vendorNeverVerified'),
  }[status] || t('vendorUnavailable');
}

function formatVendorVerification(verification) {
  if (!verification?.verified_at) return t('vendorNeverVerified');
  const source = verification.source === 'manual'
    ? t('vendorVerifiedManual')
    : t('vendorVerifiedAnalysis');
  const time = new Intl.DateTimeFormat(activeLocale === 'zh' ? 'zh-CN' : 'en', {
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(new Date(verification.verified_at));
  const latency = Number.isFinite(verification.latency_ms) ? ` · ${verification.latency_ms} ms` : '';
  return `${source} · ${time}${latency}`;
}

function renderOhlcvSettingsTable() {
  if (!ohlcvSettingsBody) return;
  const configuredRows = providersState.core_stock_apis || availableCategoryVendors.core_stock_apis.map(id => ({ id, enabled: false }));
  if (!configuredRows.length) {
    ohlcvSettingsBody.innerHTML = '';
    return;
  }

  ohlcvSettingsBody.innerHTML = configuredRows.map((setting, index) => {
    const meta = providerMeta[setting.id] || { name: setting.id };
    const status = envStatus?.data_vendors?.[setting.id];
    const credential = status
      ? (status.required
        ? (status.configured ? t('apiKeyConfigured') : t('apiKeyMissing'))
        : t('apiKeyNotRequired'))
      : t('apiKeyNotRequired');
    return `
      <tr>
        <td><strong>${escapeHtml(meta.name)}</strong></td>
        <td>${escapeHtml(index + 1)}</td>
        <td><span class="badge ${setting.enabled ? 'quality-high' : 'quality-neutral'}">${escapeHtml(setting.enabled ? t('providerEnabled') : t('providerDisabled'))}</span></td>
        <td>${escapeHtml(credential)}</td>
      </tr>
    `;
  }).join('');
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function currentProviders() {
  const result = {};
  Object.keys(providersState).forEach(cat => {
    const enabledVendors = providersState[cat]
      .filter(v => v.enabled)
      .map(v => v.id);
    result[cat] = enabledVendors.join(', ');
  });
  return result;
}
