"""
Pub/Sub Publisher - Simulates Real-Time Sales Events

This script simulates a retail POS system sending sale events to Google Pub/Sub.
Use this to test the Cloud Function locally or in production.

Usage:
    python publisher.py                    # Run with default settings
    python publisher.py --interval 0.5     # Send events every 0.5 seconds
    python publisher.py --count 100        # Send exactly 100 events then stop
"""

import argparse
import json
import random
import time
from datetime import datetime

# Optional: Uncomment for actual GCP Pub/Sub publishing
# from google.cloud import pubsub_v1
import os

# Configuration (Dynamically loaded from knowledge base)
PRODUCT_CATALOG = []

def load_catalog():
    """Load product catalog from shared knowledge base."""
    global PRODUCT_CATALOG
    kb_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base/products.json")
    
    # Defaults
    PRODUCT_CATALOG = [
        {"id": "SKU001", "name": "Red T-Shirt", "category": "T-Shirt", "base_price": 29.99},
        {"id": "SKU002", "name": "Blue Jeans", "category": "Jeans", "base_price": 79.99},
        {"id": "SKU003", "name": "White Sneakers", "category": "Sneakers", "base_price": 129.99},
        {"id": "SKU004", "name": "Black Dress", "category": "Dress", "base_price": 99.99},
        {"id": "SKU005", "name": "Winter Jacket", "category": "Jacket", "base_price": 149.99},
    ]

    if os.path.exists(kb_path):
        try:
            with open(kb_path, "r") as f:
                data = json.load(f)
            new_catalog = data.get("products", [])
            if new_catalog:
                PRODUCT_CATALOG = new_catalog
                print(f"✅ Simulator synchronized: {len(PRODUCT_CATALOG)} products in catalog.")
        except Exception as e:
            print(f"⚠️ Error syncing Simulator: {e}")

# Initial load
load_catalog()

STORES = ["Berlin_01", "Hamburg_02", "Munich_01", "Online_Store"]


def generate_sale_event():
    """Generate a realistic sale event."""
    product = random.choice(PRODUCT_CATALOG)
    quantity = random.randint(1, 3)
    
    # Simulate price variations (discounts, etc.)
    price = round(product["base_price"] * random.uniform(0.85, 1.0), 2)
    
    return {
        "transaction_id": f"TXN-{int(time.time() * 1000)}-{random.randint(1000, 9999)}",
        "product_id": product["id"],
        "product_name": product["name"],
        "category": product["category"],
        "store_id": random.choice(STORES),
        "quantity": quantity,
        "price": price,
        "total": round(price * quantity, 2),
        "timestamp": datetime.now().isoformat(),
    }


def publish_to_console(event: dict):
    """Print event to console (for local testing)."""
    print(f"📤 SALE: {event['product_name']} x{event['quantity']} = ${event['total']:.2f} @ {event['store_id']}")
    return True


def publish_to_pubsub(event: dict, project_id: str, topic_id: str):
    """Publish event to Google Pub/Sub (for production)."""
    try:
        from google.cloud import pubsub_v1
        
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(project_id, topic_id)
        
        message_data = json.dumps(event).encode("utf-8")
        future = publisher.publish(topic_path, message_data)
        
        print(f"✅ Published message ID: {future.result()}")
        return True
    except ImportError:
        print("❌ google-cloud-pubsub not installed. Run: pip install google-cloud-pubsub")
        return False
    except Exception as e:
        print(f"❌ Failed to publish: {e}")
        return False


def run_publisher(interval: float = 1.0, count: int = None, use_pubsub: bool = False,
                  project_id: str = None, topic_id: str = "live-sales"):
    """
    Main publisher loop.
    
    Args:
        interval: Seconds between events
        count: Number of events to send (None = infinite)
        use_pubsub: If True, publish to GCP Pub/Sub; else print to console
        project_id: GCP Project ID (required if use_pubsub is True)
        topic_id: Pub/Sub Topic ID
    """
    print("=" * 60)
    print("🚀 Real-Time Sales Event Publisher")
    print(f"   Mode: {'Pub/Sub' if use_pubsub else 'Console (Local Testing)'}")
    print(f"   Interval: {interval}s")
    print(f"   Count: {count if count else 'Infinite'}")
    print("=" * 60)
    print("Press Ctrl+C to stop...\n")
    
    events_sent = 0
    
    try:
        while count is None or events_sent < count:
            event = generate_sale_event()
            
            if use_pubsub:
                publish_to_pubsub(event, project_id, topic_id)
            else:
                publish_to_console(event)
            
            events_sent += 1
            
            # Random jitter for realistic traffic
            sleep_time = interval * random.uniform(0.5, 1.5)
            time.sleep(sleep_time)
            
    except KeyboardInterrupt:
        print(f"\n\n🛑 Publisher stopped. Total events: {events_sent}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pub/Sub Sales Event Publisher")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between events")
    parser.add_argument("--count", type=int, default=None, help="Number of events (default: infinite)")
    parser.add_argument("--pubsub", action="store_true", help="Publish to GCP Pub/Sub instead of console")
    parser.add_argument("--project", type=str, help="GCP Project ID")
    parser.add_argument("--topic", type=str, default="live-sales", help="Pub/Sub Topic ID")
    
    args = parser.parse_args()
    
    if args.pubsub and not args.project:
        print("❌ Error: --project is required when using --pubsub")
        exit(1)
    
    run_publisher(
        interval=args.interval,
        count=args.count,
        use_pubsub=args.pubsub,
        project_id=args.project,
        topic_id=args.topic
    )
