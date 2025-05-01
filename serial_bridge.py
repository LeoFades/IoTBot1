import serial
import time
import mysql.connector
import os
from dotenv import load_dotenv
import logging
import signal
import sys
from datetime import datetime, timedelta

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

# Data collection config
DATA_SAMPLE_INTERVAL = 5  # Seconds between sensor data samplings
STAT_AGGREGATION_INTERVAL = 300  # Seconds between stat aggregations (5 minutes)

# Global variables
arduino = None
last_control_values = {}
running = True
current_session_id = None
last_data_sample_time = 0
last_stat_aggregation_time = 0
drive_start_time = None
headlight_start_time = None
motor_state = "stop"
headlight_state = "off"


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
    if not sensor_data.startswith("SENSORS:"):
        return
    
    # Parse sensor data format: "SENSORS:DIST=20;LIGHT=300"
    try:
        data_parts = sensor_data[8:].split(';')  # Remove "SENSORS:" prefix
        parsed_data = {}
        
        for part in data_parts:
            if '=' in part:
                key, value = part.split('=')
                parsed_data[key] = value
        
        # Log the sensor values
        logger.info(f"Received sensor data: {parsed_data}")
        
        # Store sensor readings in the database
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            
            # Store each sensor reading
            for sensor_type, sensor_value in parsed_data.items():
                try:
                    cursor.execute(
                        "INSERT INTO sensor_readings (sensor_type, sensor_value) VALUES (%s, %s)",
                        (sensor_type, float(sensor_value))
                    )
                except ValueError:
                    # If value is not a float, store as 0
                    cursor.execute(
                        "INSERT INTO sensor_readings (sensor_type, sensor_value) VALUES (%s, %s)",
                        (sensor_type, 0.0)
                    )
            
            # Check for obstacle detection (if distance is below threshold)
            if 'DIST' in parsed_data:
                try:
                    distance = float(parsed_data['DIST'])
                    if distance < 20:  # 20cm threshold for obstacle detection
                        # Log the obstacle encounter
                        cursor.execute(
                            "INSERT INTO event_log (event_type, event_value) VALUES (%s, %s)",
                            ('obstacle_detected', f"Distance: {distance}cm")
                        )
                        
                        # If in a session, update obstacle count
                        if current_session_id:
                            cursor.execute(
                                "UPDATE sessions SET obstacle_encounters = obstacle_encounters + 1 WHERE id = %s",
                                (current_session_id,)
                            )
                except ValueError:
                    pass
            
            # Check if headlights should be auto-activated based on light level
            if 'LIGHT' in parsed_data:
                try:
                    light_level = float(parsed_data['LIGHT'])
                    if light_level < 200 and headlight_state == 'off':  # Low light threshold
                        # Suggest turning on headlights
                        cursor.execute(
                            "INSERT INTO event_log (event_type, event_value) VALUES (%s, %s)",
                            ('auto_headlight_suggestion', 'on')
                        )
                except ValueError:
                    pass
            
            conn.commit()
            cursor.close()
            conn.close()
        
    except Exception as e:
        logger.error(f"Error parsing sensor data: {e}")


def handle_status_update(status_message):
    """Handle status update from Arduino"""
    global motor_state, headlight_state, drive_start_time, headlight_start_time
    
    if not status_message.startswith("STATUS:"):
        return
    
    # Parse status update format: "STATUS:DRIVE=stop;REASON=obstacle"
    try:
        parts = status_message[7:].split(';')  # Remove "STATUS:" prefix
        updates = {}
        
        for part in parts:
            if '=' in part:
                key, value = part.split('=')
                updates[key] = value
        
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            
            # Handle drive motor state changes
            if 'DRIVE' in updates and updates['DRIVE'] != motor_state:
                old_state = motor_state
                motor_state = updates['DRIVE']
                
                # Update database with new state
                cursor.execute(
                    "UPDATE drone_controls SET control_value = %s WHERE control_name = %s",
                    (motor_state, 'drive_motor')
                )
                
                # Log event
                cursor.execute(
                    "INSERT INTO event_log (event_type, event_value) VALUES (%s, %s)",
                    ('drive_state_change', f"{old_state} -> {motor_state}")
                )
                
                # Handle drive timing metrics
                if motor_state in ('forward', 'backward') and old_state == 'stop':
                    # Starting to drive
                    drive_start_time = datetime.now()
                elif motor_state == 'stop' and old_state in ('forward', 'backward'):
                    # Stopping after driving
                    if drive_start_time:
                        drive_time = (datetime.now() - drive_start_time).total_seconds()
                        
                        # Update session if active
                        if current_session_id:
                            cursor.execute(
                                "UPDATE sessions SET duration_seconds = duration_seconds + %s WHERE id = %s",
                                (drive_time, current_session_id)
                            )
                            
                            # Estimate distance traveled (simplified calculation)
                            # Assuming average speed of 0.5 meters per second
                            estimated_distance = drive_time * 0.5
                            cursor.execute(
                                "UPDATE sessions SET distance_traveled = distance_traveled + %s WHERE id = %s",
                                (estimated_distance, current_session_id)
                            )
                        
                        drive_start_time = None
            
            # Handle headlight state changes
            if 'LIGHTS' in updates and updates['LIGHTS'] != headlight_state:
                old_state = headlight_state
                headlight_state = updates['LIGHTS']
                
                # Update database with new state
                cursor.execute(
                    "UPDATE drone_controls SET control_value = %s WHERE control_name = %s",
                    (headlight_state, 'headlights')
                )
                
                # Log event
                cursor.execute(
                    "INSERT INTO event_log (event_type, event_value) VALUES (%s, %s)",
                    ('headlight_state_change', f"{old_state} -> {headlight_state}")
                )
                
                # Handle headlight timing metrics
                if headlight_state == 'on' and old_state == 'off':
                    # Turning on headlights
                    headlight_start_time = datetime.now()
                elif headlight_state == 'off' and old_state == 'on':
                    # Turning off headlights
                    if headlight_start_time:
                        headlight_time = (datetime.now() - headlight_start_time).total_seconds()
                        
                        # Log headlight usage time
                        cursor.execute(
                            "INSERT INTO event_log (event_type, event_value) VALUES (%s, %s)",
                            ('headlight_usage', f"{headlight_time} seconds")
                        )
                        
                        headlight_start_time = None
            
            conn.commit()
            cursor.close()
            conn.close()
            
    except Exception as e:
        logger.error(f"Error handling status update: {e}")


