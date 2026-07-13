# NVDA 分析—复盘—P0 优化工程闭环

本流程把一次真实 NVDA 分析作为回归基准，并强制完成“运行、全链路复盘、P0 方案、P0 实现和验收”五个状态。任何 P0 未解决、缺少实现证据或修改后未重新验证，`gate` 都会失败。

## 产物

每次运行使用唯一 `run_id`，本地产物位于：

```text
.tradingagents/engineering_cycles/<run_id>/
├── cycle.json               # 当前阶段和输入
├── execution-evidence.json  # SQLite run/events/vendor calls 原始证据
├── execution-review.md      # 全流程人工复盘清单
├── findings.json            # 结构化 P0/P1 findings（权威状态）
├── p0-plan.md               # P0 根因、方案、验收与回滚要求
├── verification.json        # 修改后的固定验收命令及输出
└── completion.json          # gate 通过后才生成
```

该目录位于已 gitignore 的 `.tradingagents/` 下。需要长期保留的结论应同步到 `TODO.md`/`PLAN.md`，代码和文档一起提交。

## LLM 与 Codex 的职责边界

分析运行中的 Analyst、Researcher、Trader 和 Portfolio Manager 使用运行配置中的
分析模型（当前通常为 MiniMax-M3）。工具或输出校验失败时，允许原生成模型根据
确定性错误纠正一次；模型不能自行判定数据有效、伪造来源或放松交易数字门禁。

Codex 当前作为仓库外部的工程 Reviewer/实施者参与闭环，负责读取不可变执行证据、
完成人工语义复盘、填写 P0 根因与方案、修改代码、补测试和发起同输入重跑。
`ack-review --reviewer codex` 只记录这次职责履行，并不表示仓库后端已自动调用 Codex。
最终完成权始终属于确定性的 `gate`。

当前尚未实现自动 `review-model` 阶段。未来若接入独立 Reviewer 模型，必须只读取
持久化 evidence，输出带 event/vendor/source 证据引用的结构化 findings，且不能直接
修改历史记录或绕过人工确认和工程 gate。

## 首次真实闭环记录（2026-07-13）

- 最终验收 run：`827ade0962dc42f0a7f16a5ee1cd9064`，NVDA，分析日 `2026-07-10`。
- 最终状态：`validated`；自动复盘 P0 为 0；固定验收 76 项测试通过。
- 闭环处理的 P0：工程入口 LLM/数据库配置错配、非多头报告夹带未经验证的执行数字、
  News Analyst 幻觉 `source_id` 后缺少受限纠错路径。
- 保留的 P1：vendor fallback 频繁、上下文 token 成本过高。
- 对应提交：`92b5bdd feat: add audited NVDA engineering cycle`。

## 1. 运行 NVDA 基准分析

默认选择最近一个已完成的工作日，避免把仍在形成的当日日 K 线作为完整数据：

```bash
venv/bin/python3.12 scripts/engineering_cycle.py run --symbol NVDA --depth 1
```

历史日期必须显式传入：

```bash
venv/bin/python3.12 scripts/engineering_cycle.py run \
  --symbol NVDA --date 2026-07-10 --depth 1
```

命令使用 `tradingagents.runtime`，自动写入 SQLite events 和 run-scoped vendor ledger。保存命令输出的 `run_id`。

## 2. Review 整个执行过程

```bash
venv/bin/python3.12 scripts/engineering_cycle.py review <run_id>
```

Review 必须覆盖：

1. 每个 Analyst/Researcher/Manager 的输入、工具调用、输出和交接。
2. 每个重要事实的 vendor call 或 `source_id` 溯源。
3. fallback 的首选源失败原因、统一 validator 和最终选中源。
4. 交易数字与 verified snapshot、服务端风险政策的一致性。
5. `validated/review_required/unavailable` 是否正确传播。
6. token、延迟、重复上下文和重复事件等非 P0 成本问题。

自动检测只负责可确定判断的异常。人工发现的问题追加到 `findings.json`，不得只写在聊天记录里。完成全量复盘后确认：

```bash
venv/bin/python3.12 scripts/engineering_cycle.py ack-review <run_id> \
  --reviewer codex \
  --summary "已逐 Agent、vendor、证据、交易门禁和最终决策完成全流程复盘……"
```

## 3. 深入分析 P0 并形成方案

`review` 会生成 `p0-plan.md`。每个 P0 必须明确：

- 原始证据和影响范围；
- 可复现条件和根因；
- 为什么现有 fallback/validator 没有阻断；
- 结构化修复方案及信任边界；
- 单元、集成和同输入 NVDA 重跑验收；
- 回滚点（不得恢复 P0 绕过路径）。

P0 的成功标准必须是可由代码或持久化证据判断的条件，不能写成“效果更好”“模型更谨慎”等主观描述。

将根因分析和方案写入权威 finding；缺少这一步时 `gate` 必须失败：

```bash
venv/bin/python3.12 scripts/engineering_cycle.py plan <run_id> <finding_id> \
  --root-cause "可复现的确定性根因和影响边界" \
  --solution "代码信任边界、修复位置与失败语义" \
  --acceptance "单元/集成测试和同输入 NVDA 重跑的客观条件"
```

## 4. 完成 P0 优化

实现代码、补测试并同步 `TODO.md`/`PLAN.md`。逐项记录实现证据：

```bash
venv/bin/python3.12 scripts/engineering_cycle.py resolve <run_id> <finding_id> \
  --implementation "commit/file/line 与行为变化" \
  --verification "新增测试与同输入重跑证据"
```

不得将 P0 标记为 `accepted_risk` 后关闭；工程 gate 只接受 `resolved`。

## 5. 修改后验证并关闭循环

```bash
venv/bin/python3.12 scripts/engineering_cycle.py verify <run_id>
venv/bin/python3.12 scripts/engineering_cycle.py gate <run_id>
```

`verify` 固定执行：Python compile、前端 JavaScript 语法、项目约定的
Web/runtime 快速测试与本流程 P0 回归测试，以及 `git diff --check`。测试文件采用
显式白名单，避免未来新增的 live/network 测试意外进入确定性工程门禁。`gate` 还会验证：

- 所有 P0 均为 `resolved`；
- 每项 P0 都有实现和验证证据；
- 每项 P0 都有实质性的根因、方案和可判定验收标准；
- 已确认完成全执行过程 review；
- 最后一次验证晚于最后一项 P0 的解决时间；
- 验收命令全部成功。

只有生成 `completion.json` 才表示本轮工程循环完成。之后提交并推送代码；下一轮 NVDA 分析必须创建新的 `run_id`，不能覆盖旧证据。
