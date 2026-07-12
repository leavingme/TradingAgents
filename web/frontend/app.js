import { createProviderManager } from './components/provider-manager.js?v=20260711-indicator-validation';
import { createAgentTimeline, formatAgentName } from './components/agent-timeline.js?v=20260711-agent-status-init';
import { createReportViewer } from './components/report-viewer.js';
import { createRunHistory } from './components/run-history.js';
import { createEventLog } from './components/event-log.js';
import { api } from './api-client.js';
import { createEventStream } from './event-stream.js';
import { createRouter } from './router.js';
import { createSettingsController } from './components/settings-controller.js';
import { createI18n } from './i18n.js';

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
const readingModeToggle = document.querySelector('#readingModeToggle');
const newReportsNotice = document.querySelector('#newReportsNotice');
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
let eventCount   = 0;
let currentStatus = 'ready';
let currentStats = { llm_calls: 0, tool_calls: 0, tokens_in: 0, tokens_out: 0 };
let configDefaults = null;
let envStatus = null;
let analystPrompts = [];
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
    readingMode: 'Reading mode',
    readingModeOn: 'Reading mode on: new reports will not interrupt you',
    readingModeOff: 'Reading mode off: automatically follow new reports',
    newReportsLabel: '{count} new reports',
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
    summaryWestockNote: 'OHLCV fallback with broad coverage. Its minute-level K-line data is limited to China A-share stocks, and turnover amount requires validation.',
    knownIssueBadge: 'Known issue',
    knownIssueImpactLabel: 'Impact:',
    westockKnownIssueTitle: 'Westock turnover amount may be scaled incorrectly',
    westockKnownIssueBody: 'Observed on 0700.HK daily bars on 2026-07-10: Westock amount was 10,000 times the Longbridge turnover value. The issue is intermittent and can affect individual rows rather than the vendor\'s fixed unit convention.',
    westockKnownIssueImpact: 'OHLC and volume may remain usable, but Westock amount must not be used for turnover analysis until it passes an implied-price check or is verified by another provider.',
    summaryLongbridgeCliLatest: 'Observed current data for US stocks, China A-shares, and Hong Kong stocks',
    summaryLongbridgeGranularity: '1-minute K-line supported',
    summaryLongbridgeCliNote: 'Preferred raw OHLCV source and CLI fallback when Longbridge MCP is unavailable.',
    summaryLongbridgeMcpLatest: 'Observed current data for US stocks, China A-shares, and Hong Kong stocks',
    summaryLongbridgeMcpNote: 'Provides the same market coverage as Longbridge CLI when the Longbridge MCP credential is valid.',
    providersSummaryFootnote: 'Last real provider verification: 2026-07-11.',
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
    catNewsTitle: 'News Data',
    catNewsDesc: 'Fetches ticker news, global market news, and insider transactions. DuckDuckGo is a configurable fallback for news search.',
    catSocialTitle: 'Social Sentiment',
    catSocialDesc: 'Combines X/Twitter, Reddit, and StockTwits discussions. Bird is the configurable read-only X/Twitter provider; Reddit and StockTwits are built-in social sources used by the Sentiment Analyst.',
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
    readingMode: '阅读模式',
    readingModeOn: '阅读模式已开启：新报告不会打断当前阅读',
    readingModeOff: '阅读模式已关闭：自动跟随新报告',
    newReportsLabel: '{count} 份新报告',
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
    summaryWestockNote: '作为广覆盖的 OHLCV 后备来源；分钟级 K 线仅覆盖 A 股个股，成交额字段需要额外校验。',
    knownIssueBadge: '已知问题',
    knownIssueImpactLabel: '影响：',
    westockKnownIssueTitle: 'Westock 成交额可能发生错误缩放',
    westockKnownIssueBody: '已在 2026-07-10 的 0700.HK 日 K 数据中观测到：Westock amount 是 Longbridge turnover 的 10,000 倍。该问题具有间歇性，可能只影响个别记录，并非服务商固定的单位约定。',
    westockKnownIssueImpact: 'OHLC 与成交量可能仍可使用，但 Westock amount 在通过隐含成交均价校验或其他服务商交叉验证前，不得用于成交额分析。',
    summaryLongbridgeCliLatest: '实测美股、A 股、港股均可获得当前数据',
    summaryLongbridgeGranularity: '支持 1 分钟 K 线',
    summaryLongbridgeCliNote: '作为原始 OHLCV 的优先来源，并在 Longbridge MCP 不可用时提供 CLI 后备。',
    summaryLongbridgeMcpLatest: '实测美股、A 股、港股均可获得当前数据',
    summaryLongbridgeMcpNote: 'Longbridge MCP 凭证有效时，市场覆盖与 Longbridge CLI 一致。',
    providersSummaryFootnote: '最后一次真实服务商验证：2026-07-11。',
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
    catNewsTitle: '新闻资讯',
    catNewsDesc: '获取个股新闻、全球宏观新闻和内幕交易信息。DuckDuckGo 是可配置的新闻搜索 fallback。',
    catSocialTitle: '社交动态舆情',
    catSocialDesc: '综合 X/Twitter、Reddit 和 StockTwits 讨论。Bird 是可配置的 X/Twitter 只读数据源；Reddit 与 StockTwits 是 Sentiment Analyst 使用的内置社交数据源。',
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
const i18n = createI18n({ catalog: translations, languageField: uiLanguage });
const t = key => i18n.t(key);
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
const providerManager = createProviderManager({
  api,
  t,
  locale: i18n.locale,
  configDefaults: () => configDefaults,
  envStatus: () => envStatus,
  setEnvStatus: value => { envStatus = value; },
  ohlcvSettingsBody,
});
const AGENT_TO_SECTION = {
  'Market Analyst': 'market_report',
  'Sentiment Analyst': 'sentiment_report',
  'News Analyst': 'news_report',
  'Fundamentals Analyst': 'fundamentals_report',
  'Bull Researcher': 'bull_researcher',
  'Bear Researcher': 'bear_researcher',
  'Research Manager': 'investment_plan',
  'Trader': 'trader_investment_plan',
  'Aggressive Analyst': 'aggressive_analyst',
  'Conservative Analyst': 'conservative_analyst',
  'Neutral Analyst': 'neutral_analyst',
  'Portfolio Manager': 'final_trade_decision'
};

