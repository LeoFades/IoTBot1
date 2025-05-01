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
    """Parse sensor data and update in database if needed"""
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
        
        # Here you could update the database with sensor values if needed
        # For now, we'll just log them
    except Exception as e:
        logger.error(f"Error parsing sensor data: {e}")


def handle_status_update(status_message):
    """Handle status update from Arduino"""
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