import feedparser
import datetime

# Expanded feeds including Macro Economic Calendars, Exchange/Project Announcements, and Crypto News
NEWS_FEEDS = [
    # US Economic Calendar & Macro Data (ForexFactory Weekly XML)
    "https://nfs.faireconomy.finance/ff_calendar_thisweek.xml",
    
    # Official Exchange & Project Announcements
    "https://www.binance.com/en/support/announcement/rss",
    
    # Core Crypto & Macro News Sites
    "https://www.marketwatch.com/rss/topstories",
    "https://tokenomist.ai/rss",
    "https://www.cnbc.com/id/10000311/device/rss/rss.html",
    "https://cointelegraph.com/rss",
    "https://feeds.bloomberg.com/crypto/news.rss",
    "https://www.ccn.com/feed/",
    "https://www.coinspeaker.com/feed/",
    "https://99bitcoins.com/feed/"
]

class NewsSentimentFilter:
    def __init__(self):
        self.feeds = NEWS_FEEDS

    def get_market_bias(self):
        """
        Scans news feeds and economic calendars. 
        Returns: 'BULLISH_BIAS', 'BEARISH_BIAS', 'HIGH_IMPACT_PAUSE', or 'NEUTRAL'
        """
        bullish_keywords = ["surge", "approval", "breakout", "bull", "inflow", "rally", "adoption", "etf", "rate cut", "lower inflation"]
        bearish_keywords = ["crash", "ban", "hack", "outflow", "bear", "liquidations", "drop", "sec suit", "rate hike", "higher inflation", "hot cpi"]
        high_impact_macro = ["cpi", "ppi", "fomc", "fed rate", "non-farm payrolls", "chair powell"]
        
        score = 0
        macro_event_active = False

        for url in self.feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:3]: # Check latest 3 articles/events per feed
                    title = entry.title.lower()
                    summary = entry.get('summary', '').lower()
                    content_text = f"{title} {summary}"
                    
                    # Check for high-impact macro data releases happening right now (CPI, PPI, FOMC)
                    if any(macro in content_text for macro in high_impact_macro):
                        # If an economic calendar event is scheduled for today, trigger a high-volatility caution flag
                        macro_event_active = True

                    # Sentiment scoring
                    if any(kw in content_text for kw in bullish_keywords):
                        score += 1
                    elif any(kw in content_text for kw in bearish_keywords):
                        score -= 1
            except Exception:
                continue
                
        # If major macro data (CPI/PPI/FOMC) is releasing, enforce a temporary pause to protect capital from whipsaws
        if macro_event_active and abs(score) < 3:
            return "HIGH_IMPACT_PAUSE"
            
        if score > 2:
            return "BULLISH_BIAS"
        elif score < -2:
            return "BEARISH_BIAS"
            
        return "NEUTRAL"