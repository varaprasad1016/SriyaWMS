from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file, flash
import sqlite3
import csv
from io import BytesIO
import os
import barcode
from barcode import Code128
from barcode.writer import ImageWriter
from flask import make_response
from functools import wraps
import json
import chatbot
import re
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
import pytz

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # change this for security!

# IST timezone
IST = pytz.timezone('Asia/Kolkata')

# Utility function to convert UTC to IST
def utc_to_ist(utc_datetime_str):
    """Convert UTC datetime string to IST datetime string"""
    if not utc_datetime_str:
        return 'N/A'
    try:
        # Parse the UTC datetime
        if isinstance(utc_datetime_str, str):
            utc_dt = datetime.fromisoformat(utc_datetime_str.replace('Z', '+00:00'))
        else:
            utc_dt = utc_datetime_str
        
        # Convert to IST
        if utc_dt.tzinfo is None:
            utc_dt = pytz.UTC.localize(utc_dt)
        
        ist_dt = utc_dt.astimezone(IST)
        return ist_dt.strftime('%Y-%m-%d %H:%M:%S IST')
    except:
        return utc_datetime_str

# Jinja2 filter for IST conversion
@app.template_filter('to_ist')
def to_ist_filter(utc_datetime_str):
    return utc_to_ist(utc_datetime_str)

@app.template_filter('format_ist')
def format_ist_filter(utc_datetime_str, format_str='%B %d, %Y at %I:%M %p IST'):
    """Format datetime to IST with custom format"""
    if not utc_datetime_str:
        return 'N/A'
    try:
        if isinstance(utc_datetime_str, str):
            utc_dt = datetime.fromisoformat(utc_datetime_str.replace('Z', '+00:00'))
        else:
            utc_dt = utc_datetime_str
        
        if utc_dt.tzinfo is None:
            utc_dt = pytz.UTC.localize(utc_dt)
        
        ist_dt = utc_dt.astimezone(IST)
        return ist_dt.strftime(format_str)
    except:
        return utc_datetime_str

# Initialize the database
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            barcode TEXT UNIQUE NOT NULL,
            quantity INTEGER DEFAULT 0,
            location TEXT,
            min_stock_level INTEGER DEFAULT 5
        )
    ''')
    
    # Add the missing column if it doesn't exist
    try:
        cursor.execute('ALTER TABLE products ADD COLUMN min_stock_level INTEGER DEFAULT 5')
        conn.commit()
    except sqlite3.OperationalError:
        # Column already exists
        pass
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock (
            tracker_id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            FOREIGN KEY (barcode) REFERENCES products(barcode)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sales_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            order_data TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(customer_id) REFERENCES users(id)
        )
    ''')
    conn.commit()

    cursor.execute('SELECT * FROM users WHERE username = ?', ('admin',))
    if cursor.fetchone() is None:
        cursor.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                       ('admin', 'admin123', 'admin'))
        conn.commit()
    conn.close()

def no_cache(view):
    @wraps(view)
    def no_cache_wrapper(*args, **kwargs):
        response = make_response(view(*args, **kwargs))
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    return no_cache_wrapper

def generate_barcode_image(barcode_number):
    # Ensure the directory exists
    if not os.path.exists(os.path.join('static', 'barcodes')):
        os.makedirs(os.path.join('static', 'barcodes'))
        
    filepath = os.path.join('static', 'barcodes', f'{barcode_number}.png')
    if not os.path.exists(filepath):
        code128 = barcode.get('code128', barcode_number, writer=ImageWriter())
        code128.save(filepath[:-4])
    return filepath

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                         (username, password, role))
            conn.commit()
        except sqlite3.IntegrityError:
            return 'Username already exists!'
        conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ? AND password = ? AND role = ?',
                            (username, password, role)).fetchone()
        conn.close()
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            return redirect(url_for('customer_dashboard') if role == 'customer' else 'dashboard')
        else:
            return "Invalid Credentials!"
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# First, add this statistics function to your app.py
def get_dashboard_statistics():
    """Get statistics for the admin dashboard"""
    conn = get_db_connection()
    
    # Get total products count
    total_products = conn.execute('SELECT COUNT(*) as count FROM products').fetchone()['count']
    
    # Get low stock items (less than 10 in quantity)
    low_stock_count = conn.execute('SELECT COUNT(*) as count FROM products WHERE quantity < 10').fetchone()['count']
    
    # Get pending orders count
    pending_count = conn.execute("SELECT COUNT(*) as count FROM sales_orders WHERE status = 'Pending'").fetchone()['count']
    
    # Get shipped today count
    shipped_today = conn.execute("""
        SELECT COUNT(*) as count FROM sales_orders 
        WHERE status = 'Shipped' 
        AND date(created_at) = date('now')
    """).fetchone()['count']
    
    # Calculate percentage changes (using placeholder logic)
    # In a real app, you'd compare with historical data from another table
    products_growth = 0  # Placeholder
    pending_growth = 0   # Placeholder
    low_stock_growth = 0 # Placeholder
    shipped_growth = 0   # Placeholder
    
    # Get recent activity (simplified version)
    recent_activity = []
    
    # Get next inventory check date (placeholder)
    next_inventory_check = {
        'date': 'May 15, 2025',
        'detail_url': '#'
    }
    
    conn.close()
    
    return {
        'total_products': {
            'value': total_products,
            'change': products_growth,
            'trend': 'up' if products_growth > 0 else 'down'
        },
        'pending_orders': {
            'value': pending_count,
            'change': pending_growth,
            'trend': 'up' if pending_growth > 0 else 'down'
        },
        'low_stock': {
            'value': low_stock_count,
            'change': low_stock_growth,
            'trend': 'up' if low_stock_growth > 0 else 'down'
        },
        'shipped_today': {
            'value': shipped_today,
            'change': shipped_growth,
            'trend': 'up' if shipped_growth > 0 else 'down'
        },
        'recent_activity': recent_activity,
        'next_inventory_check': next_inventory_check
    }

