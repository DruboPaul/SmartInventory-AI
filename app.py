"""
Gradio Chatbot for SmartInventory AI

An interactive chatbot that showcases:
- RAG-powered product queries
- LangChain agent with tools
- Intelligent supplier recommendations
- Real-time inventory insights

Run: python app_gradio.py
"""
import gradio as gr
import os
import sys
from datetime import datetime
import json
import pandas as pd
import io
import requests
import threading
import time
import inventory_db

# Try to import AI modules
try:
    from ai.rag_engine import InventoryRAGEngine
    from ai.inventory_agent import InventoryAgent
except ImportError:
    print("AI modules not found. Running in localized mode.")
    InventoryRAGEngine = None
    InventoryAgent = None

# Add project root to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# State for AI engines
rag_engine = None
inventory_agent = None

# Product and Supplier databases (synchronized with JSON)
PRODUCT_DB = {}
SUPPLIER_DB = {}

PRODUCT_DB = {}
SUPPLIER_DB = {}

# Persistence
CONFIG_FILE = "config.json"

def load_config():
    """Load configuration from JSON file."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_config(new_data):
    """Update configuration with new data."""
    config = load_config()
    config.update(new_data)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def load_local_db():
    """Load product and supplier data from SQLite for local UI functions."""
    global PRODUCT_DB, SUPPLIER_DB
    try:
        # 1. Ensure DB is initialized
        inventory_db.init_db()
        
        # 2. Migrate if necessary (first run)
        inventory_db.migrate_from_json()
        
        # 3. Pull total counts for status
        count = inventory_db.get_total_product_count()
        
        # 4. Auto-Examine for Sample Data if DB is empty
        if count == 0 and os.path.exists("sample_data_50k.csv"):
            print("📦 Database empty. Auto-loading 50k sample records...")
            df_sample = pd.read_csv("sample_data_50k.csv")
            inventory_db.batch_insert_products(df_sample)
            count = inventory_db.get_total_product_count()
            return f"🟢 System Ready: Auto-loaded 50,000 sample records."

        # Legacy: Populate the in-memory DB for RAG/Agent tools if they aren't SQL-ready yet
        # For small datasets this is fine, for 1M rows we will transition tool logic to SQL
        conn = inventory_db.get_db_connection()
        df_p = pd.read_sql_query("SELECT * FROM products", conn)
        df_s = pd.read_sql_query("SELECT * FROM suppliers", conn)
        conn.close()
        
        # Convert to the expected dictionary format
        products = {}
        for _, p in df_p.iterrows():
            products[p['sku']] = {
                "name": p['name'], "category": p['category'], "stock": p['stock'],
                "price": p['base_price'], "supplier": p['supplier_id']
            }
        PRODUCT_DB = products
        
        suppliers = {}
        for _, s in df_s.iterrows():
            suppliers[s['name']] = {
                "contact": s['contact'], "email": s['email'], "lead_time": s['avg_lead_time']
            }
        SUPPLIER_DB = suppliers
        
        if count == 50000:
             return f"🟢 System Ready: Using Sample Data (50,000 records)"
        
        return f"🔧 SQL Database synchronized: {count} products loaded."
            
    except Exception as e:
        print(f"Error loading local DB: {e}")
        return f"❌ Error loading SQL database: {e}"

def get_inventory_df(page=0, limit=100):
    """Fetch paginated product data from SQLite."""
    return inventory_db.get_products_paginated(offset=page*limit, limit=limit)

# Initial load
db_status = load_local_db()
print(db_status)

def get_low_stock_items():
    """Find items with low stock using SQLite."""
    return inventory_db.get_low_stock_sql(threshold=15)

def get_product_info(query):
    """Search for product information directly in SQLite."""
    conn = inventory_db.get_db_connection()
    cursor = conn.cursor()
    sql_search = """
        SELECT sku, name, category, stock, base_price as price, supplier_id as supplier
        FROM products 
        WHERE LOWER(sku) LIKE ? OR LOWER(name) LIKE ? OR LOWER(category) LIKE ?
    """
    term = f"%{query.lower()}%"
    df = pd.read_sql_query(sql_search, conn, params=(term, term, term))
    conn.close()
    return df.to_dict('records')

def get_supplier_info(supplier_name):
    """Get supplier contact information from SQL."""
    conn = inventory_db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM suppliers WHERE LOWER(name) LIKE ?", (f"%{supplier_name.lower()}%",))
    s = cursor.fetchone()
    conn.close()
    if s:
        return {"name": s["name"], "contact": s["contact"], "email": s["email"], "lead_time": s["avg_lead_time"]}
    return None

def generate_reorder_recommendation(sku):
    """Generate AI reorder recommendation."""
    product = PRODUCT_DB.get(sku)
    if not product:
        return None
    
    supplier = SUPPLIER_DB.get(product["supplier"], {})
    lead_time = supplier.get("lead_time", 7)
    
    if product["stock"] < 10:
        urgency = "🚨 URGENT"
        qty = 50
    elif product["stock"] < 20:
        urgency = "⚠️ SOON"
        qty = 30
    else:
        urgency = "✅ NORMAL"
        qty = 20
    
    return {
        "product": product["name"],
        "current_stock": product["stock"],
        "urgency": urgency,
        "recommended_qty": qty,
        "supplier": product["supplier"],
        "lead_time": lead_time,
        "est_cost": round(product["price"] * 0.6 * qty, 2)
    }

# ============================================
# Chat Logic
# ============================================

def process_message(message, history):
    """Process user message and generate AI response."""
    global inventory_agent, rag_engine
    
    if not os.environ.get("OPENAI_API_KEY") and not inventory_agent:
        return "⚠️ Please enter your [OpenAI API Key] in the **Settings** section below to enable the AI assistant."

    message_lower = message.lower()
    
    try:
        # Use Agent for multi-tool tasks or RAG for knowledge lookup
        if inventory_agent:
            return inventory_agent.ask(message)
        elif rag_engine:
            result = rag_engine.query(message)
            return result.get("answer", "I encountered an issue processing that.")
    except Exception as e:
        return f"❌ AI Error: {str(e)}"

    # Fallback to local logic if AI is not ready
    
    # Low stock query
    if any(word in message_lower for word in ["low stock", "running low", "need reorder", "stock alert"]):
        low_items = get_low_stock_items()
        if low_items:
            response = "🚨 **Low Stock Alert!**\\n\\n"
            for item in low_items:
                response += f"• **{item['name']}** (SKU: {item['sku']})\\n"
                response += f"  📊 Stock: {item['stock']} units\\n"
                response += f"  🏭 Supplier: {item['supplier']}\\n\\n"
            response += "\\n💡 *Tip: Ask me to 'reorder SKU005' for recommendations!*"
        else:
            response = "✅ All products have healthy stock levels!"
        return response
    
    # Inventory Status query
    if any(word in message_lower for word in ["inventory status", "stock level", "overview", "portfolio", "total value"]):
        total_items = inventory_db.get_total_product_count()
        low_count = len(get_low_stock_items())
        total_stock = get_total_stock_units()
        total_val = get_total_stock_value()
        
        response = "📊 **Inventory Status Overview**\n\n"
        response += f"• **Total Products:** {total_items}\n"
        response += f"• **Total Stock Volume:** {total_stock} units\n"
        response += f"• **Portfolio Value (Live SQL):** ${total_val:,.2f}\n"
        response += f"• **Low Stock Alerts:** {low_count} items\n"
        response += f"• **System Health:** {'🟢 Stable' if low_count < 3 else '🟡 Warning' if low_count < 7 else '🔴 Critical'}\n\n"
        response += "💡 *Tip: Click 'Low Stock Alert' to see specific items needing attention.*"
        return response

    # All Products / Category Search query
    if any(word in message_lower for word in ["find all", "show all", "list", "search for"]):
        # Extract potential category or search term
        search_query = message_lower.replace("find all", "").replace("show all", "").replace("list", "").replace("search for", "").strip()
        
        if not search_query or "product" in search_query or "item" in search_query:
            df_all = inventory_db.get_products_paginated(limit=15)
            list_title = "📦 **Complete Product List (Top 15)**"
        else:
            # Search for specific term/category
            search_results = get_product_info(search_query)
            df_all = pd.DataFrame(search_results)
            # Standardize columns if not empty
            if not df_all.empty:
                df_all = df_all.rename(columns={"sku": "SKU", "name": "Name", "stock": "Stock"})
            list_title = f"🔍 **Search Results for '{search_query}'**"
            
        if df_all.empty:
            return f"📭 No items found matching '{search_query or 'all'}'."
        
        response = f"{list_title}\n\n"
        # Adjust for column name differences from get_product_info vs get_products_paginated
        name_col = "Name" if "Name" in df_all.columns else "name"
        sku_col = "SKU" if "SKU" in df_all.columns else "sku"
        stock_col = "Stock" if "Stock" in df_all.columns else "stock"
        
        for _, p in df_all.iterrows()[:15]:
            clean_stock = int(str(p[stock_col]))
            stock_emoji = "🟢" if clean_stock > 20 else "🟡" if clean_stock > 10 else "🔴"
            response += f"• **{p[name_col]}** ({p[sku_col]}) — {stock_emoji} {p[stock_col]} in stock\n"
        
        return response

    # Weekly Report query
    if any(word in message_lower for word in ["weekly report", "performance report", "show report"]):
        response = "📈 **Weekly Inventory Performance Report**\\n\\n"
        response += "• **Total Sales:** $12,450.00 (Sample Data)\\n"
        response += "• **Most Popular:** Premium Cotton T-Shirt\\n"
        response += "• **Restock Efficiency:** 94%\\n"
        response += "• **Projected Shortages:** 4 SKUs expected in 7 days\\n\\n"
        response += "📝 *Full detailed reports are available in the 'Reports' module.*"
        return response
    
    # Reorder recommendation
    if "reorder" in message_lower:
        # Extract SKU from SQL
        conn = inventory_db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT sku FROM products")
        all_skus = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        for sku in all_skus:
            if sku.lower() in message_lower:
                rec = generate_reorder_recommendation(sku)
                if rec:
                    response = f"📦 **Reorder Recommendation: {rec['product']}**\\n\\n"
                    response += f"{rec['urgency']}\\n\\n"
                    response += f"📊 Current Stock: {rec['current_stock']} units\\n"
                    response += f"📦 Recommended Order: {rec['recommended_qty']} units\\n"
                    response += f"💰 Est. Cost: ${rec['est_cost']:,.2f}\\n"
                    response += f"🏭 Supplier: {rec['supplier']}\\n"
                    response += f"⏱️ Lead Time: {rec['lead_time']} days\\n\\n"
                    response += "📧 *Reply 'contact supplier' for contact details!*"
                    return response
        
        return "❓ Please specify a SKU (e.g., 'reorder SKU005')"
    
    # Supplier contact
    if any(word in message_lower for word in ["contact supplier", "supplier info", "supplier contact"]):
        for name, info in SUPPLIER_DB.items():
            response = "📞 **Supplier Contacts:**\\n\\n"
            for name, info in SUPPLIER_DB.items():
                response += f"**{name}**\\n"
                response += f"  📞 {info['contact']}\\n"
                response += f"  📧 {info['email']}\\n"
                response += f"  ⏱️ Lead time: {info['lead_time']} days\\n\\n"
            return response
    
    # Product search
    if any(word in message_lower for word in ["find", "search", "show", "what", "product"]):
        # Try to find product
        for category in ["t-shirt", "jeans", "sneakers", "dress", "jacket"]:
            if category in message_lower:
                products = get_product_info(category)
                if products:
                    response = f"🔍 **{category.title()} Products:**\\n\\n"
                    for p in products:
                        stock_emoji = "🟢" if p["stock"] > 20 else "🟡" if p["stock"] > 10 else "🔴"
                        response += f"• **{p['name']}** ({p['sku']})\\n"
                        response += f"  💰 ${p['price']} | {stock_emoji} Stock: {p['stock']}\\n\\n"
                    return response
        
    # Help
    if any(word in message_lower for word in ["help", "what can you", "commands"]):
        return """👋 **Welcome to Inventory Assistant!**

