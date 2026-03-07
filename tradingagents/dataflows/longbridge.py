"""
长桥 (Longbridge) 数据源模块
支持港股、美股实时行情和K线数据
"""
from typing import Annotated
from datetime import datetime, timedelta
import os
import pandas as pd
from longport.openapi import QuoteContext, Config, AdjustType, Period

def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

# 全局上下文缓存
_quote_context = None

def get_quote_context():
    """获取或创建 QuoteContext（单例模式）"""
    global _quote_context
    if _quote_context is None:
        config = Config(
            app_key=_require_env("LONGBRIDGE_APP_KEY"),
            app_secret=_require_env("LONGBRIDGE_APP_SECRET"),
            access_token=_require_env("LONGBRIDGE_ACCESS_TOKEN"),
        )
        _quote_context = QuoteContext(config)
    return _quote_context


def get_longbridge_stock_data(
    symbol: Annotated[str, "ticker symbol of the company (e.g., 1810.HK, 0700.HK, NVDA)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
):
    """
    从长桥获取股票历史数据
    支持港股 (.HK) 和美股
    """
    try:
        ctx = get_quote_context()
        
        # 计算需要获取多少天的数据
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        days_needed = (end - start).days + 1
        
        # 获取K线数据
        klines = ctx.candlesticks(symbol, Period.Day, max(days_needed + 5, 30), AdjustType.NoAdjust)
        
        if not klines:
            return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"
        
        # 转换为 DataFrame
        data = []
        for k in klines:
            data.append({
                'Date': k.timestamp.date(),
                'Open': round(float(k.open), 2),
                'High': round(float(k.high), 2),
                'Low': round(float(k.low), 2),
                'Close': round(float(k.close), 2),
                'Volume': int(k.volume),
            })
        
        df = pd.DataFrame(data)
        df['Date'] = pd.to_datetime(df['Date'])
        df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]
        df = df.sort_values('Date')
        
        if df.empty:
            return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"
        
        df.set_index('Date', inplace=True)
        
        # 转换为CSV
        csv_string = df.to_csv()
        header = f"# Stock data for {symbol} from {start_date} to {end_date}\n"
        header += f"# Total records: {len(df)}\n"
        header += f"# Data retrieved from Longbridge API on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        return header + csv_string
        
    except Exception as e:
        return f"Error fetching data for {symbol}: {str(e)}"


def get_longbridge_indicators(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """
    从长桥获取技术指标分析
    """
    try:
        ctx = get_quote_context()
        
        # 获取K线数据
        total_days = look_back_days + 50  # 多获取一些用于计算指标
        klines = ctx.candlesticks(symbol, Period.Day, total_days, AdjustType.NoAdjust)
        
        if not klines:
            return f"No data available for {symbol}"
        
        # 转换为 DataFrame
        data = []
        for k in klines:
            data.append({
                'date': k.timestamp.date(),
                'open': float(k.open),
                'high': float(k.high),
                'low': float(k.low),
                'close': float(k.close),
                'volume': int(k.volume),
            })
        
        df = pd.DataFrame(data)
        df = df.sort_values('date')
        
        # 使用 stockstats 计算指标
        try:
            df['close'] = df['close'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['open'] = df['open'].astype(float)
            df['volume'] = df['volume'].astype(float)
            
            # 重命名列以符合 stockstats 格式
            df_renamed = df.rename(columns={
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume',
                'date': 'Date'
            })
            df_renamed['Date'] = pd.to_datetime(df_renamed['Date'])
            df_renamed.set_index('Date', inplace=True)
        except Exception as e:
            pass  # 如果stockstats失败，使用手动计算
        
        # 计算常用指标
        indicators_report = []
        
        # SMA
        if len(df) >= 50:
            sma50 = df['close'].rolling(window=50).mean().iloc[-1]
            indicators_report.append(f"50 SMA: {sma50:.2f}")
        
        if len(df) >= 20:
            sma20 = df['close'].rolling(window=20).mean().iloc[-1]
            indicators_report.append(f"20 SMA: {sma20:.2f}")
        
        # RSI
        if len(df) >= 14:
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1]
            indicators_report.append(f"RSI(14): {current_rsi:.2f}")
            if current_rsi > 70:
                indicators_report.append("  → RSI indicates overbought conditions (>70)")
            elif current_rsi < 30:
                indicators_report.append("  → RSI indicates oversold conditions (<30)")
        
        # MACD
        if len(df) >= 26:
            exp1 = df['close'].ewm(span=12, adjust=False).mean()
            exp2 = df['close'].ewm(span=26, adjust=False).mean()
            macd = exp1 - exp2
            signal = macd.ewm(span=9, adjust=False).mean()
            histogram = macd - signal
            indicators_report.append(f"MACD: {macd.iloc[-1]:.4f}")
            indicators_report.append(f"MACD Signal: {signal.iloc[-1]:.4f}")
            indicators_report.append(f"MACD Histogram: {histogram.iloc[-1]:.4f}")
        
        # 当前价格
        current_price = df['close'].iloc[-1]
        prev_price = df['close'].iloc[-2] if len(df) > 1 else current_price
        change = current_price - prev_price
        change_pct = (change / prev_price) * 100 if prev_price != 0 else 0
        
        report = f"""
Technical Indicators Report for {symbol}
Report Date: {curr_date}
Lookback Period: {look_back_days} days

Current Price: {current_price:.2f} ({change:+.2f}, {change_pct:+.2f}%)

Key Indicators:
{chr(10).join(indicators_report)}

Data Source: Longbridge API
"""
        return report.strip()
        
    except Exception as e:
        return f"Error calculating indicators for {symbol}: {str(e)}"


# 兼容美股格式（添加 .US 后缀）
def normalize_symbol(symbol: str) -> str:
    """
    标准化股票代码
    - 港股：1810.HK, 0700.HK
    - 美股：NVDA → NVDA.US（长桥美股需要 .US 后缀）
    """
    symbol = symbol.upper().strip()
    
    # 如果已经是标准格式，直接返回
    if '.HK' in symbol or '.US' in symbol or '.' in symbol:
        return symbol
    
    # 纯数字通常是港股
    if symbol.isdigit():
        return f"{symbol.zfill(4)}.HK"
    
    # 否则认为是美股（长桥美股需要 .US 后缀）
    return f"{symbol}.US"


# 统一的接口函数
def get_stock_data(symbol, start_date, end_date):
    """统一接口：获取股票数据"""
    symbol = normalize_symbol(symbol)
    return get_longbridge_stock_data(symbol, start_date, end_date)


def get_indicators(symbol, indicator, curr_date, look_back_days):
    """统一接口：获取技术指标"""
    symbol = normalize_symbol(symbol)
    return get_longbridge_indicators(symbol, indicator, curr_date, look_back_days)
