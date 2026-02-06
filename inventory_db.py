import sqlite3
import pandas as pd
import json
import os

DB_PATH = "knowledge_base/inventory.db"

def get_db_connection():
    """Create a database connection to the SQLite database."""
    os.makedirs("knowledge_base", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database with products and suppliers tables."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create products table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            sku TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT,
            stock INTEGER DEFAULT 0,
            base_price REAL DEFAULT 0.0,
            supplier_id TEXT,
            description TEXT,
            reorder_point INTEGER DEFAULT 10,
            lead_time_days INTEGER DEFAULT 7
        )
    ''')
    
    # Create suppliers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS suppliers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            contact TEXT,
            email TEXT,
            avg_lead_time INTEGER DEFAULT 7
        )
    ''')
    
    conn.commit()
    conn.close()

def migrate_from_json(json_path="knowledge_base/products.json"):
    """Migrate data from products.json to SQLite if the DB is empty."""
    if not os.path.exists(json_path):
        return False
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if products table is empty
    cursor.execute("SELECT COUNT(*) FROM products")
    if cursor.fetchone()[0] > 0:
        conn.close()
        return False # Already migrated or has data
        
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
            
        products = data.get("products", [])
        suppliers = data.get("suppliers", [])
        
        # Insert suppliers
        for s in suppliers:
            cursor.execute('''
                INSERT OR REPLACE INTO suppliers (id, name, contact, email, avg_lead_time)
                VALUES (?, ?, ?, ?, ?)
            ''', (s.get("id"), s.get("name"), s.get("contact"), s.get("email"), s.get("avg_lead_time", 7)))
            
        # Insert products
        for p in products:
            cursor.execute('''
                INSERT OR REPLACE INTO products (sku, name, category, stock, base_price, supplier_id, description, reorder_point, lead_time_days)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                p.get("sku") or p.get("id"),
                p.get("name"),
                p.get("category"),
                p.get("stock", 0),
                p.get("base_price") or p.get("price", 0.0),
                p.get("supplier_id") or p.get("supplier"),
                p.get("description"),
                p.get("reorder_point", 10),
                p.get("lead_time_days", 7)
            ))
            
        conn.commit()
    except Exception as e:
        print(f"Migration error: {e}")
    finally:
        conn.close()
    return True

def get_products_paginated(offset=0, limit=50):
    """Fetch a page of products for UI display."""
    conn = get_db_connection()
    # Join with suppliers to get the name instead of just ID
    query = '''
        SELECT p.sku, p.name, p.category, p.stock, p.base_price, s.name as supplier
        FROM products p
        LEFT JOIN suppliers s ON p.supplier_id = s.id
        LIMIT ? OFFSET ?
    '''
    df = pd.read_sql_query(query, conn, params=(limit, offset))
    # Rename for backward compatibility with UI
    df = df.rename(columns={
        "sku": "SKU",
        "name": "Name",
        "category": "Category",
        "stock": "Stock",
        "base_price": "Price",
        "supplier": "Supplier"
    })
    
    # Ensure Price column is present for formatting
    if not df.empty and "Price" in df.columns:
        df["Price"] = df["Price"].apply(lambda x: f"${x:.2f}")
    
    conn.close()
    return df

def get_total_product_count():
    """Get the total number of products in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM products")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_total_stock_units():
    """Calculate the total number of stock units across all products."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(stock) FROM products")
    count = cursor.fetchone()[0] or 0
    conn.close()
    return count

def batch_insert_products(df):
    """Insert or update products in batches for massive datasets."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    data = []
    for _, row in df.iterrows():
        sku = str(row.get('sku') or row.get('id', ''))
        if not sku: continue
        
        data.append((
            sku,
            row.get('name', 'Unknown'),
            row.get('category', 'Miscellaneous'),
            int(row.get('stock', 0)),
            float(row.get('base_price') or row.get('price', 0.0)),
            str(row.get('supplier_id') or row.get('supplier', 'Unknown')),
            row.get('description', ''),
            int(row.get('reorder_point', 10)),
            int(row.get('lead_time_days', 7))
        ))
        
    cursor.executemany('''
        INSERT OR REPLACE INTO products (sku, name, category, stock, base_price, supplier_id, description, reorder_point, lead_time_days)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', data)
    
    conn.commit()
    conn.close()
    return len(data)

def get_low_stock_sql(threshold=15):
    """Fetch low stock items directly from SQL."""
    conn = get_db_connection()
    query = "SELECT sku, name, stock, supplier_id as supplier FROM products WHERE stock < ?"
    df = pd.read_sql_query(query, conn, params=(threshold,))
    conn.close()
    return df.to_dict('records')

if __name__ == "__main__":
    init_db()
    migrate_from_json()
    print(f"Total products in SQLite: {get_total_product_count()}")
