# AGENTS.md — TradingAgents Fork（TauricResearch/TradingAgents v0.3.0）

本文档记录这个 fork 的日常操作约定。它相当于 Hermes 工作区
AGENTS.md 的项目级版本；做任何非平凡操作前都要先读。

## 仓库

- **上游**：`https://github.com/TauricResearch/TradingAgents`（`tauric` remote，仅 fetch）
- **Fork**：`https://github.com/leavingme/TradingAgents`（`origin` remote，fetch + push 目标）
- **工作区根目录**：`/data/workspace/TradingAgents`
- **分支**：`main`
- **版本**：v0.3.0（`85946c2 chore: release v0.3.0`）+ 15 个 fork 本地提交

## 工作优先级与路线图

- 顶层工作顺序固定为：**安全与正确性 → 运行可靠性/成本 → 核心研究能力 → 高复杂度扩展**。这是依次通过的门禁，不是混合成主观总分。
- 安全与正确性优先处理默认启用、fail-open、前视、过期、不可追溯或可能形成错误可执行决策的链路；已启用能力高于尚未开放的未来能力。
- 运行可靠性/成本处理失败状态、恢复、审计证据、并发与锁竞争，以及 token、串行调用、重复加载、延迟和写放大。
- 核心研究能力只在现有路径正确、稳定、成本可控后扩展；需要新权限、新风险模型、新交易语义或 universe 阶段的能力归入高复杂度扩展。
- 新能力必须先完成原始 schema 审计、统一领域模型、确定性 validator、失败语义和必要风险门禁，再允许进入默认链路。
- 优先级调整必须依据可复现证据、影响范围、发生概率、可逆性、默认启用状态和依赖关系。任务关闭必须同时具备实现、针对性测试、必要运行态证据和文档更新。
- `ROADMAP.md` 是任务状态、当前优先级、验收标准和中长期路线的唯一权威来源；不要另建或恢复并行的 `TODO.md` / `PLAN.md`。

## 环境

### Python 和 venv

- **Python**：3.12.3（系统二进制位于 `/usr/bin/python3.12`）
- **venv 路径**：`/data/workspace/TradingAgents/venv`
- **不要使用 `pip install -e .`** — 这个工作区有特殊处理。
  运行任何 pip 命令前，先阅读下面的 **venv 陷阱**。

### 控制台入口

- `venv/bin/tradingagents` — Typer CLI（交互式 questionary 菜单）
- `python -m cli.main` — 替代入口
- `run_smoke.py` — 非交互 smoke runner（批处理/自动化优先使用）
- `venv/bin/tradingagents web --host 127.0.0.1 --port 8765 --reload` — 最小 FastAPI Web API 开发服务（默认开发启动方式；热加载只监听 `cli/`、`tradingagents/`、`web/`）
- 执行 `pip install -e .` 后，入口脚本会根据 `pyproject.toml` 的
  `[project.scripts]` 自动重新生成；当前指向
  `tradingagents._cli_entry:app`（不是直接指向 `cli.main:app` —
  详见 PYTHONPATH 部分）。

### TradingAgents skill

- 当前用户级 skill 位于 `/home/ubuntu/.agents/skills/trading-agents/`；其中
  `analyze.py` 通过用户级 systemd transient service 启动后台分析，任务元数据
  持久化到 `~/.tradingagents/jobs/`。
- skill worker 必须调用 `tradingagents.runtime.run_analysis_once()`，让 CLI、Web
  和 skill 共用 canonical runtime 与 `~/.tradingagents/runs.db`；禁止直接调用
  `TradingAgentsGraph.propagate()` 绕过事件和历史持久化。
- `/home/ubuntu/.openclaw/skills/trading-agents/` 和旧 OpenClaw 工作区路径已经
  退休。不得在 skill 脚本、任务命令、日志或元数据中保存 API key、cookie、token
  或 webhook；凭据只从 server-side env / `.env` 加载。

### WebUI 约定

- WebUI 应该镜像 CLI 的启动分析流程，但不要把主运行页塞满。Run 页面只保留
  ticker/date/asset/analyst 选择和 start/cancel 控件。
- 运行配置放在 Settings 页面（`#settings`）：UI language、report output
  language、research depth、LLM provider、quick/deep models，以及可选
  backend URL。
- UI language 和 report language 是两件事。UI language 只本地化 WebUI；
  report language 会作为 `output_language` 传给分析运行时。
- Research depth 必须使用和 CLI 一致的三档用户可见选项：
  `Shallow` → `1`，`Medium` → `3`，`Deep` → `5`。
- Agent 进度应遵循 CLI 的 Team / Agent / Status 表格分组：
  Analyst Team、Research Team、Trading Team、Risk Management 和
  Portfolio Management。`in_progress` 必须有明显的动画状态。
- 历史 run 选择由 URL hash 表达。选中的 run 使用 `#run=<run_id>`，
  Settings 页面使用 `#settings`，这样刷新或深链接能恢复同一个视图。
- 前端静态资源 URL 在 UI 改动后要带 query string 版本号，避免本地开发时
  浏览器缓存旧 CSS/JS。
- SSE stream 应该立即推送队列事件，并用 heartbeat comment 保持长时间运行
  的分析连接。浏览器端应允许 EventSource 自动重连，不要在第一次 `onerror`
  时关闭 stream。
- CLI 的启动分析流程是 Web parity 的权威清单。变更 Web 启动配置时，要逐项
  对照 `cli.main.get_user_selections()` 的 Step 1–8：ticker、date、
  output language、analysts、research depth、provider/backend、
  quick/deep models、provider-specific thinking/reasoning knobs。
