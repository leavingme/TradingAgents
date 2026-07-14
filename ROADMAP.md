# TradingAgents Roadmap

本文档是项目任务状态、优先级、验收条件和中长期能力路线的**唯一权威来源**。
长期不变的工作原则与操作约束位于 `AGENTS.md`；具体任务的新增、完成、拆分和重新排序只在本文件维护。

## 当前结论

- 截至 2026-07-14，没有未完成的明确 P0。
- 当前排序遵循 `AGENTS.md` 的四级原则：**安全与正确性 → 运行可靠性/成本 → 核心研究能力 → 高复杂度扩展**。
- 排名是执行顺序，不是功能价值评分。默认启用且可能影响决策的链路，优先于尚未开放的未来能力。

## 未完成项权威排序

| 排名 | 未完成项 | 当前优先级依据 |
|---:|---|---|
| 1 | 预测市场确定性校验与 vendor-attempt 持久化 | 当前默认启用且会影响决策；必须补齐事件 ID、到期日、概率范围、时间截止、稳定 `source_id` 和逐次 vendor 审计。 |
| 2 | Runtime 失败状态与 vendor 轨迹 | 明确显示失败数据域、尝试过的 vendor、fallback 路径及校验原因，避免失败或降级被误读。 |
| 3 | 新闻、宏观校验覆盖审计 | 结构化模型已完成，但仍需逐项核对正文、发布时间、观察期、单位、`source_id` 与 cutoff。 |
| 4 | SSE / report-section 节流 | 降低 SQLite 锁竞争、写放大和浏览器高频重绘。 |
| 5 | 技术指标批量获取 | 减少约 12 次串行请求、重复 OHLCV 加载、事件数量和等待时间。 |
| 6 | 运行上下文压缩 | depth=1 已观测到超过 25 万输入 token；需要降低成本、延迟和长上下文遗漏风险。 |
| 7 | 仓位引擎与交易校验器解耦 | 分离建议仓位计算与服务端风险硬门禁；现有风险政策已 fail-closed，因此不是 P0。 |
| 8 | Longbridge 前瞻研究数据域 | 接入一致预期、EPS、财务日历、评级、filings 和空头数据。 |
| 9 | 跨市场 Session Engine | 正确建模交易所时区、DST、节假日、半日市及盘前/盘中/盘后。 |
| 10 | 空头与衍生品交易校验 | 在开放做空或期权前建立独立方向、收益结构和 Greeks 风险门禁。 |
| 11 | Longbridge 只读账户风险输入 | 用真实持仓、购买力、保证金和汇率约束仓位，同时坚持最小 OAuth 权限。 |
| 12 | Longbridge 基本面与持仓拥挤增强 | 增加业务分部、估值、持有人、资金流和微观结构证据。 |
| 13 | Longbridge 独立宏观 vendor | 增加 FRED 之外的结构化宏观来源，优先级低于现有宏观校验闭环。 |
| 14 | 独立 Reviewer 模型 | 增强工程复盘，但只能作为建议层，不能掌握关闭权。 |
| 15 | 衍生品数据与选股能力 | 必须等待衍生品风险模型与 universe 阶段完成。 |

## 执行计划与验收条件

### 第一阶段：安全与正确性（1–3）

- [ ] **1. 预测市场确定性校验与 vendor-attempt 持久化**
  - 统一模型必须包含稳定事件 ID、标题、标的关联、带时区到期日、概率、`observed_at`、稳定 `source_id` 和 vendor `call_id`。
  - validator 必须拒绝缺失事件 ID/到期日、概率不在 `[0, 1]`、超过信息截止时间、已失效事件和无法稳定溯源的数据。
  - `live` 运行保存调用时观察时间；`point_in_time` 对没有历史快照能力的来源 fail closed，禁止用现值冒充历史证据。
  - 每次配置的 vendor 尝试都写入 run-scoped append-only ledger，包括失败原因、fallback 和最终选中结果。

- [ ] **2. Runtime 失败状态与 vendor 轨迹**
  - Runtime、SQLite、API、SSE 和 Web 必须一致展示失败数据域、`call_id`、尝试顺序、vendor 状态、具体校验/认证/限流/无数据原因及最终 fallback 结果。
  - 降级、`review_required` 和 `unavailable` 不得显示为普通成功或投资 Hold。
  - 刷新和历史回放必须从持久化事件恢复相同的失败与 fallback 轨迹。

- [ ] **3. 新闻、宏观校验覆盖审计**
  - 新闻逐项确认来源、URL、正文可用性、真实发布时间、标的相关性、去重、稳定 `source_id` 和 cutoff。
  - 宏观逐项确认指标名称、单位、观察期、发布日期、修订语义、稳定 `source_id` 和 cutoff。
  - 对照现有 `NewsFeed` / `MacroSeries` 实现、测试和运行证据；已满足的项目关闭，缺口形成独立可验收任务。

