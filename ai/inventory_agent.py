"""
LangChain Agent for Intelligent Inventory Recommendations

Implements a multi-tool AI agent that can:
- Query product information
- Check stock levels
- Recommend reorders
- Contact suppliers

Demonstrates:
- LangChain agents
- Custom tool creation
- Multi-step reasoning
- Function calling

Usage:
    from ai.smart_agent import InventoryAgent
    
    agent = InventoryAgent()
    response = agent.process_alert(product_id="SKU001", current_stock=3)
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional

# LangChain imports
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import Tool, StructuredTool
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_classic.schema import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from ai.rag_engine import InventoryRAGEngine


# Tool Input Schemas
class ProductLookupInput(BaseModel):
    """Input for product lookup tool."""
    product_id: str = Field(description="The product SKU/ID to look up")


class SupplierLookupInput(BaseModel):
    """Input for supplier lookup tool."""
    category: str = Field(description="Product category to find suppliers for")


class ReorderInput(BaseModel):
    """Input for reorder recommendation tool."""
    product_id: str = Field(description="Product to reorder")
    current_stock: int = Field(description="Current stock level")
    urgency: str = Field(default="normal", description="Urgency: low, normal, high")


class InventoryAgent:
    """
    AI Agent for intelligent inventory management.
    
    Uses LangChain function calling to orchestrate multiple tools
    and provide comprehensive recommendations.
    """
    
    def __init__(self, model: str = "gpt-4", kb_path: Optional[str] = None):
        """Initialize the inventory agent."""
        self.kb_path = kb_path or os.path.join(
            os.path.dirname(__file__), "../knowledge_base/products.json"
        )
        self.PRODUCT_DB = {}
        self.SUPPLIER_DB = {}
        self._load_databases()
        
        self.llm = ChatOpenAI(
            model=model,
            temperature=0,
            api_key=os.environ.get("OPENAI_API_KEY")
        )
        # Initialize RAG for the agent to use as a tool
        self.rag = InventoryRAGEngine(knowledge_base_path=self.kb_path)
        
        self.tools = self._create_tools()
        self.agent = self._create_agent()

    def _load_databases(self):
        """Load product and supplier data from JSON knowledge base."""
        if not os.path.exists(self.kb_path):
            print(f"⚠️ Knowledge base not found at {self.kb_path}")
            return

        try:
            with open(self.kb_path, "r") as f:
                data = json.load(f)
            
            # Map products
            for p in data.get("products", []):
                sku = p.get("id", "UNKNOWN")
                self.PRODUCT_DB[sku] = {
                    "name": p.get("name"),
                    "category": p.get("category"),
                    "price": p.get("base_price"),
                    "reorder_point": p.get("reorder_point", 10),
                    "supplier": p.get("supplier_id"),
                    "lead_time": p.get("lead_time_days", 7)
                }
            
            # Map suppliers
            for s in data.get("suppliers", []):
                sid = s.get("id", "UNKNOWN")
                self.SUPPLIER_DB[sid] = {
                    "name": s.get("name"),
                    "contact": s.get("contact"),
                    "email": s.get("email"),
                    "categories": s.get("categories", []),
                    "rating": s.get("rating"),
                    "avg_lead_time": s.get("avg_lead_time")
                }
            print(f"✅ Loaded {len(self.PRODUCT_DB)} products and {len(self.SUPPLIER_DB)} suppliers into Agent.")
        except Exception as e:
            print(f"❌ Error loading knowledge base for Agent: {e}")
    
    def _create_tools(self) -> List[Tool]:
        """Create tools for the agent to use."""
        
        tools = [
            StructuredTool.from_function(
                func=self._lookup_product,
                name="lookup_product",
                description="Look up product details by SKU/ID. Use this to get product name, price, supplier, and reorder point.",
                args_schema=ProductLookupInput
            ),
            StructuredTool.from_function(
                func=self._find_suppliers,
                name="find_suppliers",
                description="Find suppliers for a product category. Returns supplier name, contact info, and ratings.",
                args_schema=SupplierLookupInput
            ),
            StructuredTool.from_function(
                func=self._calculate_reorder,
                name="calculate_reorder",
                description="Calculate recommended reorder quantity and timing based on current stock and lead time.",
                args_schema=ReorderInput
            ),
            Tool(
                name="search_knowledge_base",
                func=self._search_rag,
                description="Search the inventory knowledge base for general info about products, suppliers, or the dataset itself. Use this for 'What is this about?' or 'Tell me about...' questions."
            ),
            Tool(
                name="get_inventory_statistics",
                func=lambda x: f"Total Products: {len(self.PRODUCT_DB)}. Database status: Active.",
                description="Get high-level statistics about the dataset entries."
            ),
            Tool(
                name="get_current_time",
                func=lambda x: datetime.now().strftime("%Y-%m-%d %H:%M"),
                description="Get current date and time"
            )
        ]
        
        return tools
    
    def _lookup_product(self, product_id: str) -> str:
        """Look up product information."""
        product = self.PRODUCT_DB.get(product_id)
        
        if not product:
            return f"Product {product_id} not found in database."
        
        supplier = self.SUPPLIER_DB.get(product["supplier"], {})
        
        return f"""
