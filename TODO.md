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
- [x] Graph 硬门禁：ToolNode 不吞数据异常；失败运行不生成报告或 `run_completed`。
- [x] Tool 参数纠错：模型生成的参数 Schema 错误返回一次结构化 `ToolMessage` 供 LLM 修正；重复错误及 vendor/数据异常仍触发 Graph 硬门禁。
- [x] 技术指标确定性窗口：按指标预热 K 线需求统一扩展所有 vendor 的请求窗口，并区分输入历史与预热后有效输出点数。
- [x] OHLCV 缓存日期修复：显式迁移股票日 K 的日期漂移副本；读取不清理数据，写入边界执行日期/OHLCV 硬校验并原子替换缓存文件。
- [x] OHLCV 写入溯源：Longbridge MCP/CLI 与 Westock adapter 统一构造 `OHLCVBatch`，缓存拒绝裸 DataFrame，并以 JSONL sidecar 记录原始时间戳、时区语义、vendor、adapter 版本和批次 ID。
- [x] 技术指标计算起点统一：Longbridge Pine 与 Westock/stockstats 使用相同的三年 calculation_start；Pine 输出按权威 OHLCV 最新交易日校验，服务端 quant 数据滞后时自动 fallback。
- [x] 运行级 vendor 审计：新增按 run/call/attempt 追加且不可覆盖的 fallback 调用账本与查询 API；审计落盘失败时禁止继续生成可执行报告。
- [x] 交易计划确定性门禁：Buy/Overweight 的价格、ATR、仓位与最大风险必须结构化；收益风险比、ATR 倍数和组合损失由代码计算，重复校验失败降级为 `Hold / REVIEW_REQUIRED`。
- [ ] 空头与衍生品交易校验：新增显式 `side=long|short|flat` 和 `validate_short_trade_plan`，不得从 Sell/Underweight 推断开空；期权（含 Put）使用独立的权利金、行权价、到期日、乘数与 Greeks 风险模型。
- [ ] 仓位引擎解耦：将 `PositionSizingEngine`（固定风险、ATR 风险、波动率目标、分数凯利、账户权益、最大名义敞口）与 `TradePlanValidator` 分层；仓位引擎生成建议仓位，验证器统一执行组合风险、集中度和账户限制硬门禁。
- [ ] 可信市场输入绑定：ATR、最新 Close、market date 与 vendor `call_id` 由 verified market snapshot 注入交易校验器，不再允许 LLM 自行填写或转抄权威风控输入。
- [x] Runtime Agent 状态机：累积 graph snapshot 不得导致已完成 Agent 重新进入运行态；团队交接状态完整且报告事件去重。
- [x] X/Twitter 舆情：Bird 只读结构化 adapter、统一 SocialPost 模型、日期截止/去重/垃圾推广校验、独立 `social_data` vendor 路由与 Web 配置。
- [x] Web 舆情分类：新闻与社交数据分卡展示，Reddit、StockTwits 与 X/Twitter 统一归入“社交动态舆情”，后端仍保持 `news_data` / `social_data` 边界。
- [x] Web 刷新性能：本地托管 Markdown renderer、移除 Google Fonts 外网阻塞，并将开发热加载范围限制到源码目录。
- [x] Reddit 社交配置：在 `social_data` 中提供独立开关，旧浏览器配置自动迁移为启用，并让开关实际控制 Sentiment Analyst 抓取。
- [x] Web 配置归属：客户端仅保留 UI language；报告、模型、推理和数据 Vendor 配置迁移到服务端原子持久化，并兼容旧 localStorage 一次性迁移。
- [ ] Runtime 状态：记录失败的数据域、vendor 尝试轨迹和具体校验原因。

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
