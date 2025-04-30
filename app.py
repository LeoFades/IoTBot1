from flask import Flask, render_template, request, jsonify
import mysql.connector
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'drone_db')
}

def get_db_connection():
    """Create and return a database connection"""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except mysql.connector.Error as err:
        print(f"Database connection error: {err}")
        return None

def initialize_db():
    """Create tables if they don't exist"""
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        
        # Create drone_controls table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS drone_controls (
            id INT AUTO_INCREMENT PRIMARY KEY,
            control_name VARCHAR(50) NOT NULL,
            control_value VARCHAR(255) NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        ''')
        
        # Insert default values if table is empty
        cursor.execute("SELECT COUNT(*) FROM drone_controls")
        count = cursor.fetchone()[0]
        
        if count == 0:
            default_controls = [
                ('movement', 'stop'),
                ('headlights', 'off'),
                ('lcd_message', 'Hello Drone!')
            ]
            
            cursor.executemany(
                "INSERT INTO drone_controls (control_name, control_value) VALUES (%s, %s)",
                default_controls
            )
        
        conn.commit()
        cursor.close()
        conn.close()
        print("Database initialized successfully")
    else:
        print("Failed to initialize database")

# Initialize database on startup
initialize_db()

@app.route('/')
def index():
    """Render the dashboard page"""
    return render_template('index.html')

@app.route('/api/controls', methods=['GET'])
def get_controls():
    """API endpoint to get current control values"""
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT control_name, control_value FROM drone_controls")
        controls = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(controls)
    return jsonify({"error": "Database connection failed"}), 500

@app.route('/api/control/<control_name>', methods=['POST'])
def update_control(control_name):
    """API endpoint to update a specific control"""
    data = request.json
    new_value = data.get('value')
    
    if not new_value:
        return jsonify({"error": "No value provided"}), 400
    
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE drone_controls SET control_value = %s WHERE control_name = %s",
            (new_value, control_name)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"success": True, "control": control_name, "value": new_value})
    
    return jsonify({"error": "Database connection failed"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')