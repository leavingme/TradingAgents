# GOAL

## 当前目标

完成 P0-2 财务数据链路的收尾重构，确保所有 vendor 返回的财务数据在进入后续流程前都经过统一领域模型和确定性校验，并且任何异常/未验证/降级数据都不会进入 LLM、决策或报告正文。

## 目标边界

- vendor 只负责获取和规范化自己的原始数据，不做跨 vendor fallback。
- fallback 只能由路由层根据配置控制。
- 财务数据必须先映射到统一领域模型，再进入 validator。
- validator 只接受统一领域模型，不接受 vendor 文本或半结构化字符串。
- `unverified_facts`、原始 payload 和 vendor 派生值要保留在审计层，但不得直接进入 LLM 上下文。
- 对于财务数据，继续补齐跨报表勾稽、期间一致性和确定性再计算能力。

## 本轮工作项

1. 清理财务数据链路中的旧兼容路径，确保校验入口只接受统一领域模型。
2. 将 `unverified_facts` 和原始 payload 落到独立审计记录。
3. 实现资产负债表、利润表、现金流量表的跨报表勾稽与期间一致性检查。
4. 基于完整输入确定性计算 `ROE`、`ROA`、`TTM EPS`、`PE`、`净现金` 和 `EV/EBITDA`。
5. 确保校验失败的数据会被阻断，不会进入后续分析、报告或图流程。

## 验收标准

- 财务数据 validator 只接受统一领域模型输入。
- 任一财务数据校验失败时，后续流程停止，不产生伪装成有效事实的数据。
- vendor 派生值保留为审计信息，但不作为已验证指标直接喂给模型。
- 跨报表勾稽失败时，必须能给出明确原因。
- 重新计算的派生指标必须可追踪到输入字段和公式。

## 验证方式

### 单元测试

- `venv/bin/python3.12 -m pytest tests/test_financial_data_validation.py -q`
- `venv/bin/python3.12 -m pytest tests/test_vendor_verification.py -q`
- `venv/bin/python3.12 -m pytest tests/test_no_data_handling.py -q`

### 回归验证

- `venv/bin/python3.12 -m pytest tests/test_runtime_analysis_runner.py tests/test_market_toolnode.py tests/test_vendor_errors.py tests/test_vendor_routing.py -q`
- `venv/bin/python3.12 -m pytest tests/test_fred.py tests/test_westock_stale_ohlcv_guard.py -q`

### 语法与一致性

- `node --check web/frontend/app.js`
- `venv/bin/python3.12 -m compileall tradingagents tests`
- `git diff --check`

### 运行态抽查

- 使用已知标的做一次运行，确认财务数据异常不会进入最终报告。
- 检查失败场景中是否产生 `NoUsableFinancialDataError` 或对应的明确异常，而不是错误字符串或空值伪装。

## 完成后下一步

如果以上目标全部完成，再切换到下一批 P0 工作：

- 新闻数据校验
- 宏观数据校验
- 预测市场数据校验
- Runtime 状态持久化

