# TradingAgents Roadmap

本文档是项目任务状态、优先级、验收条件和中长期能力路线的**唯一权威来源**。
长期不变的工作原则与操作约束位于 `AGENTS.md`；具体任务的新增、完成、拆分和重新排序只在本文件维护。

## 当前结论

- 截至 2026-07-15，没有未完成的明确 P0。
- 当前排序遵循 `AGENTS.md` 的四级原则：**安全与正确性 → 运行可靠性/成本 → 核心研究能力 → 高复杂度扩展**。
- 排名是执行顺序，不是功能价值评分。默认启用且可能影响决策的链路，优先于尚未开放的未来能力。
- 第 1–5 项已完成；下一项是第 6 项仓位引擎与交易校验器解耦。原第 6 项
  “运行上下文压缩”经讨论后暂缓并移至路线末尾，未来基于单 Agent 单次请求审计再议。

## 路线项权威顺序与状态

| 顺序 | 状态 | 路线项 | 当前优先级依据 |
|---:|---|---|---|
| 1 | 已完成（2026-07-14） | 预测市场确定性校验与 vendor-attempt 持久化 | 当前默认启用且会影响决策；补齐事件 ID、到期日、概率范围、时间截止、稳定 `source_id` 和逐次 vendor 审计。 |
| 2 | 已完成（2026-07-14） | Runtime 失败状态与 vendor 轨迹 | 明确显示失败数据域、尝试过的 vendor、fallback 路径及校验原因，避免失败或降级被误读。 |
| 3 | 已完成（2026-07-14） | 新闻、宏观校验覆盖审计 | 已逐项核对正文、发布时间、观察期、单位、revision/vintage、`source_id` 与 cutoff，并补齐缺口。 |
| 4 | 已完成（2026-07-14） | SSE / report-section 节流 | 已按 run + section 合并高频中间版本，并消除 Web bridge 重复持久化和 SSE replay 重复发送。 |
| 5 | 已完成（2026-07-14） | 技术指标批量获取 | 已实现单次规范 OHLCV、本地批量计算、批量 MCP fallback 和逐项确定性校验。 |
| 6 | 未完成 | 仓位引擎与交易校验器解耦 | 分离建议仓位计算与服务端风险硬门禁；现有风险政策已 fail-closed，因此不是 P0。 |
| 7 | 未完成 | Longbridge 前瞻研究数据域 | 接入一致预期、EPS、财务日历、评级、filings 和空头数据。 |
| 8 | 未完成 | 跨市场 Session Engine | 正确建模交易所时区、DST、节假日、半日市及盘前/盘中/盘后。 |
| 9 | 未完成 | 空头与衍生品交易校验 | 在开放做空或期权前建立独立方向、收益结构和 Greeks 风险门禁。 |
| 10 | 未完成 | Longbridge 只读账户风险输入 | 用真实持仓、购买力、保证金和汇率约束仓位，同时坚持最小 OAuth 权限。 |
| 11 | 未完成 | Longbridge 基本面与持仓拥挤增强 | 增加业务分部、估值、持有人、资金流和微观结构证据。 |
| 12 | 未完成 | Longbridge 独立宏观 vendor | 增加 FRED 之外的结构化宏观来源，优先级低于现有宏观校验闭环。 |
| 13 | 未完成 | 独立 Reviewer 模型 | 增强工程复盘，但只能作为建议层，不能掌握关闭权。 |
| 14 | 未完成 | 衍生品数据与选股能力 | 必须等待衍生品风险模型与 universe 阶段完成。 |
| 15 | 暂缓（最低优先级） | 运行上下文压缩（原第 6 项） | 累计 token 高不等于单 Agent 上下文重复；跨角色共享证据和跨轮携带历史属于辩论机制，未来只按单 Agent 单次请求审计后再议。 |

## 执行计划与验收条件

### 第一阶段：安全与正确性（1–3）

