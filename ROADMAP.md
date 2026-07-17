# TradingAgents Roadmap

本文档是项目任务状态、优先级、验收条件和中长期能力路线的**唯一权威来源**。
长期不变的工作原则与操作约束位于 `AGENTS.md`；具体任务的新增、完成、拆分和重新排序只在本文件维护。

## 当前结论

- 截至 2026-07-17，收盘后每日运行目标新增后，发现并修复了“5 日结果在第 1 日提前结算”与历史复现写入事后反思两个 P0 正确性缺陷；没有仍未处理的明确 P0。
- 当前排序遵循 `AGENTS.md` 的四级原则：**安全与正确性 → 运行可靠性/成本 → 核心研究能力 → 高复杂度扩展**。
- 排名是执行顺序，不是功能价值评分。默认启用且可能影响决策的链路，优先于尚未开放的未来能力。
- 第 1–5 项已完成；第 6 项收盘后每日运行与固定期限结果闭环正在实施，第 7 项为
  连续多日评估和 agent 架构实验门禁。原“运行上下文压缩”继续暂缓并置于路线末尾。

## 路线项权威顺序与状态

| 顺序 | 状态 | 路线项 | 当前优先级依据 |
|---:|---|---|---|
| 1 | 已完成（2026-07-14） | 预测市场确定性校验与 vendor-attempt 持久化 | 当前默认启用且会影响决策；补齐事件 ID、到期日、概率范围、时间截止、稳定 `source_id` 和逐次 vendor 审计。 |
| 2 | 已完成（2026-07-14） | Runtime 失败状态与 vendor 轨迹 | 明确显示失败数据域、尝试过的 vendor、fallback 路径及校验原因，避免失败或降级被误读。 |
| 3 | 已完成（2026-07-14） | 新闻、宏观校验覆盖审计 | 已逐项核对正文、发布时间、观察期、单位、revision/vintage、`source_id` 与 cutoff，并补齐缺口。 |
| 4 | 已完成（2026-07-14） | SSE / report-section 节流 | 已按 run + section 合并高频中间版本，并消除 Web bridge 重复持久化和 SSE replay 重复发送。 |
| 5 | 已完成（2026-07-14） | 技术指标批量获取 | 已实现单次规范 OHLCV、本地批量计算、批量 MCP fallback 和逐项确定性校验。 |
| 6 | 进行中 | 收盘后每日运行与固定期限结果闭环 | 用户明确要求；无人值守运行会放大模型配置漂移、重复启动、短期限误结算和前视副作用，必须先做可靠性与正确性门禁。 |
| 7 | 进行中 | 连续多日评估与 agent 架构实验门禁 | 结构化保存结果、滚动指标和架构版本；无配对证据时禁止自动晋升 prompt 或拓扑。 |
| 8 | 未完成 | 仓位引擎与交易校验器解耦 | 分离建议仓位计算与服务端风险硬门禁；现有风险政策已 fail-closed，因此不是 P0。 |
| 9 | 未完成 | Longbridge 前瞻研究数据域 | 接入一致预期、EPS、财务日历、评级、filings 和空头数据。 |
| 10 | 未完成 | 跨市场 Session Engine | 正确建模交易所时区、DST、节假日、半日市及盘前/盘中/盘后。 |
| 11 | 未完成 | 空头与衍生品交易校验 | 在开放做空或期权前建立独立方向、收益结构和 Greeks 风险门禁。 |
| 12 | 未完成 | Longbridge 只读账户风险输入 | 用真实持仓、购买力、保证金和汇率约束仓位，同时坚持最小 OAuth 权限。 |
| 13 | 未完成 | Longbridge 基本面与持仓拥挤增强 | 增加业务分部、估值、持有人、资金流和微观结构证据。 |
| 14 | 未完成 | Longbridge 独立宏观 vendor | 增加 FRED 之外的结构化宏观来源，优先级低于现有宏观校验闭环。 |
| 15 | 未完成 | 独立 Reviewer 模型 | 增强工程复盘，但只能作为建议层，不能掌握关闭权。 |
| 16 | 未完成 | 衍生品数据与选股能力 | 必须等待衍生品风险模型与 universe 阶段完成。 |
| 17 | 暂缓（最低优先级） | 运行上下文压缩 | 累计 token 高不等于单 Agent 上下文重复；跨角色共享证据和跨轮携带历史属于辩论机制，未来只按单 Agent 单次请求审计后再议。 |

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
  - 2026-07-16 展示语义修复：同一数据域中成功与失败查询并存时归入 `partially_available_domains`，不再把整个能力误列为 `unavailable_domains`；异常轨迹携带逐次 vendor、状态、错误类型与脱敏详情。Web 实时完成、历史深链接和运行历史状态区分“部分证据缺失”与“已使用备用数据源”，并展示受影响主题、Agent、数据源路径及具体原因。
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

