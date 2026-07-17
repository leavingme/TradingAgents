# 收盘后每日分析与纵向评估

每日自动化由用户级 systemd timer 托管。timer 每 15 分钟唤醒一次轻量调度器；
调度器以每个标的的交易所本地时区判断是否已经到达 `run_after`，随后通过
`tradingagents.runtime.run_analysis_once()` 启动 canonical runtime。timer 本身
不直接运行 Graph，也不保存任何凭据。仓库 service 明确设置
`TimeoutStartSec=infinity`；用户级 systemd manager 常见的 90 秒默认启动超时不能
截断通常需要 5–10 分钟的完整分析。

## 配置

默认配置路径是 `~/.tradingagents/daily_schedule.json`，格式参见
`config/daily_schedule.example.json`。股票默认工作日为周一至周五，crypto 可显式
配置 `[0, 1, 2, 3, 4, 5, 6]`。`run_after` 必须晚于该市场规范日 K 的收盘缓冲；
当前 NVDA 配置为 `America/New_York` 16:30。

每个 target 还包含服务端 `architecture_version` 和
`longitudinal_context_mode=portfolio_only|research_and_portfolio`。调度幂等键是
symbol + market-data date + architecture version，因此同一标的可以做成对 shadow
实验，同时每个版本仍独立遵守重试和成本上限。

调度器从 `~/.tradingagents/web_config.json` 读取服务端已保存的研究深度、LLM、
输出语言和 vendor 顺序，因此无人值守运行与 Web 运行使用相同设置。配置和日志中
不得写 API key、cookie、token 或 webhook。

同一 symbol + `market_data_date` 已有 `pending`、`running`、`completed` 或
`review_required` run 时不会重复启动。`failed`、`cancelled`、`unavailable` 默认
等待 60 分钟后重试一次；每天最多两次，防止故障时无限消耗 token。进程级文件锁
避免 timer 重叠执行。外部/manual run 连续 360 分钟仍停留在 active 状态时视为
陈旧占位，允许在每日总次数上限内发起恢复运行，但保留原 run 不做历史篡改。

## 安装与运维

将仓库内的两个 unit 复制到 `~/.config/systemd/user/` 后执行：

```bash
systemctl --user daemon-reload
systemctl --user enable --now tradingagents-daily.timer
systemctl --user status tradingagents-daily.timer --no-pager
systemctl --user list-timers tradingagents-daily.timer --no-pager
```

常用检查：

```bash
venv/bin/python3.12 scripts/daily_analysis.py status
venv/bin/python3.12 scripts/daily_analysis.py run --dry-run
journalctl --user -u tradingagents-daily.service -n 100 --no-pager
```

## 连续多日结果评估

只有完整取得决策日收盘价以及之后第 5 个共同交易日的标的/基准收盘价时，结果才会
结算；1–4 日数据保持 pending，绝不伪装成“5d”结果。历史 `point_in_time` 运行不
执行事后结算，避免未来信息副作用。评估使用与分析相同的 canonical OHLCV vendor
路由，不再硬编码 Westock。

结构化结果写入统一 `runs.db` 的 `decision_evaluations`：原始 run、负责结算的 run、
架构版本、rating、基准、原始收益、基准收益、alpha、方向命中和确定性 score 均可
追溯。每条结果同时保存 `scoring_version` 与 Hold band；当前评分尺为
`alpha-exposure-v1` / `0.02`，这里只是固化既有确定性语义，不代表该 band 已被优化。
History Store 会按声明的评分策略重算 exposure、方向命中和 score，不一致记录拒绝入库。
每条结果还必须保存 entry/exit 交易日、标的与基准的四个收盘价，以及来自
逐交易日 `ohlcv_audit.jsonl` 的四个稳定 source ID；旧版只有日期范围而没有逐日
provenance 的缓存记录不能用于结算。正式 runtime 会把这些 SQLite 定量结果以固定
JSON schema 注入 Research Manager 和 Portfolio Manager；不会把 LLM 生成的 Markdown
反思当成可信证据。v3 上下文保留最近的同标的/跨标的逐条结果、评分身份及明确的扫描/截断计数，
但架构 rollup 只使用截止时点前扫描到的完整同标的 cohort，不再把跨标的结果或最近
样本截断混入同一均值。token、调用数和耗时仅用于 operator-facing 架构优化查询，
不会注入投资决策上下文。历史 `point_in_time` 只允许看到
`evaluated_at <= information_cutoff` 的结果；cutoff 与同/跨标的范围在 SQLite 排序和
LIMIT 之前执行，避免未来结果或其他标的大量样本挤掉当时已经存在的同标的证据。
新写入的 `evaluated_at` 统一规范为 UTC，旧偏移时间也按真实时刻而非字符串排序。
查询方式：

