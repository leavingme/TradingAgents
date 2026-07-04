# 长桥 (Longbridge) 数据源集成指南

## 已完成集成

### 1. 新增文件
- `tradingagents/dataflows/longbridge.py` - 长桥数据源实现
- `longbridge_quote.py` - 独立行情查询工具
- `demo_longbridge_analysis.py` - TradingAgents + 长桥分析示例

### 2. 修改文件
- `tradingagents/dataflows/interface.py` - 添加长桥到数据源路由
- `tradingagents/default_config.py` - 默认使用长桥数据源

### 3. 支持功能
| 功能 | 状态 | 说明 |
|------|------|------|
| 港股行情 | ✅ | 1810.HK, 0700.HK 等 |
| 美股行情 | ✅ | NVDA.US, AAPL.US 等 |
| 技术指标 | ✅ | SMA, RSI, MACD |
| K线数据 | ✅ | 日K数据 |
| 实时报价 | ✅ | 盘口数据 |

### 4. 使用方法

#### 方式1: 直接使用 TradingAgents (推荐)
```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["data_vendors"] = {
    "core_stock_apis": "longbridge",
    "technical_indicators": "longbridge",
    "fundamental_data": "yfinance",
    "news_data": "yfinance",
}

ta = TradingAgentsGraph(debug=True, config=config)
state, decision = ta.propagate("1810.HK", "2026-02-28")
```

#### 方式2: 独立查询工具
```bash
./longbridge_quote.py              # 查小米
./longbridge_quote.py 0700.HK      # 查腾讯
./longbridge_quote.py NVDA         # 查英伟达
```

#### 方式3: 运行分析示例
```bash
python demo_longbridge_analysis.py
```

### 5. API 配置
配置文件位于: `tradingagents/dataflows/longbridge.py`
- App Key, App Secret, Access Token 已内置
- 可通过环境变量覆盖: `LONGBRIDGE_APP_KEY`, `LONGBRIDGE_APP_SECRET`, `LONGBRIDGE_ACCESS_TOKEN`

### 6. 支持的股票格式
| 格式 | 示例 | 说明 |
|------|------|------|
| 港股 | `1810.HK`, `0700.HK` | 标准港股代码 |
| 美股 | `NVDA`, `AAPL` | 自动添加 .US 后缀 |
| 纯数字 | `1810` | 自动识别为港股 |

### 7. 测试验证
```bash
python test_longbridge_integration.py
```