- [x] **1. 预测市场确定性校验与 vendor-attempt 持久化**
  - 统一模型必须包含稳定事件 ID、标题、标的关联、带时区到期日、概率、`observed_at`、稳定 `source_id` 和 vendor `call_id`。
  - validator 必须拒绝缺失事件 ID/到期日、概率不在 `[0, 1]`、超过信息截止时间、已失效事件和无法稳定溯源的数据。
  - `live` 运行保存调用时观察时间；`point_in_time` 对没有历史快照能力的来源 fail closed，禁止用现值冒充历史证据。
  - 每次配置的 vendor 尝试都写入 run-scoped append-only ledger，包括失败原因、fallback 和最终选中结果。
  - 完成证据：Gamma `public-search` 原始 schema 和实时样本已审计；adapter 直接生成 `PredictionMarketFeed`，router 绑定 `call_id` 后校验并渲染。预测市场、citation、vendor ledger、runtime/Web/history 相关测试共 100 项通过。2026-07-14 补跑只读 live probe，`2028 presidential election` 返回的 3 个市场全部通过 validator，并保留 event/market ID、稳定 `prediction_*` source ID、`observed_at` 和带时区到期时间。

- [x] **2. Runtime 失败状态与 vendor 轨迹**
  - Runtime、SQLite、API、SSE 和 Web 必须一致展示失败数据域、`call_id`、尝试顺序、vendor 状态、具体校验/认证/限流/无数据原因及最终 fallback 结果。
  - 降级、`review_required` 和 `unavailable` 不得显示为普通成功或投资 Hold。
  - 刷新和历史回放必须从持久化事件恢复相同的失败与 fallback 轨迹。
  - 完成证据：新增一等 `vendor_attempt` runtime 事件，逐条携带数据域、`call_id`、attempt、vendor、状态、错误类型/脱敏详情及是否选中；事件与 append-only ledger 使用同一已落盘记录。终态事件和 Run API 通过确定性汇总分别暴露 `decision_status` 与 `data_status=available|degraded|unavailable|not_observed`，并列出 fallback/unavailable 数据域和异常轨迹。Web 实时流、历史 SSE replay 和运行历史均显示降级状态，不再把降级运行只呈现为普通完成或 Hold。相关 runtime/history/vendor/Web 回归测试 80 项及项目 Web/CLI 快速门禁 61 项通过，前端语法与模块测试通过；长期 Web 服务热加载后保持 active，真实 `/api/runs` 已从既有 SQLite ledger 恢复 `data_status=degraded` 和 `fundamental_data` 不可用轨迹。
  - Langfuse 可作为可选的 OpenTelemetry/Langfuse span 镜像，用于跨运行查询和仪表盘；它不得替代 SQLite/runtime 权威事件链，也不得因采样、网络或外部服务故障阻断分析。接入时需显式创建 vendor span 或配置过滤，因为当前 Langfuse SDK 默认聚焦 LLM/GenAI span。