I can help you with:

📦 **Stock Queries**
• "Show me low stock items"
• "What products need reorder?"

🔍 **Product Search**
• "Find all jeans"
• "Show sneakers"
• "Search for jacket"

📋 **Reorder Help**
• "Reorder SKU005"
• "Generate reorder for Winter Jacket"

📞 **Supplier Info**
• "Contact supplier"
• "Show supplier contacts"

💡 *Powered by LangChain + RAG*"""
    
    # Default response
    return """🤔 I'm not sure I understand. Try asking:

• "Show low stock items"
• "Reorder SKU005"
• "Find all jeans"
• "Contact supplier"

Or type **'help'** for all commands!"""

def handle_dataset_upload(file):
    """Handle custom dataset upload (CSV or JSON) and persist to SQLite."""
    if not file:
        return "❌ No file uploaded.", get_inventory_df()
    
    global rag_engine, inventory_agent
    
    try:
        # 1. Parse File
        if file.name.endswith('.csv'):
            df = pd.read_csv(file.name)
            required_cols = ['id', 'name', 'category', 'base_price', 'stock']
            # Also accept 'sku' instead of 'id' and 'price' instead of 'base_price'
            if 'sku' in df.columns and 'id' not in df.columns: df = df.rename(columns={'sku': 'id'})
            if 'price' in df.columns and 'base_price' not in df.columns: df = df.rename(columns={'price': 'base_price'})
            
            if not all(col in df.columns for col in required_cols):
                return f"❌ CSV must contain columns: {', '.join(required_cols)}", get_inventory_df()
            
            # 2. Persist to SQLite using Batch Insert
            count = inventory_db.batch_insert_products(df)
                
        elif file.name.endswith('.json'):
            with open(file.name, 'r') as f:
                data = json.load(f)
                df = pd.DataFrame(data.get("products", []))
                count = inventory_db.batch_insert_products(df)
        else:
            return "❌ Unsupported format.", get_inventory_df()
            
        # 3. Synchronize UI Cache
        ui_msg = load_local_db()
        
        # 4. Reload AI Engines (if active)
        ai_msg = ""
        if rag_engine:
            rag_engine.reload()
            ai_msg += " + RAG Updated"
        if inventory_agent:
            inventory_agent.reload()
            ai_msg += " + Agent Updated"
            
        return f"✅ {count} items processed! {ui_msg}{ai_msg}", get_inventory_df()
        
    except Exception as e:
        print(f"Error processing dataset: {e}")
        return f"❌ Error: {str(e)}", get_inventory_df()

def send_telegram_message(token, chat_id, text):
    """Helper to send a message to Telegram."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

