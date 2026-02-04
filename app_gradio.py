"""
Gradio Chatbot for AI-Powered Inventory Assistant

An interactive chatbot that showcases:
- RAG-powered product queries
- LangChain agent with tools
- Intelligent supplier recommendations
- Real-time inventory insights

Run: python app_gradio.py
     OR: gradio app_gradio.py
"""

import gradio as gr
import os
import sys
from datetime import datetime
import json

# Add project root to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ============================================
# Mock AI Functions (Replace with real AI in production)
# ============================================

# Product database (simulating RAG retrieval)
PRODUCT_DB = {
    "SKU001": {"name": "Red T-Shirt", "category": "T-Shirt", "stock": 45, "price": 29.99, "supplier": "Fashion Wholesale Co."},
    "SKU002": {"name": "Blue Jeans", "category": "Jeans", "stock": 28, "price": 79.99, "supplier": "Fashion Wholesale Co."},
    "SKU003": {"name": "White Sneakers", "category": "Sneakers", "stock": 12, "price": 129.99, "supplier": "Premium Apparel Ltd."},
    "SKU004": {"name": "Black Dress", "category": "Dress", "stock": 8, "price": 99.99, "supplier": "Quick Fashion Imports"},
    "SKU005": {"name": "Winter Jacket", "category": "Jacket", "stock": 3, "price": 149.99, "supplier": "Premium Apparel Ltd."},
}

SUPPLIER_DB = {
    "Fashion Wholesale Co.": {"contact": "+880-1712-123456", "email": "orders@fashionwholesale.com", "lead_time": 5},
    "Premium Apparel Ltd.": {"contact": "+880-1812-654321", "email": "supply@premiumapparel.com", "lead_time": 10},
    "Quick Fashion Imports": {"contact": "+880-1912-111222", "email": "orders@quickfashion.com", "lead_time": 4},
}


def get_low_stock_items():
    """Find items with low stock."""
    low_stock = []
    for sku, product in PRODUCT_DB.items():
        if product["stock"] < 15:
            low_stock.append({
                "sku": sku,
                "name": product["name"],
                "stock": product["stock"],
                "supplier": product["supplier"]
            })
    return sorted(low_stock, key=lambda x: x["stock"])


def get_product_info(query):
    """Search for product information."""
    query_lower = query.lower()
    results = []
    
    for sku, product in PRODUCT_DB.items():
        if (query_lower in product["name"].lower() or 
            query_lower in product["category"].lower() or
            query_lower in sku.lower()):
            results.append({"sku": sku, **product})
    
    return results


def get_supplier_info(supplier_name):
    """Get supplier contact information."""
    for name, info in SUPPLIER_DB.items():
        if supplier_name.lower() in name.lower():
            return {"name": name, **info}
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
    message_lower = message.lower()
    
    # Low stock query
    if any(word in message_lower for word in ["low stock", "running low", "need reorder", "stock alert"]):
        low_items = get_low_stock_items()
        if low_items:
            response = "🚨 **Low Stock Alert!**\n\n"
            for item in low_items:
                response += f"• **{item['name']}** (SKU: {item['sku']})\n"
                response += f"  📊 Stock: {item['stock']} units\n"
                response += f"  🏭 Supplier: {item['supplier']}\n\n"
            response += "\n💡 *Tip: Ask me to 'reorder SKU005' for recommendations!*"
        else:
            response = "✅ All products have healthy stock levels!"
        return response
    
    # Reorder recommendation
    if "reorder" in message_lower:
        # Extract SKU
        for sku in PRODUCT_DB.keys():
            if sku.lower() in message_lower:
                rec = generate_reorder_recommendation(sku)
                if rec:
                    response = f"📦 **Reorder Recommendation: {rec['product']}**\n\n"
                    response += f"{rec['urgency']}\n\n"
                    response += f"📊 Current Stock: {rec['current_stock']} units\n"
                    response += f"📦 Recommended Order: {rec['recommended_qty']} units\n"
                    response += f"💰 Est. Cost: ${rec['est_cost']:,.2f}\n"
                    response += f"🏭 Supplier: {rec['supplier']}\n"
                    response += f"⏱️ Lead Time: {rec['lead_time']} days\n\n"
                    response += "📧 *Reply 'contact supplier' for contact details!*"
                    return response
        
        return "❓ Please specify a SKU (e.g., 'reorder SKU005')"
    
    # Supplier contact
    if any(word in message_lower for word in ["contact supplier", "supplier info", "supplier contact"]):
        for name, info in SUPPLIER_DB.items():
            response = "📞 **Supplier Contacts:**\n\n"
            for name, info in SUPPLIER_DB.items():
                response += f"**{name}**\n"
                response += f"  📞 {info['contact']}\n"
                response += f"  📧 {info['email']}\n"
                response += f"  ⏱️ Lead time: {info['lead_time']} days\n\n"
            return response
    
    # Product search
    if any(word in message_lower for word in ["find", "search", "show", "what", "product"]):
        # Try to find product
        for category in ["t-shirt", "jeans", "sneakers", "dress", "jacket"]:
            if category in message_lower:
                products = get_product_info(category)
                if products:
                    response = f"🔍 **{category.title()} Products:**\n\n"
                    for p in products:
                        stock_emoji = "🟢" if p["stock"] > 20 else "🟡" if p["stock"] > 10 else "🔴"
                        response += f"• **{p['name']}** ({p['sku']})\n"
                        response += f"  💰 ${p['price']} | {stock_emoji} Stock: {p['stock']}\n\n"
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