- [x] **3. 新闻、宏观校验覆盖审计**
  - 新闻逐项确认来源、URL、正文可用性、真实发布时间、标的相关性、去重、稳定 `source_id` 和 cutoff。
  - 宏观逐项确认指标名称、单位、观察期、发布日期、修订语义、稳定 `source_id` 和 cutoff。
  - 对照现有 `NewsFeed` / `MacroSeries` 实现、测试和运行证据；已满足的项目关闭，缺口形成独立可验收任务。
  - 完成证据：router 对新闻执行 routed vendor、非空正文/摘要、HTTP(S) URL、标的相关性、精确发布时间 cutoff、规范 URL/标题去重和稳定 `source_id` 校验；`live` 运行的新闻窗口按调用时 UTC 日期推进，不再被最近完整日 K 的 `analysis_date` 截断。Longbridge MCP 实时 NVDA 样本通过完整校验；Longbridge CLI 列表缺少正文时使用同一新闻能力的 `news detail` 补齐，Alpha Vantage 的日期末端按 23:59 包含后再由 router 精确裁剪；Westock 在当前主机不可用，DuckDuckGo 缺少可信发布时间，两者均 fail closed，未伪装为有效证据。
  - 完成证据：`MacroSeries` / `MacroObservation` 已包含请求指标、series ID/title、单位、频率、观察期、初次发布日期、vendor、vintage、revision 状态与含 vintage 的稳定 `source_id`。FRED 使用历史 vintage 和 `output_type=4` 初次发布元数据；日内 point-in-time 截止保守固定到前一日 vintage。真实历史探针以 `2025-07-10T16:00:00-04:00` 为截止，固定到 `2025-07-09` vintage，返回 11 条可见 CPI 记录，最新观察期 `2025-05-01`、初次发布日期 `2025-06-11`，并通过确定性 validator。新闻、宏观、路由、runtime/Web 相关测试 98 项和项目快速门禁 61 项通过，前端语法与 Python 编译检查通过；长期 Web 服务热加载后保持 active，`/api/config/defaults` 返回 200。
  - 2026-07-15 回归修复：FRED `output_type=4` 初次发布查询不再从 `1776-07-04` 扫描至当前 vintage，而是绑定实际 observation window；显式超长窗口按最多 1800 个日历日分段，规避 JSON 每次最多 2000 个 vintage date 的限制。合并分段及修订记录时确定性保留同一观察期最早的 `realtime_start`，避免把后续修订误标为初值；新增日频 VIX 与 4000 天窗口回归覆盖。FRED/全球宏观/lookahead 测试 30 项及 evidence/vendor/runtime/Web 快速门禁 79 项通过；真实 VIX、DGS10 探针分别返回 258、250 条记录并通过统一 `MacroSeries` validator，未再触发 3887/5063-vintage 错误。
  - 2026-07-15 工程闭环补充发现 UTC/FRED 跨日边界：live runtime 在 UTC 已进入次日、America/Chicago 尚未跨日时会把未来日期作为 vintage，导致 FRED 拒绝并终止必需宏观证据链。live vintage 已改为按 FRED 所在时区生成；同时修正固定宽度 OHLCV 表的 audit 日期提取，避免把次日抓取注释误报为 `data_latest_date`。首次 remediation run 进一步发现空指标数组会终止 Graph；空列表、空字符串和纯空白现确定性映射到服务端八项多样化默认批次，非空选择仍限制最多八项并保留一次 canonical OHLCV、逐项 validator 与底层硬校验。后续真实 FRED 502 又暴露 `requests` 异常会把含 API key 的 PreparedRequest URL 带入日志；网络边界现已统一改为只传播状态码、端点和异常类型，相关 SQLite 证据已脱敏并要求轮换凭据。闭环还补齐 Portfolio Manager 的 M/B/T/亿/万亿/美元绝对值归一与 Analyst 原始证据追溯，拒绝中英文单位漂移、Risk 自我背书和无来源派生价格；扩展非多头门禁覆盖中文风险收益比、赔率及中文数词条件动作，同时只规范化明确否定标题以避免误报。News Analyst 单次 citation 纠错后仍缺来源的物质性段落会被确定性删除，未知 source_id 继续硬失败；财务 reconciliation 成功子调用的 false-degraded 汇总也已修复。最终 remediation run `c8778912f7aa4643bf013e1d926d9117` 为 `completed + validated`：12 个 Agent 完成、95 个事件、36 次 vendor attempt、所有 selected 结果均有 hash、`data_status=available`、无 error/凭据形状/不可追溯货币数值/未验证非多头执行数字，仅保留 P1 高上下文成本。父闭环与所有 remediation 证据见 `.tradingagents/engineering_cycles/6950c33a0d3f422fa1e83b97685f84dc/`；代码级相关测试 75 项通过，固定 verify 另有 106 项通过，并完成 Python 编译、前端语法和 `git diff --check`，`verification.json` 为 `passed=true`。

  - 最终提交前聚合回归覆盖 FRED、history、vendor 日期、新闻 citation、指标与交易门禁，共 114 项通过。

### 第二阶段：运行可靠性/成本（4–5）

