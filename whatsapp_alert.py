"""WhatsApp notification placeholder.

No messages are sent by this module. Configure a supported provider and explicit
user opt-in before implementing any real WhatsApp delivery.
"""


def send_whatsapp_alert(message, phone_number=None):
    """Safely report that delivery is not configured; never print personal data."""
    return {
        "sent": False,
        "status": "not_configured",
        "message": "WhatsApp delivery is not implemented. No message was sent.",
    }