### 第二阶段：运行可靠性/成本（4–6）

- [ ] **4. SSE / report-section 节流**
  - 按 run + section 合并高频中间更新，最终状态和最后一个 section 版本不得丢失。
  - heartbeat、断线重连和持久化 replay 语义保持不变。
  - 用并发运行验证 SQLite lock、写入次数和浏览器更新频率明显下降。

- [ ] **5. 技术指标批量获取**
  - 一次加载规范 OHLCV，批量计算/获取 Market Analyst 所需指标，避免约 12 次重复串行调用。
  - 保留每个指标的预热窗口、确定性 validator、vendor 来源和 fallback 可观测性。
  - 批量结果必须与现有逐项结果在约定容差内一致。

- [ ] **6. 运行上下文压缩**
  - 基准证据：NVDA depth=1 两次运行输入 token 为 254,861 和 252,244。
  - 审计 Analyst 报告、工具结果及 Bull/Bear/Risk 辩论之间的重复内容，定义确定性压缩边界。
  - 来源事实、`source_id`、vendor `call_id`、交易门禁输入和必要反方证据不得被摘要丢失。
  - 以同输入运行对比 token、延迟、决策状态和引用完整性。

### 第三阶段：核心研究能力（7–9）

- [ ] **7. 仓位引擎与交易校验器解耦**
  - `PositionSizingEngine` 负责固定风险、ATR 风险、波动率目标、分数凯利、账户权益和最大名义敞口下的建议仓位。
  - `TradePlanValidator` 独立重算并执行组合损失、集中度、购买力和账户限制硬门禁；LLM 不能提高服务端限制。

- [ ] **8. Longbridge 前瞻研究数据域**
  - 接入 `consensus`、`forecast_eps`、`finance_calendar`、`institution_rating`、`filings`、`short_positions` 和 `short_trades`。
  - 建立包含 `as_of`、发布日期、事件日期、标的、币种、期间、稳定 `source_id` 和 vendor `call_id` 的统一模型与 validator。
  - 验证后分别提供给 Fundamentals、News、Bull/Bear 和 Risk Agent；当前快照不得泄漏到历史运行。

- [ ] **9. 跨市场 Session Engine**
  - 使用权威交易日历建模交易所时区、DST、节假日、半日市和 `pre|regular|post` session。
  - 分别保存 `market_date`、`observed_at`、`published_at` 和 `available_at`；盘前盘后数据不得覆盖规范日 K。
  - A/H/ADR、汇率、换股比例和产业链映射只生成可审计只读证据；lead-lag 必须验证历史稳定性、流动性、点差、成本和可转换性，不得描述为无风险套利。

### 第四阶段：高复杂度扩展（10–15）

- [ ] **10. 空头与衍生品交易校验**
  - 新增显式 `side=long|short|flat`；Sell/Underweight 只代表减仓，不得隐式开空。
  - 空头股票验证 `target < entry < stop`；期权独立建模权利金、行权价、到期日、乘数、IV、Greeks 和非线性损益。

- [ ] **11. Longbridge 只读账户风险输入**
  - 以最小 OAuth 权限读取余额、持仓、保证金、购买力和汇率，并作为服务端风险政策输入。
  - 不向分析 Agent 暴露下单、撤单、改单、DCA、提醒或 Watchlist 写操作。

- [ ] **12. Longbridge 基本面与持仓拥挤增强**
  - 逐项审计并接入业务分部、估值历史/同行、股东/基金持仓、内部人交易、资金流、交易统计、市场温度和异动。
  - 每项必须基于真实 schema 单独建立 adapter、模型和 validator，禁止依据工具描述批量生成。

- [ ] **13. Longbridge 独立宏观 vendor**
  - 将 `macrodata` 与宏观事件日历注册为独立 vendor，映射到 `MacroSeries`。
  - 校验单位、观察期、发布日期和 cutoff；不得隐藏在 FRED 或其他 vendor 内部。

- [ ] **14. 独立 Reviewer 模型**
  - 可选 `review-model` 只读取不可变 execution evidence，输出带 event/vendor/source 引用的结构化 findings。
  - Reviewer 不得修改历史、直接关闭 finding 或决定 gate 通过；仍需人工确认和确定性验证。

- [ ] **15. 衍生品数据与选股能力**
  - option chain、IV、Greeks 必须等待第 10 项风险模型完成。
  - screener、rank、top movers 必须等待独立 universe/选股阶段，不直接塞入现有单标的 Agent 工具集。

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