const agentTimeline = createAgentTimeline({
  element: agentList,
  t,
  locale: i18n.locale,
  formatStatus,
  statusClassName,
  isAgentClickable: agentName => {
    const section = AGENT_TO_SECTION[agentName];
    if (!section) return false;
    const select = document.querySelector('#reportSectionSelect');
    if (!select) return false;
    const exists = Array.from(select.options).some(opt => opt.value === section);
    console.log(`[TimelineClick] isAgentClickable for "${agentName}" (section: "${section}"): ${exists}`);
    return exists;
  },
  onAgentClick: agentName => {
    const section = AGENT_TO_SECTION[agentName];
    console.log(`[TimelineClick] onAgentClick clicked for "${agentName}" (section: "${section}")`);
    if (!section) return;
    const select = document.querySelector('#reportSectionSelect');
    if (!select) return;
    const option = Array.from(select.options).find(opt => opt.value === section);
    if (option) {
      console.log(`[TimelineClick] onAgentClick: selecting option "${section}" and dispatching change`);
      select.value = section;
      select.dispatchEvent(new Event('change'));
    } else {
      console.log(`[TimelineClick] onAgentClick: option "${section}" not found in select`);
    }
  },
});
const reportView = createReportViewer({
  api,
  element: reportViewer,
  sectionSelect: reportSectionSelect,
  readingModeToggle,
  newReportsNotice,
  t,
  locale: i18n.locale,
  formatAgentName,
});
const runHistory = createRunHistory({
  api,
  element: historyList,
  locale: i18n.locale,
  formatStatus,
  formatEventCount,
  onSelect: runId => selectHistoryRun(runId),
  onDeleted: runId => {
    const hashRunId = window.location.hash.slice(1).startsWith('run=')
      ? decodeURIComponent(window.location.hash.slice(5))
      : null;
    if (hashRunId !== runId) return;
    window.location.hash = '';
    resetToInitialState();
  },
});
const runtimeLog = createEventLog({
  element: eventLog,
  t,
  locale: i18n.locale,
  formatAgentName,
  formatStatus,
  formatStats,
});
const eventStream = createEventStream({
  onEvent: handleRuntimeEvent,
  onReconnect: () => runtimeLog.append('error', null, 'Event stream reconnecting'),
});
const router = createRouter({
  elements: {
    runControls,
    runView,
    settingsView,
    providersView,
    runButton: runViewButton,
    settingsButton: settingsViewButton,
    providersButton: providersViewButton,
  },
  getCurrentRunId: () => currentRunId,
  onSelectRun: runId => selectHistoryRun(runId, { updateHash: false }),
});
const settings = createSettingsController({
  form: settingsForm,
  fields: {
    llmProvider,
    quickThinkLlm,
    deepThinkLlm,
    backendUrl,
    outputLanguage,
    customOutputLanguage,
    researchDepth,
    googleThinkingLevel,
    openaiReasoningEffort,
    anthropicEffort,
  },
  modelPresets,
  onProviderChange: renderApiKeyStatus,
});