def process_control_changes(new_values):
    """Process any changes in control values and send to Arduino"""
    global last_control_values, motor_state, headlight_state
    
    if not new_values:
        return
    
    commands_to_send = []
    conn = get_db_connection()
    
    try:
        if conn:
            cursor = conn.cursor()
            
            # Check for changes in drive motor
            if 'drive_motor' in new_values and (not last_control_values or new_values['drive_motor'] != last_control_values.get('drive_motor')):
                commands_to_send.append(f"DRIVE:{new_values['drive_motor']}")
                motor_state = new_values['drive_motor']
                
                # Log control event
                cursor.execute(
                    "INSERT INTO event_log (event_type, event_value) VALUES (%s, %s)",
                    ('control_change', f"drive_motor:{new_values['drive_motor']}")
                )
            
            # Check for changes in steering
            if 'steering' in new_values and (not last_control_values or new_values['steering'] != last_control_values.get('steering')):
                commands_to_send.append(f"STEER:{new_values['steering']}")
                
                # Log control event
                cursor.execute(
                    "INSERT INTO event_log (event_type, event_value) VALUES (%s, %s)",
                    ('control_change', f"steering:{new_values['steering']}")
                )
            
            # Check for changes in headlights
            if 'headlights' in new_values and (not last_control_values or new_values['headlights'] != last_control_values.get('headlights')):
                commands_to_send.append(f"LIGHTS:{new_values['headlights']}")
                headlight_state = new_values['headlights']
                
                # Log control event
                cursor.execute(
                    "INSERT INTO event_log (event_type, event_value) VALUES (%s, %s)",
                    ('control_change', f"headlights:{new_values['headlights']}")
                )
            
            # Check for changes in LCD message
            if 'lcd_message' in new_values and (not last_control_values or new_values['lcd_message'] != last_control_values.get('lcd_message')):
                commands_to_send.append(f"LCD:{new_values['lcd_message']}")
                
                # Log control event
                cursor.execute(
                    "INSERT INTO event_log (event_type, event_value) VALUES (%s, %s)",
                    ('control_change', f"lcd_message:{new_values['lcd_message']}")
                )
            
            conn.commit()
            cursor.close()
            conn.close()
    except Exception as e:
        logger.error(f"Error logging control changes: {e}")
        if conn:
            conn.close()
    
    # Send all commands
    for command in commands_to_send:
        success = send_to_arduino(command)
        if not success:
            logger.warning(f"Failed to send command: {command}")
    
    # Update last known values
    if commands_to_send:
        last_control_values = new_values.copy()


def start_new_session():
    """Start a new usage session"""
    global current_session_id
    
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sessions (start_time) VALUES (NOW())")
        current_session_id = cursor.lastrowid
        cursor.close()
        conn.commit()
        conn.close()
        logger.info(f"Started new session with ID: {current_session_id}")
        return current_session_id
    return None


def end_current_session():
    """End the current usage session"""
    global current_session_id
    
    if current_session_id:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE sessions SET end_time = NOW() WHERE id = %s", (current_session_id,))
            cursor.close()
            conn.commit()
            conn.close()
            logger.info(f"Ended session with ID: {current_session_id}")
            current_session_id = None


