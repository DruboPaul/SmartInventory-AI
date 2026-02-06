"""
Cloud Function: Real-Time Inventory Alert System

Triggered by Pub/Sub messages from the 'live-sales' topic.
Processes sale events and sends Telegram alerts for:
  - High-value transactions (> $120)
  - Low stock warnings (< 5 units)

Deployment:
    gcloud functions deploy process_sale_event \
        --runtime python311 \
        --trigger-topic live-sales \
        --set-env-vars TELEGRAM_BOT_TOKEN=xxx,TELEGRAM_CHAT_ID=xxx
"""

import base64
import json
import os
import requests
from datetime import datetime

# Stock Levels (Dynamically loaded from knowledge base)
STOCK_LEVELS = {}

def load_stock_levels():
    """Load current stock levels from shared knowledge base."""
    global STOCK_LEVELS
    kb_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base/products.json")
    
    # Defaults
    STOCK_LEVELS = {
        "SKU001": 50, "SKU002": 30, "SKU003": 20, "SKU004": 15, "SKU005": 10,
    }

    if os.path.exists(kb_path):
        try:
            with open(kb_path, "r") as f:
                data = json.load(f)
            new_levels = {p["id"]: p.get("stock", 0) for p in data.get("products", [])}
            if new_levels:
                STOCK_LEVELS = new_levels
                print(f"✅ Alert System synchronized: {len(STOCK_LEVELS)} items tracked.")
        except Exception as e:
            print(f"⚠️ Error syncing Alert System: {e}")

# Initial load
load_stock_levels()

# Thresholds
HIGH_VALUE_THRESHOLD = float(os.environ.get("HIGH_VALUE_THRESHOLD", 120))
LOW_STOCK_THRESHOLD = int(os.environ.get("LOW_STOCK_THRESHOLD", 5))


def process_sale_event(event, context):
    """
    Main Cloud Function entry point.
    Triggered from a message on a Cloud Pub/Sub topic.
    
    Args:
        event (dict): Event payload containing 'data' key
        context (google.cloud.functions.Context): Metadata for the event
    """
    # 1. Decode the Pub/Sub message
    try:
        pubsub_message = base64.b64decode(event["data"]).decode("utf-8")
        data = json.loads(pubsub_message)
    except Exception as e:
        print(f"❌ Failed to decode message: {e}")
        return
    
    print(f"📥 Processing: {data.get('transaction_id', 'UNKNOWN')}")
    
    # 2. Extract sale details
    product_id = data.get("product_id", "UNKNOWN")
    product_name = data.get("product_name", product_id)
    quantity = data.get("quantity", 1)
    total = data.get("total", data.get("price", 0))
    store_id = data.get("store_id", "UNKNOWN")
    category = data.get("category", "UNKNOWN")
    timestamp = data.get("timestamp", datetime.now().isoformat())
    
    # 3. Update stock levels (simulated)
    alerts = []
    
    if product_id in STOCK_LEVELS:
        STOCK_LEVELS[product_id] -= quantity
        current_stock = STOCK_LEVELS[product_id]
        
        # Check for low stock
        if current_stock <= LOW_STOCK_THRESHOLD:
            alerts.append({
                "type": "LOW_STOCK",
                "emoji": "⚠️",
                "title": "Low Stock Alert!",
                "details": [
                    f"📦 Product: {product_name}",
                    f"📊 Remaining: {current_stock} units",
                    f"🏪 Last Sale: {store_id}",
                ],
            })
            print(f"⚠️ LOW STOCK: {product_name} = {current_stock} units")
    
    # 4. Check for high-value transaction
    if total > HIGH_VALUE_THRESHOLD:
        alerts.append({
            "type": "HIGH_VALUE",
            "emoji": "🚀",
            "title": "High-Value Sale Detected!",
            "details": [
                f"💰 Amount: ${total:.2f}",
                f"📦 Product: {product_name}",
                f"🏪 Store: {store_id}",
                f"📁 Category: {category}",
            ],
        })
        print(f"🚀 HIGH VALUE: ${total:.2f} at {store_id}")
    
    # 5. Send Telegram alerts
    if alerts:
        send_alerts(alerts, timestamp)
    
    print(f"✅ Processed: {data.get('transaction_id')}")


def send_alerts(alerts: list, timestamp: str):
    """Send formatted alerts to Telegram."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("⚠️ Telegram credentials not configured. Skipping alert.")
        return
    
    for alert in alerts:
        message_lines = [
            f"{alert['emoji']} *{alert['title']}*",
            "",
            *alert["details"],
            "",
            f"🕒 {timestamp}",
        ]
        message = "\n".join(message_lines)
        
        send_telegram_message(bot_token, chat_id, message)


def send_telegram_message(token: str, chat_id: str, message: str):
    """Send a message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        print("📲 Telegram Alert Sent!")
    except requests.exceptions.RequestException as e:
        print(f"❌ Telegram Error: {e}")


# For local testing with functions-framework
# Run: functions-framework --target=process_sale_event --signature-type=event
if __name__ == "__main__":
    # Simulate a Pub/Sub event for local testing
    test_event = {
        "data": base64.b64encode(
            json.dumps({
                "transaction_id": "TEST-001",
                "product_id": "SKU005",
                "product_name": "Winter Jacket",
                "category": "Jacket",
                "store_id": "Berlin_01",
                "quantity": 2,
                "price": 149.99,
                "total": 299.98,
                "timestamp": datetime.now().isoformat(),
            }).encode()
        ).decode()
    }
    
    process_sale_event(test_event, None)