// ── Initialise date field ────────────────────────────────────────────────────
document.querySelector('#analysisDate').value = new Date().toISOString().slice(0, 10);

// Show empty-state placeholder in the report panel on load
i18n.initialize();
refreshLocalizedUi();
reportView.placeholder();
loadConfigDefaults();
loadEnvStatus();
loadAnalystPrompts();

runViewButton.addEventListener('click', () => router.show('run'));
settingsViewButton.addEventListener('click', () => router.show('settings'));
providersViewButton.addEventListener('click', () => {
  router.show('providers');
  loadEnvStatus();
});
resetProviders.addEventListener('click', () => {
  providerManager.reset();
});
router.handleHash();

tickerSelect.addEventListener('change', updateTickerMode);

uiLanguage.addEventListener('change', () => {
  i18n.setLanguage(uiLanguage.value);
  refreshLocalizedUi();
  renderDynamicLabels();
});

resetSettings.addEventListener('click', () => {
  settings.reset(configDefaults);
});

// ── Form submit ──────────────────────────────────────────────────────────────
form.addEventListener('submit', async event => {
  event.preventDefault();
  resetRun();

  const payload = buildPayload(new FormData(form));
  setBusy(true);
  setStatus('starting', 'running');

  try {
    const run = await api.startRun(payload);
    currentRunId   = run.run_id;
    runIdEl.textContent = shortId(run.run_id);
    agentTimeline.initialize(run.selected_analysts, 'in_progress');
    setStatus(run.status, 'running');
    cancelButton.disabled = false;
    router.setRun(run.run_id, true);
    runHistory.refresh();
    eventStream.connect(run.run_id);
  } catch (error) {
    setStatus('failed_to_start', 'error');
    runtimeLog.append('error', null, error.message);
    setBusy(false);
  }
});

// ── Cancel button ────────────────────────────────────────────────────────────
cancelButton.addEventListener('click', async () => {
  if (!currentRunId) return;
  await api.cancelRun(currentRunId);
  setStatus('cancel_requested', 'running');
  cancelButton.disabled = true;
});

// ── Clear log ────────────────────────────────────────────────────────────────
clearLog.addEventListener('click', () => {
  runtimeLog.clear();
});

// ── Refresh history ──────────────────────────────────────────────────────────
refreshHistory.addEventListener('click', () => runHistory.refresh());

clearHistory.addEventListener('click', async () => {
  const confirmMsg = i18n.locale() === 'zh' ? '您确定要清空所有运行历史数据吗？' : 'Are you sure you want to clear all history?';
  if (!confirm(confirmMsg)) return;
  try {
    await api.clearRuns();
    window.location.hash = '';
    runHistory.refresh();
    resetToInitialState();
  } catch {
    // Keep the existing history visible when the request fails.
  }
});

// ── Load report ──────────────────────────────────────────────────────────────
loadReport.addEventListener('click', async () => {
  if (!currentRunId) return;
  await reportView.load(currentRunId);
});

// Load run history on startup
runHistory.refresh();

// ── Helpers ──────────────────────────────────────────────────────────────────

async function loadConfigDefaults() {
  try {
    configDefaults = await api.getConfigDefaults();
    settings.applyDefaults(configDefaults);
    settings.applySaved();
    providerManager.load();
  } catch {
    // Keep the static HTML defaults when the API is unavailable.
    settings.applySaved();
    providerManager.load();
  }
}

async function loadEnvStatus() {
  try {
    envStatus = await api.getEnvStatus();
    renderApiKeyStatus();
    providerManager.refresh();
  } catch {
    // API key status is informational; runs still use server-side env config.
  }
}

async function loadAnalystPrompts() {
  if (!analystPromptList) return;
  try {
    const payload = await api.getAnalystPrompts();
    analystPrompts = Array.isArray(payload.analysts) ? payload.analysts : [];
    renderAnalystPrompts();
  } catch {
    analystPrompts = [];
    renderAnalystPrompts(true);
  }
}

function refreshLocalizedUi() {
  if (!currentRunId) runIdEl.textContent = t('noRun');
  statusEl.textContent = formatStatus(currentStatus);
  updateEventCount();
  updateStats(currentStats);
  renderApiKeyStatus();
  renderAnalystPrompts();
  providerManager.refresh();
  reportView.refresh();
}

