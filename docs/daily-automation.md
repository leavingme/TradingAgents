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
symbol + 请求截止日 + architecture version；实际验证的 `market_data_date` 由
runtime 另行审计。因此同一标的可以做成对 shadow 实验，同时每个版本仍独立遵守
重试和成本上限。

同一标的配置两个架构 arm 时，schema 只接受当前可归因的 RM-context 实验：恰好
两个 arm 必须共享时区、运行时点、资产类型、工作日和 analysts，并分别使用
`portfolio_only` 与 `research_and_portfolio`。启用此类 schedule 还必须显式设置
`paired_shadow_authorized=true`；否则加载直接失败。这是近似双倍 LLM 成本的
server-side 授权门禁，不影响普通单 arm 每日运行。

调度器从 `~/.tradingagents/web_config.json` 读取服务端已保存的研究深度、LLM、
输出语言和 vendor 顺序，因此无人值守运行与 Web 运行使用相同设置。配置和日志中
不得写 API key、cookie、token 或 webhook。
运行历史与 vendor 审计默认且唯一使用 `~/.tradingagents/runs.db`；只有显式
`TRADINGAGENTS_DB` 可以覆盖。canonical 路径不可访问时必须 fail closed，禁止静默
回退到工作区 `.tradingagents/runs.db` 形成第二套历史。

同一 symbol + 请求截止日 + architecture version 已有 `pending`、`running`、`completed` 或
`review_required` run 时不会重复启动。`failed`、`cancelled`、`unavailable` 默认
等待 60 分钟后重试一次；每天最多两次，防止故障时无限消耗 token。进程级文件锁
避免 timer 重叠执行。外部/manual run 连续 360 分钟仍停留在 active 状态时视为
陈旧占位，允许在每日总次数上限内发起恢复运行，但保留原 run 不做历史篡改。
若异常早于 canonical runtime 注册 run，scheduler 也会写入明确标记为
`pre-runtime-failure` 的失败占位，使该失败仍计入同一有界重试预算；不会因为缺少
SQLite attempt 而每 15 分钟无限重试。
运维状态与 canonical decision status 保持一致：`validated → completed/exit 0`，
`review_required → review_required/exit 0`，`unavailable → unavailable/exit 1`；最终
`attempts_exhausted` 也保持非零退出，避免 systemd 把“没有形成可用决策”误报为成功。
等待重试的 `retry_wait` 本身不代表一次新失败，保持 exit 0。

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

`--dry-run` 不创建 run、不调用 LLM 或外部 vendor，但会构造与真实执行相同的有效
runtime config，并输出 analysis date、analysts、研究深度、报告语言、模型、vendor
顺序、推理参数、纵向模式、计划执行位次，以及 canonical architecture manifest 与
fingerprint。manifest 使用与正式历史相同的安全白名单；backend 只显示是否自定义，
不会输出 URL、凭据、secret 环境变量名/值或本地绝对路径。

## 连续多日结果评估

分析日收盘价可能早于收盘后决策形成时刻，因此绝不直接作为可执行 entry。系统按
每个原始 run 的 `decision_as_of` 转换为标的交易所本地日期；只有完整取得该决策市场日
之后第一个标的/基准共同收盘价，以及再往后第 5 个共同交易日收盘价时，结果
才会结算；1–4 个持有时段的数据保持 pending，绝不伪装成“5d”结果。历史 `point_in_time` 运行不
执行事后结算，避免未来信息副作用。评估使用与分析相同的 canonical OHLCV vendor
路由，不再硬编码 Westock。

结构化结果写入统一 `runs.db` 的 `decision_evaluations`：原始 run、负责结算的 run、
架构版本、rating、基准、原始收益、基准收益、alpha、方向命中和确定性 score 均可
追溯。每条结果同时保存 `measurement_version`、`scoring_version` 与 Hold band；
当前计量口径为 `post-decision-day-close-v1`，先前仅按 analysis date 前移的过渡口径
标记为 `next-common-close-v1`，旧版决策日收盘口径明确标记为
`decision-close-v1` 并与新 cohort 隔离。当前评分尺为
`alpha-exposure-v1` / `0.02`，这里只是固化既有确定性语义，不代表该 band 已被优化。
History Store 会反查原始 run 的 validated terminal event，绑定 ticker、analysis date、
rating、decision timestamp、架构版本/fingerprint，并按声明的评分策略重算 exposure、
方向命中和 score；任一身份或数值不一致都会拒绝入库。
每条结果还必须保存 `decision_as_of`、交易所时区、entry cutoff、entry/exit 交易日、
标的与基准的四个收盘价，以及来自
逐交易日 `ohlcv_audit.jsonl` 的四个稳定 source ID；旧版只有日期范围而没有逐日
provenance 的缓存记录不能用于结算。正式 runtime 会把这些 SQLite 定量结果以固定
JSON schema 注入 Research Manager 和 Portfolio Manager；不会把 LLM 生成的 Markdown
反思当成可信证据。v8 上下文保留最近的同标的/跨标的逐条结果、请求分析日期、实际
验证的 `market_data_date`、决策/计量/评分身份、
分析数据状态、input-evidence 完整性、研究经理分叉前输入完整性及明确的扫描/截断计数，
但架构 rollup 只使用截止时点前扫描到的完整同标的 cohort，不再把跨标的结果或最近
样本截断混入同一均值。token、调用数和耗时仅用于 operator-facing 架构优化查询，
不会注入投资决策上下文。历史 `point_in_time` 只允许看到
`evaluated_at <= information_cutoff` 的结果；cutoff 与同/跨标的范围在 SQLite 排序和
LIMIT 之前执行，避免未来结果或其他标的大量样本挤掉当时已经存在的同标的证据。
新写入的 `evaluated_at` 统一规范为 UTC，旧偏移时间也按真实时刻而非字符串排序。
`analysis_date` 是调用方请求的日 K 截止日期，不再冒充已验证的实际交易日。运行开始时
`market_data_date` 保持为空并标记 `pending_verification`；只有 canonical OHLCV adapter
和 validator 完成后，实际最后交易日才写入 `runs.market_data_date`、
`market_data_status` 事件、terminal event 和后续 evaluation。若供应商数据晚到、周末
或休市，实际日期可以早于请求日期但绝不能晚于它。架构配对还要求两臂非空且相同的
`market_data_date`，防止把不同日 K 输入误认为同一实验样本。
当前 PM-only baseline / RM+PM challenger 模板还会在 `run_completed` 固化
`research-manager-pre-context-input/v1` 指纹。它只绑定 treatment 注入前的
instrument context 与完整 investment debate history，刻意排除 `past_context` 和
`longitudinal_context_mode`；配对比较同时要求两臂该指纹完整且一致。若上游 agent
输出因独立重跑而漂移，该 pair 会计入 `architecture_input_mismatches_excluded`，不能
冒充纵向上下文带来的架构收益。该 schema 只适用于当前研究经理分叉实验；更早的
拓扑分叉需要另设 pre-treatment schema 或共享上游 snapshot/replay。
查询方式：