def initialize_ai(key):
    """Global function to initialize AI engines."""
    global rag_engine, inventory_agent
    
    if not key or not key.startswith("sk-"):
        return False, "❌ Invalid API Key format."
        
    os.environ["OPENAI_API_KEY"] = key
    
    try:
        if InventoryRAGEngine is None or InventoryAgent is None:
            return False, "⚠️ AI Modules not found. Running in basic mode."
            
        rag_engine = InventoryRAGEngine()
        inventory_agent = InventoryAgent()
        return True, "✅ AI Initialized Successfully."
    except Exception as e:
        return False, f"❌ Init Error: {str(e)}"

# --- Background Polling Logic ---
polling_active = False
polling_thread = None

def telegram_listener(token, chat_id):
    """Background task to poll Telegram for new messages."""
    global polling_active
    
    # Clean inputs
    token = token.strip()
    chat_id = str(chat_id).strip()
    
    print(f"🤖 Telegram Listener STARTED for Chat ID: {chat_id}")
    
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    offset = 0
    
    # Initial offset setup (ignore old messages)
    try:
        resp = requests.get(url, params={"offset": -1, "timeout": 5}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("result"):
                offset = data["result"][-1]["update_id"] + 1
    except:
        pass

    while polling_active:
        try:
            # Long Polling (30s timeout)
            params = {"offset": offset, "timeout": 30}
            resp = requests.get(url, params=params, timeout=35)
            
            if resp.status_code == 200:
                data = resp.json()
                for result in data.get("result", []):
                    # Update offset to confirm receipt
                    offset = result["update_id"] + 1
                    
                    message = result.get("message", {})
                    sender_id = str(message.get("chat", {}).get("id"))
                    text = message.get("text", "")
                    
                    # SECURITY CHECK: Only reply to owner
                    if sender_id == chat_id and text:
                        print(f"📩 Inbound from Telegram: {text}")
                        
                        # Show "Typing..." status
                        requests.post(f"https://api.telegram.org/bot{token}/sendChatAction", 
                                      json={"chat_id": chat_id, "action": "typing"})
                        
                        # Process with AI
                        # Note: We pass empty history [] as Telegram chat is ephemeral for now
                        ai_response = process_message(text, [])
                        
                        # Send Reply
                        send_telegram_message(token, chat_id, ai_response)
            
            # Tiny sleep to prevent CPU spike in tight loop errors
            time.sleep(1)
            
        except Exception as e:
            print(f"⚠️ Polling Error: {e}")
            time.sleep(5) # Backoff on error

def start_telegram_bot(token, chat_id):
    """Start or Restart the background polling thread."""
    global polling_thread, polling_active
    
    # Stop existing
    polling_active = False
    if polling_thread and polling_thread.is_alive():
        print("⏳ Stopping old listener...")
        time.sleep(2) # Give it a moment to shut down
        
    if not token or not chat_id:
        return "🔴 Bot Stopped (Missing Config)"
        
    # Start new
    polling_active = True
    polling_thread = threading.Thread(target=telegram_listener, args=(token, chat_id), daemon=True)
    polling_thread.start()
    return "🟢 2-Way Bot Active"

def send_telegram_test(token, chat_id):
    """Send a test alert message to Telegram."""
    if not token or not token.strip():
        return "❌ Please enter your Bot Token."
    if not chat_id or not chat_id.strip():
        return "❌ Please enter your Chat ID."
    
    token = token.strip()
    chat_id = chat_id.strip()
    
    # Basic format check
    if ":" not in token or not token.split(":")[0].isdigit():
        return "❌ Invalid Token Format. It should look like: '123456:ABC-DEF...'"
    
    test_message = """🧪 *SmartInventory AI - Test Alert*

✅ Connection Successful!

📊 Your Telegram alerts are configured correctly.
You will receive notifications for:
• ⚠️ Low Stock Warnings
• 🚀 High-Value Transactions

🕒 """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": test_message,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        data = response.json()
        
        if response.status_code == 200 and data.get("ok"):
            return "✅ Test alert sent! Check your Telegram app 📱"
        elif response.status_code == 404:
            return "❌ Error: Bot Token not found. Please check your token."
        elif response.status_code == 401:
             return "❌ Error: Unauthorized. Your token is invalid."
        elif response.status_code == 400:
             return "❌ Error: Chat ID not found or bot not started. Message @YourBotName first!"
        else:
            error_desc = data.get("description", "Unknown error")
            return f"❌ Telegram Error: {error_desc}"
    except requests.exceptions.Timeout:
        return "❌ Request timed out. Check your internet connection."
    except requests.exceptions.RequestException as e:
        return f"❌ Connection Error: {str(e)}"

def respond(message, history):
    """Wrapper function for Gradio chat interface - Gradio 6.x format."""
    if not message:
        return "", history
        
    bot_message = process_message(message, history)
    # Legacy/Standard Gradio Tuple format
    history.append([message, bot_message])
    return "", history

def forward_last_message(history, token, chat_id):
    """Forward the last AI message from history to Telegram."""
    if not history or len(history) == 0:
        return "⚠️ No message history to forward."
    
    # Find the last assistant message
    last_assistant_msg = None
    for pair in reversed(history):
        # pair is usually [user_msg, bot_msg]
        if isinstance(pair, (list, tuple)) and len(pair) > 1:
            if pair[1]: # Check if bot message exists
                last_assistant_msg = pair[1]
                break
            
    if not last_assistant_msg:
        return "⚠️ No AI response found to forward."
    
    if not token or not token.strip():
        return "⚠️ Please set your Bot Token in Settings & Data."
    if not chat_id or not chat_id.strip():
        return "⚠️ Please set your Chat ID in Settings & Data."
    
    clean_msg = f"🤖 *SmartInventory AI Insight*\\n\\n{last_assistant_msg}"
    
    url = f"https://api.telegram.org/bot{token.strip()}/sendMessage"
    payload = {
        "chat_id": chat_id.strip(),
        "text": clean_msg,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return "✅ Success! Insight sent to Telegram 📱"
        else:
            return f"❌ Telegram Error: {response.json().get('description', 'Unknown')}"
    except Exception as e:
        return f"❌ Forwarding failed: {str(e)}"

# ============================================
# Gradio Interface - Dark Theme Command Center
# ============================================

custom_css = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

:root {
    /* Font smoothing for premium look */
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    --bg-primary: #020617;
    --bg-secondary: #0F172A;
    --bg-card: #1E293B;
    --bg-card-darker: #0F172A;
    --border-color: #1E293B;
    --border-glow: #38BDF8;
    --text-primary: #F8FAFC;
    --text-secondary: #CBD5E1;
    --text-muted: #94A3B8;
    --accent-cyan: #22D3EE;
    --accent-teal: #2DD4BF;
    --accent-pulse: #38BDF8;
}

@keyframes pulse {
    0% { transform: scale(0.95); opacity: 0.5; box-shadow: 0 0 0 0 rgba(56, 189, 248, 0.7); }
    70% { transform: scale(1); opacity: 1; box-shadow: 0 0 0 6px rgba(56, 189, 248, 0); }
    100% { transform: scale(0.95); opacity: 0.5; box-shadow: 0 0 0 0 rgba(56, 189, 248, 0); }
}

.system-status-indicator {
    width: 8px;
    height: 8px;
    background-color: #38BDF8;
    border-radius: 50%;
    display: inline-block;
    vertical-align: middle;
    margin-right: 8px;
    animation: pulse 2s infinite;
}

/* Force dark theme on everything */
*, *::before, *::after {
    box-sizing: border-box !important; /* Critical for symmetry */
}

/* Full viewport dark background */
html {
    background: #0F172A !important;
    background-color: #0F172A !important;
    min-height: 100%;
    width: 100%;
}

body {
    background: #020617 !important;
    background-color: #020617 !important;
    min-height: 100vh;
    width: 100%;
    margin: 0 !important;
    padding: 0 !important;
    overflow-x: hidden !important; /* Prevent horizontal scroll shifts */
}

/* Root Application Centering */
gradio-app, .gradio-app {
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important; /* Horizontally center children */
    width: 100% !important;
    background: #020617 !important;
}

/* Global Styles */
.gradio-container, .main, .wrap, .contain, .app, #root, [class*="gradio"], .form, .block, .gr-box, .gr-form, .gr-panel {
    background: #0F172A !important;
    background-color: #0F172A !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    color: #F1F5F9 !important;
    min-height: auto !important;
    height: auto !important;
    /* Removed justify-content/align-items overrides that broke centering */
}

.gradio-container {
    max-width: 1440px !important; /* Constrain width for large screens */
    width: 100% !important;
    margin-left: auto !important;
    margin-right: auto !important;
    padding: 0 40px !important; /* Larger gutters */
    background: #0F172A !important;
    display: flex !important;
    flex-direction: column !important;
    gap: 20px !important;
    justify-content: flex-start !important;
}

/* Override all white backgrounds and force tight verticality */
.gr-group, .gr-box, .gr-form, .gr-block, .gr-panel, .block, .wrap, .form, .container {
    background: transparent !important;
    background-color: transparent !important;
    border: none !important;
    min-height: auto !important;
    margin: 0 !important;
    padding: 0 !important;
}

/* Column backgrounds fix */
.gr-column, .column, [class*="column"] {
    background: transparent !important;
    background-color: transparent !important;
}

/* Row backgrounds fix */
/* Row backgrounds fix */
.gr-row, .row, [class*="row"] {
    background: transparent !important;
    background-color: transparent !important;
}

/* Explicit full width for main row */
.main-layout-row {
    width: 100% !important;
    gap: 30px !important; /* Increased gap for better separation */
    display: flex !important;
    justify-content: space-between !important;
}

/* Strict Layout Symmetry */
.sidebar-left, .sidebar-right {
    flex: 1 1 0 !important; /* Force equal sizing ignoring content width */
    min-width: 250px !important;
    max-width: 350px !important; /* Prevent excessive stretching */
}

.main-center {
    flex: 3 1 0 !important; /* Center takes 3 parts */
    min-width: 500px !important;
}

/* Header Banner */
#header-banner {
    background: linear-gradient(135deg, #1E3A5F 0%, #0F2744 100%) !important;
    border: 1px solid #0EA5E9 !important;
    border-radius: 12px !important;
    padding: 0.75rem 1.25rem !important;
    margin-bottom: 0.5rem !important;
    box-shadow: 0 0 20px rgba(14, 165, 233, 0.15) !important;
}

#header-banner h1 {
    color: #F1F5F9 !important;
    font-size: 1.75rem !important;
    font-weight: 800 !important;
    margin: 0 !important;
    display: flex !important;
    align-items: center !important;
    gap: 0.75rem !important;
}

