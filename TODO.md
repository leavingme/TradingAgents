# TODO

## Vendor 数据统一校验

所有 vendor 返回的数据必须在进入 Agent、LLM 或其他后续流程前，经过对应数据域的确定性校验。

统一处理流程：

1. vendor 返回数据。
2. 路由层调用对应数据域的 validator。
3. 校验通过后才允许数据进入后续流程。
4. 校验不通过时，尝试配置 fallback 链中的下一个 vendor。
5. 所有已配置数据源均未返回通过校验的数据时，终止本次分析。

数据域进度：

- [x] 行情数据：Date、OHLC、Volume，以及可选 Amount/Turnover 校验。
- [x] 技术指标：统一格式、日期、历史窗口、固定范围、价格量纲、零值、重复值和数量级异常。
- [x] 财务数据：币种、单位、报告期、年度/季度口径和字段关系。
- [ ] 新闻数据：来源、发布时间、正文可用性和分析日期截止校验。
- [ ] 宏观数据：指标名称、单位、观察期和发布日期。（部分完成：已实现 FRED 滞后非美指标 1095 天 Lookback 智能拓宽防护机制，防空回包异常）
- [ ] 预测市场：事件标识、到期时间和概率范围。
- [x] **P0 — 历史预测市场前视隔离**：正式 runtime 与兼容 `propagate()` 入口将 `analysis_date` 绑定为不可由 LLM 改写的运行上下文；只提供实时快照的 Polymarket 在历史分析中于网络请求前以类型化 `NoMarketDataError` fail closed，vendor ledger 记录 point-in-time 不可用原因。不得把运行日概率、伪造 `source_id` 或说明性文本作为历史证据；实时预测市场的结构化领域模型和确定性校验仍由上项继续跟踪。
- [x] Graph 硬门禁：ToolNode 不吞数据异常；失败运行不生成报告或 `run_completed`。
- [x] Tool 参数纠错：模型生成的参数 Schema 错误返回一次结构化 `ToolMessage` 供 LLM 修正；重复错误及 vendor/数据异常仍触发 Graph 硬门禁。
- [x] 技术指标确定性窗口：按指标预热 K 线需求统一扩展所有 vendor 的请求窗口，并区分输入历史与预热后有效输出点数。
- [x] OHLCV 缓存日期修复：显式迁移股票日 K 的日期漂移副本；读取不清理数据，写入边界执行日期/OHLCV 硬校验并原子替换缓存文件。
- [x] OHLCV 写入溯源：Longbridge MCP/CLI 与 Westock adapter 统一构造 `OHLCVBatch`，缓存拒绝裸 DataFrame，并以 JSONL sidecar 记录原始时间戳、时区语义、vendor、adapter 版本和批次 ID。
- [x] 技术指标计算起点统一：Longbridge Pine 与 Westock/stockstats 使用相同的三年 calculation_start；Pine 输出按权威 OHLCV 最新交易日校验，服务端 quant 数据滞后时自动 fallback。
- [x] 运行级 vendor 审计：新增按 run/call/attempt 追加且不可覆盖的 fallback 调用账本与查询 API；审计落盘失败时禁止继续生成可执行报告。
- [x] 交易计划确定性门禁：Buy/Overweight 的价格与仓位必须结构化；可信 ATR/Close 与服务端风险政策由运行时注入，收益风险比、ATR 倍数和组合损失由代码计算；重复校验失败生成 `NO_DECISION / REVIEW_REQUIRED`，不得伪装成 Hold。
- [ ] 空头与衍生品交易校验：新增显式 `side=long|short|flat` 和 `validate_short_trade_plan`，不得从 Sell/Underweight 推断开空；期权（含 Put）使用独立的权利金、行权价、到期日、乘数与 Greeks 风险模型。
- [ ] 仓位引擎解耦：将 `PositionSizingEngine`（固定风险、ATR 风险、波动率目标、分数凯利、账户权益、最大名义敞口）与 `TradePlanValidator` 分层；仓位引擎生成建议仓位，验证器统一执行组合风险、集中度和账户限制硬门禁。
- [x] 可信市场输入绑定：ATR、最新 Close、market date 与 vendor `call_id` 由 verified market snapshot 注入交易校验器，不再允许 LLM 自行填写或转抄权威风控输入。
- [x] **P0 — 服务端风险政策**：`max_portfolio_risk_pct`、单标的集中度、最大名义敞口、购买力和是否允许新增长仓均来自服务端配置/账户策略，不得由 LLM 自行设定；交易价相对最新可信 Close 做区间校验。
- [x] **P0 — 无决策状态**：新增 `validated|review_required|unavailable` 决策状态；`REVIEW_REQUIRED` 不编码成普通 Hold、不生成交易信号、不写入绩效记忆，SQLite/Web/API 明确显示“无有效决策”。
- [x] **P0 — 外部内容提示注入隔离**：新闻、StockTwits、Reddit、X 等攻击者可控内容作为独立 `untrusted_data` JSON 注入，不拼入 system instruction；增加控制令牌/指令检测、行级清除、输出再净化和结构化事实提取。
- [x] **P0 — Web API 安全边界**：backend URL 使用服务端 allowlist，Web 请求禁止提交任意文件系统路径，`config_overrides` 使用白名单字段；非 loopback 部署强制 bearer 认证，并为启动/删除/配置修改增加权限、频率和并发限制。
- [x] **P0 — 新闻与宏观证据模型**：统一为结构化 `NewsItem`/`NewsFeed`/`MacroObservation`/`MacroSeries`，校验日期、来源、URL、标的相关性与重复转载；重要报告事实绑定可审计 `source_id`，不再以非空文本冒充已验证数据。
- [x] **条件性 P0 — Checkpoint 并发隔离**：checkpoint thread ID 纳入 `run_id`，同 ticker/日期的并发任务不共享或互删状态；恢复必须显式指定原 run。
- [x] **条件性 P0 — 审计存储与执行入口**：SQLite 启用 WAL、busy timeout、foreign keys 和有限写入重试；正式 CLI/Web/Python 示例入口统一经过 runtime，直接 `propagate()` 也创建 run context，不再静默绕过 run-scoped vendor 审计。
- [x] Runtime Agent 状态机：累积 graph snapshot 不得导致已完成 Agent 重新进入运行态；团队交接状态完整且报告事件去重。
- [x] X/Twitter 舆情：Bird 只读结构化 adapter、统一 SocialPost 模型、日期截止/去重/垃圾推广校验、独立 `social_data` vendor 路由与 Web 配置。
- [x] Web 舆情分类：新闻与社交数据分卡展示，Reddit、StockTwits 与 X/Twitter 统一归入“社交动态舆情”，后端仍保持 `news_data` / `social_data` 边界。
- [x] Web 刷新性能：本地托管 Markdown renderer、移除 Google Fonts 外网阻塞，并将开发热加载范围限制到源码目录。
- [x] Reddit 社交配置：在 `social_data` 中提供独立开关，旧浏览器配置自动迁移为启用，并让开关实际控制 Sentiment Analyst 抓取。
- [x] Web 配置归属：客户端仅保留 UI language；报告、模型、推理和数据 Vendor 配置迁移到服务端原子持久化，并兼容旧 localStorage 一次性迁移。
- [ ] Runtime 状态：记录失败的数据域、vendor 尝试轨迹和具体校验原因。
- [ ] **P1 — 运行上下文成本**：NVDA depth=1 工程闭环连续两次输入 token 分别为 254,861 与 252,244；审计基础 Analyst 报告、工具结果、Bull/Bear/Risk 辩论之间的重复传递并设计保留来源证据的确定性压缩边界。
- [ ] **安全测试加固 — OpenAI-compatible 密钥隔离**：`test_keyless_local_uses_placeholder_and_chat_completions` 必须同时临时清除 `OPENAI_COMPATIBLE_API_KEY` 与通用 fallback `OPENAI_API_KEY`，并避免在断言差异、pytest 输出或 CI 日志中读取/打印真实密钥明文；测试结束后由 `monkeypatch` 自动恢复原环境。
- [x] **NVDA 工程闭环**：提供受审计的基准运行、完整执行证据导出、结构化 findings/P0 方案、人工 review 确认、P0 实现证据、修改后固定验收和不可绕过的完成 gate。
- [x] **Longbridge 结构化新闻接入**：个股新闻按 `longbridge_mcp → longbridge` 优先，全球宏观新闻使用 Longbridge CLI 结构化搜索；原始响应直接映射 `NewsFeed` 并通过统一来源、时间、URL、标的和截止校验。MCP `news_search` 在时间字段恢复前不得冒充有效全球新闻。
- [x] **技术指标默认路由**：默认使用 Westock/stockstats 基于规范 OHLCV 做确定性计算，Longbridge MCP 仅作 fallback；Longbridge CLI 保留可选能力但不进入默认指标链。旧 Web 默认配置自动迁移，自定义顺序保持不变。
- [ ] **P1 — Longbridge 前瞻研究数据域**：接入 `consensus`、`forecast_eps`、`finance_calendar`、`institution_rating`、`filings`、`short_positions` 和 `short_trades`；建立带 `as_of`、发布日期、事件日期、标的、币种、期间、稳定 `source_id` 与 vendor `call_id` 的统一领域模型和确定性 validator，分别供 Fundamentals、News、Bull/Bear 与 Risk Agent 使用。
- [ ] **P1 — Longbridge 可信市场上下文与跨市场 Session Engine**：将 `quote`、`market_status`、`trading_days` 以及可验证的盘前/盘后/隔夜字段接入 `verified_market_snapshot`；按交易所时区、夏令时、节假日、半日市和 `pre|regular|post` session 动态计算中美市场窗口，分别保存 `market_date`、`observed_at`、`published_at` 与 `available_at`。建立 A/H/ADR、汇率、换股比例和产业链映射，支持“中港收盘 → 美股盘前”及“美股收盘/盘后 → 次日中港开盘”的只读证据生成、价差/异常检测和开盘前增量刷新。盘前盘后数据不得覆盖规范日 K，盘中数据不得冒充完整收盘快照；历史运行只允许使用 `available_at <= analysis_cutoff` 的 point-in-time 证据，所有跨市场 lead-lag 信号必须先经历史稳定性、流动性、点差、交易成本和可转换性验证，不得表述为无风险套利。
- [ ] **P2 — Longbridge 基本面与持仓拥挤增强**：评估并接入 `business_segments`、估值历史/同行、`shareholder`、`fund_holder`、内部人交易、`capital_flow`、`trade_stats`、`market_temperature` 和异动数据；逐项审计真实 schema，禁止依据工具描述批量生成 adapter。
- [ ] **P2 — Longbridge 只读账户风险输入**：以最小 OAuth 权限接入账户余额、持仓、保证金、购买力估算和汇率，将验证后的账户约束注入服务端风险政策；不得向分析 Agent 暴露下单、撤单、改单、DCA、提醒或 Watchlist 写操作。
- [ ] **P2 — Longbridge 宏观数据独立 vendor**：将 Longbridge `macrodata` 与宏观事件日历注册为独立 vendor，映射到 `MacroSeries` 并校验单位、观察期、发布日期和分析截止时间；不得隐藏在 FRED vendor 内部。
- [ ] **P3 — Longbridge 衍生品与选股能力**：期权链、IV、Greeks 仅在独立衍生品风险模型完成后接入；screener、rank、top movers 等仅在新增 universe/选股阶段后接入，不直接塞入现有单标的 Agent 工具集。
- [ ] **独立工程 Reviewer 模型**：增加可选 `review-model` 阶段，仅读取不可变 execution evidence，输出带 event/vendor/source 引用的结构化 findings；Codex/其他 Reviewer 不得直接修改历史或决定通过，仍需人工确认、确定性验证和现有 gate。

