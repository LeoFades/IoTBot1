-- Create database if it doesn't exist
CREATE DATABASE IF NOT EXISTS drone_db;
USE drone_db;

-- Create drone_controls table
CREATE TABLE IF NOT EXISTS drone_controls (
    id INT AUTO_INCREMENT PRIMARY KEY,
    control_name VARCHAR(50) NOT NULL,
    control_value VARCHAR(255) NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Insert default values if not already present
-- Drive motor control (forward, backward, stop)
INSERT INTO drone_controls (control_name, control_value)
SELECT 'drive_motor', 'stop'
WHERE NOT EXISTS (SELECT 1 FROM drone_controls WHERE control_name = 'drive_motor');

-- Steering control (left, center, right)
INSERT INTO drone_controls (control_name, control_value)
SELECT 'steering', 'center'
WHERE NOT EXISTS (SELECT 1 FROM drone_controls WHERE control_name = 'steering');

-- Headlights control
INSERT INTO drone_controls (control_name, control_value)
SELECT 'headlights', 'off'
WHERE NOT EXISTS (SELECT 1 FROM drone_controls WHERE control_name = 'headlights');

-- LCD message
INSERT INTO drone_controls (control_name, control_value)
SELECT 'lcd_message', 'Hello Drone!'
WHERE NOT EXISTS (SELECT 1 FROM drone_controls WHERE control_name = 'lcd_message');

-- Create a sample database user with appropriate permissions
-- GRANT ALL PRIVILEGES ON drone_db.* TO 'drone_user'@'localhost' IDENTIFIED BY 'your_password';
-- FLUSH PRIVILEGES;

CREATE TABLE IF NOT EXISTS sensor_readings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    reading_type VARCHAR(50) NOT NULL,
    reading_value FLOAT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_reading_type (reading_type),
    INDEX idx_timestamp (timestamp)
);

CREATE OR REPLACE VIEW hourly_sensor_averages AS
SELECT 
    reading_type,
    DATE_FORMAT(timestamp, '%Y-%m-%d %H:00:00') AS hour_bucket,
    AVG(reading_value) AS average_value,
    MIN(reading_value) AS min_value,
    MAX(reading_value) AS max_value,
    COUNT(*) AS reading_count
FROM 
    sensor_readings
GROUP BY 
    reading_type, hour_bucket
ORDER BY 
    hour_bucket DESC, reading_type;

