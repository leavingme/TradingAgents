# GOAL

## 当前目标

完成第二批 P0 目标的重构工作：
- 新闻数据校验
- 宏观数据校验
- 预测市场数据校验
- Runtime 状态持久化

## 下一步行动顺序

1. 批量获取技术指标，消除当前多指标顺序请求的主要延迟。
2. 对 `report_section` 的 SSE 推送与 SQLite 持久化实施节流。
3. 按 P0 顺序完成新闻、宏观、预测市场确定性校验，以及 vendor 尝试轨迹持久化。

## 目标边界

- 校验失败的数据不得伪装或降级为低信息文本输出，必须能明确阻断或进行类型化降级。
- 确保所有相关分析节点只消费被验证、归一化的统一模型数据。
- 保证新闻、宏观、预测市场数据均有相应的 deterministic validator 和 structured models。

## 已完成目标

- **财务数据链路 P0-2 收尾重构 (2026-07-11)**：
  - 清理了财务数据链路中的旧文本匹配路径，确保校验入口 `validate_financial_result` 只接受统一领域模型输入。
  - 将 `unverified_facts` 和原始 payload 落到独立审计记录 `~/.tradingagents/financial_audit.jsonl` 中，防止泄露到 LLM 上下文中。
  - 实现了资产负债表、利润表、现金流量表的跨报表勾稽与期间一致性检查。
  - 基于完整输入确定性计算并注入了 `ROE`、`ROA`、`TTM EPS`、`PE`、`净现金` 和 `EV/EBITDA` 等派生指标，并具备可追踪的公式和 inputs 字段。
  - 确保任一财务数据校验或勾稽失败时抛出 `NoUsableFinancialDataError` 阻断后续分析和图流程。

## 验证方式

### 单元测试

- `venv/bin/python3.12 -m pytest tests/test_financial_data_validation.py -q`
- `venv/bin/python3.12 -m pytest tests/test_financial_reconciliation.py -q`
- `venv/bin/python3.12 -m pytest tests/test_vendor_verification.py -q`
- `venv/bin/python3.12 -m pytest tests/test_no_data_handling.py -q`

### 回归验证

- `venv/bin/python3.12 -m pytest tests/test_runtime_analysis_runner.py tests/test_market_toolnode.py tests/test_vendor_errors.py tests/test_vendor_routing.py -q`
- `venv/bin/python3.12 -m pytest tests/test_fred.py tests/test_westock_stale_ohlcv_guard.py -q`

### 语法与一致性

- `node --check web/frontend/app.js`
- `venv/bin/python3.12 -m compileall tradingagents tests`
- `git diff --check`