- Report language 必须支持 CLI 的内置语言和 custom language。不要只做 UI
  language；UI language 只影响页面文案，`output_language` 才影响报告输出。
- API key 不要收集或保存到浏览器 localStorage。Web 只应显示服务端环境变量
  状态（`/api/config/env-status`），密钥仍由 server-side env / `.env` 管理。
- 浏览器 localStorage 只保存纯 UI 偏好（当前仅 UI language）。报告语言、研究深度、
  LLM/模型/推理参数、backend URL，以及数据能力 Vendor 顺序和启停状态统一通过
  `/api/config/web` 持久化到服务端 `~/.tradingagents/web_config.json`。旧版浏览器
  `settings/providers` localStorage 只允许做一次性迁移，迁移后必须删除。
- LLM/tool/token stats 属于 runtime 能力，不要让 Web 后端直接依赖 CLI 实现。
  `StatsCallbackHandler` 的 canonical 位置是 `tradingagents.runtime`；
  `cli.stats_handler` 只是兼容 re-export。
- tool context 体积统计只允许按有界的 canonical tool/Agent 名保存调用数、输入/输出
  字符数和错误计数；未知名称统一归入 `Unattributed`。不得保存参数、结果正文、错误
  正文或其 hash。它属于 operator 复盘证据，不得进入 Agent 纵向上下文或改变决策
  architecture fingerprint。
- 多日逐工具成本只允许在 CLI/API operator 查询边界按 `run_id` 回读最终 stats；最多
  处理 5000 行，必须复制而非改写 History Store 返回值。已结算 outcome rollup 与尚未
  结算的终态 run cost rollup 必须分开：后者可立即包含 completed/review_required/failed
  的成本与状态分布，但 cost-only cohort 不得进入收益比较或降低 5-session/配对晋级门槛。
  rollup/paired comparison 可公开覆盖数、均值、差值和执行顺序分层，但
  `include_runtime_costs=False` 的 Agent 纵向上下文必须完全排除 `tool_context` 与优化
  assessment。
- 未成熟 outcome 的运行成本 rollup 必须按 ticker、架构版本和 fingerprint 隔离；跨标的
  即使架构身份相同也不得混合。同一 analysis date 的重试/remediation 必须先汇总全部终态
  尝试的 token/runtime，再进入 5/10/20 分析日窗口，避免漏算重试成本或重复加权日期。
  stats/input-token 覆盖不完整时成本诊断必须 fail closed；成本趋势只允许生成 operator
  建议，固定不得形成收益结论、自动改动架构或影响 outcome/paired promotion gate。
- 历史 run 和刷新语义必须从 SQLite + persisted events 恢复。刷新页面后，已完成
  agent 仍应显示完成状态；运行中的任务应通过 SSE replay + live queue 继续呈现。
- 每个完成 Graph 的每日调度 live run 应在 canonical decision 已形成后追加
  `architecture_evaluation_status`，仅记录当前 architecture identity、扫描/待结算/cohort
  数量、实验就绪度、建议动作，以及最多三个 Agent/工具的有界数字成本热点。不得在该
  事件复制逐条投资结果、收益值、Prompt、完整成本明细或任何工具正文；它只作为调度/
  历史回放的 operator 证据，不得进入 Agent state 或改变决策。
- 分段报告应在每个 `report_section` 事件到达时立即可见，并能通过 report
  selector 切换，不要等最终 `run_completed` 才渲染全部报告。
- 服务商与底层能力配置页面使用 `#providers` 路由。前端应提供各个底层能力（OHLCV、技术指标、基本面、新闻舆情、宏观数据、预测市场）的优先级重排（生成以逗号分隔的优先级字符串，例如 `"longbridge_mcp, longbridge"`）和开关，且通过 `config_overrides.data_vendors` 将修改后的服务商优先级传递给后端运行。后端 `build_runtime_config` 应当对 `config_overrides` 进行嵌套深度合并以防止局部键覆盖整个 data_vendors 字典。
- 连续结果与架构优化页面使用 `#evaluations` 路由。页面只读取 `/api/evaluations` 的 SQLite 权威结果，展示已结算/待结算数量、fingerprint-scoped cohort、5/10/20 结果滚动窗口、单架构实验就绪诊断及配对收益/成本/完整性门禁；不得从 Markdown 报告重建绩效，不得在浏览器端自行计算晋级结论或自动修改 prompt、模型和 Agent 拓扑。
- 评估控制面必须把“下一次自然调度将运行的 active architecture”与历史 cohort 明确
  分开。active identity 必须复用 daily scheduler 的 effective request/config/manifest 构造，
  匹配覆盖时同时要求 ticker、architecture version 和 fingerprint；旧 fingerprint 不得因
  有成本或结果样本而显示成当前架构。identity 预览不得选择行情、调用 vendor/LLM、写入
  History Store 或返回 backend URL/凭据。schedule/config 不可用时只返回安全异常类型与
  空清单，不能让 `/api/evaluations` 猜测 active identity。
- active architecture 的测量连续性只作为 operator 建议：首次稳定自然运行前、运行异常
  修复前，以及达到 canonical 最低 outcome 样本数前，应保持决策架构身份稳定，避免连续
  改动使当前 cohort 永远无法形成基线。安全与正确性修复始终优先于连续性建议；该建议
  不得阻止修复，也不得授权自动修改 prompt、模型、拓扑或启用 paired shadow。
