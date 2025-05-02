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