### 第二阶段：运行可靠性/成本（4–7）

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

- [ ] **6. 收盘后每日运行与固定期限结果闭环**
  - 用户级 systemd timer 每 15 分钟检查各标的交易所本地 `run_after`，实际执行仍通过 canonical runtime；配置、unit 和日志不得包含凭据。
  - 同 symbol + market-data date 幂等；活动/成功/人工复核结果不重跑，基础设施失败有延迟、次数上限和跨进程锁，防止并发与成本失控。
  - 自动运行复用服务端 Web 的 LLM、研究深度、输出语言和 vendor 顺序，避免 skill worker 使用不兼容默认模型。
  - 固定 5-session 结果按每个原始 run 的 `decision_as_of` 交易所本地日期确定 cutoff，使用 cutoff 后第一个标的/基准共同收盘价作为 entry，并只在再往后第 5 个共同交易日存在时结算；1–4 个持有时段保持 pending。`point_in_time` 禁止产生事后反思或结果写入。
  - 当前证据：repo-native scheduler、systemd unit、NVDA 正式配置和运维文档已实现；用户级 timer 已 `enable --now`，每 15 分钟检查，正式 oneshot 在未到时段时以 `not_due`/exit 0 完成。canonical 默认已统一为 `minimax-cn` + `MiniMax-M3`，修复 skill worker 请求错误模型的问题；runtime 现会在调用入口没有 stats callback 时自动安装 canonical `StatsCallbackHandler`，因此 timer 与 skill 的无人值守 run 在成功或失败终态前都强制保存 LLM/tool/token 最终快照。新增五轮同输入 NVDA 工程审计，依次发现并修复 Trader prose 纠错不确定、非多头否定标题假阳性、可信行情/服务端风险约束未进入 Trader 生成上下文、Portfolio schema 与 prose 门禁冲突；最终 run `0c3c7612b154454eaaad37595fd0da98` 以 `decision_status=validated`、`data_status=degraded` 完成，Trader/Portfolio 均首轮通过，自动 review 无 P0。调度、history、runtime、Web、CLI、结构化 agent、社交 vendor、纵向评估和 OHLCV provenance 相关 277 项通过；本轮安全边界相关 153 项通过，前端模块/语法检查通过；Providers 桌面与精确 390×844 视口均无横向 overflow。关闭仍需首次实际收盘后运行证据。
  - 2026-07-17 首跑前凭据审计只读取 expiry 而未输出 token：仓库根目录 MCP token 为 mode 0600，过期时间 2026-07-18 23:56 CST，晚于 04:30 首跑约 19 小时。该独立 Agent Auth bearer 当前没有可安全使用的 `client_id`，因此运行时到期后按既定规则抛 `MCPAuthError`；第一 fallback Longbridge CLI 0.24.0 的独立 OAuth 状态实测为 `valid`，`longbridge check --format json` 对 CN/Global 端点均连通且 session token 有效，后续自然运行不会因 MCP bearer 到期而中断整条数据链。
  - 首跑前 systemd 生效属性审计确认用户 manager 默认 `DefaultTimeoutStartUSec=90s`，但仓库与实际安装的 service 完全一致并显式设置 `Type=oneshot`、`TimeoutStartSec=infinity`，生效的 `RuntimeMaxUSec=infinity`；5–10 分钟 canonical 分析不会被默认启动超时终止。timer 保持 15 分钟周期、`Persistent=true` 和最多 30 秒随机延迟，仓库回归锁定这些恢复与长运行约束；相关完整门禁 209 项通过。
  - scheduler 以前会把 canonical runtime 正常返回的 `review_required` 和 `unavailable` 都打印成 `completed`，其中无决策的 `unavailable` 还会让 systemd 以 0 退出。状态现确定性映射为 `validated → completed`、`review_required → review_required`、`unavailable → unavailable`；后者与最终 `attempts_exhausted` 返回非零，`retry_wait` 不重复制造失败。SQLite、重试决策、journal 与服务退出语义不再互相矛盾；相关完整门禁 213 项通过。
  - scheduler dry-run 现构造与正式执行相同的有效 runtime config，输出 analysts、深度、语言、模型、vendor、推理设置、纵向模式、计划顺序以及安全 canonical manifest/fingerprint；不创建历史、不调用 LLM/vendor，也不输出 backend URL、凭据、secret 环境值或绝对路径。首跑时点预演已确认 NVDA `2026-07-17` 为 `would_run`，使用 4 个 analysts、Shallow=1、Chinese、`minimax-cn/MiniMax-M3`、默认完整 vendor 链、live 模式与 `research_and_portfolio`，正式数据库不会错误拦截；canonical DB fail-closed 修复后的 manifest v3 预期 fingerprint 为 `8ebeebbd5be0de708a8c4b1d56ea2eaa67e0fd897da99d0c868093bde412ffb8`，脱敏扫描未发现绝对工作区路径或 secret key 名。
  - 首跑前结果时间轴审计先发现旧实现把 `analysis_date` 当日收盘价作为 entry；继续审计又确认仅要求 entry 晚于 analysis date 仍不足以覆盖“旧日期 + live 当前信息”或跨日长运行。现按每个原始 run 的 `decision_as_of` 转换到标的交易所时区，使用决策市场日之后第一个共同收盘价入场，再持有 5 个共同交易时段；History Store 交叉验证 UTC 决策时刻、时区、entry cutoff，并拒绝 `entry_date <= cutoff`，同时反查 validated terminal event 绑定 ticker/date/rating/decision time/architecture identity，防止上层或外部调用伪造 evaluation。待结算集合改由 SQLite 中 validated 且缺 evaluation 的 run 权威驱动，不再依赖可能缺失/去重/提前完成的 Markdown pending。`analysis_date` 现仅表示请求截止日，实际最后验证交易日只从结构化 OHLCV snapshot 写入独立 `market_data_date`；验证前保持未知，且不得晚于请求日期。run、terminal event、evaluation 与架构配对均使用该实际身份。`measurement_version` 独立于评分版本持久化，`decision-close-v1`、`next-common-close-v1` 与新 `post-decision-day-close-v1` rollup/比较 cohort fail-closed 隔离，纵向注入 schema 已升级到 v8。