- 服务端 API 密钥及证书状态查询（`/api/config/env-status`）已拓展以兼容底层能力数据源（如 FRED, Alpha Vantage, Longbridge MCP 等）的状态展示。前端无需保存或输入 API Key，通过后端环境变量和本地文件存在性推断其可用性。
- Web API 非 loopback 绑定必须设置 `TRADINGAGENTS_WEB_AUTH_TOKEN`；正式入口会同时启用全 API bearer 认证。浏览器请求不得提交 `results_dir`/`report_dir`，backend URL 只能来自内置服务商端点或服务端 `TRADINGAGENTS_ALLOWED_BACKEND_URLS` 白名单。并发与每分钟启动上限分别由 `TRADINGAGENTS_WEB_MAX_ACTIVE_RUNS`（默认 2）和 `TRADINGAGENTS_WEB_RUN_RATE_LIMIT`（默认 10）控制。


### Web 服务和布局验证

- 启动 Web 服务时不要先在托管沙箱内运行 uvicorn；本环境的沙箱通常无法
  bind 本地端口。直接使用受批准的沙箱外命令启动，并且默认开启热加载，例如：
  `venv/bin/tradingagents web --host 127.0.0.1 --port 8765 --reload`。该入口会限制
  reload 目录，避免扫描 `venv/`、`results/` 和 `.git/`。
- 托管沙箱内可能无法 bind 本地端口，或 8765 被外部命名空间占用。`curl`
  失败不一定表示代码坏了；先看 uvicorn 日志是否是 `could not bind`。
- 如果 8765 不可用，不要杀未知进程。优先用临时端口（如 8766/8877/8878）
  做验证；需要本地 bind/浏览器截图时，用受批准的沙箱外命令。
- 长时间运行的 uvicorn tool session 可能在工具轮次结束时被清理。做截图验证时，
  更可靠的方式是在同一个 shell 里：启动临时 uvicorn、等待健康检查、执行
  headless Chrome 截图、再 kill 临时 server。
- **长期开发服务（2026-07-14 已配置）**：使用 user systemd 单元
  `~/.config/systemd/user/tradingagents-web.service` 托管默认 WebUI。该单元在
  `/data/workspace/TradingAgents` 中运行
  `venv/bin/tradingagents web --host 127.0.0.1 --port 8765 --reload`，通过
  `~/.zshrc` 加载服务端环境变量，设置 `Restart=always` / `RestartSec=3`，并已
  `enable --now`；用户 `ubuntu` 的 linger 为启用状态，因此退出登录或主机重启后
  仍可自动拉起。源码目录 `cli/`、`tradingagents/`、`web/` 的变更由 uvicorn
  热加载实时生效；不要再用长时 tool session 占用 8765。常用运维命令：
  `systemctl --user status tradingagents-web`、
  `systemctl --user restart tradingagents-web`、
  `journalctl --user -u tradingagents-web -f`。修改服务单元后必须执行
  `systemctl --user daemon-reload` 和 `systemctl --user restart tradingagents-web`。
- `chromium-browser` 在该环境可能只是 snap wrapper，无法使用；优先检查并使用
  `/usr/bin/google-chrome` 做 headless 截图。
- 移动端截图不能只靠肉眼。还要用浏览器读取
  `document.documentElement.scrollWidth/clientWidth`；只有业务 UI 无横向 overflow
  才算布局通过。固定背景光斑超出视口可以接受，因为不参与布局。
- 小屏 CSS 要特别注意 `fieldset` 的默认 `min-inline-size`，它会把 grid 撑出
  视口。对 form/grid/fieldset/action 区域显式设置 `min-width: 0` /
  `min-inline-size: 0`。
- 修改前端 CSS/JS 后必须 bump `index.html` 中静态资源 query string，否则容易
  被浏览器缓存误导，以为改动没有生效或旧问题仍存在。

### 关键环境变量

| Variable | Purpose | Where set |
|---|---|---|
| `OPENAI_API_KEY` | LLM（也作为所有 vendor 的 fallback，包括 `minimax-cn`） | `~/.zshrc` export |
| `OPENAI_BASE_URL` | LLM endpoint | `~/.zshrc` export |
| `MINIMAX_CN_API_KEY` | minimax（中国区） | `~/.zshrc` export |
| `MINIMAX_API_KEY` | minimax（Global） | `~/.zshrc` export |
| `.longbridge_mcp_token.json` | Longbridge API token（数据 vendor） | 仓库根目录 `.longbridge_mcp_token.json`（gitignored，mode 0600） |
| `AUTH_TOKEN` / `CT0` | Bird 只读 X/Twitter cookie 认证（社交舆情 vendor） | server-side env / browser cookie source；禁止写入配置或日志 |
| `TRADINGAGENTS_DB` | CLI、Web、runtime history 与 vendor 审计共用的 SQLite 路径；唯一受支持的数据库路径覆盖变量 | server-side env（未设置时使用 `~/.tradingagents/runs.db`） |
| `TRADINGAGENTS_REPORT_SECTION_THROTTLE_MS` | report section 按 run + section 合并更新的服务端节流窗口；默认 `500` ms，设为 `0` 仅用于诊断 | server-side env（通常无需设置） |
| `data_vendors.core_stock_apis` | 默认 `"longbridge_mcp, longbridge, westock"` | `default_config.py` |
| `llm_provider` | 默认 `"minimax-cn"` | `default_config.py` |
| `quick_think_llm` / `deep_think_llm` | 默认都是 `"MiniMax-M3"` | `default_config.py` |

## venv 陷阱（碰 pip 前先读）

### Shebang 漂移（2026-07-05 已修复）

