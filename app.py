from flask import Flask, render_template, request, jsonify
import mysql.connector
import json
import os
from dotenv import load_dotenv
from webcam_stream import init_webcam_stream

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

@app.route('/api/sensor_data', methods=['GET'])
def get_sensor_data():
    """API endpoint to get sensor data for visualization"""
    sensor_type = request.args.get('type', 'DIST')
    limit = request.args.get('limit', 100)
    
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT sensor_value, timestamp 
            FROM sensor_readings 
            WHERE sensor_type = %s 
            ORDER BY timestamp DESC 
            LIMIT %s
            """, 
            (sensor_type, int(limit))
        )
        data = cursor.fetchall()
        cursor.close()
        conn.close()
        
        # Format timestamps for better JSON serialization
        for row in data:
            row['timestamp'] = row['timestamp'].isoformat()
            
        return jsonify(data)
    return jsonify({"error": "Database connection failed"}), 500

@app.route('/api/daily_stats', methods=['GET'])
def get_daily_stats():
    """API endpoint to get daily statistics"""
    days = request.args.get('days', 7)
    
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT * FROM daily_stats
            ORDER BY stat_date DESC
            LIMIT %s
            """, 
            (int(days),)
        )
        data = cursor.fetchall()
        cursor.close()
        conn.close()
        
        # Format dates for better JSON serialization
        for row in data:
            row['stat_date'] = row['stat_date'].isoformat()
            
        return jsonify(data)
    return jsonify({"error": "Database connection failed"}), 500

@app.route('/api/event_logs', methods=['GET'])
def get_event_logs():
    """API endpoint to get event logs"""
    limit = request.args.get('limit', 50)
    event_type = request.args.get('type', None)
    
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        
        if event_type:
            cursor.execute(
                """
                SELECT event_type, event_value, timestamp
                FROM event_log
                WHERE event_type = %s
                ORDER BY timestamp DESC
                LIMIT %s
                """, 
                (event_type, int(limit))
            )
        else:
            cursor.execute(
                """
                SELECT event_type, event_value, timestamp
                FROM event_log
                ORDER BY timestamp DESC
                LIMIT %s
                """, 
                (int(limit),)
            )
            
        data = cursor.fetchall()
        cursor.close()
        conn.close()
        
        # Format timestamps for better JSON serialization
        for row in data:
            row['timestamp'] = row['timestamp'].isoformat()
            
        return jsonify(data)
    return jsonify({"error": "Database connection failed"}), 500

@app.route('/api/sessions', methods=['GET'])
def get_sessions():
    """API endpoint to get session data"""
    limit = request.args.get('limit', 10)
    
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, start_time, end_time, distance_traveled, duration_seconds, obstacle_encounters
            FROM sessions
            WHERE end_time IS NOT NULL
            ORDER BY start_time DESC
            LIMIT %s
            """, 
            (int(limit),)
        )
        data = cursor.fetchall()
        cursor.close()
        conn.close()
        
        # Format timestamps for better JSON serialization
        for row in data:
            row['start_time'] = row['start_time'].isoformat()
            if row['end_time']:
                row['end_time'] = row['end_time'].isoformat()
            
        return jsonify(data)
    return jsonify({"error": "Database connection failed"}), 500

@app.route('/api/summary', methods=['GET'])
def get_summary():
    """API endpoint to get summary statistics"""
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        
        # Get total driving time
        cursor.execute(
            "SELECT SUM(duration_seconds) as total_drive_time FROM sessions"
        )
        total_drive_time = cursor.fetchone()['total_drive_time'] or 0
        
        # Get total distance traveled
        cursor.execute(
            "SELECT SUM(distance_traveled) as total_distance FROM sessions"
        )
        total_distance = cursor.fetchone()['total_distance'] or 0
        
        # Get total obstacle encounters
        cursor.execute(
            "SELECT SUM(obstacle_encounters) as total_obstacles FROM sessions"
        )
        total_obstacles = cursor.fetchone()['total_obstacles'] or 0
        
        # Get average light level
        cursor.execute(
            """
            SELECT AVG(sensor_value) as avg_light 
            FROM sensor_readings 
            WHERE sensor_type = 'LIGHT'
            """
        )
        avg_light = cursor.fetchone()['avg_light'] or 0
        
        # Get average distance reading
        cursor.execute(
            """
            SELECT AVG(sensor_value) as avg_distance 
            FROM sensor_readings 
            WHERE sensor_type = 'DIST'
            """
        )
        avg_distance = cursor.fetchone()['avg_distance'] or 0
        
        # Get session count
        cursor.execute("SELECT COUNT(*) as session_count FROM sessions")
        session_count = cursor.fetchone()['session_count'] or 0
        
        cursor.close()
        conn.close()
        
        summary = {
            'total_drive_time': total_drive_time,
            'total_distance': round(total_distance, 2),
            'total_obstacles': total_obstacles,
            'avg_light': round(avg_light, 2),
            'avg_distance': round(avg_distance, 2),
            'session_count': session_count
        }
            
        return jsonify(summary)
    return jsonify({"error": "Database connection failed"}), 500

# Initialize SocketIO and webcam streaming
socketio, webcam_streamer = init_webcam_stream(app)

if __name__ == '__main__':
    # Use socketio.run instead of app.run
    socketio.run(app, debug=True, host='0.0.0.0', allow_unsafe_werkzeug=True)