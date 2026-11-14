import ccxt
import os

# CONFIGURATION SETTINGS
EXCHANGE_ID = 'bybit'
SANDBOX_MODE = True  # True for Bybit Testnet (Paper Trading), False for Live
LEVERAGE = 7
TARGET_RR = 5.0
WHATSAPP_NUMBER = '+94777915274'

# Crypto Pairs Only
ACTIVE_PAIRS = ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT']

def get_exchange_client():
    exchange_class = getattr(ccxt, EXCHANGE_ID)
    exchange = exchange_class({
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'} # Linear Perpetual Futures
    })
    if SANDBOX_MODE:
        exchange.set_sandbox_mode(True)
    return exchange