# Then, update your dashboard route
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') == 'admin':
        conn = get_db_connection()
        orders = conn.execute('''
            SELECT sales_orders.*, users.username 
            FROM sales_orders
            LEFT JOIN users ON sales_orders.customer_id = users.id
            ORDER BY sales_orders.created_at DESC
        ''').fetchall()
        
        # Process orders to extract products information
        processed_orders = []
        for order in orders:
            order_dict = dict(order)
            try:
                # Parse the JSON data to get the product details
                order_data = json.loads(order['order_data'])
                
                # Count unique products in the order
                product_count = len(order_data)
                
                # Format the display string
                order_dict['products'] = f"{product_count} item" + ("s" if product_count != 1 else "")
                
                processed_orders.append(order_dict)
            except:
                order_dict['products'] = 'Unknown'
                processed_orders.append(order_dict)
        
        conn.close()
        
        # Get live statistics for the dashboard
        stats = get_dashboard_statistics()
        
        return render_template('dashboard.html', 
                            orders=processed_orders, 
                            stats=stats,
                            total_products=stats['total_products']['value'],
                            pending_count=stats['pending_orders']['value'],
                            low_stock_count=stats['low_stock']['value'],
                            shipped_today=stats['shipped_today']['value'])
    else:
        return redirect(url_for('customer_dashboard'))