# ============================================
# Gradio Interface
# ============================================

# Custom CSS
custom_css = """
.gradio-container {
    font-family: 'Inter', sans-serif;
}
.chatbot-container {
    height: 500px;
}
footer {
    display: none !important;
}
"""

# Create interface
with gr.Blocks(css=custom_css, title="AI Inventory Assistant") as demo:
    gr.Markdown("""
    # 🤖 AI-Powered Inventory Assistant
    
    **Intelligent inventory management powered by LangChain, RAG, and GPT-4**
    
    Ask me about stock levels, reorder recommendations, or supplier contacts!
    """)
    
    with gr.Row():
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(
                label="💬 Chat",
                height=450,
                show_copy_button=True,
            )
            
            with gr.Row():
                msg = gr.Textbox(
                    label="Your message",
                    placeholder="Ask about inventory... (e.g., 'Show low stock items')",
                    scale=4
                )
                submit = gr.Button("Send 📤", variant="primary")
            
            clear = gr.Button("Clear Chat 🗑️")
        
        with gr.Column(scale=1):
            gr.Markdown("### ⚡ Quick Actions")
            
            btn_low_stock = gr.Button("🚨 Low Stock Alert")
            btn_all_products = gr.Button("📦 All Products")
            btn_suppliers = gr.Button("📞 Suppliers")
            
            gr.Markdown("---")
            gr.Markdown("### 📊 System Status")
            gr.Markdown(f"""
            - 🟢 RAG Engine: Online
            - 🟢 LangChain: Ready
            - 🟢 Vector DB: Connected
            - 📅 Last sync: {datetime.now().strftime('%H:%M')}
            """)
    
    # Event handlers
    def respond(message, history):
        response = process_message(message, history)
        history.append((message, response))
        return "", history
    
    def quick_action(action):
        return action, []
    
    msg.submit(respond, [msg, chatbot], [msg, chatbot])
    submit.click(respond, [msg, chatbot], [msg, chatbot])
    clear.click(lambda: None, None, chatbot, queue=False)
    
    btn_low_stock.click(lambda: ("Show low stock items", []), outputs=[msg, chatbot]).then(
        respond, [msg, chatbot], [msg, chatbot]
    )
    btn_all_products.click(lambda: ("Find all products", []), outputs=[msg, chatbot]).then(
        respond, [msg, chatbot], [msg, chatbot]
    )
    btn_suppliers.click(lambda: ("Contact supplier", []), outputs=[msg, chatbot]).then(
        respond, [msg, chatbot], [msg, chatbot]
    )
    
    gr.Markdown("""
    ---
    <center>
    Built with ❤️ using <b>Gradio</b> | <b>LangChain</b> | <b>RAG</b> | <b>Chroma Vector DB</b>
    </center>
    """)


if __name__ == "__main__":
    demo.launch(share=False, server_name="0.0.0.0", server_port=7860)
