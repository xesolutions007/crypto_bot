class RiskManager:
    def __init__(self, entry_price, direction, risk_amount, target_rr=5.0):
        self.entry_price = entry_price
        self.direction = direction
        self.risk_amount = risk_amount
        
        if direction == "LONG":
            self.stop_loss = entry_price - risk_amount
            self.take_profit = entry_price + (risk_amount * target_rr)
            self.be_trigger = entry_price + (risk_amount * 1.5) # Move SL to entry at 1.5R
        else:
            self.stop_loss = entry_price + risk_amount
            self.take_profit = entry_price - (risk_amount * target_rr)
            self.be_trigger = entry_price - (risk_amount * 1.5)
            
        self.be_activated = False
        self.status = "ACTIVE"

    def monitor_trade(self, current_price):
        if self.direction == "LONG":
            if not self.be_activated and current_price >= self.be_trigger:
                self.stop_loss = self.entry_price + 0.0002 # Secure fee buffer
                self.be_activated = True
            if current_price >= self.take_profit:
                self.status = "WIN_TP_1_5"
            elif current_price <= self.stop_loss:
                self.status = "BREAK_EVEN" if self.be_activated else "LOSS"
        else:
            if not self.be_activated and current_price <= self.be_trigger:
                self.stop_loss = self.entry_price - 0.0002
                self.be_activated = True
            if current_price <= self.take_profit:
                self.status = "WIN_TP_1_5"
            elif current_price >= self.stop_loss:
                self.status = "BREAK_EVEN" if self.be_activated else "LOSS"
        return self.status