venv 在 2026-04-01 工作区迁移时，从
`/home/ubuntu/.openclaw/workspace/TradingAgents/` 被搬到当前路径。迁移后，
所有 `venv/bin/pip*` 的 shebang 都硬编码了旧 `.openclaw` 路径，导致直接
调用 `pip` 失败。**2026-07-05 已修复**：用
`/usr/bin/python3.12 -m venv` 从头重建了 venv。所有 wrapper 现在都有正确的
shebang，不需要通过 `python -m` 间接调用。

如果 venv 以后再次漂移（例如搬到新主机），重建 venv，不要尝试手工修复
shebang。

### Vendor fallback chain

`data_vendors` 是**路由层 fallback 链**，不是单个 vendor。顺序很重要：

```
core_stock_apis    : "longbridge_mcp, longbridge, westock"
technical_indicators: "westock, longbridge_mcp"
fundamental_data   : "longbridge_mcp, longbridge, westock"
news_data          : "longbridge_mcp, longbridge, westock, duckduckgo, alpha_vantage"
```

`route_to_vendor()` 必须捕获 vendor-specific 异常
（`MCPAuthError`、`LongbridgeCLIError`、`AlphaVantageRateLimitError`），
并静默进入链上的下一个 vendor。加载失败并返回 `None` 的 vendor impl 也必须
跳过，绝不能 raise。这是硬规则。

### Vendor 方法签名（graph 会按这些调用）

新增 vendor 时，必须严格匹配以下签名，否则 graph 会抛 `TypeError`：

```
get_stock_data(symbol, start_date, end_date)
get_indicators(symbol, indicator, date, lookback_days)
get_fundamentals(symbol, curr_date=None)
get_income_statement(symbol, freq=None, curr_date=None)
get_balance_sheet(symbol, freq=None, curr_date=None)
get_cashflow(symbol, freq=None, curr_date=None)
```

**已退休 vendor**：保留 `<name>_legacy.py.bak` 文件。不要把某个 vendor 从
`VENDOR_METHODS` 里彻底删除；当 vendor-specific bug 出现时，需要旧实现作对比。

### Vendor 原始能力优先

- **以下各项均为硬规则，不是建议。** 新增或修改 vendor 时必须逐项满足，并由测试覆盖。
- 使用或新增 vendor 数据前，先审计接口原始响应能力、结构、字段元数据和信息完整度，再设计 adapter、统一领域模型和 validator；不要先沿用现有文本接口再补解析。
- vendor 原始响应为 JSON、表格或其他结构化数据时，adapter 必须直接转换为统一领域模型。禁止先压平成面向 LLM 的文本，再通过正则或字符串解析恢复结构。
- 统一处理顺序应为：`vendor 原始响应 → vendor-specific adapter → 统一领域模型 → deterministic validator → LLM renderer`。
- 面向 LLM 的 Markdown/文本只允许在验证通过后生成，不得作为数据层、fallback 层或 validator 的内部交换格式。
- 当 MCP 比 CLI 提供更完整的结构化字段、逐条序列或元数据时，默认优先 MCP；CLI 作为 MCP 不可用时的 fallback，但不得把信息较少的摘要伪装成与完整数据等价。
- 如果现有 vendor adapter 丢失原始接口已经提供的字段，应先修复 adapter 和统一模型，再编写依赖缺失字段的上层校验。
- vendor 实现只能调用自身接口和自身缓存，禁止导入或调用其他 vendor 形成内部 fallback。所有跨 vendor fallback 必须由 `route_to_vendor()` 按配置链统一控制。
- vendor 请求失败、认证失败、限流、无数据、字段缺失或能力不支持时必须抛出对应的类型化异常；禁止返回 `"Error ..."`、`"No data ..."`、空字符串、说明性 Markdown 或 `None` 冒充成功数据。
- vendor 只能返回其原始接口实际提供并可规范化的数据。禁止用 Web Search、新闻摘要、估算值、静态说明或低信息摘要替代请求的数据类型。
- 同一 vendor 内部的网络重试可以保留，但必须保持同一数据源、同一能力和同一语义；缓存命中也必须经过与在线响应相同的规范化和校验。
- 若某个 fallback 来源需要独立配置、可观测性或质量判断，必须注册为独立 vendor，不得隐藏在另一个 vendor 实现内部。
- 新闻、宏观和预测市场 vendor 必须返回 `NewsFeed` / `MacroSeries` / `PredictionMarketFeed` 结构化领域对象；发布时间、URL、标的/主题关联、观察期、单位、事件/市场 ID、带时区到期日、概率范围与稳定 `source_id` 在 router 层验证后才能渲染给 LLM。新闻必须包含非空正文或可用于研究的摘要，URL 规范化后去重，发布时间必须精确到时间并且不超过 `information_cutoff`；只有标题的结果不得冒充完整新闻证据。预测市场 `call_id` 由 router 绑定，所有 configured vendor attempt 必须写入 run-scoped ledger。DuckDuckGo 等不提供真实发布时间的结果不得用抓取时间冒充发布时间。
- FRED 宏观证据必须同时保留指标请求名、series ID/title、单位、频率、观察期、初次发布日期、查询 vintage、修订状态和稳定 `source_id`。历史时点必须查询对应 vintage；由于 FRED vintage 只有日期精度，带时区的日内 `information_cutoff` 统一使用截止日前一日 vintage，宁可少用截止日当天已经发布的数据，也不得泄漏当天稍后发布或修订的值。
- Longbridge 个股新闻默认优先使用 MCP `news`，CLI `news --format json` 为 fallback；全球新闻使用 CLI `news search --format json`。截至 2026-07-13，MCP `news_search` 原始响应会把 `time` 返回为 Unix epoch，修复前不得注册为已验证全球新闻来源。
- 新闻、社交和外部工具文本必须使用 `untrusted_data` JSON 数据消息传输，不得插入 system instruction；检测到的中英文指令行和控制令牌必须在进入后续辩论前清除。