📦 Product: {product['name']}
   SKU: {product_id}
   Category: {product['category']}
   Price: ${product['price']}
   Reorder Point: {product['reorder_point']} units
   Lead Time: {product['lead_time']} days
   Supplier: {supplier.get('name', 'Unknown')}
"""
    
    def _find_suppliers(self, category: str) -> str:
        """Find suppliers for a category."""
        matching = []
        
        for sup_id, supplier in self.SUPPLIER_DB.items():
            if category in supplier["categories"]:
                matching.append(f"""
🏭 {supplier['name']} (ID: {sup_id})
   📞 Contact: {supplier['contact']}
   📧 Email: {supplier['email']}
   ⭐ Rating: {supplier['rating']}/5
   ⏱️ Avg Lead Time: {supplier['avg_lead_time']} days
""")
        
        if not matching:
            return f"No suppliers found for category: {category}"
        
        return "Suppliers found:\n" + "\n".join(matching)
    
    def _calculate_reorder(
        self,
        product_id: str,
        current_stock: int,
        urgency: str = "normal"
    ) -> str:
        """Calculate reorder recommendation."""
        product = self.PRODUCT_DB.get(product_id)
        
        if not product:
            return f"Product {product_id} not found."
        
        reorder_point = product["reorder_point"]
        lead_time = product["lead_time"]
        
        # Calculate recommended quantity
        urgency_multiplier = {"low": 1.0, "normal": 1.5, "high": 2.0}
        multiplier = urgency_multiplier.get(urgency, 1.5)
        
        recommended_qty = int(reorder_point * multiplier * 2)
        
        # Determine if reorder is needed
        if current_stock <= reorder_point:
            status = "🚨 URGENT: Below reorder point!"
        elif current_stock <= reorder_point * 1.5:
            status = "⚠️ WARNING: Approaching reorder point"
        else:
            status = "✅ Stock levels adequate"
        
        return f"""
📊 Reorder Analysis for {product['name']}:

{status}

Current Stock: {current_stock} units
Reorder Point: {reorder_point} units
Lead Time: {lead_time} days

📦 Recommendation:
   Quantity to Order: {recommended_qty} units
   Expected Delivery: {lead_time} days from order
   Estimated Cost: ${product['price'] * 0.6 * recommended_qty:.2f} (wholesale)
"""
    
    def _search_rag(self, query: str) -> str:
        """Use the RAG engine to find answers."""
        result = self.rag.query(query)
        return result.get("answer", "No info found.")

    def _create_agent(self) -> AgentExecutor:
        """Create the LangChain agent."""
        
        system_prompt = """You are an intelligent inventory management assistant for a retail company.
Your role is to help manage stock levels and make smart reorder recommendations. 

You have access to a 'Knowledge Base' which contains the actual dataset of products and suppliers. 
If someone asks 'What is this dataset about?' or meta-questions, use the 'search_knowledge_base' OR 'get_inventory_statistics' tools.

You are NOT just a general AI; you are the dedicated brain of this specific Inventory System. 

Format your responses for Telegram messages (use emojis, keep it scannable)."""

        prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=system_prompt),
            ("user", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
        
        agent = create_openai_functions_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=prompt
        )
        
        return AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=True,
            handle_parsing_errors=True
        )
    
    def process_alert(
        self,
        product_id: str,
        current_stock: int,
        event_type: str = "low_stock"
    ) -> str:
        """
        Process an inventory alert and generate intelligent response.
        
        Args:
            product_id: Product that triggered alert
            current_stock: Current stock level
            event_type: Type of alert (low_stock, high_value, etc.)
            
        Returns:
            Formatted recommendation for Telegram
        """
        prompt = f"""
An inventory alert was triggered:

📦 Product ID: {product_id}
📊 Current Stock: {current_stock} units
🔔 Alert Type: {event_type}

Please:
1. Look up this product's details
2. Find suppliers for this product category
3. Calculate a reorder recommendation
4. Provide a complete action plan
"""
        
        result = self.agent.invoke({"input": prompt})
        return result.get("output", "Unable to process alert")

    def reload(self):
        """Reload databases from JSON knowledge base."""
        print("🔄 Inventory Agent reloading...")
        self.PRODUCT_DB = {}
        self.SUPPLIER_DB = {}
        self._load_databases()
        print("✅ Inventory Agent reload complete.")
    
    def ask(self, question: str) -> str:
        """
        Ask the agent any inventory-related question.
        
        Args:
            question: Natural language question
            
        Returns:
            Agent's response
        """
        result = self.agent.invoke({"input": question})
        return result.get("output", "Unable to process question")


# Example usage
if __name__ == "__main__":
    print("🔧 Testing Inventory Agent...")
    print("Note: Requires OPENAI_API_KEY environment variable")
    
    if os.environ.get("OPENAI_API_KEY"):
        agent = InventoryAgent()
        
        # Test alert processing
        print("\n📊 Processing low stock alert for SKU005...")
        response = agent.process_alert(
            product_id="SKU005",
            current_stock=2,
            event_type="low_stock"
        )
        print(f"\n🤖 Agent Response:\n{response}")
    else:
        print("⚠️ Set OPENAI_API_KEY to run full test")
        
        # Test tools without LLM
        print(f"\n📦 Available products: {list(agent.PRODUCT_DB.keys())}")