function renderDynamicLabels() {
  updateEventCount();
  agentTimeline.render();
  reportView.refresh();
  runHistory.refresh();
}

function updateEventCount() {
  eventCountEl.textContent = formatEventCount(eventCount);
}

function formatEventCount(count) {
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

function statusClassName(status) {
  return String(status || 'pending')
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_')
    .replace(/[^a-z0-9_]/g, '');
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
  return formatAgentName(title, i18n.locale());
}

function buildPayload(data) {
  const selectedAnalysts = data.getAll('analysts');
  const runSettings = settings.current();
  const activeVendors = providerManager.current();
  return {
    ticker: selectedTicker(data),
    analysis_date: data.get('analysisDate'),
    asset_type: data.get('assetType'),
    selected_analysts: selectedAnalysts.length ? selectedAnalysts : ['market'],
    ...runSettings,
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

/** Return a short, displayable run ID (last 8 chars). */
function shortId(id) {
  if (!id || id === t('noRun')) return id;
  return id.length > 12 ? '…' + id.slice(-8) : id;
}

function resetRun() {
  eventStream.close();
  currentRunId = null;
  eventCount   = 0;
  currentStats = { llm_calls: 0, tool_calls: 0, tokens_in: 0, tokens_out: 0 };
  agentTimeline.clear();
  runtimeLog.clear();
  reportView.reset();
  runIdEl.textContent       = t('noRun');
  updateEventCount();
  updateStats(currentStats);
  loadReport.disabled       = true;
}

function handleRuntimeEvent(type, event) {
  eventCount += 1;
  updateEventCount();

  if (type === 'agent_status' && event.agent) {
    agentTimeline.update(event.agent, event.content?.status ?? 'pending');
  }

  if (type === 'report_section') {
    reportView.updateSection(event.content);
    agentTimeline.render();
  }

  if (type === 'stats') {
    updateStats(event.content);
    return;
  }

  if (type === 'run_completed') {
    setStatus('completed', 'done');
    loadReport.disabled = false;
    cancelButton.disabled = true;
    runtimeLog.append(type, event.agent, event.content?.decision ?? t('runCompleted'));
    reportView.load(currentRunId);
    runHistory.refresh();
    loadEnvStatus();
    closeStream();
    return;
  }

  if (type === 'run_cancelled') {
    setStatus('cancelled', 'error');
    cancelButton.disabled = true;
    runtimeLog.append(type, event.agent, event.content?.message ?? t('runCancelled'));
    runHistory.refresh();
    closeStream();
    return;
  }

  if (type === 'error') {
    setStatus('failed', 'error');
    cancelButton.disabled = true;
    runtimeLog.append(type, event.agent, event.content?.error ?? t('runFailed'));
    runHistory.refresh();
    closeStream();
    return;
  }

  if (type === 'run_started') setStatus('running', 'running');
  runtimeLog.append(type, event.agent, runtimeLog.text(type, event.content));
}

function resetToInitialState() {
  currentRunId = null;
  eventStream.close();
  setStatus('ready', 'ready');
  setBusy(false);
  runtimeLog.clear();
  reportView.reset({ showPlaceholder: false });
  agentTimeline.clear();
  llmCountEl.textContent = '--';
  toolCountEl.textContent = '--';
  tokenCountEl.textContent = '--';
  eventCountEl.textContent = '--';
  document.querySelector('#runDuration').textContent = '--';
}

async function selectHistoryRun(runId, options = {}) {
  if (options.updateHash !== false) {
    router.setRun(runId);
    return;
  }

  eventStream.close();

  let run;
  try {
    run = await api.getRun(runId);
  } catch {
    return;
  }

  currentRunId   = run.run_id;
  runIdEl.textContent      = shortId(run.run_id);
  setStatus(run.status, statusClass(run.status));
  eventCount     = 0;
  currentStats = { llm_calls: 0, tool_calls: 0, tokens_in: 0, tokens_out: 0 };
  updateEventCount();
  updateStats(currentStats);
  reportView.reset();
  loadReport.disabled      = !run.report_path;
  cancelButton.disabled    = !['pending', 'running'].includes(run.status);
  runtimeLog.clear();
  agentTimeline.initialize(
    run.selected_analysts,
    ['pending', 'running'].includes(run.status) ? 'in_progress' : 'pending',
  );

  eventStream.connect(run.run_id);
  if (run.report_path) await reportView.load(run.run_id);
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

// ── Stream management ─────────────────────────────────────────────────────────
function closeStream() {
  eventStream.close();
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
