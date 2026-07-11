# TradingAgents 运行复盘与优化方案

## 1. 文档目的

本文复盘 Web run `0700.HK-29ffc75d1851` 的完整分析过程，记录已观察到的问题、风险和优化方案，并将其中影响交易结论可信度的问题定义为 P0 质量门禁。

本文只描述优化设计，不代表相关代码已经实现。

## 2. 复盘对象

| 项目 | 值 |
|---|---|
| Run ID | `0700.HK-29ffc75d1851` |
| 标的 | `0700.HK`（腾讯控股） |
| 分析日期 | `2026-07-10` |
| 资产类型 | `stock` |
| 分析师 | `market`、`social`、`news`、`fundamentals` |
| Research depth | `1`（Shallow） |
| LLM provider | `minimax-cn` |
| 状态 | `completed` |
| 开始时间 | `2026-07-10T13:09:43Z` |
| 完成时间 | `2026-07-10T13:19:14Z` |
| 总耗时 | 约 9 分 31 秒 |
| LLM 调用 | 17 次 |
| Tool 调用 | 17 次 |
| 输入 tokens | 113,679 |
| 输出 tokens | 42,098 |
| 持久化事件 | 210 条 |
| 最终评级 | `Overweight` |

最终完整报告位于：

`results/0700.HK/2026-07-10/reports/complete_report.md`

## 3. 分析流程回顾

本次运行按以下顺序执行：

1. Market Analyst 获取 OHLCV、verified market snapshot 和 VWMA。
2. Sentiment Analyst 分析新闻、StockTwits 和 Reddit 情绪。
3. News Analyst 获取个股新闻、全球新闻、宏观指标和预测市场数据。
4. Fundamentals Analyst 获取公司概况、资产负债表、现金流量表和利润表。
5. Bull Researcher 与 Bear Researcher进行多空辩论。
6. Research Manager形成 `Overweight` 研究方案。
7. Trader将研究方案转换为 `BUY` 交易计划。
8. Aggressive、Conservative、Neutral三个风险Agent讨论仓位和触发条件。
9. Portfolio Manager输出最终 `Overweight` 评级、目标价和分批建仓方案。

流程覆盖完整，但“流程完成”不等于“证据质量和交易参数均通过验证”。本次运行最突出的问题是：异常数据和低等级证据虽然被部分Agent识别，却没有形成能够阻断或降级最终决策的系统性门禁。

## 4. 总体评价

### 4.1 做得较好的部分

- 核心 OHLCV另有 verified snapshot，可在原始成交额异常时提供可信价格和成交量。
- Market Analyst明确指出7月9日和10日成交额数量级异常。
- Sentiment Analyst明确披露 StockTwits不可用、Reddit为空，并降低置信度。
- 多空研究和三类风险Agent确实提出了不同观点，而不是完全一致地追随新闻情绪。
- 最终报告包含止损、目标价、持仓周期、组合上限和再评估节点，具备基本执行框架。
- SQLite历史记录完整保留了主要事件和报告，能够支持事后审计。

### 4.2 主要不足

- 原始数据异常没有形成结构化质量状态，也没有阻断依赖该数据的指标和决策。
- 财务指标缺少币种、期间、单位和计算定义，部分解释属于模型猜测。
- 新闻标题和卖方观点被多次升级为确定性事实，并在多个Agent间重复计权。
- 最终交易计划存在价格方向、风险比例、仓位和时间尺度冲突。
- Shallow模式仍消耗超过11万输入tokens，并重复持久化大量相同报告。
- Tool事件缺少Agent、vendor、fallback、耗时和结果质量等关键可观测字段。

## 5. 优化优先级

### P0：影响交易结论可信度

1. 成交额、VWMA及其他市场数据异常缺少硬校验与阻断机制。
2. 财务数据币种、期间、单位和指标定义不明确。
3. 新闻标题被升级为商业化、收入和利润事实。
4. 最终评级、仓位、价格触发条件和风险收益计算不一致。

### P1：影响运行成本、可观测性和复盘效率

1. `report_section` 重复持久化和重复SSE传输。
2. Shallow模式上下文和输出过长。
3. Tool事件缺少Agent归属、vendor轨迹和结果摘要。
4. 报告内容中英文混杂，结论展示层级不够清晰。

