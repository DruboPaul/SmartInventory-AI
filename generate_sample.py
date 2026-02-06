import pandas as pd
import random
import time

def generate_sample_dataset(num_rows=50000):
    print(f"🚀 Generating {num_rows} sample products...")
    
    categories = ["Electronics", "Clothing", "Home & Garden", "Toys", "Automotive", "Books", "Beauty", "Sports"]
    suppliers = ["MegaCorp Int.", "FastSupply Co.", "Global Traders", "Local Source Ltd.", "EcoGoods Inc."]
    
    data = {
        "sku": [f"SKU{i:05d}" for i in range(1, num_rows + 1)],
        "name": [f"Sample Product {i}" for i in range(1, num_rows + 1)],
        "category": [random.choice(categories) for _ in range(num_rows)],
        "stock": [random.randint(0, 500) for _ in range(num_rows)],
        "price": [round(random.uniform(5.0, 300.0), 2) for _ in range(num_rows)],
        "supplier": [random.choice(suppliers) for _ in range(num_rows)]
    }
    
    df = pd.DataFrame(data)
    # Ensure correct column names for our app
    # App expects: SKU, Name, Category, Stock, Price, Supplier (csv headers)
    # The batch_insert_products expects normalized lowercase columns but let's stick to CSV standard
    df.columns = ["SKU", "Name", "Category", "Stock", "Price", "Supplier"]
    
    filename = "sample_data_50k.csv"
    df.to_csv(filename, index=False)
    print(f"✅ Generated {filename}")

if __name__ == "__main__":
    generate_sample_dataset()
