"""
RAG Engine for Intelligent Inventory Management

Implements Retrieval-Augmented Generation (RAG) using:
- LangChain for orchestration
- Chroma for vector storage
- OpenAI embeddings

Demonstrates:
- RAG pipeline architecture
- Vector database integration
- Semantic search
- Context-aware responses

Usage:
    from ai.rag_engine import InventoryRAGEngine
    
    rag = InventoryRAGEngine()
    response = rag.query("What supplier has the best price for Winter Jackets?")
"""

import os
import json
from typing import List, Dict, Optional
from pathlib import Path
import shutil

# LangChain imports
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_classic.prompts import ChatPromptTemplate
from langchain_classic.schema import Document
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_classic.chains import RetrievalQA


class InventoryRAGEngine:
    """
    RAG-powered inventory knowledge assistant.
    
    Combines product knowledge base with LLM to provide
    context-aware recommendations for inventory management.
    """
    
    def __init__(
        self,
        knowledge_base_path: Optional[str] = None,
        persist_directory: str = "./chroma_db",
        model: str = "gpt-4",
        embedding_model: str = "text-embedding-3-small"
    ):
        """
        Initialize RAG engine.
        
        Args:
            knowledge_base_path: Path to JSON knowledge base
            persist_directory: Directory for Chroma persistence
            model: OpenAI model for generation
            embedding_model: OpenAI model for embeddings
        """
        self.persist_directory = persist_directory
        
        # Initialize LLM
        self.llm = ChatOpenAI(
            model=model,
            temperature=0.2,
            api_key=os.environ.get("OPENAI_API_KEY")
        )
        
        # Initialize embeddings
        self.embeddings = OpenAIEmbeddings(
            model=embedding_model,
            api_key=os.environ.get("OPENAI_API_KEY")
        )
        
        # Load knowledge base
        self.knowledge_base_path = knowledge_base_path or self._default_kb_path()
        self.documents = []
        self.vector_store = None
        
        # Load and index if knowledge base exists
        if os.path.exists(self.knowledge_base_path):
            self._load_knowledge_base()
            self._create_vector_store()
    
    def _default_kb_path(self) -> str:
        """Get default knowledge base path."""
        return os.path.join(
            os.path.dirname(__file__),
            "../knowledge_base/products.json"
        )
    
    def _load_knowledge_base(self):
        """Load product knowledge from JSON file."""
        with open(self.knowledge_base_path, "r") as f:
            data = json.load(f)
        
        # Convert to LangChain documents
        for product in data.get("products", []):
            content = self._format_product_document(product)
            doc = Document(
                page_content=content,
                metadata={
                    "product_id": product.get("id"),
                    "category": product.get("category"),
                    "type": "product"
                }
            )
            self.documents.append(doc)
        
        # Add supplier information
        for supplier in data.get("suppliers", []):
            content = self._format_supplier_document(supplier)
            doc = Document(
                page_content=content,
                metadata={
                    "supplier_id": supplier.get("id"),
                    "type": "supplier"
                }
            )
            self.documents.append(doc)
        
        print(f"📚 Loaded {len(self.documents)} documents into RAG engine")
    
    def _format_product_document(self, product: Dict) -> str:
        """Format product info for embedding."""
        return f"""
Product: {product.get('name', 'Unknown')}
ID: {product.get('id', 'N/A')}
Category: {product.get('category', 'Unknown')}
Price: ${product.get('base_price', 0):.2f}
Stock Level: {product.get('stock', 0)} units
Reorder Point: {product.get('reorder_point', 5)} units
Lead Time: {product.get('lead_time_days', 7)} days
Preferred Supplier: {product.get('supplier_id', 'N/A')}
Description: {product.get('description', '')}
Tags: {', '.join(product.get('tags', []))}
"""
    
    def _format_supplier_document(self, supplier: Dict) -> str:
        """Format supplier info for embedding."""
        return f"""
Supplier: {supplier.get('name', 'Unknown')}
ID: {supplier.get('id', 'N/A')}
Contact: {supplier.get('contact', 'N/A')}
Email: {supplier.get('email', 'N/A')}
Categories: {', '.join(supplier.get('categories', []))}
Average Lead Time: {supplier.get('avg_lead_time', 7)} days
Rating: {supplier.get('rating', 'N/A')}/5
Payment Terms: {supplier.get('payment_terms', 'N/A')}
Notes: {supplier.get('notes', '')}
"""
    
    def _create_vector_store(self):
        """Create or load Chroma vector store."""
        if not self.documents:
            print("⚠️ No documents to index")
            return
        
        # Split documents for better retrieval
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50
        )
        splits = text_splitter.split_documents(self.documents)
        
        # Create vector store
        self.vector_store = Chroma.from_documents(
            documents=splits,
            embedding=self.embeddings,
            persist_directory=self.persist_directory
        )
        
        print(f"✅ Created vector store with {len(splits)} chunks")
    
    def query(
        self,
        question: str,
        k: int = 3,
        include_sources: bool = True
    ) -> Dict:
        """
        Query the RAG system with a natural language question.
        
        Args:
            question: User's question about inventory
            k: Number of relevant documents to retrieve
            include_sources: Whether to include source documents
            
        Returns:
            Dict with 'answer' and optionally 'sources'
        """
        if not self.vector_store:
            return {
                "answer": "Knowledge base not loaded. Please initialize with product data.",
                "sources": []
            }
        
        # Create retrieval chain
        retriever = self.vector_store.as_retriever(
            search_kwargs={"k": k}
        )
        
        # Custom prompt for inventory context
        prompt = ChatPromptTemplate.from_template("""
You are an intelligent inventory management assistant. Use the following context 
to answer the question. If you don't know the answer, say so - don't make up information.

Context:
{context}

Question: {question}

Provide a helpful, actionable response focused on inventory management.
""")
        
        # Build QA chain
        qa_chain = RetrievalQA.from_chain_type(
            llm=self.llm,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=include_sources
        )
        
        # Execute query
        result = qa_chain.invoke({"query": question})
        
        response = {
            "answer": result.get("result", "No answer generated"),
        }
        
        if include_sources and "source_documents" in result:
            response["sources"] = [
                {
                    "content": doc.page_content[:200] + "...",
                    "metadata": doc.metadata
                }
                for doc in result["source_documents"]
            ]
        
        return response

    def reload(self):
        """Reload and re-index the knowledge base."""
        print("🔄 RAG Engine reloading...")
        
        # Clear existing vector store if it exists
        if os.path.exists(self.persist_directory):
            try:
                shutil.rmtree(self.persist_directory)
                print(f"🗑️ Cleared old vector store at {self.persist_directory}")
            except Exception as e:
                print(f"⚠️ Error clearing vector store: {e}")
        
        self.documents = []
        if os.path.exists(self.knowledge_base_path):
            self._load_knowledge_base()
            self._create_vector_store()
            print("✅ RAG Engine reload complete.")
        else:
            print(f"⚠️ Cannot reload: {self.knowledge_base_path} not found.")
    
    def get_product_context(self, product_id: str) -> str:
        """
        Get RAG context for a specific product.
        
        Used by the alert system to enrich notifications.
        """
        if not self.vector_store:
            return ""
        
        # Search for product-specific context
        results = self.vector_store.similarity_search(
            f"product {product_id}",
            k=2
        )
        
        return "\n".join([doc.page_content for doc in results])
    
    def suggest_reorder(self, product_id: str, current_stock: int) -> str:
        """
        Generate AI-powered reorder suggestion.
        
        Args:
            product_id: Product to check
            current_stock: Current stock level
            
        Returns:
            Formatted reorder suggestion
        """
        context = self.get_product_context(product_id)
        
        prompt = f"""
Based on this product information:
{context}

Current Stock: {current_stock} units

Provide a brief reorder recommendation including:
1. Should we reorder now?
2. Recommended quantity
3. Best supplier to contact
"""
        
        response = self.llm.invoke(prompt)
        return response.content


# Example usage
if __name__ == "__main__":
    print("🔧 Testing RAG Engine...")
    print("Note: Requires OPENAI_API_KEY environment variable")
    
    if os.environ.get("OPENAI_API_KEY"):
        rag = InventoryRAGEngine()
        
        # Test query
        result = rag.query("Which products are running low on stock?")
        print(f"\n📊 Answer: {result['answer']}")
    else:
        print("⚠️ Set OPENAI_API_KEY to run full test")