#header-banner p {
    color: #94A3B8 !important;
    font-size: 0.9rem !important;
    margin: 0.5rem 0 0 0 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
}

/* Section Titles */
.section-title {
    color: #22D3EE !important;
    font-size: 0.8rem !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.15em !important;
    margin-bottom: 0.25rem !important;
    margin-top: 0px !important;
    display: flex !important;
    align-items: center !important;
    gap: 0.5rem !important;
    background: transparent !important;
}

/* Chat History Sidebar */
#chat-history-panel {
    background: linear-gradient(180deg, #1E3A5F 0%, #0F2744 100%) !important;
    border: 1px solid #334155 !important;
    border-radius: 12px !important;
    padding: 1rem !important;
}

.history-item {
    background: rgba(15, 39, 68, 0.8) !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
    padding: 0.5rem 0.75rem !important;
    margin-bottom: 0.35rem !important;
    cursor: pointer !important;
    transition: all 0.2s ease !important;
}

.history-item:hover {
    border-color: #0EA5E9 !important;
    background: rgba(14, 165, 233, 0.1) !important;
}

.history-item h4 {
    color: #F1F5F9 !important;
    font-size: 0.9rem !important;
    font-weight: 600 !important;
    margin: 0 !important;
}

.history-item span {
    color: #64748B !important;
    font-size: 0.75rem !important;
}

/* Chat Interface - Main Area */
.chatbot, .gradio-chatbot, div[data-testid="chatbot"], [class*="chatbot"] {
    background: linear-gradient(180deg, #0F2744 0%, #0F172A 100%) !important;
    background-color: #0F2744 !important;
    border: 1px solid #334155 !important;
    border-radius: 12px !important;
    min-height: 450px !important;
    height: 450px !important;
}

/* Chatbot inner container */
.chatbot > div, [class*="chatbot"] > div {
    background: transparent !important;
    background-color: transparent !important;
}

/* Chat bubble wrapper */
.bubble-wrap, .message-wrap, [class*="bubble"], [class*="message-row"] {
    background: transparent !important;
    background-color: transparent !important;
}

/* Chat Messages - User */
[data-testid="user"], .user-message, [class*="user"] .message-content {
    background: linear-gradient(135deg, rgba(30, 58, 95, 0.9) 0%, rgba(15, 39, 68, 0.9) 100%) !important;
    backdrop-filter: blur(8px) !important;
    border: 1px solid rgba(14, 165, 233, 0.3) !important;
    color: #F1F5F9 !important;
    border-radius: 16px 16px 2px 16px !important;
    padding: 1.25rem !important;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2) !important;
}

/* Chat Messages - Bot/Assistant */
[data-testid="bot"], .bot-message, [class*="bot"] .message-content, .assistant {
    background: rgba(30, 41, 59, 0.7) !important;
    backdrop-filter: blur(8px) !important;
    border: 1px solid rgba(51, 65, 85, 0.5) !important;
    color: #E2E8F0 !important;
    border-radius: 16px 16px 16px 2px !important;
    padding: 1.25rem !important;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1) !important;
}

/* Message text color fix */
.message *, .chatbot *, [class*="message"] p, [class*="message"] span {
    color: #E2E8F0 !important;
}

/* Message bubble backgrounds */
[class*="message"] > div {
    background: transparent !important;
}

/* Textbox input styling */
textarea, input[type="text"], input[type="password"], .gr-input, .gr-textbox {
    background: #1E3A5F !important;
    background-color: #1E3A5F !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
    color: #F1F5F9 !important;
    font-size: 0.95rem !important;
}

textarea::placeholder, input::placeholder {
    color: #64748B !important;
}

textarea:focus, input:focus {
    border-color: #0EA5E9 !important;
    box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.2) !important;
    outline: none !important;
}

/* Chatbot Interface - Lighter Background & Fixed Scroll */
#chatbot {
    background-color: #1E293B !important; /* Lighter Slate-800 */
    border: 1px solid #334155 !important;
    border-radius: 12px !important;
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.1) !important;
    height: 600px !important;        /* Fixed Height */
    max-height: 600px !important;    /* Prevent expansion */
    overflow-y: auto !important;     /* Enable Scrollbar */
}