@app.route('/order-detail/<int:order_id>')
def view_order_detail(order_id):
    """View detailed sales order in Sage-like format with print option"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Get order details
    order = conn.execute('''
        SELECT sales_orders.*, users.username, users.id as customer_id
        FROM sales_orders
        LEFT JOIN users ON sales_orders.customer_id = users.id
        WHERE sales_orders.id = ?
    ''', (order_id,)).fetchone()
    
    if not order:
        conn.close()
        flash("Order not found", "error")
        return redirect(url_for('dashboard'))
    
    # Process order items
    order_items = []
    order_total = 0
    
    try:
        order_data = json.loads(order['order_data'])
        
        for barcode, details in order_data.items():
            # Get product details
            product = conn.execute('SELECT * FROM products WHERE barcode = ?', (barcode,)).fetchone()
            
            if product:
                # Calculate price based on product name or use a pricing logic
                # For now, using a simple pricing scheme based on product characteristics
                base_price = 10.00  # Base price
                
                # Simple pricing logic - you can customize this
                product_name = product['name'].lower()
                if 'premium' in product_name or 'deluxe' in product_name:
                    price = base_price * 1.5
                elif 'basic' in product_name or 'standard' in product_name:
                    price = base_price * 0.8
                else:
                    price = base_price
                
                quantity = details.get('quantity', 1) if isinstance(details, dict) else details
                item_total = price * quantity
                order_total += item_total
                
                order_items.append({
                    'product_id': product['id'],
                    'name': product['name'],
                    'barcode': barcode,
                    'quantity': quantity,
                    'price': price,
                    'total': item_total
                })
            else:
                # Handle missing products
                price = 10.00
                quantity = details.get('quantity', 1) if isinstance(details, dict) else details
                item_total = price * quantity
                order_total += item_total
                
                order_items.append({
                    'product_id': 'N/A',
                    'name': f'[Deleted Product - {barcode}]',
                    'barcode': barcode,
                    'quantity': quantity,
                    'price': price,
                    'total': item_total
                })
    except Exception as e:
        # Handle JSON parsing errors
        order_items.append({
            'product_id': 'ERROR',
            'name': f'[Data parsing error: {str(e)}]',
            'barcode': 'N/A',
            'quantity': 0,
            'price': 0,
            'total': 0
        })
    
    conn.close()
    
    return render_template('order_detail.html', 
                          order=order, 
                          items=order_items,
                          total=order_total)

@app.route('/scan')
def scan():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('scan.html')

@app.route('/api/scan', methods=['POST'])
def scan_barcode():
    data = request.get_json()
    barcode_value = data.get('barcode')
    conn = get_db_connection()
    product = conn.execute('SELECT * FROM products WHERE barcode = ?', (barcode_value,)).fetchone()
    conn.close()
    return jsonify({'status': 'found', 'product': dict(product)}) if product else jsonify({'status': 'not_found'})

@app.route('/products')
def products():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM products').fetchall()
    conn.close()
    for product in products:
        generate_barcode_image(product['barcode'])
    return render_template('products.html', products=products)
    
@app.route('/shipments')
def shipment():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    orders = conn.execute('SELECT * FROM sales_orders ORDER BY created_at DESC LIMIT 20').fetchall()

    processed_orders = []
    for order in orders:
        order_dict = dict(order)
        
        # Convert created_at to IST
        order_dict['created_at_ist'] = utc_to_ist(order['created_at'])
        
        try:
            order_data = json.loads(order['order_data'])
            item_list = []
            
            for barcode, details in order_data.items():
                # Get product info (removed price column reference)
                product = conn.execute('SELECT name FROM products WHERE barcode = ?', (barcode,)).fetchone()
                
                if product:
                    product_name = product['name']
                else:
                    # Check if barcode exists in any format
                    all_products = conn.execute('SELECT barcode, name FROM products WHERE barcode LIKE ?', (f'%{barcode}%',)).fetchall()
                    if all_products:
                        # Use the first match
                        product_name = all_products[0]['name']
                    else:
                        # Still no match, show clearer message for deleted products
                        product_name = f"[Deleted Product - {barcode}]"
                
                # Ensure details has quantity key
                quantity = details.get('quantity', 1) if isinstance(details, dict) else details
                item_list.append(f"{product_name} (Qty: {quantity})")
            
            order_dict['product_names'] = item_list if item_list else ['No items found']
            
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            # Better error handling
            order_dict['product_names'] = [f'[Data parsing error: {str(e)}]']
        
        processed_orders.append(order_dict)

    conn.close()
    return render_template('shipments.html', orders=processed_orders)

# Add this debug route to check your data
@app.route('/debug-shipments')
def debug_shipments():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Get sample products
    products = conn.execute('SELECT barcode, name FROM products LIMIT 10').fetchall()
    
    # Get sample orders
    orders = conn.execute('SELECT id, order_data FROM sales_orders LIMIT 5').fetchall()
    
    debug_info = {
        'sample_products': [dict(p) for p in products],
        'sample_orders': []
    }
    
    for order in orders:
        try:
            order_data = json.loads(order['order_data'])
            debug_info['sample_orders'].append({
                'order_id': order['id'],
                'barcodes_in_order': list(order_data.keys()),
                'order_data': order_data
            })
        except:
            debug_info['sample_orders'].append({
                'order_id': order['id'],
                'error': 'Could not parse order_data'
            })
    
    conn.close()
    
    return jsonify(debug_info)




@app.route('/add-product', methods=['GET', 'POST'])
def add_product():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        name = request.form['name']
        barcode_number = request.form['barcode']
        quantity = int(request.form['quantity'])
        location = request.form['location']
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO products (name, barcode, quantity, location) VALUES (?, ?, ?, ?)',
                         (name, barcode_number, quantity, location))
            conn.commit()
        except sqlite3.IntegrityError:
            return 'Barcode already exists!'
        conn.close()
        generate_barcode_image(barcode_number)
        return redirect(url_for('products'))
    return render_template('add_product.html')

# @app.route('/sales-orders')
# def view_sales_orders():
    # if 'user_id' not in session or session.get('role') != 'admin':
        # return redirect(url_for('login'))
    # conn = get_db_connection()
    # orders = conn.execute('''
        # SELECT sales_orders.*, users.username 
        # FROM sales_orders
        # LEFT JOIN users ON sales_orders.customer_id = users.id
        # ORDER BY sales_orders.created_at DESC
    # ''').fetchall()
    # conn.close()

    # Process orders to extract items from JSON data for easier display
    processed_orders = []
    for order in orders:
        order_dict = dict(order)
        try:
            # Parse the JSON data to get the items
            order_items = json.loads(order['order_data'])
            items = []
            # Process the items based on the structure
            for barcode, details in order_items.items():
                items.append({
                    'barcode': barcode,
                    'quantity': details['quantity']
                })
            order_dict['items'] = items
            processed_orders.append(order_dict)
        except:
            # If there's an error parsing, just add the original order
            processed_orders.append(order_dict)

    return render_template('sales_orders.html', orders=processed_orders)

@app.route('/edit-order/<int:order_id>', methods=['GET', 'POST'])
def edit_order(order_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    if request.method == 'POST':
        # Get form data
        new_status = request.form.get('status')
        
        # Update order status
        conn.execute('UPDATE sales_orders SET status = ? WHERE id = ?', 
                    (new_status, order_id))
        conn.commit()
        
        flash('Order updated successfully', 'success')
        return redirect(url_for('dashboard'))
    
    # Get order details for display
    order = conn.execute('''
        SELECT sales_orders.*, users.username 
        FROM sales_orders 
        LEFT JOIN users ON sales_orders.customer_id = users.id 
        WHERE sales_orders.id = ?
    ''', (order_id,)).fetchone()
    
    if not order:
        conn.close()
        flash('Order not found', 'error')
        return redirect(url_for('dashboard'))
    
    # Get order items
    order_items = []
    try:
        order_data = json.loads(order['order_data'])
        for barcode, details in order_data.items():
            product = conn.execute('SELECT * FROM products WHERE barcode = ?', 
                                 (barcode,)).fetchone()
            if product:
                order_items.append({
                    'product_id': product['id'],
                    'name': product['name'],
                    'barcode': barcode,
                    'quantity': details['quantity']
                })
    except:
        pass
    
    conn.close()
    
    return render_template('edit_order.html', 
                          order=order, 
                          items=order_items)

@app.route('/update-order-status/<int:order_id>', methods=['POST'])
def update_order_status(order_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Unauthorized'}), 401
    new_status = request.form['status']
    conn = get_db_connection()
    conn.execute('UPDATE sales_orders SET status = ? WHERE id = ?', (new_status, order_id))
    if new_status == 'Accepted':
        order = conn.execute('SELECT * FROM sales_orders WHERE id = ?', (order_id,)).fetchone()
        if order:
            try:
                order_data = json.loads(order['order_data'])
                for barcode, details in order_data.items():
                    qty = details['quantity']
                    conn.execute('UPDATE products SET quantity = quantity - ? WHERE barcode = ?', (qty, barcode))
            except Exception as e:
                print("Error processing order data:", e)
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/customer-dashboard')
def customer_dashboard():
    if 'user_id' not in session or session.get('role') != 'customer':
        return redirect(url_for('login'))
    
    # Get search query parameter (if any)
    search_query = request.args.get('search', '')
    
    conn = get_db_connection()
    
    if search_query:
        # If there's a search query, filter products
        products = conn.execute('''
            SELECT * FROM products 
            WHERE quantity > 0 AND (name LIKE ? OR barcode LIKE ?)
            ORDER BY name
        ''', (f'%{search_query}%', f'%{search_query}%')).fetchall()
    else:
        # Otherwise get all available products
        products = conn.execute('SELECT * FROM products').fetchall()
    
    # Get user's orders
    orders = conn.execute('''
        SELECT * FROM sales_orders 
        WHERE customer_id = ? 
        ORDER BY created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    # Process orders to extract items from JSON data
    processed_orders = []
    for order in orders:
        try:
            order_items = json.loads(order['order_data'])
            items = []
            for barcode, details in order_items.items():
                # Get product name for display
                product = conn.execute('SELECT name FROM products WHERE barcode = ?', (barcode,)).fetchone()
                product_name = product['name'] if product else "Unknown Product"
                
                items.append({
                    'barcode': barcode,
                    'name': product_name,
                    'quantity': details['quantity']
                })
            
            processed_orders.append({
                'id': order['id'],
                'status': order['status'],
                'created_at': order['created_at'],
                'items': items
            })
        except:
            # Handle any JSON parsing errors
            continue
    
    conn.close()
    
    # Calculate cart count for display
    cart_count = sum(item['quantity'] for item in session.get('cart', {}).values())
    
    return render_template('customer_dashboard.html', 
                          products=products, 
                          orders=processed_orders, 
                          cart_count=cart_count,
                          search_query=search_query)
@app.route('/add-stock', methods=['GET', 'POST'])
def add_stock():
    """Route to add stock quantity to existing products"""
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    message = None
    message_type = None
    
    # Get all products for the dropdown
    conn = get_db_connection()
    products = conn.execute('SELECT id, name, barcode, quantity FROM products ORDER BY name').fetchall()
    
    if request.method == 'POST':
        product_id = request.form.get('product_id')
        quantity = request.form.get('quantity')
        
        # Validate inputs
        if not product_id or not quantity:
            message = "Both product and quantity are required"
            message_type = "error"
        else:
            try:
                quantity = int(quantity)
                if quantity <= 0:
                    message = "Quantity must be greater than zero"
                    message_type = "error"
                else:
                    # Get current product details
                    product = conn.execute('SELECT name, barcode, quantity FROM products WHERE id = ?', 
                                          (product_id,)).fetchone()
                    
                    if product:
                        # Update product quantity
                        conn.execute('UPDATE products SET quantity = quantity + ? WHERE id = ?', 
                                    (quantity, product_id))
                        
                        # Remove the problematic stock table insertion
                        # since you only use the products table
                        
                        # Log activity to activity_log table
                        product_name = product['name']
                        new_quantity = product['quantity'] + quantity
                        
                        # Optional: Log activity if activity_log table exists
                        try:
                            conn.execute('''
                                INSERT INTO activity_log (activity_type, description, related_id) 
                                VALUES (?, ?, ?)
                            ''', ('stock_added', f"Added {quantity} units to {product_name}. New total: {new_quantity}", product_id))
                        except:
                            # Skip if activity_log table doesn't exist
                            pass
                        
                        conn.commit()
                        message = f"Successfully added {quantity} units to {product_name}"
                        message_type = "success"
                        
                        # Refresh products list after update
                        products = conn.execute('SELECT id, name, barcode, quantity FROM products ORDER BY name').fetchall()
                    else:
                        message = "Product not found"
                        message_type = "error"
            except ValueError:
                message = "Quantity must be a number"
                message_type = "error"
    
    conn.close()
    return render_template('add_stock.html', products=products, message=message, message_type=message_type)

@app.route('/add-stock-to-product', methods=['POST'])
def add_stock_to_product():
    """Handle adding stock to a product from the report page"""
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    message = None
    message_type = None
    
    product_id = request.form.get('product_id')
    quantity = request.form.get('quantity')
    
    # Validate inputs
    if not product_id or not quantity:
        message = "Both product and quantity are required"
        message_type = "error"
    else:
        try:
            quantity = int(quantity)
            if quantity <= 0:
                message = "Quantity must be greater than zero"
                message_type = "error"
            else:
                conn = get_db_connection()
                
                # Get current product details
                product = conn.execute('SELECT name, barcode, quantity FROM products WHERE id = ?', 
                                      (product_id,)).fetchone()
                
                if product:
                    # Update product quantity - this is the main operation
                    conn.execute('UPDATE products SET quantity = quantity + ? WHERE id = ?', 
                                (quantity, product_id))
                    
                    # Remove the problematic stock table insertion
                    # since you only use the products table
                    
                    product_name = product['name']
                    new_quantity = product['quantity'] + quantity
                    
                    # Optional: Log activity if activity_log table exists
                    try:
                        conn.execute('''
                            INSERT INTO activity_log (activity_type, description, related_id) 
                            VALUES (?, ?, ?)
                        ''', ('stock_added', f"Added {quantity} units to {product_name}. New total: {new_quantity}", product_id))
                    except:
                        # Skip if activity_log table doesn't exist
                        pass
                    
                    conn.commit()
                    message = f"Successfully added {quantity} units to {product_name}"
                    message_type = "success"
                else:
                    message = "Product not found"
                    message_type = "error"
                
                conn.close()
        except ValueError:
            message = "Quantity must be a number"
            message_type = "error"
    
    # Redirect back to inventory report
    flash(message, message_type)
    return redirect(url_for('inventory_report'))

@app.route('/add-to-cart', methods=['POST'])
def add_to_cart():
    if 'user_id' not in session or session.get('role') != 'customer':
        return jsonify({'success': False, 'message': 'Please log in as a customer'})
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Invalid request data'})
        
        barcode = data.get('barcode')
        quantity = data.get('quantity')
        
        if not barcode or not quantity:
            return jsonify({'success': False, 'message': 'Missing product or quantity information'})
        
        quantity = int(quantity)
        if quantity <= 0:
            return jsonify({'success': False, 'message': 'Quantity must be greater than 0'})
        
        # Check if product exists
        conn = get_db_connection()
        product = conn.execute('SELECT * FROM products WHERE barcode = ?', (barcode,)).fetchone()
        conn.close()
        
        if not product:
            return jsonify({'success': False, 'message': 'Product not found'})
        
        cart = session.get('cart', {})
        if barcode in cart:
            cart[barcode]['quantity'] += quantity
        else:
            cart[barcode] = {'quantity': quantity}
        
        session['cart'] = cart
        session.modified = True
        total_items = sum(item['quantity'] for item in cart.values())
        
        return jsonify({
            'success': True, 
            'cart_count': total_items,
            'message': f'Added {quantity} item(s) to cart'
        })
        
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid quantity value'})
    except Exception as e:
        return jsonify({'success': False, 'message': 'An error occurred while adding to cart'})

@app.route('/remove-from-cart', methods=['POST'])
def remove_from_cart():
    if 'user_id' not in session or session.get('role') != 'customer':
        return jsonify({'success': False, 'message': 'Unauthorized'})
    
    data = request.get_json()
    barcode = data.get('barcode')
    
    if not barcode:
        return jsonify({'success': False, 'message': 'Invalid request'})
    
    cart = session.get('cart', {})
    
    if barcode in cart:
        del cart[barcode]
        session['cart'] = cart
        session.modified = True
        total_items = sum(item['quantity'] for item in cart.values())
        return jsonify({'success': True, 'cart_count': total_items, 'message': 'Item removed from cart'})
    else:
        return jsonify({'success': False, 'message': 'Item not found in cart'})

@app.route('/cart')
def view_cart():
    if 'user_id' not in session or session.get('role') != 'customer':
        return redirect(url_for('login'))
    cart = session.get('cart', {})
    conn = get_db_connection()
    products = []
    for barcode, item in cart.items():
        product = conn.execute('SELECT * FROM products WHERE barcode = ?', (barcode,)).fetchone()
        if product:
            products.append({
                'name': product['name'],
                'barcode': barcode,
                'quantity': item['quantity']
            })
    conn.close()
    cart_count = sum(item['quantity'] for item in cart.values())
    return render_template('cart.html', products=products, cart_count=cart_count)

@app.route('/checkout', methods=['POST'])
def checkout():
    if 'user_id' not in session or session.get('role') != 'customer':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Please log in'}), 401
        return redirect(url_for('login'))
    
    cart = session.get('cart', {})
    if not cart:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Your cart is empty'}), 400
        return redirect(url_for('customer_dashboard'))
    
    conn = get_db_connection()
    
    # Check stock and prepare order status info
    stock_issues = []
    for barcode, item in cart.items():
        product = conn.execute('SELECT quantity FROM products WHERE barcode = ?', (barcode,)).fetchone()
        if not product:
            stock_issues.append(f"{item.get('name', 'Unknown product')} - Product not found")
        elif product['quantity'] < item['quantity']:
            available = product['quantity']
            requested = item['quantity']
            stock_issues.append(f"{item.get('name', 'Product')} - Only {available} available (requested {requested})")
    
    # Place order regardless of stock issues
    order_data = json.dumps(cart)
    customer_id = session['user_id']
    
    # Add stock status to order for tracking
    order_status = 'Confirmed' if not stock_issues else 'Partial Stock'
    
    conn.execute('INSERT INTO sales_orders (customer_id, order_data, status) VALUES (?, ?, ?)',
                 (customer_id, order_data, order_status))
    
    # Optionally: Deduct available stock (don't go below 0)
    for barcode, item in cart.items():
        product = conn.execute('SELECT quantity FROM products WHERE barcode = ?', (barcode,)).fetchone()
        if product:
            stock_to_deduct = min(item['quantity'], product['quantity'])
            if stock_to_deduct > 0:
                conn.execute('UPDATE products SET quantity = quantity - ? WHERE barcode = ?',
                           (stock_to_deduct, barcode))
    
    conn.commit()
    conn.close()
    
    # Clear cart
    session['cart'] = {}
    
    # Prepare success message
    if stock_issues:
        message = f'Order placed successfully! Note: Some items have limited stock and will be fulfilled when available.'
    else:
        message = 'Order placed successfully!'
    
    # If AJAX request, return JSON instead of redirect
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': message})
    
    flash(message, 'success')
    return redirect(url_for('customer_dashboard'))

@app.route('/report')
def report():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM products').fetchall()
    conn.close()
    return render_template('inventory_report.html', products=products)

@app.route('/download-csv')
def download_csv():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM products').fetchall()
    conn.close()
    
    # Create CSV content as string
    csv_content = "ID,Name,Barcode,Quantity,Location\n"
    for product in products:
        csv_content += f"{product['id']},{product['name']},{product['barcode']},{product['quantity']},{product['location']}\n"
    
    # Convert to BytesIO
    output = BytesIO(csv_content.encode('utf-8'))
    output.seek(0)
    
    return send_file(output, mimetype='text/csv', download_name='inventory.csv', as_attachment=True)

@app.route('/your-orders')
def your_orders():
    if 'user_id' not in session or session.get('role') != 'customer':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Get user's orders
    orders = conn.execute('''
        SELECT * FROM sales_orders 
        WHERE customer_id = ? 
        ORDER BY created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    # Process orders to extract items from JSON data
    processed_orders = []
    for order in orders:
        try:
            order_items = json.loads(order['order_data'])
            items = []
            for barcode, details in order_items.items():
                # Get product name for display
                product = conn.execute('SELECT name FROM products WHERE barcode = ?', (barcode,)).fetchone()
                product_name = product['name'] if product else "Unknown Product"
                
                items.append({
                    'barcode': barcode,
                    'name': product_name,
                    'quantity': details['quantity']
                })
            
            processed_orders.append({
                'id': order['id'],
                'status': order['status'],
                'created_at': order['created_at'],
                'items': items
            })
        except:
            # Handle any JSON parsing errors
            continue
    
    conn.close()
    
    # Calculate cart count for display
    cart_count = sum(item['quantity'] for item in session.get('cart', {}).values())
    
    return render_template('your_orders.html', orders=processed_orders, cart_count=cart_count)

def fetch_order_status(order_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT status FROM sales_orders WHERE id = ?', (order_id,))
    result = cursor.fetchone()
    conn.close()

    if result:
        return f"The status of your order {order_id} is: {result[0]}"
    else:
        return f"Order ID {order_id} not found in our system."

# --- CHATBOT FUNCTION ---

def generate_response(message):
    message = message.lower()
    words = set(re.findall(r'\w+', message))

    # Extract numeric order ID if mentioned
    number_match = re.search(r"\b\d{1,10}\b", message)  # match order numbers like 4, 123, 999999
    contains_status_keywords = words & {"status", "track", "where", "check"}

    if contains_status_keywords and number_match:
        return fetch_order_status(number_match.group())

    # Basic numeric ID detection fallback
    if number_match and "order" in words:
        return fetch_order_status(number_match.group())

    # Greeting
    if words & {"hi", "hello", "hey"}:
        return "Hello! 👋 How can I assist you with your order today?"

    # Asking how to order
    if words & {"order", "buy", "purchase"} and words & {"how", "want", "place"}:
        return "To place an order, browse products, add items to your cart, and click 'Checkout'."

    # Delivery time
    if words & {"delivery", "arrive", "receive", "ship", "reach"}:
        return "Delivery usually takes 3 to 5 business days depending on your location."

    # Cancel order
    if "cancel" in words:
        return "To cancel your order, please provide your order ID (e.g., 12345)."

    # Check status (without number yet)
    if contains_status_keywords:
        return "Sure! Just provide your numeric order ID (e.g., 12345) so I can check the status for you."

    # Help
    if words & {"help", "can", "do"}:
        return "I can help you place orders, check order status, cancel orders, and answer delivery-related questions."

    # Default fallback
    return (
        "I'm not quite sure I got that 🤔 Try asking things like:\n"
        "- How do I place an order?\n"
        "- What's the status of my order 12345?\n"
        "- Cancel my order\n"
        "- When will my order arrive?\n"
        "- How do I get a refund?"
    )

@app.route("/index", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        # Serve the HTML page
        return render_template("index.html")
    elif request.method == "POST":
        # Handle chat messages
        user_input = request.json.get("message", "")
        response = generate_response(user_input)
        return jsonify({"response": response})
        
@app.route('/print-barcode/<barcode>')
@no_cache
def print_barcode(barcode):
    image_path = generate_barcode_image(barcode)
    return render_template('print_barcode.html', barcode=barcode)

@app.route('/cleanup-orders')
def cleanup_orders():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Find orders with non-existent products
    orders = conn.execute('SELECT * FROM sales_orders').fetchall()
    orphaned_orders = []
    
    for order in orders:
        try:
            order_data = json.loads(order['order_data'])
            for barcode in order_data.keys():
                product = conn.execute('SELECT name FROM products WHERE barcode = ?', (barcode,)).fetchone()
                if not product:
                    orphaned_orders.append({
                        'order_id': order['id'],
                        'missing_barcode': barcode,
                        'customer_id': order['customer_id']
                    })
                    break
        except:
            continue
    
    conn.close()
    return jsonify({'orphaned_orders': orphaned_orders})

@app.route('/inventory-report')
def inventory_report():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    # Get filter parameters
    location_filter = request.args.get('location', 'all')
    stock_filter = request.args.get('stock', 'all')
    
    conn = get_db_connection()
    
    # Build the query based on filters
    query = 'SELECT * FROM products'
    params = []
    conditions = []
    
    if location_filter != 'all':
        conditions.append('location = ?')
        params.append(location_filter)
    
    if stock_filter == 'low':
        # Since there's no min_stock_level, define low stock as quantity <= 10
        conditions.append('quantity <= 10')
    elif stock_filter == 'out':
        conditions.append('quantity = 0')
    elif stock_filter == 'in':
        conditions.append('quantity > 0')
    
    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)
    
    query += ' ORDER BY name'
    
    products = conn.execute(query, params).fetchall()
    
    # Get statistics - removed min_stock_level references
    total_products = conn.execute('SELECT COUNT(*) as count FROM products').fetchone()['count']
    total_items = conn.execute('SELECT SUM(quantity) as total FROM products').fetchone()['total'] or 0
    # Define low stock as quantity <= 10 since no min_stock_level column exists
    low_stock_count = conn.execute('SELECT COUNT(*) as count FROM products WHERE quantity <= 10').fetchone()['count']
    out_of_stock_count = conn.execute('SELECT COUNT(*) as count FROM products WHERE quantity = 0').fetchone()['count']
    
    # Get unique locations
    locations = [row['location'] for row in conn.execute('SELECT DISTINCT location FROM products WHERE location IS NOT NULL').fetchall()]
    
    conn.close()
    
    return render_template('inventory_report.html', 
                         products=products,
                         total_products=total_products,
                         total_items=total_items,
                         low_stock_count=low_stock_count,
                         out_of_stock_count=out_of_stock_count,
                         locations=locations,
                         location_filter=location_filter,
                         stock_filter=stock_filter)

@app.route('/forecast')
def sales_forecast():
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT created_at, order_data FROM sales_orders", conn)
    products_df = pd.read_sql_query("SELECT id, name FROM products", conn)
    conn.close()

    # Parse order_data
    records = []
    for i, row in df.iterrows():
        try:
            created_at = pd.to_datetime(row['created_at'])
            order_data = json.loads(row['order_data'])
            for barcode, details in order_data.items():
                records.append({
                    'created_at': created_at,
                    'barcode': barcode,
                    'quantity': details['quantity']
                })
        except Exception:
            continue

    sales_df = pd.DataFrame(records)
    if sales_df.empty:
        flash("No sales data available for forecasting.", "error")
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    barcode_name_map = {row['barcode']: row['name'] for row in conn.execute('SELECT barcode, name FROM products')}
    conn.close()

    sales_df['product_name'] = sales_df['barcode'].map(barcode_name_map)
    sales_df['created_at'] = pd.to_datetime(sales_df['created_at'])
    sales_df.set_index('created_at', inplace=True)

    summaries = {}
    for period, label in zip(['W', 'M', 'Q'], ['weekly', 'monthly', 'quarterly']):
        period_group = sales_df.groupby([pd.Grouper(freq=period), 'product_name'])['quantity'].sum().reset_index()
        top = (
            period_group.sort_values(['created_at', 'quantity'], ascending=[True, False])
            .drop_duplicates(subset=['created_at'])
            .sort_values('created_at', ascending=False)
        )
        summaries[label] = top.head(1).to_dict(orient='records')

        # Plot total quantity per period
        trend = sales_df.resample(period)['quantity'].sum()
        plt.figure(figsize=(10, 4))
        sns.lineplot(x=trend.index, y=trend.values)
        plt.title(f"{label.capitalize()} Sales Trend")
        plt.ylabel('Quantity Sold')
        plt.xlabel('Date')
        plt.tight_layout()
        path = f'static/{label}_trend.png'
        plt.savefig(path)
        plt.close()

    return render_template("forecast.html",
                           weekly_top=summaries['weekly'],
                           monthly_top=summaries['monthly'],
                           quarterly_top=summaries['quarterly'],
                           weekly_img='static/weekly_trend.png',
                           monthly_img='static/monthly_trend.png',
                           quarterly_img='static/quarterly_trend.png')


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