```bash
venv/bin/python3.12 scripts/daily_analysis.py evaluate --ticker NVDA
curl -s 'http://127.0.0.1:8765/api/evaluations?ticker=NVDA'
curl -s 'http://127.0.0.1:8765/api/evaluations?ticker=NVDA&baseline=baseline&challenger=challenger'
```

架构 challenger 的比较要求 baseline/challenger 各至少 20 个已结算样本。由于连续
实盘样本受行情 regime 混杂，正式 gate 使用相同 ticker + analysis date + horizon 的
成对 shadow 结果。两边必须有相同 entry/exit 日期、四个收盘价、四个 stable OHLCV
source ID 以及 raw/benchmark/alpha outcome；缺失或不一致会从
配对样本排除并单独计数。两边还必须有可审计的 runtime start timestamp，默认启动
间隔不得超过 3600 秒；延迟重试形成的跨时段决策不能伪装成同一时点 shadow pair。
小样本 score delta 的 95% 下界使用 Student-t 临界值，
不使用偏乐观的正态近似。日频固定期限结果会共享部分市场交易日，因此标准误还会
按 ticker 和实际 entry/exit 窗口执行最多 `horizon - 1` 阶的 Bartlett/Newey-West
自相关校正，并取 IID 与校正值中更保守的一项；输出同时保留两者、使用的 lag、
重叠 pair 数和不确定性等效样本量，避免把 20 个彼此重叠的 5-session 结果误当成
20 个独立样本。Student-t 临界值也使用向下取整的等效样本量，不继续沿用偏大的
原始 pair 数作为自由度。
每个 run 还保存包含 analyst 集合、研究深度、模型和
纵向上下文拓扑的 canonical manifest 与 SHA-256 fingerprint。manifest v2 还包含
路径无关的 `tradingagents/**/*.py` 实现摘要，以及非密钥的有效 vendor、风险策略、
输出语言、推理强度、temperature、benchmark 和新闻配置；源码或决策配置变化会自动
拆分 fingerprint cohort。摘要不包含绝对路径、环境变量值、backend URL、凭据或
非 Python 文件；backend 只记录是否使用自定义端点。
rollup 按版本、fingerprint 和 horizon 分组，同一版本混入多个 fingerprint 时直接拒绝
比较；评分版本与 Hold band 也属于 cohort 身份，baseline/challenger 必须各自唯一且
完全一致。改变评分尺必须形成新 cohort，不能被报告成 agent 提升。即使成对 score
delta 的 95% 下界通过
阈值，结果也只返回 `review_required`，不得自动晋升或自动修改 prompt/agent 拓扑。

canonical runtime 会为 CLI、Web、skill 和 timer 自动安装运行级统计，不依赖调用入口
自行挂 callback；成功和失败路径都会在终态事件前强制保存最终快照。已结算结果查询
会从同一 SQLite 事件链关联最终 `stats` 快照和 run
起止时间，rollup 显示 runtime、LLM/tool calls、input/output tokens 的均值与各自样本
覆盖数。成对架构比较还返回这些成本指标的 `challenger_minus_baseline` 差值、平均降幅
和 Student-t 95% 区间；成本证据缺失会单独计数，不会被当成零成本，也不会改变收益
门禁。架构优化必须同时审阅收益证据和成本证据。

默认禁用的实验模板位于 `config/architecture_experiment.example.json`。它比较
PM-only baseline 与 Research Manager + PM challenger。启用会把 LLM 成本近似翻倍，
因此不得替换正式 `daily_schedule.json`，除非用户明确批准实验预算。可先只做校验：

```bash
TRADINGAGENTS_DAILY_SCHEDULE=config/architecture_experiment.example.json \
  venv/bin/python3.12 scripts/daily_analysis.py run --dry-run
```

同一 symbol/date 有多个 architecture arm 时，scheduler 只按此前“所有 arm 均完成”
的配对日期数轮换执行顺序；失败或缺失的半对不会推进轮换。这样 baseline-first 与
challenger-first 在完整执行样本中轮换，避免首个 run 补齐 OHLCV 磁盘缓存后让固定
后跑的一方获得虚假 runtime/vendor 成本优势；最终可评估样本仍由比较器检查是否
counterbalanced。调度日志输出
`planned_execution_order` / `execution_group_size`；比较器从 SQLite 的实际启动时间
复核真正顺序，
分别聚合两种顺序下的成本 delta，并给出 `counterbalanced`、
`order_confounded`、`unverifiable_order` 或 `insufficient_order_samples` 状态。