### P2：影响研究深度和长期决策质量

1. 缺少 Bear/Base/Bull概率情景和独立估值模型。
2. 同源新闻在多个Agent间重复放大。
3. 缺少按数据域划分的置信度评分。
4. 缺少“事实、推断、假设、触发条件”的结构化表达。

## 6. P0-1：市场数据异常

### 6.1 观察到的问题

原始OHLCV中存在明显异常：

- 2026年7月9日成交额约为 `201,363,580,052,380`。
- 2026年7月10日成交额约为 `187,609,092,154,520`。
- 7月10日成交量为 `40,440,298`，收盘价为 `460.20`。
- `amount / volume` 得出的隐含均价约为 463.9万，远离实际股价。
- VWMA在大部分交易日为 `0`，最后一天却为约 `361,966.91`，与460港元左右的价格量纲严重不符。

Market Analyst识别了成交额异常，并在正文中提示风险，但系统仍把运行标记为完整成功。VWMA虽然最终没有成为核心结论，却仍被作为有效工具结果传入模型上下文，浪费token并增加误用风险。

### 6.2 根因

- Vendor输出进入Graph前缺少通用schema校验。
- 各技术指标没有价格量纲和有效区间校验。
- verified snapshot只提供另一份结果，没有对冲突字段产生机器可读状态。
- 数据质量信息停留在自然语言报告中，下游Agent无法稳定执行统一策略。
- 运行状态只有成功或失败，缺少 `degraded` 等中间质量状态。

### 6.3 优化手段：OHLCV硬校验

OHLCV进入分析Graph前至少执行以下规则：

```text
open > 0
high > 0
low > 0
close > 0
volume >= 0
amount >= 0
low <= open <= high
low <= close <= high
low <= high
```

对成交额计算隐含成交均价：

```text
implied_price = amount / volume
```

建议初始合法范围：

```text
0.5 * low <= implied_price <= 2.0 * high
```

实际阈值应按市场和vendor口径配置。如果vendor返回的amount单位是千元、万元或手数，应先根据明确元数据归一化，不能靠模型猜测单位。

### 6.4 优化手段：技术指标校验

价格型指标需要与当前价格处于合理量纲：

```text
0.2 * close <= SMA/EMA/VWMA/Bollinger <= 5.0 * close
```

固定范围指标执行明确边界：

```text
0 <= RSI <= 100
ATR >= 0
volume >= 0
```

连续序列还应检查：

- 零值比例异常，例如 `zero_ratio > 20%`。
- 大量重复值或突然跨越多个数量级。
- 非交易日是否被错误填入0。
- 指标需要的历史窗口是否足够。
- 最新指标日期是否等于或早于analysis date。

### 6.5 优化手段：异常处理和fallback

建议为每个字段返回结构化质量信息：

```json
{
  "field": "amount",
  "value": null,
  "status": "invalid",
  "vendor": "westock",
  "reason": "implied average price is outside OHLC range",
  "fallback_attempted": true,
  "as_of": "2026-07-10"
}
```

处理顺序：

1. 校验当前vendor结果。
2. 对无效字段尝试fallback链上的下一vendor。
3. 对多个vendor进行日期、币种、单位归一化后再比较。
4. 若可信vendor一致，使用verified值并记录被替换字段。
5. 若vendor继续冲突，将对应数据域标记为 `degraded`。
6. 若核心OHLC无法验证，禁止输出具体BUY/SELL、入场价和止损。

建议的数据域状态：

- `verified`：通过校验且至少一个可信来源可用。
- `degraded`：部分字段缺失或vendor冲突，但仍可进行有限分析。
- `invalid`：关键字段不可用，禁止下游交易决策。

## 7. P0-2：财务口径和指标定义不明确

### 7.1 观察到的问题

报告直接给出Q1收入、营业利润、净利润、EPS、ROE和毛利率，并统一使用“港元”表述，但没有展示原始财务币种和是否发生换算。腾讯财务报告通常使用人民币口径，股票以港元交易并不意味着财务报表也应自动视为港元。

其他问题包括：

