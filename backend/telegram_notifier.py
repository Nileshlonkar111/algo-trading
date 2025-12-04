import os
import requests
import logging
import time

logger = logging.getLogger("TelegramNotifier")

class TelegramNotifier:
    def __init__(self):
        self.bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.enabled = bool(self.bot_token and self.chat_id)
        
        if not self.enabled:
            logger.warning("[TELEGRAM] Bot token or chat ID not set. Telegram notifications disabled.")
        else:
            logger.info("[TELEGRAM] Telegram notifications enabled")
    
    def send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send a Telegram message with error handling and timeout"""
        if not self.enabled:
            logger.debug("[TELEGRAM] Notifications disabled, skipping")
            return False
        
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode
        }
        
        try:
            logger.info("[TELEGRAM] Sending notification...")
            start_time = time.time()
            response = requests.post(url, data=payload, timeout=5)
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                logger.info(f"[TELEGRAM] ✅ Notification sent. Delay: {elapsed:.3f}s")
                return True
            else:
                logger.error(f"[TELEGRAM] Failed with status {response.status_code}: {response.text}")
                return False
        except Exception as e:
            logger.error(f"[TELEGRAM] Notification failed: {e}")
            return False
    
    def send_ema_crossover_alert(self, signal_side: str, ema5: float, ema20: float,
                                  spot_ltp: float, atm: int, symbol: str = None) -> bool:
        """Send EMA crossover alert with rich formatting"""
        emoji = "🔵" if signal_side == "CE" else "🔴"
        direction = "BULLISH" if signal_side == "CE" else "BEARISH"
        crossover_type = "ABOVE" if signal_side == "CE" else "BELOW"
        
        message = f"""
{emoji} <b>EMA CROSSOVER DETECTED!</b> {emoji}

<b>Direction:</b> {direction} ({signal_side})
<b>Spot Price:</b> ₹{spot_ltp:.2f}
<b>ATM Strike:</b> {atm}

<b>Technical Details:</b>
• EMA5: {ema5:.2f}
• EMA20: {ema20:.2f}
• Difference: {abs(ema5 - ema20):.2f}

<b>Signal:</b> EMA5 crossed {crossover_type} EMA20
"""
        
        if symbol:
            message += f"\n<b>Target Symbol:</b> {symbol}"
        
        message += f"\n\n⏰ <i>Time: {time.strftime('%Y-%m-%d %H:%M:%S IST')}</i>"
        
        return self.send_message(message)
    
    def send_session_summary(self, trade_logs: list, positions: dict, realized_pnl: float,
                            capital_base: float, session_start: str, session_end: str) -> bool:
        """Send comprehensive end-of-day trading session summary"""
        
        # Calculate statistics
        total_trades = len([log for log in trade_logs if log.get('action') == 'BUY' and log.get('status') == 'SUCCESS'])
        winning_trades = len([log for log in trade_logs if log.get('action') == 'SELL' and log.get('status') == 'SUCCESS' and log.get('pnl', 0) > 0])
        losing_trades = len([log for log in trade_logs if log.get('action') == 'SELL' and log.get('status') == 'SUCCESS' and log.get('pnl', 0) < 0])
        
        pnl_percentage = (realized_pnl / capital_base * 100) if capital_base > 0 else 0
        win_rate = (winning_trades / (winning_trades + losing_trades) * 100) if (winning_trades + losing_trades) > 0 else 0
        
        # Determine overall result emoji
        if realized_pnl > 0:
            result_emoji = "✅💰"
        elif realized_pnl < 0:
            result_emoji = "❌📉"
        else:
            result_emoji = "➖"
        
        # Build the message
        message = f"""
{result_emoji} <b>TRADING SESSION SUMMARY</b> {result_emoji}

📅 <b>Date:</b> {session_end.split()[0]}
⏰ <b>Session:</b> {session_start} - {session_end}

💼 <b>PERFORMANCE</b>
━━━━━━━━━━━━━━━━
<b>P&L:</b> ₹{realized_pnl:.2f} ({pnl_percentage:+.2f}%)
<b>Capital Base:</b> ₹{capital_base:,.0f}

📊 <b>TRADE STATISTICS</b>
━━━━━━━━━━━━━━━━
<b>Total Entries:</b> {total_trades}
<b>Winning Trades:</b> {winning_trades} ✅
<b>Losing Trades:</b> {losing_trades} ❌
<b>Win Rate:</b> {win_rate:.1f}%
"""
        
        # Add individual trade details if any
        if total_trades > 0:
            message += "\n📝 <b>TRADE DETAILS</b>\n━━━━━━━━━━━━━━━━\n"
            
            trade_count = 0
            for log in trade_logs:
                if log.get('action') == 'SELL' and log.get('status') == 'SUCCESS':
                    trade_count += 1
                    symbol = log.get('symbol', 'N/A')
                    pnl = log.get('pnl', 0)
                    pnl_pct = log.get('pnl_pct', 0)
                    emoji = "✅" if pnl > 0 else "❌"
                    
                    message += f"{trade_count}. {emoji} <code>{symbol}</code>\n"
                    message += f"   P&L: ₹{pnl:.2f} ({pnl_pct:+.2f}%)\n"
                    
                    # Limit to 10 trades to avoid message length issues
                    if trade_count >= 10:
                        remaining = total_trades - 10
                        if remaining > 0:
                            message += f"\n... and {remaining} more trade(s)\n"
                        break
        
        # Check for open positions
        open_positions = [sym for sym, pos in positions.items() if pos.get('status') == 'OPEN']
        if open_positions:
            message += f"\n⚠️ <b>OPEN POSITIONS:</b> {len(open_positions)}\n"
            for sym in open_positions[:5]:  # Show max 5
                message += f"• <code>{sym}</code>\n"
        
        # Add final notes
        message += f"\n━━━━━━━━━━━━━━━━\n"
        if realized_pnl > 0:
            message += "🎉 <b>Great session! Keep it up!</b>"
        elif realized_pnl < 0:
            message += "💪 <b>Learn and improve for tomorrow!</b>"
        else:
            message += "📊 <b>Flat session. Stay disciplined!</b>"
        
        message += f"\n\n🤖 <i>Automated summary generated at {time.strftime('%H:%M:%S IST')}</i>"
        
        return self.send_message(message)