架构约束：

- vendor 只负责获取和规范化自己的数据，不负责跨 vendor fallback。
- fallback 统一由路由层按配置顺序控制。
- validator 使用确定性代码，不由 LLM 判断数据是否有效。
- 不得把错误提示字符串当作有效数据传入后续流程。
- 使用 vendor 前先审计其原始接口能力；结构化响应必须直接映射到统一领域模型，禁止先转成 LLM 文本再反向提取。
- 固定数据链路：`vendor 原始响应 → vendor-specific adapter → 统一领域模型 → validator → LLM renderer`。
- MCP 能提供比 CLI 更完整的结构化数据时优先 MCP，CLI 仅作为 fallback。

P0-2 财务数据后续重构：

- [x] Longbridge MCP 原始 JSON 直接映射 `FinancialMetric`，不经过 `_flatten_financial()` 文本。
- [x] Longbridge CLI JSON 直接映射 `FinancialMetric`；文本解析仅保留为旧接口兼容层。
- [x] validator 只接收统一领域模型，不接收 vendor 文本。
- [x] 验证通过后再渲染为提供给 Fundamentals Analyst 的 JSON。
- [x] Vendor 派生值完整保留为 `unverified_facts`，基础输入充分时由代码重算利润率并记录公式和输入。
- [x] 将 `unverified_facts` 和原始 payload 持久化到独立审计记录，不进入 LLM 上下文。
- [x] 实现资产负债表、现金流量表和利润表的跨报表勾稽与期间一致性检查。
- [x] 基于完整输入确定性计算 ROE、ROA、TTM EPS/PE、净现金和 EV/EBITDA。