## `_cli_entry.py` shim（调试 CLI 失败前先读）

`venv/bin/tradingagents`（console script）从 `tradingagents._cli_entry`
导入；它会在执行任何 `from cli.main import app` 之前修改 `sys.path`。这不是
可有可无的装饰 — 没有它，CLI 会静默失败。

### 原因

Hermes sandbox 启动子进程时会设置
`PYTHONPATH=/tmp/hermes_sandbox_xxx:/data/hermes/hermes-agent`。
`/data/hermes/hermes-agent/` 中有一个 Hermes 内部的单文件 `cli.py` 模块，
这会让 Python 把 `cli` 解析成一个*模块*（不是*包*）。随后
`from cli.main import app` 会失败：
`ModuleNotFoundError: No module named 'cli.main'; 'cli' is not a package`。

### shim 做了什么

1. 从 `sys.path` 中移除 `/data/hermes/hermes-agent`（只移除路径字符串，
   不动目录或目录里的文件）
2. 之后 `from cli.main import app` 会通过 editable finder 解析到
   TradingAgents 自己的 `cli/` 包

### shim 不做什么

- 不修改磁盘上的任何文件
- 不影响其他 Python 进程
- 不影响系统 Python 或其他 venv

### CLI 出问题时的诊断顺序

如果 `tradingagents --help` 失败，按下面顺序检查：

1. `echo $PYTHONPATH` — 从干净 shell 运行时，不应包含 `/data/hermes/hermes-agent`
2. `head -1 venv/bin/tradingagents` — 应该是
   `#!/data/workspace/TradingAgents/venv/bin/python3.12`
3. `cat venv/bin/tradingagents` — 应该从 `tradingagents._cli_entry` 导入，
   而不是从 `cli.main` 导入
4. `git status` — 确认 `tradingagents/_cli_entry.py` 和 `pyproject.toml`
   的 entry-point 改动已经提交并存在
5. `venv/bin/python3.12 -c "import tradingagents; print(tradingagents.__file__)"`
   — 应该输出 `/data/workspace/TradingAgents/tradingagents/__init__.py`

**shim 是 PYTHONPATH 冲突的真正修复。** 不要通过编辑 pip config、再次升级
pip 或删除 `.pth` 文件来解决；这些都是当初诊断过程中的误导方向。

## M3 reasoning round-trip（MiniMax-M3 细节）

`MinimaxChatOpenAI` client（位于
`tradingagents/llm_clients/openai_client.py`）需要**两个 hook 点**来支持
M3 的 Interleaved Thinking 功能：

- **接收侧**（`_create_chat_result`）：把服务端返回的 `reasoning_details[]`
  和 `reasoning_content` 放进 `AIMessage.additional_kwargs`
- **发送侧**（`_get_request_payload`）：当消息被 round-trip 到下一次请求时，
  把这些字段写回 outgoing wire message dict

这个模式参考 `langchain-deepseek==1.1.0`。两个 hook 都必须存在；只修一边会
破坏长链路 agent 任务（模型在多轮之间丢失 chain-of-thought）。

OpenAI SDK 2.x 会把 `extra_body` 自动 flatten 成顶层请求字段
（`reasoning_split: true` 可以直接工作），所以 wire-format 侧不需要自定义
client。真正会丢 `reasoning_details` 的是 langchain message-conversion 层，
这就是为什么 langchain 侧需要两个 hook。

## 运行 smoke test

验证完整 pipeline 的非交互方式：

```bash
cd /data/workspace/TradingAgents
venv/bin/python run_smoke.py NVDA 2026-07-05
```

- 后台运行（5–10 分钟）：使用 `background=true, notify_on_complete=true`
- 输出写到 stdout 和 `results/<SYMBOL>/...`（自 2026-07-05 起已 gitignored）
- exit code 0 表示 propagate 到达了 final decision
- 2026-07-05 的 smoke run（NVDA）：FINAL DECISION = `Hold`

## NVDA 工程闭环

- 涉及“运行分析后复盘并处理 P0”的工作统一使用 `scripts/engineering_cycle.py`，详细规范见 `docs/engineering-cycle.md`。
- 固定阶段为 `run → review → ack-review → P0 plan/implementation → resolve → verify → gate`。不得跳过全流程 review，也不得在 P0 未解决、缺少证据或验证早于修复时关闭循环。
- 每轮使用新的 `run_id`；原始 events/vendor ledger 来自 SQLite，生成的本地 cycle 产物位于 gitignored 的 `.tradingagents/engineering_cycles/<run_id>/`。需要长期追踪的 finding 必须同步到 `ROADMAP.md`。
- 默认基准标的是 NVDA，默认日期为最近已完成工作日，避免使用仍在形成的当日日 K；需要复现历史运行时显式传 `--date`。

## 分析时间轴语义

