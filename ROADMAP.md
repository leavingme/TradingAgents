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
  - 当前证据：repo-native scheduler、systemd unit、NVDA 正式配置和运维文档已实现；用户级 timer 已 `enable --now`，每 15 分钟检查，正式 oneshot 在未到时段时以 `not_due`/exit 0 完成。canonical 默认已统一为 `minimax-cn` + `MiniMax-M3`，修复 skill worker 请求错误模型的问题；runtime 现会在调用入口没有 stats callback 时自动安装 canonical `StatsCallbackHandler`，因此 timer 与 skill 的无人值守 run 在成功或失败终态前都强制保存 LLM/tool/token 最终快照。新增五轮同输入 NVDA 工程审计，依次发现并修复 Trader prose 纠错不确定、非多头否定标题假阳性、可信行情/服务端风险约束未进入 Trader 生成上下文、Portfolio schema 与 prose 门禁冲突；最终 run `0c3c7612b154454eaaad37595fd0da98` 以 `decision_status=validated`、`data_status=degraded` 完成，Trader/Portfolio 均首轮通过，自动 review 无 P0。调度、history、runtime、Web、CLI、结构化 agent、社交 vendor、纵向评估和 OHLCV provenance 相关 277 项通过；本轮安全边界相关 153 项通过，前端模块/语法检查通过；Providers 桌面与精确 390×844 视口均无横向 overflow。首次实际收盘后触发已发生；关闭仍需修复版本的下一次自然运行及首个真实 5-session 结算证据。
  - 2026-07-17 首跑前凭据审计只读取 expiry 而未输出 token：仓库根目录 MCP token 为 mode 0600，过期时间 2026-07-18 23:56 CST，晚于 04:30 首跑约 19 小时。该独立 Agent Auth bearer 当前没有可安全使用的 `client_id`，因此运行时到期后按既定规则抛 `MCPAuthError`；第一 fallback Longbridge CLI 0.24.0 的独立 OAuth 状态实测为 `valid`，`longbridge check --format json` 对 CN/Global 端点均连通且 session token 有效，后续自然运行不会因 MCP bearer 到期而中断整条数据链。
  - 首跑前 systemd 生效属性审计确认用户 manager 默认 `DefaultTimeoutStartUSec=90s`，但仓库与实际安装的 service 完全一致并显式设置 `Type=oneshot`、`TimeoutStartSec=infinity`，生效的 `RuntimeMaxUSec=infinity`；5–10 分钟 canonical 分析不会被默认启动超时终止。timer 保持 15 分钟周期、`Persistent=true` 和最多 30 秒随机延迟，仓库回归锁定这些恢复与长运行约束；相关完整门禁 209 项通过。
  - `Persistent=true` 过去只保证错过的 timer wake-up 会补触发，但 scheduler 仍按恢复当天的 weekday/time 判定；主机若从周五收盘前停到周末，周末补触发会返回 `not_due`，周五最新完整交易日永久漏跑。due 窗口现绑定最新完整 market-data date：周末或下一交易日收盘前可补跑最新一个配置工作日，并继续以 symbol + analysis date + architecture version 幂等；不遍历更早日期、不伪造历史 `point_in_time`，结果用 `schedule_trigger=latest_completed_date_catch_up` 与正常窗口区分。周六首次恢复执行周五、第二次只返回 `already_recorded` 的确定性回归已覆盖；2026-07-19 周日使用正式等价 schedule + 隔离 SQLite 的 dry-run 选择 NVDA `2026-07-17`、返回 catch-up trigger，且生产 fingerprint 保持 `05e8d1eec366af4ec4a379cca31ea0c6a08954099d81e37a550877a3624cfeb9`。同次审计移除了 pre-runtime scheduler JSON 对异常正文的持久化，只保留 `error_type`，sentinel URL/credential 回归证明不会进入 journal。相关调度/日期/OHLCV/runtime/history/Web/纵向/Agent/operator/i18n 回归 354 项、前端模块、编译、语法和 diff 检查通过；真实 systemd 恢复态证据仍待下一次可控恢复窗口。
  - scheduler 以前会把 canonical runtime 正常返回的 `review_required` 和 `unavailable` 都打印成 `completed`，其中无决策的 `unavailable` 还会让 systemd 以 0 退出。状态现确定性映射为 `validated → completed`、`review_required → review_required`、`unavailable → unavailable`；后者与最终 `attempts_exhausted` 返回非零，`retry_wait` 不重复制造失败。SQLite、重试决策、journal 与服务退出语义不再互相矛盾；相关完整门禁 213 项通过。
  - scheduler dry-run 现构造与正式执行相同的有效 runtime config，输出 analysts、深度、语言、模型、vendor、推理设置、纵向模式、计划顺序以及安全 canonical manifest/fingerprint；不创建历史、不调用 LLM/vendor，也不输出 backend URL、凭据、secret 环境值或绝对路径。首跑时点预演已确认 NVDA `2026-07-17` 为 `would_run`，使用 4 个 analysts、Shallow=1、Chinese、`minimax-cn/MiniMax-M3`、默认完整 vendor 链、live 模式与 `research_and_portfolio`，正式数据库不会错误拦截；MCP expiry fail-closed、错误净化与 canonical credential status 加入 dataflows 摘要后，当前 manifest v4 预期 fingerprint 为 `9386a3abb773eab583a5fb97e2fe7269b2cd4c981715b1df197bd14670115ff5`，脱敏扫描未发现绝对工作区路径或 secret key 名。
  - 2026-07-18 04:30 CST 首个自然 timer run `daily-NVDA-2026-07-17.2-20260717-e22ba560` 准时读取 `2026-07-17` 完整日 K，后续周期均 `already_recorded`，证明收盘时点、幂等与长时 oneshot 生效。该 run 的 Trader 结构化计划有效，但 Portfolio Manager 两次把执行数字复制到 prose，终态正确 fail closed 为 `review_required/NO_DECISION`，没有进入 evaluation pending。修复后同输入 remediation `b6443aa3695340429bae07e5f203a55f` 以 `validated` 完成；多头 prose 只删除命中的冗余执行片段并显式渲染 `Prose Safety Normalization`，Entry/Stop/Target/position 仍仅由结构化字段、可信 close/ATR 与服务端风险政策复算，净化后无定性论据仍 fail closed。remediation 自动 review 无 P0，19 次 LLM、35 次 tool、427431 input/73047 output tokens；高上下文成本继续作为 P1，不以正确性修复掩盖。
  - 沙箱内 remediation 的 DNS 失败暴露 Alpha Vantage `requests` 异常会把带 `apikey` 的 PreparedRequest URL 写入进程日志；网络边界现丢弃原异常文本并只传播固定 `/query` 标签、可选 HTTP status 与异常类的 `VendorUnavailableError`，fallback 语义不变。sentinel secret 的直接异常、router warning 与 ledger 扫描均不得出现 secret、参数名或 URL；观测到的凭据应按泄露事件轮换，代码和复盘产物不保存原值。
  - 首跑前结果时间轴审计先发现旧实现把 `analysis_date` 当日收盘价作为 entry；继续审计又确认仅要求 entry 晚于 analysis date 仍不足以覆盖“旧日期 + live 当前信息”或跨日长运行。现按每个原始 run 的 `decision_as_of` 转换到标的交易所时区，使用决策市场日之后第一个共同收盘价入场，再持有 5 个共同交易时段；History Store 交叉验证 UTC 决策时刻、时区、entry cutoff，并拒绝 `entry_date <= cutoff`，同时反查 validated terminal event 绑定 ticker/date/rating/decision time/architecture identity，防止上层或外部调用伪造 evaluation。待结算集合改由 SQLite 中 validated 且缺 evaluation 的 run 权威驱动，不再依赖可能缺失/去重/提前完成的 Markdown pending。`analysis_date` 现仅表示请求截止日，实际最后验证交易日只从结构化 OHLCV snapshot 写入独立 `market_data_date`；验证前保持未知，且不得晚于请求日期。run、terminal event、evaluation 与架构配对均使用该实际身份。`measurement_version` 独立于评分版本持久化，`decision-close-v1`、`next-common-close-v1` 与新 `post-decision-day-close-v1` rollup/比较 cohort fail-closed 隔离，纵向注入 schema 已升级到 v8。