```bash
venv/bin/python3.12 scripts/daily_analysis.py evaluate --ticker NVDA
curl -s 'http://127.0.0.1:8765/api/evaluations?ticker=NVDA'
curl -s 'http://127.0.0.1:8765/api/evaluations?ticker=NVDA&baseline=baseline&challenger=challenger'
```

CLI 与 API 同时返回 `pending_evaluation_count` / `pending_evaluations`。每条 pending
记录只来自 SQLite 中 validated 且尚无对应 5-session evaluation 的 run，并显示
决策时刻、请求日期、实际 market-data date、架构身份与
`awaiting_fixed_horizon_outcome` 状态。因此 `evaluation_count=0` 时可以区分“尚无首个
决策”“正常等待固定期限成熟”，而不必从 Markdown 或日志猜测。

待结算集合直接来自 SQLite 中 `decision_status=validated` 且缺少对应 horizon evaluation
的 run，不再由兼容 Markdown memory log 的 pending 标签驱动。Markdown 反思只做
best-effort 展示；缺失、重复或写入失败不会使结构化结果永久失去结算资格。

架构 challenger 的比较要求 baseline/challenger 各至少 20 个已结算样本。由于连续
实盘样本受行情 regime 混杂，正式 gate 使用相同 ticker + analysis date + horizon 的
成对 shadow 结果。两边必须有相同 entry/exit 日期、四个收盘价、四个 stable OHLCV
source ID 以及 raw/benchmark/alpha outcome；缺失或不一致会从
配对样本排除并单独计数。两边还必须有可审计的 runtime start timestamp，默认启动
间隔不得超过 3600 秒；延迟重试形成的跨时段决策不能伪装成同一时点 shadow pair。
每个已结算 run 还保存分析输入 evidence fingerprint：绑定 canonical vendor、方法、
agent、symbol、规范化参数、fallback 状态、结果 hash 和数据观察范围，但忽略 call ID、
延迟与执行时间噪声。只有两边 fingerprint 相同且所有成功证据都有 result hash 的 pair
才能进入架构收益门禁；数据源退化、实时内容漂移或不同工具输入会作为
`evidence_mismatches_excluded` 排除。rollup 同时报告 data-status 分布与 evidence 完整数。
小样本 score delta 的 95% 下界使用 Student-t 临界值，
不使用偏乐观的正态近似。日频固定期限结果会共享部分市场交易日，因此标准误还会
按 ticker 和实际 entry/exit 窗口执行最多 `horizon - 1` 阶的 Bartlett/Newey-West
自相关校正，并取 IID 与校正值中更保守的一项；输出同时保留两者、使用的 lag、
重叠 pair 数和不确定性等效样本量，避免把 20 个彼此重叠的 5-session 结果误当成
20 个独立样本。Student-t 临界值也使用向下取整的等效样本量，不继续沿用偏大的
原始 pair 数作为自由度。
比较器从首个双臂 evaluation 起就返回 `sample_progress` 和完整的 paired exclusion
诊断，即使每个架构尚未达到 20 个结果。这样可以尽早发现 vendor evidence、
pre-treatment agent state、时间窗口或 outcome provenance 漂移，停止无效实验；
未达到样本门槛时状态仍为 `insufficient_data`，且 `passes_paired_gate=false`。
每个 run 还保存包含 analyst 集合、研究深度、模型和
纵向上下文拓扑的 canonical manifest 与 SHA-256 fingerprint。manifest v3 还包含
路径无关的决策实现摘要，以及非密钥的有效 vendor、风险策略、
输出语言、推理强度、temperature、benchmark 和新闻配置；源码或决策配置变化会自动
拆分 fingerprint cohort。摘要不包含绝对路径、环境变量值、backend URL、凭据或
非 Python 文件；backend 只记录是否使用自定义端点。manifest v3 的实现摘要只覆盖
agents、graph、dataflows、LLM clients，以及影响请求、配置、时间审计和纵向上下文的
canonical runtime 模块；scheduler、CLI、报表与 evaluation 展示代码不再因纯运维
修改切碎长期 agent cohort。
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
因此不得替换正式 `daily_schedule.json`，除非用户明确批准实验预算；获批后必须同时
把模板的 `enabled` 与 `paired_shadow_authorized` 改为 `true`。只改 `enabled` 会被
确定性拒绝。可先在临时副本中完成授权位与 schema 校验：

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