def request_sensor_data():
    """Request sensor data from Arduino"""
    send_to_arduino("GET_SENSORS")


def aggregate_daily_stats():
    """Aggregate sensor data into daily statistics"""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # Get today's date
            today = datetime.now().date()
            
            # Check if we already have a record for today
            cursor.execute("SELECT id FROM daily_stats WHERE stat_date = %s", (today,))
            result = cursor.fetchone()
            
            if result:
                # Update existing record
                stat_id = result[0]
                
                # Calculate average light level from today's readings
                cursor.execute(
                    """
                    SELECT AVG(sensor_value) 
                    FROM sensor_readings 
                    WHERE sensor_type = 'LIGHT' 
                    AND DATE(timestamp) = %s
                    """, 
                    (today,)
                )
                avg_light = cursor.fetchone()[0] or 0
                
                # Calculate average distance from today's readings
                cursor.execute(
                    """
                    SELECT AVG(sensor_value) 
                    FROM sensor_readings 
                    WHERE sensor_type = 'DIST' 
                    AND DATE(timestamp) = %s
                    """, 
                    (today,)
                )
                avg_distance = cursor.fetchone()[0] or 0
                
                # Count obstacle encounters
                cursor.execute(
                    """
                    SELECT COUNT(*) 
                    FROM event_log 
                    WHERE event_type = 'obstacle_detected' 
                    AND DATE(timestamp) = %s
                    """, 
                    (today,)
                )
                obstacles = cursor.fetchone()[0] or 0
                
                # Calculate total drive time
                cursor.execute(
                    """
                    SELECT SUM(duration_seconds) 
                    FROM sessions 
                    WHERE DATE(start_time) = %s
                    """, 
                    (today,)
                )
                drive_time = cursor.fetchone()[0] or 0
                
                # Calculate headlight usage time (approximate from events)
                cursor.execute(
                    """
                    SELECT SUM(CAST(SUBSTRING_INDEX(event_value, ' ', 1) AS DECIMAL)) 
                    FROM event_log 
                    WHERE event_type = 'headlight_usage' 
                    AND DATE(timestamp) = %s
                    """, 
                    (today,)
                )
                headlight_time = cursor.fetchone()[0] or 0
                
                # Update stats
                cursor.execute(
                    """
                    UPDATE daily_stats 
                    SET avg_light_level = %s, 
                        avg_distance = %s, 
                        obstacle_encounters = %s, 
                        total_drive_time_seconds = %s,
                        headlight_time_seconds = %s
                    WHERE id = %s
                    """, 
                    (avg_light, avg_distance, obstacles, drive_time, headlight_time, stat_id)
                )
            else:
                # Create new record with initial values
                cursor.execute(
                    """
                    INSERT INTO daily_stats 
                    (stat_date, avg_light_level, avg_distance, obstacle_encounters, total_drive_time_seconds, headlight_time_seconds)
                    VALUES (%s, 0, 0, 0, 0, 0)
                    """, 
                    (today,)
                )
            
            conn.commit()
            logger.info("Updated daily statistics")
        except Exception as e:
            logger.error(f"Error aggregating stats: {e}")
        finally:
            cursor.close()
            conn.close()


def signal_handler(sig, frame):
    """Handle exit signals gracefully"""
    global running
    logger.info("Shutting down serial bridge...")
    running = False
    
    # Clean up before exit
    end_current_session()
    
    if arduino and arduino.is_open:
        arduino.close()
    sys.exit(0)


def main():
    """Main function to run the serial bridge"""
    global running, last_data_sample_time, last_stat_aggregation_time
    
    logger.info("Starting enhanced serial bridge between database and Arduino")
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Connect to Arduino
    if not connect_to_arduino():
        logger.error(f"Could not connect to Arduino on {SERIAL_PORT}. Check connection and try again.")
        return
    
    # Start a new session
    start_new_session()
    
    # Send initial command to request control values from Arduino
    send_to_arduino("GET_ALL")
    
    # Initial sensor data request
    request_sensor_data()
    last_data_sample_time = time.time()
    last_stat_aggregation_time = time.time()
    
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
                
                # Process sensor data
                if response.startswith("SENSORS:"):
                    update_sensor_data(response)
                
                # Process status updates
                elif response.startswith("STATUS:"):
                    handle_status_update(response)
                
                # Process other responses
                elif response.startswith("REQUEST:"):
                    # Arduino is requesting data
                    if response == "REQUEST:CONTROLS":
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
            
            # Periodically request sensor data
            current_time = time.time()
            if current_time - last_data_sample_time >= DATA_SAMPLE_INTERVAL:
                request_sensor_data()
                last_data_sample_time = current_time
            
            # Periodically aggregate stats
            if current_time - last_stat_aggregation_time >= STAT_AGGREGATION_INTERVAL:
                aggregate_daily_stats()
                last_stat_aggregation_time = current_time
            
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