- [ ] **7. 连续多日评估与 agent 架构实验门禁**
  - `decision_evaluations` 以原始 run 为主键保存架构版本、固定 horizon、rating、benchmark、raw/benchmark/alpha return、方向命中、确定性 score、计量版本、评分版本与 Hold band；不得只依赖 Markdown 反思，也不得把不同计量/评分口径混入同一架构 cohort。
  - 提供按架构版本、配置 fingerprint 和 horizon 的 sample count、hit rate、平均 return/alpha/score，以及 runtime/LLM/tool/token 成本与各自覆盖数聚合，并保留 CLI/API 查询；同名但不同实际配置不得混入同一 rollup。
  - 架构 challenger 至少满足样本门槛；顺序实盘 cohort 受 regime 混杂，即使 point estimate 更好也只能 `review_required`，无配对 shadow 证据不得自动晋升或改写 prompt/agent 拓扑。
  - 当前证据：结构化表、确定性评分、fingerprint-scoped rollup、CLI 与 `/api/evaluations` 已实现，API 可用成对 baseline/challenger 参数直接查询比较结果；每条结果强制保存实际 `market_data_date`、decision timestamp/timezone/cutoff、entry/exit 日期、标的/基准四个收盘价和四个逐交易日 OHLCV stable source ID，旧 range-only provenance 不能冒充可审计结果。已结算结果查询从同一 SQLite 关联 run 起止时间与最终 stats 快照，operator-facing rollup 对 runtime、LLM/tool calls、input/output tokens 同时输出均值和覆盖数；配对 shadow 输出 `challenger_minus_baseline` 成本差、平均降幅、Student-t 95% 区间和缺失排除数，缺失成本不会冒充零成本或改变收益门禁。canonical runtime 已从 SQLite 构造 cutoff-safe v8 固定 schema JSON，统一注入 Research Manager 与 Portfolio Manager，不再依赖 LLM Markdown 反思；逐条上下文明确扫描/截断计数、历史分析 data-status、input-evidence 与 pre-treatment agent-state 完整性，同标的架构 rollup 使用截止时点前扫描到的完整同标的 cohort，不再把最近样本截断或跨标的结果混入均值，运行成本字段也不会进入投资决策上下文。cutoff 与同/跨标的范围已下推到 SQLite 的排序/LIMIT 之前，新写入评估时间规范为 UTC，旧偏移时间按真实时刻排序，避免未来或跨标的样本挤掉历史时点已存在的证据。每个 run 保存有效 agent/model/topology manifest 与 SHA-256 fingerprint；每条 evaluation 另从 immutable vendor ledger 生成 analysis-input-evidence/v1 fingerprint，绑定规范化参数、fallback 状态、结果 hash 与观察范围但排除 call ID/延迟/时间戳噪声。当前 RM-context 实验还在 terminal event 固化 treatment 前的 `research-manager-pre-context-input/v1` 指纹，绑定 instrument context 与完整 debate history，但排除纵向上下文 treatment 自身。比较器拒绝同版本混杂配置，只接受 vendor evidence、pre-treatment agent state 与非空 `market_data_date` 都完整且相同，并且 measurement/scoring policy、ticker/date/horizon、entry/exit、四个收盘价、benchmark/raw/alpha return 以及四个 stable source ID 均一致的成对 shadow；vendor 输入漂移计入 `evidence_mismatches_excluded`，上游 LLM 输出漂移计入 `architecture_input_mismatches_excluded`，均不得归因于 agent。该输入 schema 只覆盖当前 Research Manager 分叉；更早的架构分叉仍需专用 schema 或共享 snapshot/replay。小样本 95% score-delta 下界使用 Student-t 临界值而非正态近似，并显式统计排除样本，任何结果仍需人工复核。默认禁用的 PM-only baseline / RM+PM challenger 模板已提供，未在无预算授权下开启。真实成本审计已将财务底层 attempts 20→8；跨表 derived metrics 不再在 IS/BS/CF 三份工具结果重复，财务 LLM renderer 改为无信息损失的紧凑 JSON，等待下一次自然调度 run 测量 token 变化。新增门禁的针对性测试 102 项通过；关闭仍需累积至少一个真实 5-session 结果，并在用户批准成本后积累配对 shadow 样本。
  - pre-treatment、实际 `market_data_date`、有界失败恢复与 paired-cost 授权门禁加入后的架构、纵向、history、runtime、结构化 agent、调度、CLI 与 Web 回归共 236 项通过；`market_data_status` / terminal event 现在也会通过 History Store 的确定性日期门禁重建 `runs.market_data_date`，避免仅依赖调用侧先写字段。正式 SQLite 只读审计此前确认所需 schema 已迁移，当前仍为 1 个旧失败 run、0 个 evaluation。
  - 首次自然运行前的失败恢复审计发现 scheduler 过去只从 SQLite run 数量执行每日 attempt 上限；若异常发生在 canonical runtime 注册 run 之前，日志虽失败但不会消耗 attempt，可能形成 15 分钟一次的无界重试。现在此路径写入 `pre-runtime-failure` 失败占位并纳入相同 retry budget，且不会覆盖 canonical runtime 已经持久化的失败证据。
  - 配对架构实验的预算约束现由 schema 强制：同标的双 arm 只有在共享 schedule/analysts、恰好隔离 `portfolio_only` 与 `research_and_portfolio` treatment，并显式设置 `paired_shadow_authorized=true` 时才能启用。仅把默认禁用模板改为 `enabled=true` 会 fail closed，避免误操作使无人值守成本近似翻倍或用不可比较的上游配置浪费样本。
  - 纵向评估 CLI 与 `/api/evaluations` 现暴露 SQLite 权威的 pending count/list，包括 decision timestamp、请求/实际数据日期与架构身份，能区分正常等待 5-session 成熟和评估链路无记录。审计同时发现 history/vendor verification 在 home 不可写时会静默使用工作区 `.tradingagents/runs.db`，把 19 条旧测试型记录误显示为正式 pending；该回退已删除，默认固定 `~/.tradingagents/runs.db`，只有 `TRADINGAGENTS_DB` 可覆盖且不可访问时 fail closed。沙箱外 CLI 与运行中 Web API 均确认正式库为 0 evaluation、0 pending；标准门禁 235 项与 vendor verification 9 项通过。
  - 架构比较器过去在每臂达到 20 个结果前提前返回，付费实验可能累计 40 次运行后才暴露 vendor evidence 或 pre-treatment state 全部漂移。现在首个双臂 evaluation 就计算并返回 `sample_progress`、有效 pair 数和所有 exclusion counters；样本不足仍保持 `insufficient_data` / `passes_paired_gate=false`，让 operator 能尽早停止不可归因的实验而不降低晋级门槛。
  - 2026-07-17 22:30 CST 的真实 systemd timer 新进程已加载 canonical DB fail-closed 版本，正常返回 NVDA `not_due`、exit 0，未读取工作区回退历史、未创建 run、未调用 LLM/vendor；这补足了 CLI/Web 之外的无人值守入口运行态证据。

  - 本轮新增纵向上下文 v3、数据库时点过滤、轻量 agent 查询与结构化 agent 回归证据；相关门禁扩大至 127 项并全部通过。
  - 评分身份现逐条保存 `alpha-exposure-v1` 与 Hold band；History Store 会按声明策略重算并校验 exposure、directional hit 与 score，rollup 按评分策略隔离，baseline/challenger 评分策略不唯一或不一致时比较器 fail closed，防止伪造分数或换评分尺冒充 agent 改进。相关纵向、history、memory、runtime、结构化 agent、调度与 CLI/Web 回归 202 项通过。
  - agent architecture manifest v2 曾纳入路径无关的完整 `tradingagents/**/*.py` 摘要和白名单决策配置；首跑前复核发现该范围会因 scheduler、CLI、报表或 evaluation 展示等非决策运维修改切碎长期 cohort。v3 现仅摘要 agents、graph、dataflows、LLM clients，以及影响请求、配置、时间审计和纵向上下文的 canonical runtime 模块；prompt、schema、validator、数据或决策实现变化仍会拆分 cohort，而纯运维修复不再改变 agent identity。摘要继续排除绝对路径、backend URL 与凭据。
  - 连续日频的 5-session outcome 会共享市场交易日，原先仅用 IID Student-t 标准误会低估架构 delta 的不确定性。配对门禁现按 ticker 与真实 entry/exit 窗口执行最多 `horizon - 1` 阶的 Bartlett/Newey-West 校正，并确定性取 IID 与 overlap-adjusted 标准误中的较大值；输出保留两种估计、lag、实际重叠 pair 数与不确定性等效样本量，Student-t 临界值也按向下取整的等效样本量选取。强正自相关回归样本在 IID 下会错误越过 `0.002` 门槛，校正后会 fail closed；相关纵向、history、memory、runtime、结构化 agent、调度与 CLI/Web 回归 206 项通过。
  - 配对实验原先按配置固定先跑 baseline，首个 run 会补齐同 symbol/date 的 OHLCV 磁盘缓存，使固定后跑的 challenger 获得虚假 runtime/vendor 成本优势。scheduler 现只按此前所有 arm 均完成的 run pair 数轮换同组 arm，失败或缺失半对不推进轮换；日志显式输出计划执行位次。History 查询保留权威 run start/finish timestamp，严格配对默认排除缺时间戳或启动间隔超过 3600 秒的跨时段结果；比较器分别聚合 baseline-first/challenger-first 成本并标记最终可评估样本的顺序是否 counterbalanced，防止不平衡缓存顺序被报告为架构降本。相关纵向、history、memory、runtime、结构化 agent、调度与 CLI/Web 回归 208 项通过。