- [x] **4. SSE / report-section 节流**
  - 按 run + section 合并高频中间更新，最终状态和最后一个 section 版本不得丢失。
  - heartbeat、断线重连和持久化 replay 语义保持不变。
  - 用并发运行验证 SQLite lock、写入次数和浏览器更新频率明显下降。
  - 完成证据：canonical runtime 新增按 `run_id + section` 的 500 ms leading/trailing throttle；首版立即可见，窗口内只保留最新版，并在 agent 完成、终态事件和流结束前强制 flush。100 次同 section 合成测试只持久化并通过 SSE 发送首末 2 个版本，SQLite 写入和浏览器 section 更新下降 98%；4 个并发 run 的 400 个原始更新只生成 8 条 report 事件，无 lock 错误且每个 run 的终版均为第 100 版。Web bridge 不再对 runtime 已落盘事件执行第二次 SQLite 去重事务；SSE 改用广播 condition + 每连接独立 replay cursor，活动连接不再重复发送连接前事件，多连接不再争抢单一队列。heartbeat 格式、历史 replay 和 EventSource 自动重连保持不变。相关 runtime/history/Web 节流测试及项目 Web/CLI 门禁共 76 项通过，前端语法检查通过；长期 Web 服务热加载后保持 active，defaults、env-status、runs 和持久化 SSE replay 接口均验证可用。

- [x] **5. 技术指标批量获取**
  - 一次加载规范 OHLCV，批量计算/获取 Market Analyst 所需指标，避免约 12 次重复串行调用。
  - 保留每个指标的预热窗口、确定性 validator、vendor 来源和 fallback 可观测性。
  - 批量结果必须与现有逐项结果在约定容差内一致。
  - 完成证据：Market Analyst 的 `get_indicators` schema 改为一次接收最多 8 个指标，默认 westock/stockstats 路径只加载一次 canonical OHLCV、创建一个 stockstats frame 并逐项生成结构化 `IndicatorBatch`；同 symbol/date 的缓存填充增加 singleflight，避免并发 cache miss 击穿 Longbridge。router 对每条序列分别执行预热、日期、freshness、数值范围与 Close 相对范围 validator；本地部分失败时只把缺失集合合并为一次 Longbridge MCP 多 `plot()` `quant_run`，仍未解决的个别项才进入旧单项兼容 fallback，所有 batch 与 fallback vendor attempt 保持 run-scoped ledger 可见。基线 NVDA 运行曾产生 10 次技术指标调用和 26 次 Longbridge OHLCV 调用，同秒最多 6 个 OHLCV 请求；新默认 live probe 以一次 batch 在 1.2 秒内返回 8 个有效 section，真实 MCP probe 以一次请求返回 RSI+ATR 并通过 `2026-07-13` 最新交易日校验。批量与旧逐项结果在 `1e-12` 相对容差内一致；指标/OHLCV/router/Web 相关测试 97 项通过、1 项显式 live provider 测试按环境跳过，项目 Web/CLI 门禁 101 项通过，前端语法与 Python 编译检查通过。

### 第三阶段：核心研究能力（6–8）

- [ ] **6. 仓位引擎与交易校验器解耦**
  - `PositionSizingEngine` 负责固定风险、ATR 风险、波动率目标、分数凯利、账户权益和最大名义敞口下的建议仓位。
  - `TradePlanValidator` 独立重算并执行组合损失、集中度、购买力和账户限制硬门禁；LLM 不能提高服务端限制。

- [ ] **7. Longbridge 前瞻研究数据域**
  - 接入 `consensus`、`forecast_eps`、`finance_calendar`、`institution_rating`、`filings`、`short_positions` 和 `short_trades`。
  - 建立包含 `as_of`、发布日期、事件日期、标的、币种、期间、稳定 `source_id` 和 vendor `call_id` 的统一模型与 validator。
  - 验证后分别提供给 Fundamentals、News、Bull/Bear 和 Risk Agent；当前快照不得泄漏到历史运行。

- [ ] **8. 跨市场 Session Engine**
  - 使用权威交易日历建模交易所时区、DST、节假日、半日市和 `pre|regular|post` session。
  - 分别保存 `market_date`、`observed_at`、`published_at` 和 `available_at`；盘前盘后数据不得覆盖规范日 K。
  - A/H/ADR、汇率、换股比例和产业链映射只生成可审计只读证据；lead-lag 必须验证历史稳定性、流动性、点差、成本和可转换性，不得描述为无风险套利。

