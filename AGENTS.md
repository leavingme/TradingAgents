# AGENTS.md — TradingAgents Fork（TauricResearch/TradingAgents v0.3.0）

本文档记录这个 fork 的日常操作约定。它相当于 Hermes 工作区
AGENTS.md 的项目级版本；做任何非平凡操作前都要先读。

## 仓库

- **上游**：`https://github.com/TauricResearch/TradingAgents`（`tauric` remote，仅 fetch）
- **Fork**：`https://github.com/leavingme/TradingAgents`（`origin` remote，fetch + push 目标）
- **工作区根目录**：`/data/workspace/TradingAgents`
- **分支**：`main`
- **版本**：v0.3.0（`85946c2 chore: release v0.3.0`）+ 15 个 fork 本地提交

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
- `venv/bin/uvicorn web.backend.main:app --host 127.0.0.1 --port 8765 --reload` — 最小 FastAPI Web API 开发服务（默认热加载）
- 执行 `pip install -e .` 后，入口脚本会根据 `pyproject.toml` 的
  `[project.scripts]` 自动重新生成；当前指向
  `tradingagents._cli_entry:app`（不是直接指向 `cli.main:app` —
  详见 PYTHONPATH 部分）。

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
- LLM/tool/token stats 属于 runtime 能力，不要让 Web 后端直接依赖 CLI 实现。
  `StatsCallbackHandler` 的 canonical 位置是 `tradingagents.runtime`；
  `cli.stats_handler` 只是兼容 re-export。
- 历史 run 和刷新语义必须从 SQLite + persisted events 恢复。刷新页面后，已完成
  agent 仍应显示完成状态；运行中的任务应通过 SSE replay + live queue 继续呈现。
- 分段报告应在每个 `report_section` 事件到达时立即可见，并能通过 report
  selector 切换，不要等最终 `run_completed` 才渲染全部报告。
- 服务商与底层能力配置页面使用 `#providers` 路由。前端应提供各个底层能力（OHLCV、技术指标、基本面、新闻舆情、宏观数据、预测市场）的优先级重排（生成以逗号分隔的优先级字符串，例如 `"longbridge_mcp, longbridge"`）和开关，且通过 `config_overrides.data_vendors` 将修改后的服务商优先级传递给后端运行。后端 `build_runtime_config` 应当对 `config_overrides` 进行嵌套深度合并以防止局部键覆盖整个 data_vendors 字典。
- 服务端 API 密钥及证书状态查询（`/api/config/env-status`）已拓展以兼容底层能力数据源（如 FRED, Alpha Vantage, Longbridge MCP 等）的状态展示。前端无需保存或输入 API Key，通过后端环境变量和本地文件存在性推断其可用性。


### Web 服务和布局验证

- 启动 Web 服务时不要先在托管沙箱内运行 uvicorn；本环境的沙箱通常无法
  bind 本地端口。直接使用受批准的沙箱外命令启动，并且默认开启热加载，例如：
  `venv/bin/uvicorn web.backend.main:app --host 127.0.0.1 --port 8765 --reload`。
- 托管沙箱内可能无法 bind 本地端口，或 8765 被外部命名空间占用。`curl`
  失败不一定表示代码坏了；先看 uvicorn 日志是否是 `could not bind`。
- 如果 8765 不可用，不要杀未知进程。优先用临时端口（如 8766/8877/8878）
  做验证；需要本地 bind/浏览器截图时，用受批准的沙箱外命令。
- 长时间运行的 uvicorn tool session 可能在工具轮次结束时被清理。做截图验证时，
  更可靠的方式是在同一个 shell 里：启动临时 uvicorn、等待健康检查、执行
  headless Chrome 截图、再 kill 临时 server。
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
| `.longbridge_mcp_token.json` | Longbridge API token（数据 vendor） | `tradingagents/.longbridge_mcp_token.json`（gitignored） |
| `data_vendors.core_stock_apis` | 默认 `"westock, longbridge_mcp, longbridge"` | `default_config.py` |
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
core_stock_apis    : "westock, longbridge_mcp, longbridge"
technical_indicators: "westock, longbridge_mcp, longbridge"
fundamental_data   : "westock, longbridge_mcp, longbridge"
news_data          : "web_search, duckduckgo, alpha_vantage, westock"
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
- Web 运行态接口可用性至少验证：
  `/api/config/defaults`、`/api/config/env-status`、`/api/runs`、SSE events、
  `/api/runs/{run_id}/report`。
- 完成目标前做证据审计：检查当前工作区、最新提交、PLAN 覆盖矩阵、测试输出、
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

## 需要定期检查的事项

- **Longbridge token 过期时间**：token 位于
  `tradingagents/.longbridge_mcp_token.json`，签发后约 30 天过期。运行长
  smoke 前先检查 expiry 字段。截至 2026-07-05：过期时间为 2026-07-18。
- **Westock first-level vendor**：Westock 是默认数据链路的第一顺位供应商。
  Longbridge MCP/CLI 作为覆盖率、认证或 Westock 不可用时的 fallback。

## 不需要先问权限的操作

- 运行 `tradingagents --help` 或任何非交互 smoke
- 读取工作区内文件
- 运行 `git status` / `git log` / `git diff` 做检查
- 用新学到的经验更新本文档

## 交互与语言习惯

- **沟通语言**：与用户的所有对话交互一律使用**中文**。