### 第三阶段：核心研究能力（8–10）

- [ ] **8. 仓位引擎与交易校验器解耦**
  - `PositionSizingEngine` 负责固定风险、ATR 风险、波动率目标、分数凯利、账户权益和最大名义敞口下的建议仓位。
  - `TradePlanValidator` 独立重算并执行组合损失、集中度、购买力和账户限制硬门禁；LLM 不能提高服务端限制。

- [ ] **9. Longbridge 前瞻研究数据域**
  - 接入 `consensus`、`forecast_eps`、`finance_calendar`、`institution_rating`、`filings`、`short_positions` 和 `short_trades`。
  - 建立包含 `as_of`、发布日期、事件日期、标的、币种、期间、稳定 `source_id` 和 vendor `call_id` 的统一模型与 validator。
  - 验证后分别提供给 Fundamentals、News、Bull/Bear 和 Risk Agent；当前快照不得泄漏到历史运行。

- [ ] **10. 跨市场 Session Engine**
  - 使用权威交易日历建模交易所时区、DST、节假日、半日市和 `pre|regular|post` session。
  - 分别保存 `market_date`、`observed_at`、`published_at` 和 `available_at`；盘前盘后数据不得覆盖规范日 K。
  - A/H/ADR、汇率、换股比例和产业链映射只生成可审计只读证据；lead-lag 必须验证历史稳定性、流动性、点差、成本和可转换性，不得描述为无风险套利。