- `analysis_date` 表示调用方请求的日 K 截止日期；`market_data_date` 表示结构化 OHLCV 验证后实际使用的最近完整交易日，两者不得预先假定相等。例如周一美股盘前请求周一截止时，实际完整日 K 可以仍是周五，但周末至周一盘前的新闻、宏观和 Polymarket 实时信息仍可用于当前决策。
- 默认 `analysis_mode="live"`：新闻、宏观、社交和预测市场允许使用各自在运行调用时可获得的最新信息，最终 `run_completed.decision_as_of` 记录决策形成时刻。
- 历史回测或时点复现必须显式使用 `analysis_mode="point_in_time"` 并提供带时区的 `information_cutoff`；不支持历史快照的当前型 vendor 必须 fail closed，不得用运行时现值冒充历史证据。
- 必须分别保存和解释 `market_data_date`、`decision_as_of`、`information_cutoff` 与 vendor 自身的 `observed_at`/`published_at`。禁止仅因 `analysis_date` 早于当前自然日就关闭实时信息源。
- `market_data_date` 只能从通过 deterministic validator 的结构化 OHLCV 最新行确定；验证前必须保持未知，且不得晚于 `analysis_date`。run、terminal event、evaluation 和纵向上下文必须保存该实际日期；架构 paired comparison 必须要求两臂日期非空且相同。
- live 决策不得使用 `decision_as_of` 所在交易所本地日期当日或更早的收盘价作为可执行 entry 或结果计量起点，即使 `analysis_date` 更早。固定期限评估按原始 run 分别使用决策市场日之后第一个标的/基准共同收盘价入场，再到第 5 个后续共同收盘价结算；计量版本、决策时刻、交易所时区和 entry cutoff 必须持久化并隔离旧 cohort。SQLite 是待结算 run 的权威来源，不得依赖 Markdown pending 条目触发结算。
- 每日调度的 due 窗口绑定“最新完整 market-data date”而不是恢复进程当下的自然日。
  `Persistent=true` 在周末或下一交易日收盘前补触发时，必须允许补跑最新一个已完成且
  尚无同版本 run 的配置工作日；不得遍历更早日期或伪造历史 live 决策。相同 symbol、
  analysis date 和 architecture version 继续使用 SQLite 幂等与有界重试语义。
- 每日普通失败次数必须再按 active architecture fingerprint 隔离：同 version 下旧
  fingerprint 的 `failed|cancelled|unavailable` 不得耗尽新 fingerprint 的预算或延迟；
  但 `legacy-unspecified` / `pre-runtime-failure` 及 identity 预览失败必须保守计数。
  `completed|review_required` 仍跨 fingerprint 保持一日期一次决策，active run、最终日 K
  readiness 与 outcome settlement 状态也继续跨 fingerprint 生效，禁止用源码部署绕过
  幂等、并发或数据门禁。
- 无人值守 scheduler 的失败 JSON/journal 只能保留安全状态、run identity 和内部异常类型；
  不得序列化异常正文，因为 provider/backend 异常可能携带 URL、token 或请求参数。
- live runtime 必须在 market-data readiness 通过后、读取纵向上下文和构造 Agent state 前，
  先结算当前已经成熟的 SQLite pending outcomes；同轮新写入结果必须立即出现在 canonical
  longitudinal context。`point_in_time` 不得执行事后结算，未成熟结果继续保持 pending。
- 单条 validated 历史 run 若缺少终态决策、可识别 rating、合法 analysis/market-data date
  或带时区 decision timestamp，必须按 run + horizon 写入类型化
  `decision_evaluation_issues` 并保持 outcome fail closed；不得生成评分、进入纵向上下文，
  也不得让该历史“毒丸”阻断其他成熟结果或当天新分析。CLI/API/每日架构快照必须区分正常
  等待成熟与 `blocked_invalid_history`；只允许保存白名单 issue code，不得保存异常正文。
- 同一个 run + horizon 的 outcome 结算必须先获取 SQLite 原子租约。并发 live run 中只允许
  一个 owner 调用 vendor、写 evaluation 和兼容反思；其他 run 必须在构造 Agent 前以类型化
  `OutcomeSettlementInProgressError` fail closed，不得用尚未包含该成熟结果的旧上下文继续。
  租约固定有界并允许崩溃后接管，非 owner 不得释放；CLI/API/每日快照必须把活跃租约显示为
  `settlement_in_progress`，不得把它误报为普通等待或损坏历史。
- outcome resolver 只有在标的与基准均取得有效 OHLCV、但共同收盘点不足 entry + 完整
  horizon 时才能返回普通 pending。空数据、vendor/router 异常、字段/日期/数值/精确来源证明
  失败必须在 strict live 结算中写入白名单 `decision_evaluation_failures`，然后以类型化
  `OutcomeSettlementDataError` 在 Agent 前 fail closed；不得把这些故障压成 `None` 或记录
  外部异常正文。CLI/API/每日快照必须显示 `retryable_settlement_failure`、安全 failure code
  和累计次数；数据恢复或确认尚未成熟后关闭失败生命周期。
- 每日 scheduler 必须把 `OutcomeSettlementDataError` 与
  `OutcomeSettlementInProgressError` 保留为安全类型，并记录为独立的
  `outcome_settlement_pending` 零 LLM 探测；它们不得消耗普通
  `max_attempts_per_date`。默认每 15 分钟重试、首次等待 240 分钟后转为
  `outcome_settlement_unavailable`/exit 1；等待窗口内恢复后，同一 market-data date
  必须仍能进入完整 Agent 分析。该窗口由独立的 outcome settlement 配置控制，不得与
  final-bar readiness 或普通分析失败重试混用；CLI/API/Web 和成本汇总必须识别这些状态。

## 测试和验证注意事项

- 针对 Web/CLI parity 的快速验证优先跑：
  `node --check web/frontend/app.js` 和
  `venv/bin/python3.12 -m pytest tests/test_runtime_analysis_runner.py tests/test_web_backend.py tests/test_api_key_env.py tests/test_cli_env_skip.py -q`。
