import serial
import time
import mysql.connector
import os
from dotenv import load_dotenv
import logging
import signal
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("serial_bridge.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("SerialBridge")

# Load environment variables
load_dotenv()

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'drone_db')
}

# Serial port configuration
SERIAL_PORT = os.getenv('SERIAL_PORT', 'COM3')  # Default to COM3
BAUD_RATE = 9600
RECONNECT_DELAY = 5  # Seconds to wait before trying to reconnect

# Global variables
arduino = None
last_control_values = {}
running = True


def get_db_connection():
    """Create and return a database connection"""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except mysql.connector.Error as err:
        logger.error(f"Database connection error: {err}")
        return None


def connect_to_arduino():
    """Attempt to connect to the Arduino via serial port"""
    global arduino
    try:
        arduino = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        logger.info(f"Connected to Arduino on {SERIAL_PORT}")
        time.sleep(2)  # Wait for Arduino to reset after connection
        return True
    except serial.SerialException as e:
        logger.error(f"Failed to connect to Arduino: {e}")
        return False


def read_control_values():
    """Read control values from the database"""
    conn = get_db_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT control_name, control_value FROM drone_controls")
        controls = {item['control_name']: item['control_value'] for item in cursor.fetchall()}
        cursor.close()
        conn.close()
        return controls
    except mysql.connector.Error as err:
        logger.error(f"Error reading control values: {err}")
        if conn:
            conn.close()
        return None


def send_to_arduino(command):
    """Send a command to the Arduino"""
    global arduino
    
    if arduino is None or not arduino.is_open:
        logger.warning("Serial connection not open, attempting to reconnect")
        if not connect_to_arduino():
            return False
    
    try:
        # Add newline to command for Arduino to recognize end of command
        command_with_newline = command + '\n'
        arduino.write(command_with_newline.encode())
        logger.info(f"Sent to Arduino: {command}")
        
        # Wait for response
        time.sleep(0.1)
        return True
    except serial.SerialException as e:
        logger.error(f"Error sending command to Arduino: {e}")
        arduino = None  # Reset the connection
        return False


def read_from_arduino():
    """Read any available data from Arduino"""
    global arduino
    
    if arduino is None or not arduino.is_open:
        return None
    
    try:
        if arduino.in_waiting > 0:
            line = arduino.readline().decode('utf-8').strip()
            return line
        return None
    except serial.SerialException as e:
        logger.error(f"Error reading from Arduino: {e}")
        arduino = None  # Reset the connection
        return None


def update_sensor_data(sensor_data):
    """Parse sensor data and update in database"""
    # Handle both formats: direct "SENSORS:..." and "Sending: SENSORS:..."
    if "SENSORS:" in sensor_data:
        # Extract the part after "SENSORS:"
        sensors_part = sensor_data.split("SENSORS:")[1]
        
        # Parse sensor data format: "DIST=20;LIGHT=300"
        try:
            data_parts = sensors_part.split(';')
            parsed_data = {}
            
            for part in data_parts:
                if '=' in part:
                    key, value = part.split('=')
                    parsed_data[key] = value
            
            # Log the sensor values
            logger.info(f"Received sensor data: {parsed_data}")
            
            # Store sensor data in the database
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                
                # Insert each sensor reading as a separate row
                for sensor_type, sensor_value in parsed_data.items():
                    try:
                        # Convert the sensor value to float
                        float_value = float(sensor_value)
                        
                        cursor.execute(
                            "INSERT INTO sensor_readings (reading_type, reading_value) VALUES (%s, %s)",
                            (sensor_type, float_value)
                        )
                    except ValueError:
                        logger.warning(f"Could not convert sensor value to float: {sensor_type}={sensor_value}")
                
                conn.commit()
                cursor.close()
                conn.close()
                logger.info(f"Successfully saved sensor data to database")
                
        except Exception as e:
            logger.error(f"Error parsing sensor data: {e}")
    else:
        logger.warning(f"Received data does not contain SENSORS format: {sensor_data}")

def handle_status_update(status_message):
    """Handle status update from Arduino"""
    if "STATUS:" not in status_message:
        return
    
    # Extract the part after "STATUS:"
    status_part = status_message.split("STATUS:")[1]
    
    # Parse status update format: "DRIVE=stop;REASON=obstacle"
    try:
        parts = status_part.split(';')
        updates = {}
        
        for part in parts:
            if '=' in part:
                key, value = part.split('=')
                updates[key] = value
        
        # Update database if arduino reports state change
        if 'DRIVE' in updates:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE drone_controls SET control_value = %s WHERE control_name = %s",
                    (updates['DRIVE'], 'drive_motor')
                )
                conn.commit()
                cursor.close()
                conn.close()
                logger.info(f"Updated database with Arduino status: drive_motor = {updates['DRIVE']}")
    except Exception as e:
        logger.error(f"Error handling status update: {e}")
        