- ROE `20.37%` 未说明是单季、年化还是TTM。
- `16–17倍PE` 进入最终决策，但基本面报告没有展示计算公式和输入值。
- “营业利润/经营现金流为66.48”定义不清，却被解释为现金流覆盖较好。
- 部分同比历史值由模型反推，而不是直接引用原始财务期数据。
- 报告没有区分reported、adjusted或non-GAAP净利润。

### 7.2 根因

- 财务vendor返回扁平文本或无元数据数值。
- 数据层没有统一的FinancialMetric schema。
- 派生指标部分由LLM自行解释和计算。
- 三张报表缺少勾稽检查。
- 估值结论没有绑定可审计的输入和公式。

### 7.3 优化手段：财务字段强制元数据

每个财务值必须至少携带：

```json
{
  "metric": "revenue",
  "value": 222733000000,
  "currency": "CNY",
  "unit": "yuan",
  "period": "2026Q1",
  "period_start": "2026-01-01",
  "period_end": "2026-03-31",
  "period_type": "quarterly",
  "accounting_standard": "IFRS",
  "reported_or_adjusted": "reported",
  "source": "vendor/source identifier",
  "as_of": "2026-03-31"
}
```

缺少 `currency`、`unit`、`period` 或 `period_type` 的字段不得用于估值、同比和最终交易决策。

### 7.4 优化手段：派生指标由代码计算

以下指标应由确定性代码计算，不由LLM计算：

- 同比和环比增长率。
- 毛利率、营业利润率和净利率。
- ROE和ROA。
- 经营现金流覆盖率。
- TTM EPS和PE。
- 净现金、企业价值和EV/EBITDA。

计算结果需要携带公式与输入：

```json
{
  "metric": "pe_ttm",
  "value": 16.8,
  "formula": "market_cap / net_income_ttm",
  "inputs": {
    "market_cap": 4000000000000,
    "net_income_ttm": 238095238095
  },
  "currency": "CNY",
  "status": "verified"
}
```

币种不同的输入必须先按指定日期和明确汇率转换，并在结果中记录汇率来源。不能将港元股价与人民币盈利直接混算。

### 7.5 优化手段：禁止猜测定义

无法确认含义的指标应直接排除：

```text
指标定义不明确，未纳入现金流质量判断。
```

禁止出现“若按百分比理解”“可能意味着”等先猜定义再用于决策的表达。

### 7.6 优化手段：三表勾稽和期间一致性

至少执行：

- 资产约等于负债加权益。
- 期初现金加现金净变动约等于期末现金。
- 单季、累计和TTM数据不得混算。
- 净利润必须区分归母、持续经营和调整后口径。
- 经营现金流和利润的比较必须使用同一期间。
- 每股数据需结合期内加权平均股数检查。

校验失败时将fundamentals域降级，不允许以“高ROE”“低PE”等为最终评级的核心依据。

## 8. P0-3：新闻标题被升级为确定性事实

### 8.1 观察到的问题

新闻工具主要返回标题、来源、发布时间和链接，但部分报告将标题直接扩展为：

- “调用激增”证明用户增长和需求侧验证。
- “紧急扩容”证明商业化拐点。
- 公司投入capex说明变现路径已经可规划。
- 游戏现金流足以吸收2至3个季度毛利率波动。
- Hy3将在Q3/Q4开始贡献收入。

这些结论缺少正文、公司公告、付费转化率、收入贡献、单位推理成本或管理层指引支持。

另外，Sentiment Analyst和News Analyst使用同一批新闻，Bull、Bear及风险Agent又继续引用这些结论，使同一个标题在多Agent链路中被重复计权。

### 8.2 根因

- 系统没有区分标题、正文、公告和模型推断。
- 新闻源没有证据等级。
- 多Agent共享相同事件时没有事件级去重。
- Prompt允许模型跨越多个因果环节进行推断。
- 最终报告没有要求事实和假设分栏。

### 8.3 优化手段：证据等级

建议采用四级证据体系：

| 等级 | 类型 | 允许用途 |
|---|---|---|
| A | 公司公告、港交所披露、监管文件、正式财报 | 可作为已验证事实 |
| B | 公司官方发布、采访全文、权威统计数据 | 可作为高可信证据 |
| C | 完整媒体正文、券商报告摘要 | 可作为待交叉验证信息 |
| D | 新闻标题、自媒体、评论、社区帖子 | 仅用于情绪或线索发现 |