- 全量 `pytest -q` 当前会受到环境和既有测试问题影响。常见非本次改动失败：
  DeepSeek live 测试因沙箱 DNS/网络失败；`test_market_data_validator.py` 仍引用
  旧的 `load_ohlcv` 属性；`test_openai_compatible_provider.py` 会被当前 shell 中
  的 OpenAI/OpenAI-compatible key 环境变量污染。
- 报告全量测试结果时要区分“本次相关测试失败”和“既有/环境失败”。不要为了让
  全量测试变绿而改无关测试或清理用户环境变量，除非用户明确要求。
- pytest 运行历史已做强制隔离：`tests/conftest.py` 在测试模块收集前设置进程唯一
  bootstrap `TRADINGAGENTS_DB`，并为每个测试创建独立 `tmp_path/runs.db`，让
  runtime `history_store`、Web `TaskStore` 与 vendor 审计共用该临时库。测试不得
  绕过此 fixture 写入正式 `~/.tradingagents/runs.db` 或工作区回退数据库。
- 测试日期分两类：离线确定性单元测试保留固定日期，以稳定覆盖周末、时区、收盘
  边界、陈旧数据和前视偏差；真实 live integration/smoke 必须按标的调用
  `latest_completed_daily_bar_date()`，不得把 `date.today()` 或长期硬编码日期用作
  完整日 K 截止。分钟级 live capability probe 可以使用当前交易自然日，但不得将
  其结果写入规范日 K。
- Web 运行态接口可用性至少验证：
  `/api/config/defaults`、`/api/config/env-status`、`/api/runs`、SSE events、
  `/api/runs/{run_id}/report`。
- 完成目标前做证据审计：检查当前工作区、最新提交、ROADMAP 覆盖、测试输出、
  运行态接口、桌面/移动端截图或 scroll 审计。不要只凭记忆宣布完成。

## Git 工作流

- **推送目标**：`origin`（不是 `tauric`）
- `tauric` 是上游只读镜像；不要推送到那里
- 正常同步使用 `git push origin main`
- GitHub SSH 22 端口可能超时。若 `git push origin main` 报
  `ssh: connect to host github.com port 22: Connection timed out`，使用：
  `env GIT_SSH_COMMAND='ssh -o HostName=ssh.github.com -o Port=443 -o StrictHostKeyChecking=accept-new' git push origin main`
- 如果已经 push 后又 `commit --amend`，用 `--force-with-lease`，不要普通
  force push：`git push --force-with-lease origin main`。
- `results/` 已 gitignored — smoke output 不应提交
- API key 位于 `~/.zshrc` export 和 `.longbridge_mcp_token.json` —
  不要写入 config 文件，也不要提交（遵守 secret-file-editing protocol）

## 运行历史持久化设计 (History Store)

- 核心运行时分析流 `run_analysis_stream` 已集成 `history_store` 包装器。无论是通过 CLI（`tradingagents` 交互式运行）还是 Web 界面启动的分析任务，均会自动向统一的 SQLite 数据库 `~/.tradingagents/runs.db` 中持久化记录运行历史与完整的事件步骤（`events`）。
- `RunHistoryStore` 实现了多进程/线程环境下的并发安全访问和 SQL 事件入库时的去重机制（Deduplication），保证了 WebUI 内部的 SSE 分发与核心流自带的持久化之间不会发生事件双写或冲突。
- 前端与后端 TaskStore 已全面对接该核心模块，废除了原本仅存在于 `/web` 下的独立 SQL 查询与表初始化结构。
- vendor 尝试必须先写入 run-scoped append-only ledger，再由同一记录生成
  `vendor_attempt` runtime 事件；`decision_status` 与 `data_status` 是两个不同维度，
  fallback 或部分数据不可用不得因最终决策通过校验而显示为普通成功。
- Langfuse、OpenTelemetry 或其他外部可观测平台只能作为可选异步镜像，不能替代
  SQLite/runtime 权威事件链。采样、网络失败、外部服务停机或未配置凭据不得影响
  分析执行、SSE 历史回放和本地审计完整性。
- agent 架构 paired comparison 必须要求 baseline/challenger 的分析输入 evidence fingerprint 完整且相同；fingerprint 绑定 vendor、规范化参数、状态与结果 hash，忽略 call ID、延迟和执行时间噪声。输入不同或成功结果缺 hash 的 pair 必须排除，不得把数据源退化/漂移归因于 agent 架构改进。
- 当前 PM-only / RM+PM 纵向上下文实验还必须要求 Research Manager 分叉前的 agent-state fingerprint 完整且相同；该指纹绑定 instrument context 与完整 debate history，并排除 treatment 自身。独立重跑造成的上游 LLM 输出漂移必须排除；若实验分叉点改变，需新增对应的 pre-treatment schema 或共享 snapshot/replay，不得沿用不匹配的指纹冒充因果证据。
- 同标的 paired shadow 会近似翻倍 LLM 成本，启用 schedule 必须显式设置 `paired_shadow_authorized=true`。当前只允许恰好两个共享时区、运行时点、资产类型、工作日和 analysts 的 arm，并分别使用 `portfolio_only` / `research_and_portfolio`，以隔离已支持的 Research Manager context treatment；只改 `enabled=true` 或改变上游输入必须 fail closed。
- agent architecture fingerprint 只应覆盖真正影响决策的实现：agents、graph、dataflows、LLM clients，以及影响请求、配置、时间审计和纵向上下文的 canonical runtime 模块。scheduler、CLI、报表和 evaluation 展示等纯运维代码不得切碎长期 cohort；若新增会改变决策输入、prompt、validator、模型 wire format 或风险语义的模块，必须同步加入 manifest digest scope。
- runtime history 与 vendor verification 不得因 home 目录不可写而回退到工作区数据库。默认路径只能是 `~/.tradingagents/runs.db`，替代路径只能由显式 `TRADINGAGENTS_DB` 提供；canonical 路径不可访问必须 fail closed，避免测试或沙箱数据形成第二套“正式”纵向历史。
- paired architecture comparison 必须从首个双臂 evaluation 起暴露有效 pair 与 exclusion 诊断，不能等满最低样本数才发现输入漂移；但早期诊断不得降低 `minimum_samples` / `minimum_paired_samples`，不足时必须保持 `insufficient_data` 且禁止通过 paired gate。
- architecture manifest 必须显式绑定会进入 agent 纵向上下文的 measurement/scoring version、Hold band 与默认 horizon。evaluation 展示实现可以排除出源码 digest，但这些政策身份不得仅依赖模块常量而在同一 fingerprint 下静默变化；所有 settlement、pending 状态与 comparison 默认 horizon 必须共享同一 canonical 常量。