def process_control_changes(new_values):
    """Process any changes in control values and send to Arduino"""
    global last_control_values
    
    if not new_values:
        return
    
    commands_to_send = []
    
    # Check for changes in drive motor
    if 'drive_motor' in new_values and (not last_control_values or new_values['drive_motor'] != last_control_values.get('drive_motor')):
        commands_to_send.append(f"DRIVE:{new_values['drive_motor']}")
    
    # Check for changes in steering
    if 'steering' in new_values and (not last_control_values or new_values['steering'] != last_control_values.get('steering')):
        commands_to_send.append(f"STEER:{new_values['steering']}")
    
    # Check for changes in headlights
    if 'headlights' in new_values and (not last_control_values or new_values['headlights'] != last_control_values.get('headlights')):
        commands_to_send.append(f"LIGHTS:{new_values['headlights']}")
    
    # Check for changes in LCD message
    if 'lcd_message' in new_values and (not last_control_values or new_values['lcd_message'] != last_control_values.get('lcd_message')):
        commands_to_send.append(f"LCD:{new_values['lcd_message']}")
    
    # Send all commands
    for command in commands_to_send:
        success = send_to_arduino(command)
        if not success:
            logger.warning(f"Failed to send command: {command}")
    
    # Update last known values
    if commands_to_send:
        last_control_values = new_values.copy()


def signal_handler(sig, frame):
    """Handle exit signals gracefully"""
    global running
    logger.info("Shutting down serial bridge...")
    running = False
    if arduino and arduino.is_open:
        arduino.close()
    sys.exit(0)


def get_sensor_analytics(timeframe='24h'):
    """
    Get sensor analytics for the dashboard
    timeframe can be '1h', '24h', '7d', etc.
    """
    conn = get_db_connection()
    if not conn:
        return None
    
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
        
        # Get operation stats based on control changes
        cursor.execute(f"""
            SELECT 
                control_name,
                control_value,
                COUNT(*) AS change_count
            FROM 
                drone_controls_history
            WHERE 
                updated_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
            GROUP BY 
                control_name, control_value
            ORDER BY 
                control_name, change_count DESC
        """)
        
        operation_stats = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return {
            'summary': summary_stats,
            'time_series': time_series,
            'operations': operation_stats
        }
        
    except mysql.connector.Error as err:
        logger.error(f"Error getting sensor analytics: {err}")
        if conn:
            conn.close()
        return None
def main():
    """Main function to run the serial bridge"""
    global running
    
    logger.info("Starting serial bridge between database and Arduino")
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Connect to Arduino
    if not connect_to_arduino():
        logger.error(f"Could not connect to Arduino on {SERIAL_PORT}. Check connection and try again.")
        return
    
    # Send initial command to request control values from Arduino
    send_to_arduino("GET_ALL")
    
    poll_counter = 0
    
    # Main loop
    while running:
        try:
            # Every 10th iteration (approximately every second), check database for updates
            if poll_counter % 10 == 0:
                new_control_values = read_control_values()
                process_control_changes(new_control_values)
            
            # Read from Arduino
            response = read_from_arduino()
            if response:
                logger.info(f"Received from Arduino: {response}")
                
                # Process sensor data - check if "SENSORS:" is in the response, not just at the beginning
                if "SENSORS:" in response:
                    update_sensor_data(response)
                
                # Process status updates - check if "STATUS:" is in the response, not just at the beginning
                elif "STATUS:" in response:
                    handle_status_update(response)
                
                # Process other responses - check if "REQUEST:" is in the response, not just at the beginning
                elif "REQUEST:" in response:
                    # Arduino is requesting data
                    if "REQUEST:CONTROLS" in response:
                        control_values = read_control_values()
                        if control_values:
                            for name, value in control_values.items():
                                if name == 'drive_motor':
                                    send_to_arduino(f"DRIVE:{value}")
                                elif name == 'steering':
                                    send_to_arduino(f"STEER:{value}")
                                elif name == 'headlights':
                                    send_to_arduino(f"LIGHTS:{value}")
                                elif name == 'lcd_message':
                                    send_to_arduino(f"LCD:{value}")
            
            # Wait a short time
            time.sleep(0.1)
            poll_counter += 1
            if poll_counter > 100:
                poll_counter = 0
                
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
            time.sleep(1)  # Prevent tight error loop

if __name__ == "__main__":
    main()