D级标题不能直接用于收入预测、利润预测、估值或仓位决策。

### 8.4 优化手段：事实与推断分离

每个主张使用结构化对象：

```json
{
  "claim": "Hy3调用量增长",
  "evidence": "新闻标题称调用激增",
  "evidence_level": "D",
  "verified_fact": false,
  "inference": "可能反映试用需求增长",
  "unsupported_extensions": [
    "付费用户增长",
    "收入增长",
    "商业化拐点"
  ]
}
```

报告生成时应使用与证据等级相符的语言：

```text
新闻标题显示调用需求可能增长，但尚无付费转化率、收入贡献或单位推理成本数据。
```

### 8.5 优化手段：事件聚类和独立信源计数

根据以下字段进行新闻聚类：

- 公司和证券代码。
- 事件类型。
- 发生日期。
- 关键实体和产品。
- 标题语义相似度。
- 原始来源或转载链。

如果20篇新闻实际来自3个事件，应显示“3个独立事件簇”，不能将20个标题当成20份独立证据。

Sentiment Analyst可以统计媒体热度，但News Analyst和Research Manager使用的是去重后的事件与证据等级。

### 8.6 优化手段：限制因果推理跨度

对商业化结论使用证据阶梯：

```text
产品发布
→ 调用量
→ 活跃用户
→ 付费转化
→ 收入
→ 毛利
→ 估值
```

缺少中间证据时，不允许从产品发布直接推导收入、利润和目标价。模型可以提出假设，但必须写成待验证条件，不能写成已发生事实。

## 9. P0-4：最终交易参数不一致

### 9.1 观察到的问题

本次报告存在以下冲突：

- 当前价为 `460.20`，但最终摘要写“回踩465–470加仓”；465–470高于当前价，不能称为回踩。
- Neutral Analyst讨论在495–505进行第二次加仓，最终摘要却改成突破481.66后直接加至70%。
- Trader建议首仓30–40%，Portfolio Manager改为25%，完整报告同时保留两个可执行版本。
- Market Analyst为 `HOLD`，News Analyst和Trader为 `BUY`，Portfolio Manager为 `Overweight`，没有统一评级映射。
- 最终目标价630、周期6个月，但主要锚点来自券商660–680的12个月目标价，时间尺度不一致。
- 报告反复使用“上行47.8% vs下行13%”，但460到止损420的直接跌幅约为8.7%，13%的来源没有清晰公式。
- 最终报告一方面称技术趋势尚未确认，另一方面设计了最高90–100%的单标的目标仓位，风险级别与结论措辞不完全匹配。

### 9.2 根因

- 各Agent输出自然语言交易计划，没有共享唯一决策对象。
- Research、Trader、Risk和Portfolio阶段可以各自修改参数，但没有版本和覆盖规则。
- 百分比由模型自行计算。
- Markdown是多个Agent文本的拼接，不是从最终结构化决策统一渲染。
- 输出前没有执行金融和逻辑一致性校验。

### 9.3 优化手段：统一Decision Schema

最终决策应以结构化对象为唯一事实来源：

```json
{
  "rating": "overweight",
  "current_price": 460.2,
  "current_price_as_of": "2026-07-10",
  "initial_position_pct": 25,
  "entry_rules": [
    {
      "condition": "close_above",
      "price": 481.66,
      "confirmation_sessions": 2,
      "target_position_pct": 50
    }
  ],
  "hard_stop": 420,
  "portfolio_cap_pct": 15,
  "base_target": 550,
  "bull_target": 630,
  "horizon_months": 6,
  "confidence": 0.55,
  "data_quality": "degraded"
}
```

Research Manager可以提出建议，Trader转换为候选计划，Risk Agent提出修改，Portfolio Manager负责产生唯一终版。完整报告中的Executive Summary、表格和最终结论均从终版Decision对象渲染。

### 9.4 优化手段：统一评级语义

建议系统内部只使用一个枚举，例如：

```text
strong_sell
sell
underweight
neutral
overweight
buy
strong_buy
```

每个Agent可以给观点，但最终报告必须明确：