### 第四阶段：高复杂度扩展（9–14）

- [ ] **9. 空头与衍生品交易校验**
  - 新增显式 `side=long|short|flat`；Sell/Underweight 只代表减仓，不得隐式开空。
  - 空头股票验证 `target < entry < stop`；期权独立建模权利金、行权价、到期日、乘数、IV、Greeks 和非线性损益。

- [ ] **10. Longbridge 只读账户风险输入**
  - 以最小 OAuth 权限读取余额、持仓、保证金、购买力和汇率，并作为服务端风险政策输入。
  - 不向分析 Agent 暴露下单、撤单、改单、DCA、提醒或 Watchlist 写操作。

- [ ] **11. Longbridge 基本面与持仓拥挤增强**
  - 逐项审计并接入业务分部、估值历史/同行、股东/基金持仓、内部人交易、资金流、交易统计、市场温度和异动。
  - 每项必须基于真实 schema 单独建立 adapter、模型和 validator，禁止依据工具描述批量生成。

- [ ] **12. Longbridge 独立宏观 vendor**
  - 将 `macrodata` 与宏观事件日历注册为独立 vendor，映射到 `MacroSeries`。
  - 校验单位、观察期、发布日期和 cutoff；不得隐藏在 FRED 或其他 vendor 内部。

- [ ] **13. 独立 Reviewer 模型**
  - 可选 `review-model` 只读取不可变 execution evidence，输出带 event/vendor/source 引用的结构化 findings。
  - Reviewer 不得修改历史、直接关闭 finding 或决定 gate 通过；仍需人工确认和确定性验证。

- [ ] **14. 衍生品数据与选股能力**
  - option chain、IV、Greeks 必须等待第 9 项风险模型完成。
  - screener、rank、top movers 必须等待独立 universe/选股阶段，不直接塞入现有单标的 Agent 工具集。

### 暂缓议题：最低优先级（15）

- [ ] **15. 运行上下文压缩（原第 6 项，暂缓）**
  - 历史基准证据：NVDA depth=1 两次运行累计输入 token 为 254,861 和 252,244；
    该总量只证明运行成本较高，不能证明单个 Agent 收到了重复或无用上下文。
  - 讨论结论：不同角色读取相同 Analyst 证据，以及同一角色在后续轮次携带既有历史，
    都是 Bull/Bear/Risk 独立辩论和连续推理的必要组成，不按运行级重复计算为缺陷。
  - 未来若重启本项，只以“单个 Agent 的单次实际 LLM 请求”为审计单位；按 system、
    报告、工具结果、辩论历史、最新回复和 reasoning 分块，仅记录类型、长度与内容 hash，
    不持久化实际 Prompt 或敏感内容，也不把跨 Agent 或跨轮次复用判为重复。
  - 只有在单次请求内证明存在精确结构重复、无效工具载荷或上下文容量风险后才实施优化；
    不做模糊语义去重，不以强制 token 降幅为目标，不删除 M3 reasoning round-trip。
  - 来源事实、`source_id`、vendor `call_id`、交易门禁输入、完整反方证据和辩论结构不得
    因压缩丢失；相关方案与验收指标留待未来重新讨论后确定。

## 已完成的安全与架构基础

以下能力已经完成，保留为后续任务不可破坏的回归基线：

### Runtime、CLI 与 Web

- [x] CLI、Web 和 Python 正式入口统一使用 `tradingagents.runtime`；`run_analysis_stream()` / `run_analysis_once()` 输出结构化事件并使用共享报告器。
- [x] Web API 支持运行创建、状态、SSE、取消、报告和历史回放；CLI/Web 启动配置保持 Step 1–8 parity。
- [x] `TaskStore` 与 runtime history 共用 `~/.tradingagents/runs.db`；SQLite 使用 WAL、busy timeout、foreign keys、有限重试和事件去重。
- [x] agent 状态单调、报告 section 增量可见且历史刷新可恢复；`run_id` 隔离 checkpoint 和并发执行。
- [x] 用户级 systemd 长期托管 Web 开发服务，源码目录变更由受限 `--reload` 实时生效。