### 第四阶段：高复杂度扩展（11–16）

- [ ] **11. 空头与衍生品交易校验**
  - 新增显式 `side=long|short|flat`；Sell/Underweight 只代表减仓，不得隐式开空。
  - 空头股票验证 `target < entry < stop`；期权独立建模权利金、行权价、到期日、乘数、IV、Greeks 和非线性损益。

- [ ] **12. Longbridge 只读账户风险输入**
  - 以最小 OAuth 权限读取余额、持仓、保证金、购买力和汇率，并作为服务端风险政策输入。
  - 不向分析 Agent 暴露下单、撤单、改单、DCA、提醒或 Watchlist 写操作。

- [ ] **13. Longbridge 基本面与持仓拥挤增强**
  - 逐项审计并接入业务分部、估值历史/同行、股东/基金持仓、内部人交易、资金流、交易统计、市场温度和异动。
  - 每项必须基于真实 schema 单独建立 adapter、模型和 validator，禁止依据工具描述批量生成。

- [ ] **14. Longbridge 独立宏观 vendor**
  - 将 `macrodata` 与宏观事件日历注册为独立 vendor，映射到 `MacroSeries`。
  - 校验单位、观察期、发布日期和 cutoff；不得隐藏在 FRED 或其他 vendor 内部。

