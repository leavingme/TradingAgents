# 🚀 迭代记录：多源全网搜索与社交舆情集成系统升级 (2026-03-08)

## 🎯 核心目标
重构 TradingAgents 的新闻和舆情获取能力，突破 Alpha Vantage API 的速率限制和信息陈旧问题，为 Agent 赋予“**全网实时搜索**”以及“**真实高质量社交媒体侦听**”的能力。

---

## 🛠️ 具体迭代与改进详情

### 1. 社交媒体舆情 (Twitter) 真实接入
*   **痛点**：此前的 `social_media_analyst` 虽然名为社交媒体分析师，但本质上仍在调用 Alpha Vantage 的财经长文 API，缺乏散户情绪与实时市场探讨的感知。
*   **解决方案**：
    *   通过复用 `x-news` 项目中的 `bird` CLI 环境，直接抓取真实的 Twitter/X 实时动态。
    *   创建专门的 `social_media_tools.py`，新增工具 `get_twitter_stock_sentiment`。
*   **质量控制 (高热度过滤)**：为了避免广告与无效噪音，严格限定检索参数，只抓取满足 `min_faves:100 OR min_retweets:100 OR min_replies:100` 的高热度精华帖。

### 2. 构建多供应商混合互联网搜索体系 (Internet Search Vendors)
*   为了不仅依赖单一来源并保证服务的绝对稳定，构建了一套多层的智能回退全网搜索架构（代码位于 `dataflows/internet_search.py`），支持如下供应商：
    1.  **Kimi Web Search (`web_search`)**：系统默认的高质量深度中文 / 搜索融合方案。
    2.  **Tavily (`tavily`)**：专为大模型 (AI Agent) 打造的高质量网页摘要搜索（已配置 API Key）。
    3.  **Serper (`serper`)**：高速高精度的 Google 搜索结果镜像（已配置 API Key）。
    4.  **DuckDuckGo (`duckduckgo`)**：基于 `ddgs` 包的完全免费无限制搜索池。

### 3. 数据流链式智能回退 (Fallback Override)
*   **配置更新**：修改 `default_config.py`，实现了数据源的链式容灾能力。
*   **最终设定的优先级**：`"news_data": "alpha_vantage, web_search, duckduckgo"`
    *   **Alpha Vantage 第一**：优先保证获取专业、正统的英文机构财经数据。
    *   **Kimi 搜索 第二**：若主源受限或无足够信息，利用其强大的 AI 即时搜索功能补足最新的中/英文市场概况。
    *   **DuckDuckGo 第三**：当所有受控接口都不可用时的终极免费兜底方案。

### 4. Agent 武器库拓展
*   **新闻分析师 (`news_analyst`)** 现配备武器：
    *   `get_news` & `get_global_news` (走上述的链式回退流程)
    *   `search_internet_news` (补充能力：显式指定任意搜索引擎)
*   **社交分析师 (`social_media_analyst`)** 现配备武器：
    *   `get_twitter_stock_sentiment` (核心情绪抓取，带百赞过滤机制)
    *   `get_news` (补充对比)

### 5. 提供开发测试全矩阵支持
*   新增了全方位的诊断与验证脚本，确保各线路正常连通：
    1.  `test_kimi_websearch.py` / `test_litellm_websearch.py`: 测试大模型和内置大模型搜索链。
    2.  `test_social_integration.py`: 测试新版舆情分析师的工作流连通状态。
    3.  `verify_all_search.py`: “全能一键诊断”，并发执行四大全网搜刮接口验证。

---

## 🌟 阶段成果总结
经历了本次更新，TradingAgents 从只能获取单一过期消息的“爬虫 1.0”，进化成了拥有**多重智能降级链路、高阈值垃圾信息过滤**、以及**全媒体覆盖矩阵（专业研报 + 谷歌全网 + Twitter散户** 的高级研报分析中台系统。
