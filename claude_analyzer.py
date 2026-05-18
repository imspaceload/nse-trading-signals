from typing import List

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL


def analyze_market(
    spot_prices: dict,
    signal: dict,
    rsi: dict,
    macd: dict,
    supertrend: dict,
    vwap: dict,
    oi: dict,
    news: List[dict],
) -> str:
    if not ANTHROPIC_API_KEY:
        return "Set the ANTHROPIC_API_KEY environment variable to enable Claude analysis."

    headlines_text = "\n".join(
        f"- [{n['sentiment']}] {n['headline']}" for n in news if n.get("headline")
    )

    prompt = f"""You are an Indian stock market analyst. Based on the following real-time data, give a 2-3 line trading verdict.

SPOT PRICES:
- NIFTY: {spot_prices.get('nifty', 'N/A')}
- BANKNIFTY: {spot_prices.get('banknifty', 'N/A')}

SIGNAL: {signal['action']} (Entry: {signal['entry_price']}, SL: {signal['stop_loss']}, Target: {signal['target']})
Indicator alignment: {signal['buy_count']} BUY, {signal['sell_count']} SELL, {signal['neutral_count']} NEUTRAL

INDICATORS:
- RSI: {rsi['value']} ({rsi['signal']})
- MACD: Line={macd['macd_line']}, Signal={macd['signal_line']}, Hist={macd['histogram']} ({macd['signal']})
- SuperTrend: {supertrend['value']} Direction={'UP' if supertrend['direction'] == 1 else 'DOWN'} ({supertrend['signal']})
- VWAP: {vwap['value']} vs Price {vwap['current_price']} ({vwap['signal']})
- OI: PCR={oi['pcr']}, Net OI Change={oi['net_oi_change']} ({oi['signal']})

LATEST NEWS HEADLINES (scraped from Moneycontrol):
{headlines_text}

Rules:
- Give a clear BUY/SELL/HOLD verdict with reasoning
- Reference specific indicator values and news sentiment
- Every trade suggestion MUST include a stop loss
- Be concise: 2-3 lines maximum
- Do NOT fabricate any news or data — only reference what is provided above"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        return f"Claude analysis unavailable: {e}"
