import sqlite3
from faker import Faker
import random
import json
from datetime import datetime, timedelta

DB = "database.db"
faker = Faker()
conn = sqlite3.connect(DB)
cursor = conn.cursor()

# --- 1. Populate Products (Safe for UNIQUE constraints) ---
product_names = ["Beef Sausage", "Chicken Wings", "Ham", "Veggie Burger", "Turkey Breast", "Bacon Strips"]
locations = ["Freezer 1", "Aisle 2", "Rack 3", "Cooler 1", "Storage Room"]

product_data = []
used_names = set()

while len(product_data) < 2000:
    base_name = random.choice(product_names)
    suffix = faker.unique.random_int(1000, 9999)
    name = f"{base_name} {suffix}"
    
    if name in used_names:
        continue

    barcode = f"BC{faker.unique.random_int(10000, 99999)}"
    quantity = random.randint(5, 200)
    location = random.choice(locations)

    product_data.append((name, barcode, quantity, location))
    used_names.add(name)

cursor.executemany("INSERT INTO products (name, barcode, quantity, location) VALUES (?, ?, ?, ?)", product_data)
conn.commit()

conn.close()
print("✅ Inserted 2000 records into products, users, and sales_orders.")