"""Position-level stop, target and break-even state for paper trades.

risk_amount is a PRICE DISTANCE (not account-currency risk). Position sizing must
be calculated separately from account equity and quantity.
"""


class RiskManager:
    def __init__(self, entry_price, direction, risk_amount, target_rr=5.0,
                 break_even_r=1.5, fee_buffer=0.0):
        if entry_price <= 0 or risk_amount <= 0 or target_rr <= 0:
            raise ValueError("entry_price, risk_amount and target_rr must be positive")
        direction = str(direction).upper()
        if direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        if break_even_r <= 0 or fee_buffer < 0:
            raise ValueError("break_even_r must be positive and fee_buffer non-negative")

        self.entry_price = float(entry_price)
        self.direction = direction
        self.risk_amount = float(risk_amount)
        self.target_rr = float(target_rr)
        self.fee_buffer = float(fee_buffer)
        self.stop_loss = (
            self.entry_price - self.risk_amount if direction == "LONG"
            else self.entry_price + self.risk_amount
        )
        self.initial_stop_loss = self.stop_loss
        self.take_profit = (
            self.entry_price + self.risk_amount * self.target_rr if direction == "LONG"
            else self.entry_price - self.risk_amount * self.target_rr
        )
        self.be_trigger = (
            self.entry_price + self.risk_amount * break_even_r if direction == "LONG"
            else self.entry_price - self.risk_amount * break_even_r
        )
        self.be_activated = False
        self.status = "ACTIVE"

    def monitor_trade(self, current_price):
        if self.status != "ACTIVE":
            return self.status
        if current_price is None or float(current_price) <= 0:
            raise ValueError("current_price must be positive")

        price = float(current_price)
        if self.direction == "LONG":
            if not self.be_activated and price >= self.be_trigger:
                self.stop_loss = self.entry_price + self.fee_buffer
                self.be_activated = True
            if price >= self.take_profit:
                self.status = "WIN_TP"
            elif price <= self.stop_loss:
                self.status = "BREAK_EVEN" if self.be_activated else "LOSS"
        else:
            if not self.be_activated and price <= self.be_trigger:
                self.stop_loss = self.entry_price - self.fee_buffer
                self.be_activated = True
            if price <= self.take_profit:
                self.status = "WIN_TP"
            elif price >= self.stop_loss:
                self.status = "BREAK_EVEN" if self.be_activated else "LOSS"
        return self.status

    def snapshot(self):
        return {
            "entry_price": self.entry_price,
            "direction": self.direction,
            "initial_stop_loss": self.initial_stop_loss,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "break_even_trigger": self.be_trigger,
            "break_even_activated": self.be_activated,
            "target_rr": self.target_rr,
            "status": self.status,
        }