## 需要定期检查的事项

- **Longbridge token 过期时间**：token 位于仓库根目录
  `.longbridge_mcp_token.json`，签发后约 14–30 天过期（以文件内 `expiry` 为准）。
  运行长 smoke 或自然调度前只读取并检查 expiry 字段，不输出 token 字段。截至
  2026-07-19 安全状态函数已确认该 bearer 于 2026-07-18 23:56 CST 过期，返回
  `status=expired` / `configured=false`。expiry 缺失、格式错误或无时区必须视为过期并触发
  `MCPAuthError`；不得假定 token 有效。独立 Longbridge CLI OAuth 是 MCP 认证失败时
  的第一 fallback；到期前的 CLI/OHLCV/财务/新闻探测不能替代到期后的真实网络能力
  证据，下一次自然运行前仍需重新探测，未探测时只能报告“fallback 已配置”。
  `/api/config/env-status` 的 `configured` 必须基于 token schema 和带时区 expiry
  验证，不能只根据文件是否存在；可额外返回不含凭据的 `credential_status` 和
  UTC `expires_at`。
- **Longbridge-first OHLCV**：原始 OHLCV 默认优先使用 Longbridge MCP/CLI，
  Westock 作为覆盖率或 Longbridge 不可用时的 fallback。技术指标和基本面仍按
  各自配置链路。当分析日为当前交易日时，收盘缓冲期结束前不得把当日日 K
  视为完整数据；共享 OHLCV 缓存只保留规范的 Date/Open/High/Low/Close/Volume
  列，新获取的同日完整 K 线必须覆盖盘中残缺记录。
- **技术指标批量路径**：Market Analyst 应在一次 `get_indicators` 调用中传入最多
  8 个指标。默认 stockstats 引擎只加载一次 canonical OHLCV 并批量计算；部分失败
  由 router 将缺失集合批量交给 Longbridge MCP `quant_run`，不得恢复逐指标重复
  OHLCV 获取。每条指标仍必须保留独立 validator 结果、vendor 来源和 fallback 审计。
- Market Analyst 的 LLM 工具面只暴露批量 `get_indicators` 与紧凑的
  `get_verified_market_snapshot`；不得重新暴露原始 `get_stock_data`，避免多年度日线表在
  工具循环中反复进入模型上下文。底层 snapshot/indicator 仍必须通过 canonical OHLCV
  router、统一模型、validator、缓存和 run-scoped ledger 获取完整计算窗口，不得为了降
  token 截断 200 SMA 等确定性计算输入。
- Fundamentals Analyst 的 LLM 工具面只暴露 `get_financial_evidence`，一次返回通过
  validator 与跨表 reconciliation 的 IS/BS/CF 组合证据。紧凑 schema 只能把重复元数据
  提升为 columns/series/observations，必须保留每条 verified metric/value/period/context；
  禁止以摘要、Top-N 或最新期截断替代完整统一模型。四类原始 vendor subcall、fallback、
  unverified fact count、确定性 derived metrics 与 run-scoped ledger 仍必须保留。

## 开发最佳实践与文档维护约定

- **ROADMAP.md 维护**：Agent 完成新功能开发或数据校验重构并确认相关测试通过后，必须同步更新 `ROADMAP.md` 的状态、验收证据或优先级，并与代码改动一同提交和推送。
- **Tool 参数安全性加固 (`**kwargs`)**：为了防止 LLM 在长上下文或交织思考（Interleaved Thinking）时发生幻觉并在 arguments 中夹带非标控制参数（例如 `"/invoke"` ），所有暴露给 LLM 调用的数据工具（`@tool`）函数签名末尾必须添加 `**kwargs`，在运行时自动忽略这些多余键值，严防因 Unexpected Keyword Argument 报错导致 Graph 崩溃。
- **非美宏观指标回溯窗口**：由于 FRED 数据库中的中国/香港等非美宏观指标（如中国 CPI `CHNCPIALLMINMEI`、香港 CPI `FPCPITOTLZGHKG`）存在显著的数据发布滞后，直接请求 180 或 365 天的回溯极易因窗口内无数据导致 API 报错。对此类滞后指标在底层请求端必须强制采用至少 1095 天（3 年）的最小 Lookback 周期。

## 不需要先问权限的操作

- 运行 `tradingagents --help` 或任何非交互 smoke
- 读取工作区内文件
- 运行 `git status` / `git log` / `git diff` 做检查
- 用新学到的经验更新本文档

## 交互与语言习惯

- **沟通语言**：与用户的所有对话交互一律使用**中文**。