- Analyst opinion。
- Research recommendation。
- Executable portfolio decision。

`HOLD`、`BUY`和`Overweight`不能在不同章节中同时作为最终建议出现。

### 9.5 优化手段：确定性一致性校验

报告落盘和`run_completed`之前执行：

- 多头“回踩价”必须低于当前价。
- 多头“突破价”必须高于当前价。
- 加仓后的目标仓位必须单调增加。
- 单标的实际组合占比不得超过portfolio cap。
- 多头止损必须低于入场价。
- 空头止损必须高于入场价。
- 风险比例、收益比例和盈亏比必须由代码计算。
- 时间周期必须与目标价来源匹配。
- Executive Summary必须与Decision对象一致。
- 评级和动作必须符合统一映射。

本次运行应自动识别：

```text
ERROR: pullback level 465-470 is above current price 460.20
ERROR: stated downside 13% conflicts with stop-loss downside 8.73%
ERROR: trader initial position 30-40% conflicts with final position 25%
WARNING: 6-month target is derived from 12-month analyst targets
```

### 9.6 优化手段：分级阻断

建议设置：

- `warning`：可完成运行，但报告显著标注。
- `degraded`：只能输出条件式观点，不输出确定性满仓路径。
- `blocking`：禁止输出BUY/SELL、入场价、仓位和止损。

如果市场数据或财务数据关键字段无效，或者最终Decision存在方向性冲突，应阻断`run_completed`交易决策，改为输出“分析完成，但交易建议因质量门禁未通过而暂缓”。

## 10. P1优化：运行效率、事件持久化与可观测性

### 10.1 重复report_section

本次210条事件中：

| 事件类型 | 数量 | 唯一payload |
|---|---:|---:|
| `report_section` | 98 | 12 |
| `agent_status` | 41 | 3 |
| `message` | 30 | 23 |
| `stats` | 22 | 21 |
| `tool_call` | 17 | 17 |

`report_section`约占1.4 MB；每个Agent的相同报告被反复写入，例如Market Analyst重复20次、Sentiment Analyst重复18次。

优化建议：

- 以 `(run_id, agent, content_hash)` 去重。
- 只有报告首次出现或内容变化时才发`report_section`。
- 状态变化只发`agent_status`，不要重新发全部已有报告。
- SSE replay按事件ID增量恢复，不重复拼装历史报告。
- 数据库可保存report revision，前端只接收最新revision或delta。

### 10.2 Shallow模式token过高

Research depth为1时仍使用113,679输入和42,098输出tokens，不符合Shallow的成本预期。

优化建议：

- 每个分析师输出结构化摘要和有限长度正文。
- 下游只接收上游摘要、关键证据和引用ID，不接收全部长报告。
- Shallow减少辩论轮次和每个风险Agent的最大输出。
- 重复事实建立共享Evidence Store，Agent引用证据ID。
- 在LLM调用前进行token预算审计，超过预算时压缩上下文。

### 10.3 Tool事件可观测性

当前17个`tool_call`没有Agent归属，也没有记录实际vendor、fallback、耗时和结果状态。

建议事件模型：

```text
tool_started
tool_vendor_attempt
tool_vendor_failed
tool_vendor_succeeded
tool_result_summary
```

至少记录：

- `agent`
- `tool_name`
- `vendor`
- `fallback_index`
- `latency_ms`
- `as_of`
- `row_count`
- `status`
- `quality_flags`
- 错误类型，但不记录密钥或token

### 10.4 报告展示

优化建议：

- Report language为中文时，统一最终章节标题和动作术语。
- 报告首屏先显示最终Decision、数据质量和关键冲突。
- 将各Agent原始长报告放在可展开区域。
- 对未验证主张、低等级证据和降级数据使用明显标记。

## 11. P2优化：研究质量

### 11.1 情景估值

避免直接使用单一券商最高目标价。建立：

| 情景 | 概率 | 核心假设 | 目标价 |
|---|---:|---|---:|
| Bear | 待计算 | AI变现不及预期、利润率下滑 | 待模型计算 |
| Base | 待计算 | 核心业务稳定、AI贡献有限 | 待模型计算 |
| Bull | 待计算 | AI商业化超预期、估值扩张 | 待模型计算 |