- [ ] **15. 独立 Reviewer 模型**
  - 可选 `review-model` 只读取不可变 execution evidence，输出带 event/vendor/source 引用的结构化 findings。
  - Reviewer 不得修改历史、直接关闭 finding 或决定 gate 通过；仍需人工确认和确定性验证。

- [ ] **16. 衍生品数据与选股能力**
  - option chain、IV、Greeks 必须等待第 11 项风险模型完成。
  - screener、rank、top movers 必须等待独立 universe/选股阶段，不直接塞入现有单标的 Agent 工具集。

### 暂缓议题：最低优先级（17）

- [ ] **17. 运行上下文压缩（暂缓）**
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
- [x] StockTwits 当前 symbol stream 已作为独立 `stocktwits_browser` vendor 接入默认 Sentiment 路径；无状态 Playwright/系统 Chrome 只读取 endpoint 原始 JSON，不保存 cookie、不抓取 HTML。原始消息直接映射 `SocialFeed`，经日期、去重、垃圾内容、标的、来源与 `information_cutoff` validator 后才渲染为 `untrusted_data`，所有尝试写入 run-scoped ledger；不支持快照的 `point_in_time` 运行 fail closed。
  - 完成证据：NVDA 公共 JSON live probe 返回 30 条消息；结构化 adapter、validator、路由审计、历史时点关闭、Sentiment 预取与 Web 配置迁移均有针对性测试。Playwright 复用系统 `google-chrome`/`chromium`，不要求浏览器 cookie。
