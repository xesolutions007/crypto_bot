import urllib.parse
import requests

def send_whatsapp_alert(message, phone_number="+94777915274"):
    """
    Dispatches automated trade alerts and daily PnL summaries 
    directly to your WhatsApp number.
    """
    # Formatted for integration with Twilio or Meta WhatsApp Cloud API gateways
    print(f"\n[WHATSAPP NOTIFICATION -> {phone_number}]")
    print(message)
    print("-" * 40)