目标价由盈利、估值倍数、净现金和币种换算共同计算，券商目标价只作为外部比较。

### 11.2 数据域置信度

分别评分：

- Market data confidence。
- Technical indicator confidence。
- Fundamentals confidence。
- News evidence confidence。
- Sentiment coverage confidence。
- Valuation confidence。

最终决策置信度不得高于关键数据域中的最低可信水平，或应采用明确的加权/门槛规则。

### 11.3 事实、推断、假设和触发条件分离

建议所有Agent输出：

```text
Facts
Inferences
Assumptions
Unknowns
Invalidation conditions
```

Portfolio Manager只能将Facts和通过门禁的派生指标作为核心证据；Inference和Assumption必须转化为监控项或情景条件。

### 11.4 催化剂可验证化

每个催化剂都应包含：

- 预期发生日期。
- 权威信息来源。
- 可观测指标。
- 成功阈值。
- 失败阈值。
- 对估值或仓位的具体影响。

例如，不能只写“Q2验证AI叙事”，而应明确关注收入、capex、毛利率、AI订单或管理层指引中的哪些变化。

## 12. 推荐落地顺序

### 第一阶段：建立P0质量门禁

1. 增加市场数据与技术指标validator。
2. 将validator接入vendor fallback链。
3. 为财务字段补齐currency、unit、period和definition。
4. 将常用财务和估值指标改为代码计算。
5. 实现Decision Schema和终稿一致性校验。
6. 增加`verified/degraded/invalid`运行质量状态。

### 第二阶段：治理新闻证据

1. 建立证据等级。
2. 区分标题和正文。
3. 新闻事件聚类去重。
4. 在Prompt和输出schema中拆分事实与推断。
5. 对跨越证据阶梯的商业化推断进行降级或阻断。

### 第三阶段：降低运行成本

1. 去重`report_section`。
2. 为Shallow模式设置token和报告长度预算。
3. 使用共享Evidence Store和证据ID。
4. 只向下游传递结构化摘要。

### 第四阶段：增强研究与UI

1. 加入概率情景和独立估值。
2. 增加数据域置信度。
3. 在WebUI突出数据质量、证据等级和决策冲突。
4. 提供工具fallback和指标计算审计视图。

## 13. 建议验收标准

### P0验收

- 构造异常成交额时，validator能够识别并触发fallback。
- VWMA为0或跨越数量级时，不进入LLM上下文。
- 财务字段缺少币种或期间时，不得计算PE或ROE结论。
- 只有新闻标题时，报告不得使用“已证明商业化拐点”等确定性表述。
- 当前价460且“回踩价”为465时，Decision校验必须失败。
- 所有收益、风险和盈亏比均可由结构化输入重新计算得到。
- `run_completed`应包含整体data quality和未通过门禁列表。

### P1验收

- 每个Agent相同报告只持久化一次。
- 页面刷新后仍能恢复报告和Agent状态。
- Shallow模式token消耗有明确预算并可观测。
- 每次tool调用能够看到Agent、实际vendor、耗时、fallback和质量状态。

### P2验收

- 最终目标价可追溯至情景模型输入，不只来自券商目标价。
- 同一新闻事件不会因转载和跨Agent引用而重复增加证据权重。
- 报告明确区分事实、推断、假设和失效条件。

## 14. 对本次运行结论的重新定性

本次`Overweight`方向并非完全不合理，但底层证据质量不足以支撑报告表现出的精确度和较激进仓位路径：

- 市场价格和成交量有verified snapshot支持，但成交额和VWMA存在明显异常。
- 基本面方向偏正面，但币种、期间和估值计算缺少完整审计链。
- 新闻情绪偏正面，但部分关键商业化判断只来自标题或推断。
- 多周期技术信号仍矛盾。
- 最终交易参数存在明显内部冲突。

因此，在P0门禁实施前，更合适的系统输出应是：

```text
条件式Overweight，数据质量为degraded。
可以保留有限观察仓位，但在财务口径、市场异常字段和关键新闻主张完成验证前，不生成后续大比例加仓指令。
```

这一定性不是对腾讯本身作新的实时投资判断，而是对本次TradingAgents运行产物的质量评估。
