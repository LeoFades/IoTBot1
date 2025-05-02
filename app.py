from flask import Flask, render_template, request, jsonify
import mysql.connector
import json
import os
from dotenv import load_dotenv
from webcam_stream import init_webcam_stream
from datetime import datetime, timedelta

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
                ('drive_motor', 'stop'),
                ('steering', 'center'),
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

@app.route('/api/sensor_analytics', methods=['GET'])
def get_sensor_analytics():
    """API endpoint to get sensor analytics data"""
    timeframe = request.args.get('timeframe', '24h')
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cursor = conn.cursor(dictionary=True)
        
        # Calculate the time boundary based on the timeframe
        if timeframe == '1h':
            time_sql = "timestamp >= DATE_SUB(NOW(), INTERVAL 1 HOUR)"
        elif timeframe == '24h':
            time_sql = "timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)"
        elif timeframe == '7d':
            time_sql = "timestamp >= DATE_SUB(NOW(), INTERVAL 7 DAY)"
        else:
            time_sql = "timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)"  # Default to 24h
        
        # Get summary stats for each sensor type
        cursor.execute(f"""
            SELECT 
                reading_type, 
                AVG(reading_value) AS avg_value,
                MIN(reading_value) AS min_value,
                MAX(reading_value) AS max_value,
                COUNT(*) AS reading_count
            FROM 
                sensor_readings
            WHERE 
                {time_sql}
            GROUP BY 
                reading_type
        """)
        
        summary_stats = cursor.fetchall()
        
        # Get time series data for charts (hourly averages)
        cursor.execute(f"""
            SELECT 
                reading_type,
                DATE_FORMAT(timestamp, '%Y-%m-%d %H:00:00') AS hour_bucket,
                AVG(reading_value) AS avg_value
            FROM 
                sensor_readings
            WHERE 
                {time_sql}
            GROUP BY 
                reading_type, hour_bucket
            ORDER BY 
                hour_bucket
        """)
        
        time_series = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'summary': summary_stats,
            'time_series': time_series
        })
        
    except mysql.connector.Error as err:
        print(f"Error getting sensor analytics: {err}")
        if conn:
            conn.close()
        return jsonify({"error": f"Database error: {str(err)}"}), 500

# Initialize SocketIO and webcam streaming
socketio, webcam_streamer = init_webcam_stream(app)

if __name__ == '__main__':
    # Use socketio.run instead of app.run
    socketio.run(app, debug=True, host='0.0.0.0', allow_unsafe_werkzeug=True)