### 数据模型、校验与审计

- [x] 行情、技术指标和财务数据进入 Agent 前经过统一领域模型与确定性 validator。
- [x] `NewsFeed`、`MacroSeries` 和 `SocialFeed` 已结构化；外部内容以 `untrusted_data` JSON 传输并清除提示注入控制文本。
- [x] StockTwits 历史 keyless symbol stream 已因 Cloudflare browser challenge 从默认 Sentiment 路径退役；运行不再重复请求并产生 403。当前使用已验证的 Bird/X 与 Reddit，只有取得官方批准的服务端 API 和原始 schema 后才允许将 StockTwits 作为独立结构化 vendor 重新接入，禁止保存浏览器 challenge cookie 或抓取 HTML 绕过。
  - 完成证据：官方旧 endpoint 的只读探针返回 HTTP 403、`cf-mitigated: challenge`；403 现在映射为明确且不可重试的 unavailable marker，Sentiment 默认只注入 disabled marker 而不发起网络请求。StockTwits/Sentiment/不可信内容相关测试 34 项通过。
- [x] OHLCV 采用 `OHLCVBatch` 写入契约、日期/OHLC 硬校验、原子缓存替换及 JSONL 溯源；盘中或日期漂移数据不能冒充规范日 K。
- [x] 技术指标统一预热窗口和三年 calculation start；默认 Westock/stockstats，Longbridge MCP 为验证后 fallback。
- [x] run-scoped vendor ledger 按 `run_id + call_id + attempt` 追加保存；审计落盘失败时禁止生成可执行报告。
- [x] Longbridge 个股新闻使用 `longbridge_mcp → longbridge`，全球新闻使用 CLI 结构化搜索；MCP `news_search` 的 epoch 时间问题修复前不注册为全球新闻来源。
- [x] 财务 MCP/CLI 原始 JSON 直接映射 `FinancialMetric`，完成跨报表勾稽、期间一致性及 ROE/ROA/TTM EPS/PE/净现金/EV-EBITDA 的确定性计算。

### 决策与安全门禁

- [x] 可信 ATR、Close、market date 和 vendor `call_id` 由 verified snapshot 注入；LLM 不能提供权威风控输入。
- [x] Buy/Overweight 交易计划结构化，收益风险比、ATR 距离和组合损失由代码重算；重复失败进入 `REVIEW_REQUIRED`。
- [x] `validated|review_required|unavailable` 是一等状态；无有效决策不伪装成 Hold、不生成信号、不写绩效记忆。
- [x] Web backend URL allowlist、路径/配置白名单、非 loopback bearer 认证、启动频率与并发限制已经完成。
- [x] 模型 tool 参数 Schema 错误只允许一次受限纠正；vendor、认证、无数据和 validator 错误继续 fail closed。

### 测试与工程闭环

- [x] pytest 为每个测试隔离 `TRADINGAGENTS_DB`；runtime、TaskStore 和 vendor ledger 不写正式数据库。
- [x] 离线边界测试保留固定日期；live integration/smoke 使用按市场计算的最近完整日 K。
- [x] `scripts/engineering_cycle.py` 固化 `run → review → ack-review → P0 plan/implementation → resolve → verify → gate`，缺少证据或存在未解决 P0 时不能关闭。
- [x] OpenAI-compatible keyless 测试不会在断言或日志中展开环境凭据。

## 完成与重新排序规则

- 新 finding 先判断是否为明确 P0。会导致默认启用链路错误决策、信任边界突破、前视泄漏、审计证据破坏或 fail-open 的问题，优先升级处理。
- 重新排序必须引用可复现运行证据、影响范围、发生概率、可逆性、默认启用状态和依赖关系。
- 项目只有在实现、针对性测试、必要的运行态证据和本文件状态同步后才能勾选完成。
- 涉及真实分析后复盘及 P0 修复时，必须遵循 `docs/engineering-cycle.md`，并为每轮创建新的 `run_id`。
- 已完成的详细实现历史保留在 Git；本文件只保存仍影响后续工作的回归基线，不继续累积逐日开发日志。