- [ ] **7. 连续多日评估与 agent 架构实验门禁**
  - `decision_evaluations` 以原始 run 为主键保存架构版本、固定 horizon、rating、benchmark、raw/benchmark/alpha return、方向命中、确定性 score、计量版本、评分版本与 Hold band；不得只依赖 Markdown 反思，也不得把不同计量/评分口径混入同一架构 cohort。
  - 提供按架构版本、配置 fingerprint 和 horizon 的 sample count、hit rate、平均 return/alpha/score，以及 runtime/LLM/tool/token 成本与各自覆盖数聚合；LLM/tool/token 还必须按 canonical Agent 归因，工具上下文体积必须按 canonical tool 归因，并保留覆盖数、均值、严格配对差值及必要的执行顺序分层，同时保留 CLI/API 查询；同名但不同实际配置不得混入同一 rollup。
  - 架构 challenger 至少满足样本门槛；顺序实盘 cohort 受 regime 混杂，即使 point estimate 更好也只能 `review_required`，无配对 shadow 证据不得自动晋升或改写 prompt/agent 拓扑。
  - 当前证据：结构化表、确定性评分、fingerprint-scoped rollup、CLI 与 `/api/evaluations` 已实现，API 可用成对 baseline/challenger 参数直接查询比较结果；每条结果强制保存实际 `market_data_date`、decision timestamp/timezone/cutoff、entry/exit 日期、标的/基准四个收盘价和四个逐交易日 OHLCV stable source ID，旧 range-only provenance 不能冒充可审计结果。已结算结果查询从同一 SQLite 关联 run 起止时间与最终 stats 快照，operator-facing rollup 对 runtime、LLM/tool calls、input/output tokens 同时输出均值和覆盖数，并按 12 个 canonical Agent（未知元数据收敛到 `Unattributed`）输出 LLM/tool/token 覆盖数与均值；配对 shadow 输出总成本及逐 Agent 的 `challenger_minus_baseline` 覆盖数、差值、平均降幅和 Student-t 95% 区间，缺失成本不会冒充零成本或改变收益门禁。工程 review 会从真实 terminal stats 列出 input-token 最高的三个 Agent，替代只能看到四个初始 Analyst 聚合成本的粗粒度证据。canonical runtime 已从 SQLite 构造 cutoff-safe v8 固定 schema JSON，统一注入 Research Manager 与 Portfolio Manager，不再依赖 LLM Markdown 反思；逐条上下文明确扫描/截断计数、历史分析 data-status、input-evidence 与 pre-treatment agent-state 完整性，同标的架构 rollup 使用截止时点前扫描到的完整同标的 cohort，不再把最近样本截断或跨标的结果混入均值，运行成本字段及逐 Agent 成本都不会进入投资决策上下文。cutoff 与同/跨标的范围已下推到 SQLite 的排序/LIMIT 之前，新写入评估时间规范为 UTC，旧偏移时间按真实时刻排序，避免未来或跨标的样本挤掉历史时点已存在的证据。每个 run 保存有效 agent/model/topology manifest 与 SHA-256 fingerprint；每条 evaluation 另从 immutable vendor ledger 生成 analysis-input-evidence/v1 fingerprint，绑定规范化参数、fallback 状态、结果 hash 与观察范围但排除 call ID/延迟/时间戳噪声。当前 RM-context 实验还在 terminal event 固化 treatment 前的 `research-manager-pre-context-input/v1` 指纹，绑定 instrument context 与完整 debate history，但排除纵向上下文 treatment 自身。比较器拒绝同版本混杂配置，只接受 vendor evidence、pre-treatment agent state 与非空 `market_data_date` 都完整且相同，并且 measurement/scoring policy、ticker/date/horizon、entry/exit、四个收盘价、benchmark/raw/alpha return 以及四个 stable source ID 均一致的成对 shadow；vendor 输入漂移计入 `evidence_mismatches_excluded`，上游 LLM 输出漂移计入 `architecture_input_mismatches_excluded`，均不得归因于 agent。该输入 schema 只覆盖当前 Research Manager 分叉；更早的架构分叉仍需专用 schema 或共享 snapshot/replay。小样本 95% score-delta 下界使用 Student-t 临界值而非正态近似，并显式统计排除样本，任何结果仍需人工复核。默认禁用的 PM-only baseline / RM+PM challenger 模板已提供，未在无预算授权下开启。真实成本审计已将财务底层 attempts 20→8；跨表 derived metrics 不再在 IS/BS/CF 三份工具结果重复，财务 LLM renderer 改为无信息损失的紧凑 JSON，等待下一次自然调度 run 测量 token 变化。逐 Agent 成本新增门禁 90 项通过；runtime stats 现在还按有界 canonical 工具与 Agent 记录调用数、输入/输出字符数和错误计数，未知名统一折叠为 `Unattributed`，且不保存参数、结果、错误正文或 hash。高上下文工程 finding 会同时列出输出字符最多的三个工具，让下一自然 run 可直接判断 News、财务或指标证据谁在扩大上下文；该 operator-only 指标不进入纵向 Agent 输入和 architecture fingerprint。关闭仍需累积至少一个真实 5-session 结果，并在用户批准成本后积累配对 shadow 样本。
  - 逐 Agent 成本归因收尾后的针对性门禁 91 项、扩展回归 347 项、Python 编译和前端语法检查均通过；该改动只增加 operator-facing 统计与评估证据，没有修改决策 prompt、Agent 拓扑或默认 schedule。
  - 架构比较现额外生成 `architecture-optimization-assessment/v1`：实验完整性、收益证据和成本证据分别判定，列出 baseline input-token 最高的三个 Agent，并只返回继续收集、修复 pair、保留 baseline 或人工复核建议，`automatic_mutation_allowed=false`。收益门禁即使通过，只要 exclusion 多于有效 pair 仍判定 integrity degraded 并要求修复，避免选择偏差。CLI/API 现支持同时指定 baseline/challenger fingerprint 来查询实现变更前后的独立 cohort；只指定一臂或完全不指定但标签内混合 fingerprint 继续 fail closed。比较政策在零样本分支也完整返回，不会把真实的 20-pair 门槛显示成 0。相关核心回归 66 项、扩展门禁 350 项、Python 编译及前端语法检查均通过，默认单臂 schedule 与决策链不变。
  - 运行中 Web API 热加载验证已返回新 schema、固定 20-pair/0.002 改善政策、`not_observed` 完整性与 `continue_sample_collection`，正式库仍为 0 evaluation/0 pending；该纯评估控制面提交当时的 canonical dry-run fingerprint 保持 `aad8eeaa5998020076078ffbf0d7d0b03bde112ef60f33f463c0574cf1022af8`，证明展示改动本身没有切碎生产决策 cohort；后续 dataflows 安全修复按预期形成新 fingerprint。
  - 单架构 rollup 现提供 operator-only 的 `architecture-outcome-assessment/v2`：score 分布/负值风险、raw/alpha 中位数、rating 分层表现，以及按 ticker 与真实 entry/exit 窗口做 Bartlett/Newey-West 重叠校正的 mean-score 95% 区间。少于 20 个样本或 temporal window 不完整会分别标记为 `insufficient_samples` / `incomplete_temporal_evidence`。v2 新增 `rolling-outcome-monitoring/v1`，按 ticker 与唯一 analysis date 展示最近 5/10/20 个结果相对前一等长窗口的 score、alpha、方向命中与负分率变化；同日重跑/remediation 全部作为歧义日期排除，避免重复加权。该滚动层明确为 exposure-overlapping、regime-confounded 的描述性监控，`causal_claim_allowed=false`、`automatic_architecture_mutation_allowed=false`。整个 assessment 与成本统计一起从 `include_runtime_costs=False` 的 Agent 纵向上下文排除，不会在 fingerprint 不变时改变生产 Agent 输入；针对性纵向/Web 门禁 47 项、扩展架构/调度/runtime/history/vendor/CLI/Web 门禁 443 项、Python 编译、前端语法与 diff 检查均通过。临时 DB 中模拟下一正式窗口的 canonical dry-run 仍为 `would_run`，fingerprint 保持 `9386a3abb773eab583a5fb97e2fe7269b2cd4c981715b1df197bd14670115ff5`。
  - 连续结果不再只存在于 CLI/API：WebUI 新增 `#evaluations` 深链接，直接读取 `/api/evaluations`，按标的展示已结算/待结算/cohort 数量、fingerprint-scoped 总体结果、5/10/20 滚动表格，以及双架构实验完整性、收益、成本和建议动作。动态状态均随 UI language 本地化；浏览器端没有评分重算或架构写入口。零样本正式库与合成双 cohort/滚动/比较响应均通过真实 headless Chrome 验证；桌面 1440 和精确 390×844 视口的 `scrollWidth == clientWidth`，业务 UI 无横向 overflow，滚动明细表只在自身容器内横向滚动；中文模式实测标题、导航与 `insufficient_samples` 状态分别显示为中文。前端模块测试、前端语法检查、针对性纵向/Web/i18n 门禁 61 项与扩展门禁 457 项全部通过。
  - 单一生产架构现额外生成 operator-only 的 `single-architecture-optimization-assessment/v1`，把“结果怎么样”推进到“何时可以设计优化实验”：依次门禁 20 个成熟结果、完整 temporal uncertainty、analysis evidence 与 pre-treatment input audit，再汇总近期 5/10/20 负向变化、输入 Token 最高的三个 Agent 和均分最弱 rating。建议动作只能是继续积累、修复时间/输入证据、调查近期/持续退化或设计受控 challenger；即使就绪也固定 `automatic_mutation_allowed=false`、`paired_shadow_authorization_required=true`。该诊断只在 operator rollup 生成，`include_runtime_costs=False` 的 Agent 上下文继续完全排除；针对性纵向/Web/i18n 门禁 62 项、扩展架构/调度/runtime/history/vendor/CLI/Web 门禁 458 项及前端模块/语法检查均通过。合成成熟 cohort 的中文 WebUI 实测显示“可以设计受控实验 / 调查近期退化”，精确 390×844 视口仍无横向 overflow；下一正式窗口 dry-run fingerprint 保持 `9386a3abb773eab583a5fb97e2fe7269b2cd4c981715b1df197bd14670115ff5`，确认纯 operator 诊断没有改变生产 Agent cohort。
  - 每个完成 Graph 的每日调度 live run 现在会在 canonical decision 已形成后追加 `architecture-evaluation-status/v2`，自动固化同标的评估扫描数、pending/cohort 数，以及该 run 的 architecture version/fingerprint 所对应的 outcome status、实验就绪度和建议动作；v2 还从最终 stats 固化 input token 最高的三个 Agent 与输出字符最多的三个工具，旧 run 没有逐工具数据时明确标记 `not_observed/agent_only`。行情仍为 pending 时不生成。事件不包含逐条投资结果、收益、价格、Prompt、完整成本明细或工具正文，不进入 Agent state，也不改写已经形成的决策；SQLite/Web 历史回放只显示紧凑且本地化的 operator 状态，失败响应只保留内部异常类型。这样无人值守 timer 的每个真实决策 run 都能证明当时累积证据和优化诊断是什么，不再依赖事后打开 API 猜测；实现位于 architecture fingerprint 排除的调度层，纯可观测性变更不会拆分生产 cohort。v1 快照/纵向/history/Web 针对性门禁 85 项、扩展架构/调度/runtime/vendor/CLI/Web 门禁 460 项、Python 编译、前端模块与语法检查均通过；v2 的新增验证证据见后续上下文 attribution 条目。
  - 首个自然 run 与 remediation 的 Shallow 输入仍分别达到 38.6 万和 42.7 万 token。调用链审计确认 Market Analyst 同时拥有原始 `get_stock_data`、批量指标和 verified snapshot，三年 OHLCV 会作为 4.6 万字符的冗余工具结果进入对话；相同缓存上的批量 8 指标与 snapshot 合计约 1.5 万字符，仍保留完整底层计算窗口、最新 OHLCV、200 SMA 等指标和最近 30 个收盘。生产 Market Analyst 工具面现统一为后两项，原始 OHLCV 仍由 canonical router/统一验证/缓存/ledger 在底层供计算使用，不再直接复制给 LLM；Web prompt catalog 与 ToolNode 共用同一工具清单并由回归锁定。该改变发生在正式库 0 evaluation/0 pending 时，不混入既有有效 cohort；针对性门禁 96 项、扩展架构/调度/runtime/Agent/vendor/CLI/Web 门禁 476 项和 Python 编译均通过，下一正式窗口 dry-run 为 `would_run`，新 fingerprint `e488203a4481ea2fe423738abc48c2b905ce5610b06f83c98219700f7bd158ea`。下一自然运行仍需用逐 Agent terminal stats 验证真实 token 降幅和结论证据完整性。
  - Fundamentals Analyst 的四工具结果虽已统一验证且跨表 derived metrics 不再重复，但真实 NVDA quarterly 响应仍把 661 条 verified metric 及重复 JSON 字段拆成约 16.5 万字符。新增的 `reconciled-financial-evidence/v1` 在完整 IS/BS/CF 进入统一模型、时点 validator 和 reconciliation 之后，按 series/observation columns 无损折叠重复元数据；真实响应保留 180/225/256 条三表记录与 4 条确定性 derived metric，缩至约 4.2 万字符（减少 74.3%）。Fundamentals Analyst、ToolNode 与 Web prompt catalog 统一只暴露这个组合工具，且 LLM schema 强制要求 `curr_date`；底层四类 vendor subcall、fallback、缓存、unverified fact count 与 ledger 均未移除，缺任一报表不会冒充完整证据，并把整个组合能力交给下一 vendor 原子 fallback。针对性门禁 112 项、扩展架构/调度/runtime/Agent/vendor/CLI/Web 门禁 485 项通过，1 项显式 live provider probe 按环境跳过；Python 编译、前端模块/语法与 diff 检查通过。下一正式窗口 dry-run 为 `would_run`，新 fingerprint `05e8d1eec366af4ec4a379cca31ea0c6a08954099d81e37a550877a3624cfeb9`；下一自然运行仍需验证真实 Agent token 与报告完整性。
  - 上下文压缩后的 attribution 已补齐：canonical runtime stats 对固定白名单工具记录调用数、输入/输出字符数、错误数及其 Agent 分布，未知工具或 Agent 只进入 `Unattributed`；递归/超大 payload 有界处理，错误正文、参数、结果正文和 hash 均不持久化。工程复盘的 P1 高上下文 finding 会同时列出 input token 最高的三个 Agent 与输出字符最多的三个工具。针对性与扩展门禁共 147 项通过，Python 编译、前端语法与 diff 检查通过；按正式 schedule/Web 配置重建 manifest 后 fingerprint 仍为 `05e8d1eec366af4ec4a379cca31ea0c6a08954099d81e37a550877a3624cfeb9`，证明纯 operator telemetry 未切分生产 cohort。下一自然 run 将提供首次真实逐工具体积基线。
  - attribution 已接入无人值守闭环：scheduler 复用单个 `architecture_evaluation_status` 写入，将最终 stats 规范化为 `context-cost-diagnostic/v1`，只保留 top-3 Agent/tool 数字行；未知名称、非法/超界数值、嵌套 by-agent 明细及任意正文均丢弃。Web 在终态前到达的 stats 行和历史架构快照中都显示相同工具输出热点，旧 run 无数据时保持兼容的 `not_observed`。扩展后端回归 162 项、前端模块测试、Python 编译、前端语法和 diff 检查通过；正式配置重建 fingerprint 继续为 `05e8d1eec366af4ec4a379cca31ea0c6a08954099d81e37a550877a3624cfeb9`。热加载后的 Web 与 daily timer 均为 active，页面已返回新静态资源版本，正式评估库仍为 0 evaluation/0 pending；等待下一自然 run 生成首个真实 v2 快照。
  - 多日成本评估现不再止于 Agent/token：CLI 与 `/api/evaluations` 在纯 operator 边界按 evaluation `run_id` 有界回读最终 stats，规范化为逐工具 `tool_context`，不修改 History Store 行；cohort rollup 输出每个工具调用数、输入/输出字符数和错误数的覆盖数与均值。`single-architecture-optimization-assessment/v2` 列出输出最大的三个工具；`architecture-optimization-assessment/v2` 和 paired comparison 输出 baseline/challenger 均值、严格配对差值、95% 区间及 baseline-first/challenger-first 分层，避免把缓存先后优势误判为工具压缩收益；challenger 新增而 baseline 不存在的工具也会进入热点但显示 paired coverage=0，不会被差值伪装为零。Agent 纵向 `include_runtime_costs=False` 路径的回归明确证明不含 tool context 或 optimization assessment。相关 operator/纵向/history/memory/runtime/调度/Web/架构/Agent 回归 227 项、前端模块、Python 编译、前端语法和 diff 检查通过；空正式库的 CLI/API 均返回 0 evaluation/0 pending，Web 与 timer active，静态资源版本已更新，生产 fingerprint 仍为 `05e8d1eec366af4ec4a379cca31ea0c6a08954099d81e37a550877a3624cfeb9`。
  - 成本优化不再被 5-session outcome 成熟期阻塞：`architecture-run-cost-rollup/v1` 独立扫描最多 5000 个最新终态 run，按架构 fingerprint 聚合日期范围、运行/决策状态、stats 覆盖、runtime/LLM/tool/token 均值及 Agent/工具热点；completed、review_required、unavailable、failed、cancelled 都保留各自状态，运行中和行情等待不混入。CLI/API/Web 明确分开“已结算结果”“待结算结果”和“成本运行样本”；只有成本而无 outcome 的 cohort 可以立即显示，但不会进入收益比较选择器或降低 20 outcome/5-session/paired gate。正式 API 已立即恢复旧自然 run 的一个 cost-only cohort：`review_required=1`、stats coverage `1/1`、runtime `657.89s`、19 LLM/32 tool、385658 input/80053 output token；它没有新 by-Agent/by-tool 字段，因此热点保持缺失而非伪造。Web/timer 均 active；精确 390×844 Chrome 实测渲染 1 张成本卡，`scrollWidth=clientWidth=390`、无横向 overflow，移动截图确认结果/待结算/架构/成本指标按纵向卡片展示。相关 operator/纵向/history/memory/runtime/调度/Web/架构/Agent 回归 228 项、前端模块、Python 编译、前端语法与 diff 检查通过；生产 fingerprint 保持 `05e8d1eec366af4ec4a379cca31ea0c6a08954099d81e37a550877a3624cfeb9`。
  - 即时成本时间轴升级为 `architecture-run-cost-rollup/v2`：cohort 现在按 ticker + architecture version + fingerprint 隔离，避免无 ticker 的 CLI 查询把同一架构下不同标的成本混合；`rolling-run-cost-monitoring/v1` 将同一分析日的全部终态尝试先相加，再比较最近与前一组 5/10/20 个分析日的日均 input token/runtime，因此失败重试和 remediation 成本不会丢失或伪造额外日期。`run-cost-assessment/v1` 对缺失 stats/token、历史不足、终态可靠性和最近至少 10% 且 10000 token 的上升分别给出保守 operator 建议；所有分支固定禁止收益结论、自动架构修改并保持 `promotion_gate_effect=none`。Web 同时展示成本诊断、建议动作和三个滚动窗口，cost-only cohort 继续不能进入收益比较。跨标的隔离、同日重试求和、窗口比较及缺失 token fail-closed 已有后端与前端回归覆盖。正式 CLI/API 均返回 NVDA 单样本、单分析日、三个 `insufficient_history` 窗口和 `continue_cost_collection`，0 outcome/0 pending 未被成本证据提升；Web 与 daily timer 保持 active。精确 390×844 Chrome 审计为 `scrollWidth=clientWidth=390`、1 张成本卡且无业务横向 overflow，长截图确认三窗口位于自身滚动容器。相关架构/调度/runtime/history/Web/Agent/operator/stats 回归 230 项、前端模块与语法检查通过；正式配置重建 fingerprint 保持 `05e8d1eec366af4ec4a379cca31ea0c6a08954099d81e37a550877a3624cfeb9`，证明 operator 诊断未切分生产决策 cohort。
  - 评估控制面过去只展示已有 run/outcome cohort，因此正式页面会突出旧自然 run 的 `5891…` 成本，却完全看不到等待首次自然验证的当前 `05e8…` 生产架构，存在把历史成本误当 active baseline 的风险。新增 `scheduled-architecture-identity/v1` 与 inventory/observation：复用 daily scheduler 的 effective request/config/manifest 构造且与 dry-run fingerprint 回归相等，不访问行情/vendor/LLM、不写历史、不返回 backend URL；CLI/API 按 ticker + version + fingerprint 绑定终态 run 和 mature outcome，确定性区分 `awaiting_first_active_run`、`active_run_requires_attention`、`awaiting_outcome_maturity`、`active_outcome_observed`。Web 把没有 active match 的旧 cohort 明确标为 historical，active 零样本卡仍不会进入收益比较。配置缺失、禁用、跨 ticker、非法 fingerprint 及含敏感正文的内部错误均有 fail-closed 回归。使用显式临时 SQLite、仓库正式 NVDA schedule 和缺失 Web 配置的零外部调用 CLI 验证返回 active `2026-07-17.2`、fingerprint `05e8d1eec366af4ec4a379cca31ea0c6a08954099d81e37a550877a3624cfeb9`、`awaiting_first_active_run`、0 terminal/0 outcome 且 paired shadow 仍需授权；相关架构/调度/runtime/history/Web/Agent/operator/stats 回归 241 项、前端模块、编译、语法与 diff 检查通过。正式 Web 运行态与移动布局证据待沙箱外执行额度恢复后补记。
  - active identity 现同时进入 `daily_analysis.py status`，不再要求恰好处于 `would_run` 窗口才能看到下一次自然运行的 fingerprint。真实 CLI 子进程回归使用临时 schedule、缺失 Web 配置和隔离 SQLite，锁定 `status` 返回安全 identity、`evaluate` 返回 `awaiting_first_active_run`，两条路径均无 vendor/LLM 调用、无路径/backend 泄露。2026-07-19 的安全凭据状态已确认 MCP bearer 为 `expired/configured=false`；到期前 Longbridge CLI 健康证据不冒充到期后网络证据，post-expiry 结构化能力探测仍待沙箱外额度恢复。相关调度/active identity/架构/纵向/runtime/history/Web/Agent/operator/stats 回归 243 项、前端模块、编译、语法与 diff 检查通过；正式 schedule 等价配置继续重建 fingerprint `05e8d1eec366af4ec4a379cca31ea0c6a08954099d81e37a550877a3624cfeb9`。该纯调度/控制面改动不进入 agent architecture digest。
  - active 架构新增 `architecture-measurement-continuity/v1` operator 诊断，复用 canonical 20-outcome 最低门槛，依次给出收集首次稳定自然运行、先修复异常运行、等待结果成熟、继续积累 outcome 或进入人工评估的建议。在达到最低样本前建议保持决策 fingerprint 稳定，防止连续改动让当前 `05e8…` cohort 永远没有自然基线；安全与正确性修复明确覆盖连续性建议，自动架构修改和未授权 paired shadow 仍固定关闭。Web 只为精确 active identity 展示连续性状态、建议、结果进度和安全修复覆盖规则，历史 cohort 不继承该建议。正式等价 schedule + 隔离 SQLite 的 CLI `evaluate` 返回 `awaiting_initial_run`、0/20 outcome 进度及安全覆盖规则，fingerprint 仍为 `05e8d1eec366af4ec4a379cca31ea0c6a08954099d81e37a550877a3624cfeb9`；相关后端/CLI/Web/纵向/Agent/operator/i18n 回归 324 项、前端模块、Python/JS 语法、编译和 diff 检查通过。正式 Web 运行态、移动布局及 post-expiry Longbridge CLI 能力证据仍待沙箱外执行额度恢复后补记。
  - 2026-07-18 下一自然窗口前审计确认 MCP bearer 将于 23:56 CST 到期。独立 Longbridge CLI `check` 的 CN/Global 连通与 session 均健康；在临时 DB/进程内模拟过期 MCP 后，真实 NVDA OHLCV 一次 CLI fallback 得到 `2026-07-17` 完整日 K，财务 IS/BS/CF/fundamentals 各调用一次并完成 reconciliation，个股新闻返回 20 条结构化 `NewsFeed`。代码审计同时修复 expiry 缺失/坏格式/无时区时“假定有效”的 fail-open，并丢弃 HTTP reason/body、网络 reason、JSON-RPC message、tool-error content 与服务端工具清单等外部错误正文，避免其进入日志、ledger 或 Agent；固定安全错误仍由 router 类型化 fallback。相关针对性门禁 40 项、扩展回归 391 项及 Python 编译通过；该决策数据路径修复按预期把 fingerprint 更新为 `1b4fd04c02f7ee026bae19556220c3d33afbb8db9d194796745d4dcd37b94158`。
  - Web `/api/config/env-status` 不再把存在但过期/无效的 MCP token 文件显示为 configured；canonical `get_token_status()` 只返回 `valid|missing|invalid|expired`、布尔可用性和安全 UTC expiry，不返回 token、绝对路径或外部错误正文。到期前运行态应显示 valid，到期后自动显示 expired，同时 scheduler 继续按已验证的 CLI fallback 运行。MCP/Web/vendor 针对性门禁 95 项通过。
  - 运行中 Web API 已确认当前返回 `valid/configured=true` 和安全 UTC expiry，未返回 credential material；加入同模块的 canonical status 后最终 dry-run fingerprint 为 `9386a3abb773eab583a5fb97e2fe7269b2cd4c981715b1df197bd14670115ff5`。
  - MCP expiry/error/status 收尾后的扩展门禁 396 项、Python 编译、前端语法和 diff 检查均通过；真实能力探测和测试均使用临时数据库，未写入正式运行历史。
  - pre-treatment、实际 `market_data_date`、有界失败恢复与 paired-cost 授权门禁加入后的架构、纵向、history、runtime、结构化 agent、调度、CLI 与 Web 回归共 236 项通过；`market_data_status` / terminal event 现在也会通过 History Store 的确定性日期门禁重建 `runs.market_data_date`，避免仅依赖调用侧先写字段。正式 SQLite 只读审计此前确认所需 schema 已迁移，当前仍为 1 个旧失败 run、0 个 evaluation。
  - 首次自然运行前的失败恢复审计发现 scheduler 过去只从 SQLite run 数量执行每日 attempt 上限；若异常发生在 canonical runtime 注册 run 之前，日志虽失败但不会消耗 attempt，可能形成 15 分钟一次的无界重试。现在此路径写入 `pre-runtime-failure` 失败占位并纳入相同 retry budget，且不会覆盖 canonical runtime 已经持久化的失败证据。
  - 首跑前继续发现供应商在收盘后延迟提供最终日 K 时，runtime 虽记录较早的实际 `market_data_date`，仍会调用 LLM，并让 requested date 幂等键永久阻止当日数据就绪后的重跑。每日入口现强制 exact-market-date：较早快照只生成零 LLM 调用的 `market_data_pending` 审计 run，每 15 分钟重试且不占普通失败次数；默认 240 分钟仍未就绪则 `market_data_unavailable`/exit 1，禁止旧日 K 形成可执行决策。runtime 与 scheduler 针对性测试 38 项通过，扩展到架构、纵向、history、Web、结构化 agent、行情 provenance 与 vendor 的回归 253 项及前端模块测试通过；正式 schedule 沙箱外状态检查确认新窗口生效，未到时段 dry-run 保持 `not_due`。
  - readiness 门禁的二次成本审计发现旧结果结算位于门禁之前；主 graph stream 虽未开始，兼容 Markdown reflection 在已有成熟结果时仍可能调用 LLM。结构化快照 probe 现先应用有效 vendor 配置并在 `TradingAgentsGraph`/LLM client 构造之前完成；陈旧快照路径不会结算历史、创建 graph 或初始化 LLM。测试用会立即报错的 Graph 构造器证明该分支完全未触达，并同时验证 probe 使用 per-run vendor override、最终 stats 全零；另一路相等日期测试证明数据就绪后仍进入完整 validated 流程。
  - 配对架构实验的预算约束现由 schema 强制：同标的双 arm 只有在共享 schedule/analysts、恰好隔离 `portfolio_only` 与 `research_and_portfolio` treatment，并显式设置 `paired_shadow_authorized=true` 时才能启用。仅把默认禁用模板改为 `enabled=true` 会 fail closed，避免误操作使无人值守成本近似翻倍或用不可比较的上游配置浪费样本。
  - 纵向评估 CLI 与 `/api/evaluations` 现暴露 SQLite 权威的 pending count/list，包括 decision timestamp、请求/实际数据日期与架构身份，能区分正常等待 5-session 成熟和评估链路无记录。审计同时发现 history/vendor verification 在 home 不可写时会静默使用工作区 `.tradingagents/runs.db`，把 19 条旧测试型记录误显示为正式 pending；该回退已删除，默认固定 `~/.tradingagents/runs.db`，只有 `TRADINGAGENTS_DB` 可覆盖且不可访问时 fail closed。沙箱外 CLI 与运行中 Web API 均确认正式库为 0 evaluation、0 pending；标准门禁 235 项与 vendor verification 9 项通过。
  - 架构比较器过去在每臂达到 20 个结果前提前返回，付费实验可能累计 40 次运行后才暴露 vendor evidence 或 pre-treatment state 全部漂移。现在零/单臂阶段先返回 `sample_progress` / `missing_architectures`，首个双臂 evaluation 再计算有效 pair 数和所有 exclusion counters；样本不足仍保持 `insufficient_data` / `passes_paired_gate=false`，让 operator 能尽早发现半对失败或停止不可归因实验，而不降低晋级门槛。
  - 2026-07-17 22:30 CST 的真实 systemd timer 新进程已加载 canonical DB fail-closed 版本，正常返回 NVDA `not_due`、exit 0，未读取工作区回退历史、未创建 run、未调用 LLM/vendor；这补足了 CLI/Web 之外的无人值守入口运行态证据。
  - 同输入 remediation 还证明旧 pending outcome 的 SPY 结算调用会与当前决策输入共享 run ledger，使 attempt 从自然首跑的 47 增至 100，并污染 `data_status` 与 `analysis-input-evidence`。vendor attempt 现持久化 `purpose=analysis|outcome_evaluation`：两类调用仍在同一追加式审计链可查，旧行迁移默认为 analysis，但 run summary、数据状态和架构输入证据只使用 analysis rows；purpose context 在每个历史结果测量后恢复，防止评估成本/失败被误归因为当前 agent 输入。
  - 2026-07-17 23:00 CST 的下一次自然 systemd timer 已加载 exact-market-date 提交 `e2c3e8f`，继续以 NVDA `not_due`、exit 0 在约 2.5 秒内结束；随后正式 SQLite 仍为 0 evaluation、0 pending，证明新 readiness 状态机进入真实无人值守入口且未在非运行时段制造 run 或成本。
  - 2026-07-17 23:15 CST 的自然 timer 已加载 readiness-before-LLM 提交 `22c0b98` 及测试提交 `484e092`，NVDA 继续 `not_due`、exit 0，约 2.5 秒结束；首跑前最终门禁版本已进入真实 systemd 新进程。
  - 连续结果利用链现在为每个 run 生成持久化 `longitudinal_context_status`：只记录 canonical v8 schema、模式/cutoff、同/跨标的 scanned/included count 与同标的架构 rollup 数，不复制投资内容或运行成本。非 canonical JSON、非法 count 或 included 大于 scanned 会在 agent state 构造前 fail closed；Web SSE 同步支持该事件。新增端到端回归用真实临时 SQLite 创建 validated pending run，在当前 live run 内通过 canonical resolver 写入 evaluation，验证 `evaluated_by_run_id` 指向当前 run；随后重读的 v8 context、Agent `past_context`、流式 status event 与持久化 event 均立即包含该 outcome 和 score，证明当天刚成熟的结果无需再等一轮。`point_in_time` 继续完全跳过事后结算。相关调度/日期/OHLCV/runtime/history/Web/纵向/Agent/operator/i18n 回归 355 项、前端模块、语法与 diff 检查通过。该轮只补证据与规则，没有改动 `analysis_runner.py` 或决策路径，避免在首次自然基线前无必要地切换当前 `05e8…` fingerprint。
  - 继续审计发现一条损坏的 validated pending run 会在 Agent 构造前抛异常，导致以后每个自然 live run 都被同一历史“毒丸”阻断。现在缺失 validated terminal、decision、可识别 5 档 rating、合法 analysis/market-data date 或带时区 decision timestamp 的记录会按 run + horizon 写入 `decision_evaluation_issues`，只保留白名单 issue code 与生命周期时间；该条结果保持 fail closed、不会评分或进入纵向上下文，但同轮其他成熟结果和当天新决策继续执行。正常等待成熟与 `blocked_invalid_history` 已在 CLI、`/api/evaluations`、Web 和 `architecture-evaluation-status/v3` 中分开，系统性 SQLite/validator 故障仍会中止而不被静默吞掉。真实临时 SQLite 端到端回归同时放入一条坏历史和一条当天成熟结果，证明坏记录被隔离、好结果同轮写入 v8 context、当前 run 仍以 validated 完成；扩展架构/调度/runtime/history/Web/纵向/Agent/operator/i18n 门禁 357 项、前端模块、Python 编译、前端语法与 diff 检查通过。该安全/正确性修复优先于首次自然基线的 fingerprint 连续性；正式等价 NVDA schedule + 隔离 SQLite 的零 vendor/LLM `status` 与 `run --dry-run` 均重建出新 active fingerprint `f0e0a925ae071a12312b44449ee9f59ceea516a49ddde7ed2ac4d12683260cca`，dry-run 以 `latest_completed_date_catch_up` 选择 `2026-07-17` 且输出完整生产请求身份；旧 `05e8…` cohort 不会与其混合，下一自然运行需以新 identity 建立首个稳定基线。
  - 并发审计继续发现 `INSERT OR IGNORE` 只能阻止第二条 evaluation 入库，两个 live 进程仍会重复抓取 outcome 行情、重复反思，且竞争者可能在 owner 提交前构造缺少已成熟结果的 Agent 上下文。现在每个 run + horizon 必须先获取 SQLite `decision_evaluation_claims` 原子租约：只有 owner 能调用 vendor、持久化 evaluation 和更新兼容视图；竞争者以 `OutcomeSettlementInProgressError` 在 Agent 前 fail closed。owner 在成功、未成熟和 Python 异常路径均释放租约，非 owner 不能释放；硬退出租约一小时后允许原子接管。CLI/API/Web 与 `architecture-evaluation-status/v4` 区分 `settlement_in_progress` 并显示有界归属/expiry。两个独立 store、两个线程同步争抢的回归严格得到一个 `claimed`、一个 `busy` 和单一 SQLite owner；租约续占、非 owner 释放、过期接管、Graph busy/未成熟路径均有确定性覆盖。扩展架构/调度/runtime/history/Web/纵向/Agent/operator/i18n 门禁 361 项、前端模块、Python 编译、前端语法与 diff 检查通过；正式等价 NVDA schedule + 隔离 SQLite 的零 vendor/LLM `status` 和 `run --dry-run` 均重建出新 active fingerprint `1fc0e374fa4ae59462a02565320c581d069decdee2fd821b044098c1b1a12572`，dry-run 以 `latest_completed_date_catch_up` 选择 `2026-07-17`，下一自然运行需以该 identity 建立稳定基线。
  - 失败语义审计发现 `_fetch_returns` 把“共同交易日尚不足 5-session”与空 OHLCV、vendor/router 异常、字段/来源证明失败全部吞成 `None` 并记录原始异常正文；坏掉的结算会无限伪装为普通等待，当前 Agent 还可能在缺少本应成熟结果时继续。现在 canonical resolver 使用 strict 模式：只有两腿结构化 OHLCV 有效但共同收盘点不足 entry + 5 个后续 session 才保持普通 pending；数据不可用或 deterministic validator/provenance 失败会写入 `decision_evaluation_failures` 的白名单 `ohlcv_unavailable|outcome_validation_failed`、累计次数和安全 UTC 时间，随后以 `OutcomeSettlementDataError` 在 Agent 前 fail closed。CLI/API/Web 与 `architecture-evaluation-status/v5` 显示 `retryable_settlement_failure` / failed count；数据恢复或确认未成熟会关闭失败生命周期。带 token URL 的异常回归证明日志仅保留 failure code/type，未复制正文；失败持久化、重复计数、类型变化重置、恢复解除、租约释放及真实 CLI 三种 pending 状态均有覆盖。扩展门禁 365 项、前端模块、Python 编译、前端语法与 diff 检查通过；正式等价 NVDA schedule + 隔离 SQLite 的零 vendor/LLM `status` 与 `run --dry-run` 均重建出 active fingerprint `3f18822e6cdb4a3b96ef6e844db46dd4d195fc243b01b38be0e7662c0a98a022`，dry-run 继续以 `latest_completed_date_catch_up` 选择 `2026-07-17`，下一自然运行需以该 identity 建立稳定基线。
  - scheduler 衔接审计发现 canonical error event 虽保留 `OutcomeSettlementDataError` / `OutcomeSettlementInProgressError`，`run_analysis_once()` 却把类型压成通用 `RuntimeError`，导致零 LLM 的历史结算故障按普通 `failed` 消耗当天两次分析预算；数据稍后恢复也可能漏掉整天决策。runtime 现通过只含内部类名的 `AnalysisExecutionError` 保留安全类型，SQLite/API/Web 将两类故障记为 `outcome_settlement_pending`；scheduler 使用独立的 15 分钟重试与 240 分钟最大等待窗口，不计普通分析次数，恢复后仍允许同 market-data date 完整运行，超时则转为 `outcome_settlement_unavailable`/exit 1。错误类型经过 ASCII identifier 门禁，scheduler JSON 不复制 provider 正文；零 LLM、无 Agent status、两种错误、等待、恢复、普通次数为 1 仍成功、超时 fail-closed、配置边界、History/Web 状态与 operator 成本均有确定性覆盖。扩展核心门禁 328 项通过；全仓离线门禁在排除明确依赖外网的 DeepSeek live 用例及未隔离 Longbridge-first 环境的旧 symbol-normalization 用例后为 915 项、69 个 subtest 通过、3 项依赖缺失/显式 live probe 跳过。未排除运行只出现上述 2 个环境失败。前端模块、语法、Python 编译与 diff 检查通过；正式 NVDA schedule + 正式 Web 配置 + 隔离 SQLite 的零 vendor/LLM `status` 与 `run --dry-run` 一致得到 active fingerprint `812d66f662c0b1765bbd7e9ff22c7e1d8e7d7ba3f555d039de2764a1170a34ec`，dry-run 以 `latest_completed_date_catch_up` 选择 `2026-07-17` 且未创建历史 run。
  - manifest v3 虽排除了纯 evaluation 展示代码，却没有显式绑定会进入后续 agent 历史上下文的评分/计量政策；改变 Hold band 或 horizon 可能在同一 fingerprint 下改变校准语义。v4 现绑定 `post-decision-day-close-v1`、`alpha-exposure-v1`、Hold band `0.02` 与默认 5-session horizon，并将 horizon 默认值统一为 evaluation、settlement、pending CLI/API 与比较器共享的单一常量。
  - 运行中 `/api/evaluations` 的零样本比较已验证：正式 NVDA baseline/challenger 返回 `sample_progress=0:0`、门槛 20、`sufficient=false`，并明确列出两条 `missing_architectures`；实验尚未授权或启动时不会伪造 pair 诊断。
  - 2026-07-17 22:45 CST 的 systemd timer 独立新进程已实际加载 manifest v4 与统一 evaluation horizon 依赖，正常返回 NVDA `not_due`、exit 0；CLI help、生产 schedule status、Web evaluation API 与 timer 四个正式入口均未出现循环导入或数据库路径分叉。

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
  - 2026-07-18 自然运行证明提示词重试仍不能可靠阻止 MiniMax 把已验证执行数字复制回多头 prose。Portfolio 渲染边界现确定性删除命中的冗余执行片段、重新扫描并留下审计标记；不从 prose 恢复或修改任何数值，净化后无定性证据继续拒绝授权。同输入 live remediation `b6443aa3695340429bae07e5f203a55f` 真实通过并由代码重新渲染所有交易指标。
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