- [x] OHLCV 采用 `OHLCVBatch` 写入契约、日期/OHLC 硬校验、原子缓存替换及 JSONL 溯源；盘中或日期漂移数据不能冒充规范日 K。
- [x] 技术指标统一预热窗口和三年 calculation start；默认 Westock/stockstats，Longbridge MCP 为验证后 fallback。
- [x] run-scoped vendor ledger 按 `run_id + call_id + attempt` 追加保存；审计落盘失败时禁止生成可执行报告。
- [x] Longbridge 个股新闻使用 `longbridge_mcp → longbridge`，全球新闻使用 CLI 结构化搜索；MCP `news_search` 的 epoch 时间问题修复前不注册为全球新闻来源。
- [x] 财务 MCP/CLI 原始 JSON 直接映射 `FinancialMetric`，完成跨报表勾稽、期间一致性及 ROE/ROA/TTM EPS/PE/净现金/EV-EBITDA 的确定性计算。
  - 2026-07-17 真实连续运行发现 reconciliation 把 `get_fundamentals(ticker, curr_date)` 的第二参误读为 `freq`，会让历史截止日不进入三张子报表 validator，并因不同 cache key 重复抓取；现已按方法 contract 归一化签名，并以 `run_id + ticker + freq + curr_date + vendor implementation` 做有界跨线程 singleflight。并发测试证明四个逻辑工具只执行一次四表抓取且保留 3 条独立 cache-hit audit；同输入 live run `97b21b3475a54dccb41e5cd135f68b9b` 中每种财务方法从 5 条 attempt 降为 2 条，总 vendor attempt 从 49 降为 41，最终 `validated` 且自动 review 无 P0。财务/vendor/runtime 针对性测试 64 项通过。

### 决策与安全门禁

- [x] 可信 ATR、Close、market date 和 vendor `call_id` 由 verified snapshot 注入；LLM 不能提供权威风控输入。
- [x] Buy/Overweight 交易计划结构化，收益风险比、ATR 距离和组合损失由代码重算；重复失败进入 `REVIEW_REQUIRED`。
  - 完成证据：Research Manager 的非权威计划在 Trader 边界前确定性清除入场、止损、目标、期权和仓位数字；Trader schema 移除未经验证的自由文本 `position_sizing`，可执行数字只能进入服务器 validator 覆盖的专用字段。Trader 现在从 server-side state 读取可信 close/ATR 与风险上限作为生成约束，但最终仍由同一 validator 独立复算；Trader/Portfolio 的 schema、首轮 prompt 和 retry 统一使用可机械判断的无数字 prose 协议，PM 维持多头时只能复制已验证 Trader structured fields。否定动作标题规范化只消除 detector 假阳性，真实条件减仓反例仍命中。结构化决策与 runtime/Web 针对性回归共 133 项通过；本轮组合回归 153 项通过；MiniMax-M3 live 运行 `0c3c7612b154454eaaad37595fd0da98` 以 `decision_status=validated` 完成且自动工程 review 无 P0。
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