/* Quick Action Buttons - Colorful Cards */
#btn-low-stock {
    background: linear-gradient(135deg, #7F1D1D 0%, #450A0A 100%) !important;
    border: 1px solid #991B1B !important;
    color: #F8FAFC !important;
    border-radius: 12px !important;
    padding: 1rem !important;
    font-weight: 600 !important;
}

#btn-all-products {
    background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%) !important;
    border: 1px solid #334155 !important;
    color: #F8FAFC !important;
    border-radius: 12px !important;
    padding: 1rem !important;
    font-weight: 600 !important;
}

#btn-inventory {
    background: linear-gradient(135deg, #713F12 0%, #422006 100%) !important;
    border: 1px solid #854D0E !important;
    color: #F8FAFC !important;
    border-radius: 12px !important;
    padding: 1rem !important;
    font-weight: 600 !important;
}

#btn-products {
    background: linear-gradient(135deg, #4C1D95 0%, #2E1065 100%) !important;
    border: 1px solid #5B21B6 !important;
    color: #F8FAFC !important;
    border-radius: 12px !important;
    padding: 1rem !important;
    font-weight: 600 !important;
}

#btn-suppliers {
    background: linear-gradient(135deg, #134E4A 0%, #042F2E 100%) !important;
    border: 1px solid #0D9488 !important;
    color: #F8FAFC !important;
    border-radius: 12px !important;
    padding: 1rem !important;
    font-weight: 600 !important;
}

#btn-reports {
    background: linear-gradient(135deg, #7C2D12 0%, #431407 100%) !important;
    border: 1px solid #9A3412 !important;
    color: #F8FAFC !important;
    border-radius: 12px !important;
    padding: 1rem !important;
    font-weight: 600 !important;
}

/* Button hover effects */
#btn-low-stock:hover, #btn-all-products:hover, #btn-inventory:hover,
#btn-products:hover, #btn-suppliers:hover, #btn-reports:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3) !important;
}

/* Send Button */
button.primary, button[variant="primary"], .primary {
    background: linear-gradient(135deg, #0EA5E9 0%, #0284C7 100%) !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    padding: 0.75rem 1.5rem !important;
    font-weight: 600 !important;
    cursor: pointer !important;
}

button.primary:hover {
    background: linear-gradient(135deg, #38BDF8 0%, #0EA5E9 100%) !important;
    transform: translateY(-1px) !important;
}

/* Secondary Button */
button.secondary, button[variant="secondary"] {
    background: #1E3A5F !important;
    color: #94A3B8 !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
}

/* Accordion styling */
.accordion, [class*="accordion"] {
    background: #1E3A5F !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
}

.accordion-header, [class*="accordion"] > button {
    background: #1E3A5F !important;
    color: #F1F5F9 !important;
}

.accordion-header span, [class*="accordion"] > button span {
    color: #F1F5F9 !important;
}

/* Premium styling for Settings & Message Area */
#main_settings, #message_area {
    background: #1E293B !important;
    border: 1px solid #334155 !important;
    border-radius: 12px !important;
    padding: 20px !important;
    box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.5) !important;
}

#main_settings span, #main_settings > button > span {
    color: #FFFFFF !important;
    font-weight: 700 !important;
    font-size: 1.1rem !important;
    letter-spacing: -0.01em !important;
}

/* Headers in Settings */
#main_settings h3 {
    color: #38BDF8 !important; /* Cyan accent for headers */
    font-size: 0.95rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
    margin-bottom: 1rem !important;
    border-bottom: 1px solid rgba(56, 189, 248, 0.2) !important;
    padding-bottom: 0.5rem !important;
    display: inline-block !important;
    width: 100% !important;
}

/* Paragraphs and descriptions */
#main_settings p {
    color: #94A3B8 !important;
    font-size: 0.85rem !important;
    line-height: 1.5 !important;
}

/* Form Labels - Clean & Modern */
#main_settings label, #main_settings span.label {
    color: #CBD5E1 !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important; /* Slightly larger */
    margin-bottom: 6px !important;
    text-transform: none !important; /* Remove harsh uppercase */
}

/* Input text - Premium Feel */
#main_settings input, #main_settings textarea {
    color: #F8FAFC !important;
    background: #0F172A !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
    padding: 10px 12px !important;
    transition: all 0.2s ease !important;
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.1) !important;
}

#main_settings input:focus, #main_settings textarea:focus {
    border-color: #38BDF8 !important;
    box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.2), inset 0 2px 4px rgba(0,0,0,0.1) !important;
    transform: translateY(-1px) !important;
}

/* Buttons inside settings */
#main_settings button {
    font-weight: 500 !important;
    letter-spacing: 0.01em !important;
}

/* Upload area styling */
/* Upload area styling */
.upload-container {
    border: 2px dashed #475569 !important;
    background: rgba(30, 41, 59, 0.5) !important;
    border-radius: 12px !important;
    padding: 20px !important;
    text-align: center !important;
    transition: all 0.3s ease !important;
    min-height: 120px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    flex-direction: column !important;
}

.upload-container:hover {
    border-color: #38BDF8 !important;
    background: rgba(56, 189, 248, 0.1) !important;
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.upload-container .icon {
    color: #38BDF8 !important;
    width: 32px !important;
    height: 32px !important;
    margin-bottom: 8px !important;
}

.upload-container span {
    color: #94A3B8 !important;
    font-size: 0.9rem !important;
}

/* Labels */
label, .gr-label, span.label {
    color: #94A3B8 !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    background: transparent !important;
}

/* Scrollbar */
::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

::-webkit-scrollbar-track {
    background: #0F172A;
    border-radius: 4px;
}

::-webkit-scrollbar-thumb {
    background: #334155;
    border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
    background: #475569;
}

/* Footer */
#footer-text {
    text-align: center !important;
    color: #64748B !important;
    font-size: 0.8rem !important;
    margin-top: 1.5rem !important;
    padding: 1rem !important;
    border-top: 1px solid #334155 !important;
    background: transparent !important;
}

/* Hide Gradio footer */
footer { display: none !important; }

/* SVG icons fix */
svg, svg path {
    fill: currentColor !important;
}

/* Copy button fix */
button[title="Copy"], button[aria-label="Copy"] {
    background: #334155 !important;
    color: #94A3B8 !important;
    border: none !important;
}

/* Telegram Button visual hierarchy */
#btn-test-telegram {
    background: linear-gradient(135deg, #059669 0%, #047857 100%) !important;
    border: 1px solid #10B981 !important;
    color: #ffffff !important;
    font-weight: 700 !important;
    margin-top: 10px !important;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06) !important;
}

#btn-test-telegram:hover {
    background: linear-gradient(135deg, #10B981 0%, #059669 100%) !important;
    transform: translateY(-2px) !important;
    box-shadow: 0 10px 15px -3px rgba(16, 185, 129, 0.4) !important;
}

/* Zero-gap row for "Input Group" feel */
.token-input-row {
    gap: 0 !important;
    align-items: stretch !important;
}

/* Remove right border radius from input to fuse with button */
.token-input-row .block.svelte-1t38q2d, .token-input-row input {
    border-top-right-radius: 0 !important;
    border-bottom-right-radius: 0 !important;
    border-right: none !important;
}

/* Eye Button Styling */
#btn-eye-toggle-token, #btn-eye-toggle-chat {
    border-top-left-radius: 0 !important;
    border-bottom-left-radius: 0 !important;
    border-left: none !important;
    background: #334155 !important;
    color: #ffffff !important; /* White icon */
    width: 50px !important;
    flex-grow: 0 !important;
}

/* Force Input Text White */
.token-input-row input {
    color: #ffffff !important;
    opacity: 1 !important;
}

#chk-toggle-token label span {
    color: #94A3B8 !important; /* Match other labels */
    font-weight: 500 !important;
}

/* Fix Dataframe contrast and scrolling - Uniform White Background */
#inventory-dataframe {
    border: 1px solid #CBD5E1 !important;
    border-radius: 12px !important;
    background-color: #FFFFFF !important;
    overflow: hidden !important;
}

#inventory-dataframe .table-wrap {
    max-height: 600px !important; 
    overflow-y: auto !important;
    overflow-x: auto !important;
    background-color: #FFFFFF !important;
}

#inventory-dataframe table {
    background-color: #FFFFFF !important;
    color: #0F172A !important;
    width: 100% !important;
    border-collapse: collapse !important;
}

#inventory-dataframe thead th {
    background-color: #F1F5F9 !important;
    color: #0EA5E9 !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    font-size: 0.75rem !important;
    letter-spacing: 0.1em !important;
    padding: 12px !important;
    border-bottom: 2px solid #E2E8F0 !important;
}

/* Row coloring - Uniform White */
#inventory-dataframe tr {
    background-color: #FFFFFF !important; 
}

#inventory-dataframe tr:hover {
    background-color: #F8FAFC !important;
}

#inventory-dataframe td, #inventory-dataframe td span {
    color: #0F172A !important;
    padding: 12px !important;
    border: 1px solid #F1F5F9 !important;
    font-size: 0.9rem !important;
}
"""

js_func = """
function refresh() {
    const url = new URL(window.location);
    if (url.searchParams.get('__theme') !== 'dark') {
        url.searchParams.set('__theme', 'dark');
        window.location.href = url.href;
    }
}
"""

with gr.Blocks(title="SmartInventory AI", css=custom_css, js=js_func, theme=gr.themes.Base()) as demo:
    # Pagination State
    current_page = gr.State(0)
    
    # --- Shared Dataset Explorer View (Full Screen Toggle) ---
    with gr.Column(visible=False) as dataset_view_container:
        gr.HTML("""
            <div style="background: #1E293B; padding: 20px; border-radius: 12px; border: 1px solid #334155; margin-bottom: 20px;">
                <h2 style="color: #38BDF8; margin: 0;">📋 Full Inventory Database</h2>
                <p style="color: #94A3B8; margin: 5px 0 0 0;">Actual data form viewer - Production Mode (SQLite Backend)</p>
            </div>
        """)
        
        modal_viewer = gr.Dataframe(
            value=get_inventory_df(),
            headers=["SKU", "Name", "Category", "Stock", "Price", "Supplier"],
            datatype=["str", "str", "str", "number", "str", "str"],
            interactive=False,
            elem_id="inventory-dataframe"
        )
        
        # Pagination Controls
        with gr.Row(elem_id="pagination-controls"):
            btn_prev = gr.Button("⬅️ Previous 100", scale=1)
            page_display = gr.Number(value=1, label="Page", interactive=False, scale=0, min_width=80)
            btn_next = gr.Button("Next 100 ➡️", scale=1)
            
        with gr.Row():
            btn_refresh_modal = gr.Button("🔄 Refresh Data", variant="secondary")
            btn_exit_explorer = gr.Button("⬅️ Back to Control Center", variant="primary")

    # Pagination Logic
    def go_next(page):
        new_page = page + 1
        return new_page, get_inventory_df(page=new_page), new_page + 1
    
    def go_prev(page):
        new_page = max(0, page - 1)
        return new_page, get_inventory_df(page=new_page), new_page + 1

    btn_next.click(go_next, [current_page], [current_page, modal_viewer, page_display])
    btn_prev.click(go_prev, [current_page], [current_page, modal_viewer, page_display])

    # --- Main Control Center View ---
    with gr.Column(visible=True) as main_view_container:
        initial_message = [
            [None, """[System initialized - Supply chain monitoring active]

Analyzing inventory levels across 47 warehouses...
• Low stock items: 12 products require attention
• Supplier delivery status: 3 shipments in transit
• Demand forecasting updated for Q1 2026

Ready for your command..."""]
        ]
        
        # Header
        gr.HTML("""
            <div id="header-banner">
                <h1><div class="system-status-indicator"></div> 📊 SMARTINVENTORY AI</h1>
                <p>Real-Time Supply Chain Monitoring Node • Stable</p>
            </div>
        """)
    
        with gr.Row(elem_classes="main-layout-row"):
            # Left Sidebar - Chat History
            with gr.Column(scale=1, min_width=250, elem_classes="sidebar-left"):
                gr.HTML('<div class="section-title">● CHAT HISTORY</div>')
                gr.HTML("""
                    <div id="chat-history-panel">
                        <div class="history-item">
                            <h4>Inventory Alert Log</h4>
                            <span>19:30 PM Today</span>
                        </div>
                        <div class="history-item">
                            <h4>Global Sales Stream</h4>
                            <span>Yesterday 14:15</span>
                        </div>
                    </div>
                """)
            
            # Center - Chat Interface
            with gr.Column(scale=3, min_width=500, elem_classes="main-center"):
                gr.HTML('<div class="section-title">💬 CHAT INTERFACE</div>')
                chatbot = gr.Chatbot(
                    value=initial_message,
                    elem_id="chatbot",
                    label=None,
                    show_label=False,
                    avatar_images=(None, "https://api.dicebear.com/7.x/bottts/svg?seed=InventoryAI")
                )
                
                # Message Input Area
                with gr.Group(elem_id="message_area"):
                    gr.HTML('<div class="section-title" style="margin-bottom: 10px;">✉️ MESSAGE</div>')
                    with gr.Row():
                        msg = gr.Textbox(
                            label="",
                            placeholder="Ask me about inventory...",
                            show_label=False,
                            scale=7
                        )
                        submit = gr.Button("🏹", variant="primary", scale=1)
                        btn_forward = gr.Button("📲 Send to Telegram", variant="secondary", scale=2)
                
                forward_status = gr.Markdown("", elem_id="forward-status")
        
            # Right Sidebar - Quick Actions
            with gr.Column(scale=1, min_width=250, elem_classes="sidebar-right"):
                gr.HTML('<div class="section-title">⚡ QUICK ACTIONS</div>')
                
                btn_low_stock = gr.Button("🚨 Low Stock Alert", elem_id="btn-low-stock")
                btn_all_products = gr.Button("📦 All Products", elem_id="btn-all-products")
                btn_inventory = gr.Button("📊 Inventory Status", elem_id="btn-inventory")
                btn_products = gr.Button("🔍 Search Products", elem_id="btn-products")
                btn_suppliers = gr.Button("💛 Suppliers", elem_id="btn-suppliers")
                btn_reports = gr.Button("📈 Reports", elem_id="btn-reports")
        
        # Hidden Settings Tab
        with gr.Accordion("⚙️ Settings & Data", open=False, elem_id="main_settings"):
            config_data = load_config()
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### 🔐 AI Configuration")
                    # Custom Label for API Key to match style
                    gr.HTML("""
                        <div style="margin-bottom: 4px;">
                            <div style="color: #FFFFFF !important; font-size: 0.875rem; font-weight: 700;">OpenAI API Key</div>
                            <div style="color: #E2E8F0 !important; font-size: 0.75rem; opacity: 0.9;">Your key is not saved permanently. It's only used for this session.</div>
                        </div>
                    """)
                    with gr.Row(elem_classes="token-input-row"):
                        api_input = gr.Textbox(
                            label=None,
                            show_label=False,
                            placeholder="sk-...",
                            type="password",
                            value=config_data.get("openai_api_key", ""),
                            scale=10,
                            min_width=200,
                            container=True
                        )
                        btn_eye_api = gr.Button("👁️", scale=0, min_width=50, elem_id="btn-eye-toggle-api")
                    api_status = gr.Textbox(label="Status", value="🔑 Enter API Key for Live AI", interactive=False)
                    with gr.Row():
                        btn_run_session = gr.Button("🚀 Run (Session Only)", variant="secondary")
                        btn_save_permanent = gr.Button("💾 Save & Run", variant="primary")
                        btn_reset_key = gr.Button("🗑️ Reset", variant="secondary")
                
                with gr.Column():
                    gr.Markdown("### 📤 Upload Dataset")
                    gr.Markdown("Custom Dataset (.csv or .json)")
                    upload_input = gr.File(
                        label=None,
                        file_types=[".csv", ".json"],
                        file_count="single",
                        elem_id="upload-dataset",
                        elem_classes=["upload-container"],
                        container=False
                    )
                    upload_status = gr.Textbox(label="Upload Status", value="Waiting for file...", interactive=False, elem_id="upload-status")
                    btn_upload = gr.Button("Process Dataset", variant="secondary")
                    
                with gr.Column(scale=2):
                    gr.Markdown("### 📊 Dataset Explorer")
                    gr.Markdown("Explore the full dataset in detail.")
                    btn_open_explorer = gr.Button("🔍 Open Dataset Explorer", variant="primary", scale=1)
                    btn_refresh_view = gr.Button("🔄 Quick Sync (Internal)", variant="secondary", size="sm", visible=False)
            
                with gr.Column():
                    gr.Markdown("### 📱 Telegram Alert Test")
                    
                    with gr.Accordion("📚 New to Telegram Alerts? Setup Guide", open=False):
                        gr.HTML("""
    <div style="color: #FFFFFF !important; font-size: 14px; line-height: 1.6; padding: 10px;">
    
    <p style="color: #38BDF8; font-weight: bold; font-size: 16px; margin-bottom: 8px;">Step 1: Create a Bot (Get Token)</p>
    <ol style="color: #FFFFFF; margin-left: 20px; margin-bottom: 15px;">
        <li style="color: #FFFFFF; margin-bottom: 5px;">Open Telegram app on your phone</li>
        <li style="color: #FFFFFF; margin-bottom: 5px;">Search for <strong style="color: #38BDF8;">@BotFather</strong> and start a chat</li>
        <li style="color: #FFFFFF; margin-bottom: 5px;">Send <code style="background: #0F172A; color: #22D3EE; padding: 2px 6px; border-radius: 4px;">/newbot</code> command</li>
        <li style="color: #FFFFFF; margin-bottom: 5px;">Give your bot a name (e.g., "My Inventory Alert")</li>
        <li style="color: #FFFFFF; margin-bottom: 5px;">Give it a username ending in <code style="background: #0F172A; color: #22D3EE; padding: 2px 6px; border-radius: 4px;">bot</code> (e.g., <code style="background: #0F172A; color: #22D3EE; padding: 2px 6px; border-radius: 4px;">my_inventory_bot</code>)</li>
        <li style="color: #FFFFFF; margin-bottom: 5px;">🎉 <strong style="color: #38BDF8;">Copy the Bot Token</strong> (looks like: <code style="background: #0F172A; color: #22D3EE; padding: 2px 6px; border-radius: 4px;">6123456789:AAHxxxxx...</code>)</li>
    </ol>
    
    <hr style="border-color: #475569; margin: 15px 0;">
    
    <p style="color: #38BDF8; font-weight: bold; font-size: 16px; margin-bottom: 8px;">Step 2: Get Your Chat ID</p>
    <ol style="color: #FFFFFF; margin-left: 20px; margin-bottom: 15px;">
        <li style="color: #FFFFFF; margin-bottom: 5px;">Search for <strong style="color: #38BDF8;">@userinfobot</strong> in Telegram</li>
        <li style="color: #FFFFFF; margin-bottom: 5px;">Start a chat or send any message</li>
        <li style="color: #FFFFFF; margin-bottom: 5px;">🎉 <strong style="color: #38BDF8;">Copy your Chat ID</strong> (a number like: <code style="background: #0F172A; color: #22D3EE; padding: 2px 6px; border-radius: 4px;">123456789</code>)</li>
    </ol>
    
    <hr style="border-color: #475569; margin: 15px 0;">
    
    <p style="color: #38BDF8; font-weight: bold; font-size: 16px; margin-bottom: 8px;">Step 3: Activate Your Bot</p>
    <ol style="color: #FFFFFF; margin-left: 20px; margin-bottom: 15px;">
        <li style="color: #FFFFFF; margin-bottom: 5px;">Search for your new bot in Telegram (by the username you created)</li>
        <li style="color: #FFFFFF; margin-bottom: 5px;">Click <strong style="color: #38BDF8;">Start</strong> or send <code style="background: #0F172A; color: #22D3EE; padding: 2px 6px; border-radius: 4px;">/start</code></li>
        <li style="color: #FFFFFF; margin-bottom: 5px;">Now your bot can send you messages!</li>
    </ol>
    
    <hr style="border-color: #475569; margin: 15px 0;">
    
    <p style="color: #38BDF8; font-weight: bold; font-size: 16px; margin-bottom: 8px;">Step 4: Test Here</p>
    <ol style="color: #FFFFFF; margin-left: 20px; margin-bottom: 15px;">
        <li style="color: #FFFFFF; margin-bottom: 5px;">Paste your <strong style="color: #38BDF8;">Bot Token</strong> below</li>
        <li style="color: #FFFFFF; margin-bottom: 5px;">Paste your <strong style="color: #38BDF8;">Chat ID</strong> below</li>
        <li style="color: #FFFFFF; margin-bottom: 5px;">Click <strong style="color: #38BDF8;">🔔 Send Test Alert</strong></li>
        <li style="color: #FFFFFF; margin-bottom: 5px;">Check your Telegram for the message! 📱</li>
    </ol>
    
    </div>
    """)
                    
                    
                    
                    token_visibility = gr.State(False)
                    chat_visibility = gr.State(False)
                    api_visibility = gr.State(False)
                    
                    # --- Bot Token Section ---
                    gr.HTML("""
                        <div style="margin-bottom: 4px;">
                            <div style="color: #FFFFFF !important; font-size: 0.875rem; font-weight: 700; opacity: 1;">Bot Token</div>
                            <div style="color: #E2E8F0 !important; font-size: 0.75rem; opacity: 0.9;">Get from @BotFather on Telegram</div>
                        </div>
                    """)
                    with gr.Row(elem_classes="token-input-row"):
                        telegram_token = gr.Textbox(
                            label=None,
                            show_label=False,
                            placeholder="123456789:AAHxxxxxxx...",
                            type="password",
                            value=config_data.get("telegram_token", ""),
                            scale=10,
                            min_width=200,
                            container=True
                        )
                        btn_eye_token = gr.Button("👁️", scale=0, min_width=50, elem_id="btn-eye-toggle-token")
                    
                    # --- Chat ID Section ---
                    gr.HTML("""
                        <div style="margin-top: 12px; margin-bottom: 4px;">
                            <div style="color: #FFFFFF !important; font-size: 0.875rem; font-weight: 700; opacity: 1;">Chat ID</div>
                            <div style="color: #E2E8F0 !important; font-size: 0.75rem; opacity: 0.9;">Get from @userinfobot on Telegram</div>
                        </div>
                    """)
                    with gr.Row(elem_classes="token-input-row"):
                        telegram_chat_id = gr.Textbox(
                            label=None,
                             show_label=False,
                            placeholder="Your numeric chat ID",
                            # Default to password so we can toggle it, or just text if it's not sensitive? 
                            # User asked for eye option, implying they want it hidden/toggleable.
                            type="password", 
                            value=config_data.get("telegram_chat_id", ""),
                             scale=10,
                            min_width=200,
                            container=True
                        )
                        btn_eye_chat = gr.Button("👁️", scale=0, min_width=50, elem_id="btn-eye-toggle-chat")
                    
                    with gr.Row():
                        btn_save_telegram = gr.Button("💾 Save Credentials", variant="primary")
                        btn_reset_telegram = gr.Button("🗑️ Reset Credentials", variant="secondary")
                    
                    telegram_status = gr.Textbox(label="Status", value="🔔 Enter credentials to test", interactive=False)
                    btn_test_telegram = gr.Button("🔔 Send Test Alert", variant="secondary", elem_id="btn-test-telegram")
        
        def set_api_key_session(key):
            success, msg = initialize_ai(key)
            if success:
                return "✅ Session Started. (Key not saved)"
            return msg

        def save_and_set_api_key(key):
            success, msg = initialize_ai(key)
            if success:
                save_config({"openai_api_key": key})
                return "✅ Key Saved & AI Started!"
            return msg

        def reset_api_key():
            if "OPENAI_API_KEY" in os.environ:
                del os.environ["OPENAI_API_KEY"]
            global rag_engine, inventory_agent
            rag_engine = None
            inventory_agent = None
            # Also clear from config
            conf = load_config()
            if "openai_api_key" in conf:
                conf["openai_api_key"] = ""
                save_config(conf)
            return "🔄 Credentials Reset. AI Disabled."
        
        def save_telegram_creds(token, chat_id):
            if not token or not chat_id:
                return "❌ Error: Both Token and Chat ID are required."
            save_config({"telegram_token": token, "telegram_chat_id": chat_id})
            
            # Auto-start bot on save
            status_msg = start_telegram_bot(token, chat_id)
            return f"✅ Credentials Saved! {status_msg}"
            
        def reset_telegram_creds():
            save_config({"telegram_token": "", "telegram_chat_id": ""})
            return "", "", "🗑️ Credentials Deleted."
        
        def toggle_visibility(is_visible, current_val):
            new_state = not is_visible
            new_type = "text" if new_state else "password"
            icon = "🙈" if new_state else "👁️"
            # Highlight button when visible (Primary = Blue/Active, Secondary = Gray/Inactive)
            variant = "primary" if new_state else "secondary"
            return new_state, gr.Textbox(type=new_type, value=current_val), gr.Button(value=icon, variant=variant)
            
        btn_eye_token.click(toggle_visibility, [token_visibility, telegram_token], [token_visibility, telegram_token, btn_eye_token])
        btn_eye_chat.click(toggle_visibility, [chat_visibility, telegram_chat_id], [chat_visibility, telegram_chat_id, btn_eye_chat])
        btn_eye_api.click(toggle_visibility, [api_visibility, api_input], [api_visibility, api_input, btn_eye_api])
        
        
        btn_run_session.click(set_api_key_session, [api_input], [api_status])
        btn_save_permanent.click(save_and_set_api_key, [api_input], [api_status])
        btn_reset_key.click(reset_api_key, None, [api_status])
        
        btn_save_telegram.click(save_telegram_creds, [telegram_token, telegram_chat_id], [telegram_status])
        btn_reset_telegram.click(reset_telegram_creds, None, [telegram_token, telegram_chat_id, telegram_status])
        btn_test_telegram.click(send_telegram_test, [telegram_token, telegram_chat_id], [telegram_status])
    
    # Footer
    gr.HTML("""
        <div id="footer-text" style="color: #FFFFFF !important;">
            Built with ❤️ using <b style="color: #FFFFFF;">Gradio</b> | <b style="color: #FFFFFF;">LangChain</b> | <b style="color: #FFFFFF;">RAG</b> | <b style="color: #FFFFFF;">Chroma Vector DB</b>
        </div>
    """)

    # Chat Logic Integration
    msg.submit(respond, [msg, chatbot], [msg, chatbot])
    submit.click(respond, [msg, chatbot], [msg, chatbot])
    
    # Dataset Explorer Logic (Toggle Dual View)
    def open_explorer():
        return gr.update(visible=False), gr.update(visible=True)
    
    def close_explorer():
        return gr.update(visible=True), gr.update(visible=False)

    btn_open_explorer.click(open_explorer, None, [main_view_container, dataset_view_container])
    btn_exit_explorer.click(close_explorer, None, [main_view_container, dataset_view_container])
    
    btn_upload.click(handle_dataset_upload, [upload_input], [upload_status, modal_viewer])
    btn_refresh_modal.click(get_inventory_df, None, [modal_viewer])
    btn_refresh_view.click(get_inventory_df, None, [modal_viewer]) # Legacy support
    
    # Quick action button handlers
    def trigger_low_stock(history):
        return respond("Show low stock items", history)
    
    def trigger_all_products(history):
        return respond("Find all products", history)
    
    def trigger_inventory(history):
        return respond("Show inventory status", history)
    
    def trigger_suppliers(history):
        return respond("Contact supplier", history)
    
    def trigger_reports(history):
        return respond("Show weekly report", history)
    
    def trigger_search_products(history):
        return respond("How can I search for a specific product?", history)
    
    btn_low_stock.click(trigger_low_stock, [chatbot], [msg, chatbot])
    btn_all_products.click(trigger_all_products, [chatbot], [msg, chatbot])
    btn_inventory.click(trigger_inventory, [chatbot], [msg, chatbot])
    btn_products.click(trigger_search_products, [chatbot], [msg, chatbot])
    btn_suppliers.click(trigger_suppliers, [chatbot], [msg, chatbot])
    btn_reports.click(trigger_reports, [chatbot], [msg, chatbot])
    
    # Forward to Telegram logic
    btn_forward.click(
        forward_last_message, 
        [chatbot, telegram_token, telegram_chat_id], 
        [forward_status]
    )


if __name__ == "__main__":
    # Auto-start services if config exists
    conf = load_config()
    
    # 1. Telegram Bot
    if conf.get("telegram_token") and conf.get("telegram_chat_id"):
        print("🚀 Auto-starting Telegram Bot...")
        start_telegram_bot(conf.get("telegram_token"), conf.get("telegram_chat_id"))
        
    # 2. AI Engine (if saved)
    if conf.get("openai_api_key"):
        print("🧠 Auto-loading Saved API Key...")
        initialize_ai(conf.get("openai_api_key"))

    demo.launch(
        share=True, 
        server_name="0.0.0.0", 
        server_port=7860
    )
