import math
import os
import serial
import collections
import numpy as np
import time
from pathlib import Path
from serial.tools import list_ports

from leader_calibration import CalibrationDataGenerator

def find_available_ports():
    if os.name == "nt":  # Windows
        # List COM ports using pyserial
        ports = [port.device for port in list_ports.comports()]
    else:  # Linux/macOS
        # List /dev/tty* ports for Unix-based systems
        ports = [str(path) for path in Path("/dev").glob("tty*")]
    return ports

def find_port():
    print("Finding all available ports for the MotorsBus.")
    ports_before = find_available_ports()
    print("Detected all ports before disconnection.")
    print("Remove the USB cable from your system and press Enter when done.")
    input()  # Wait for user to disconnect the device

    time.sleep(0.5)  # Allow some time for port to be released
    ports_after = find_available_ports()
    ports_diff = list(set(ports_before) - set(ports_after))

    if len(ports_diff) == 1:
        port = ports_diff[0]
        print(f"The port for the leader arm is '{port}'")
        with open("leader_port.txt", "w") as f:
            f.write(port + "\n")
        print("Saved port to leader_port.txt")

        print("Reconnect the USB cable.")
        input("Press Enter when done to continue...")  # Wait for user to reconnect the device
        time.sleep(0.5)  # Allow some time for port to be re-established
        print("Port detection complete. You can now run the AS5600 sensor script.")
        # Save to file
    elif len(ports_diff) == 0:
        raise OSError(f"Could not detect the port. No difference was found ({ports_diff}).")
    else:
        raise OSError(f"Could not detect the port. More than one port was found ({ports_diff}).")

# === Get port from leader_port.txt ===
PORT_FILE = "leader_port.txt"
if not os.path.exists(PORT_FILE):
    print(
        "leader_port.txt not found. Finding port and saving to file."
    )
    find_port()

with open(PORT_FILE, "r") as f:
    LEADER_PORT = f.readline().strip()

def signed_delta(raw, ref):
    return ((raw - ref + 2048) % 4096) - 2048

class AS5600Sensor:
    def __init__(self, serial_port=LEADER_PORT, baud_rate=115200):
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.esp = serial.Serial(serial_port, baud_rate, timeout=1)
        self.dummy_angles = [0.0] * 6
        self.window_size = 10
        self.angle_windows = [collections.deque(maxlen=self.window_size) for _ in range(6)]

        # Load or generate calibration data
        self.zero_pose, self.pose_90 = self.load_or_generate_calibration_data()
        self.slopes = self.compute_slopes(self.zero_pose, self.pose_90)
        print(f"Zero Pose:  {self.zero_pose}")
        print(f"90° Pose:   {self.pose_90}")
        print(f"Slopes:     {self.slopes}")
        print("AS5600 Sensor class has been Initialized")

    def load_or_generate_calibration_data(self, file_path='Calibration_Data.txt'):
        if not os.path.exists(file_path):
            print("Calibration_Data.txt not found. Running calibration process.")
            generator = CalibrationDataGenerator(
                serial_port=self.serial_port,
                baud_rate=self.baud_rate,
                samples=10,
                sample_delay=0.05
            )
            generator.generate(file_path)

        with open(file_path, 'r') as f:
            lines = f.readlines()
            if len(lines) < 2:
                raise ValueError("Calibration_Data.txt does not contain enough data.")
            zero_vals = list(map(int, lines[0].strip().split(',')))
            pose_90_vals = list(map(int, lines[1].strip().split(',')))
            if len(zero_vals) != 6 or len(pose_90_vals) != 6:
                raise ValueError("Each line in Calibration_Data.txt must contain 6 values.")
            return zero_vals, pose_90_vals

    def compute_slopes(self, zero_vals, pose_90_vals):
        slopes = []
        for z, n in zip(zero_vals, pose_90_vals):
            d90 = signed_delta(n, z)
            slopes.append(0.0 if d90 == 0 else 90.0 / d90)
        return slopes

    def convert_raw_to_degrees(self, raw_values):
        degrees = []
        for i, raw in enumerate(raw_values):
            d = signed_delta(raw, self.zero_pose[i])
            angle = d * self.slopes[i]
            degrees.append(angle)
        return degrees

    def apply_median_filter(self, angle_values):
        filtered_angles = []
        for i, angle in enumerate(angle_values):
            self.angle_windows[i].append(angle)
            angles_window = np.array(self.angle_windows[i])
            angles_unwrapped = np.unwrap(np.deg2rad(angles_window))
            median_unwrapped = np.median(angles_unwrapped)
            median_deg = math.degrees(median_unwrapped)
            median_deg = (median_deg + 180) % 360 - 180
            filtered_angles.append(median_deg)
        return filtered_angles

    def map_value(self, x, in_min, in_max, out_min, out_max):
        return max(out_min, min(out_max, (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min))

    def clip_angle(self, angle, min_angle, max_angle):
        return max(min(angle, max_angle), min_angle)

    def read_sensor_data(self):
        try:
            data = self.esp.readline().decode('utf-8').strip()
            if data:
                raw_values = list(map(int, data.split(",")))
                angles = self.convert_raw_to_degrees(raw_values)
                median_filtered_angles = self.apply_median_filter(angles)

                gripper_value = self.map_value(abs(median_filtered_angles[5]), 0.0, 92.0, 0, 20)
                self.dummy_angles = [
                    self.clip_angle(median_filtered_angles[0], -90.0, 90.0),
                    abs(median_filtered_angles[1]),
                    abs(median_filtered_angles[2]),
                    self.clip_angle(median_filtered_angles[3], -90.0, 90.0),
                    median_filtered_angles[4],
                    gripper_value
                ]
                return self.dummy_angles
        except Exception as e:
            print(f"Error from AS5600: {e}")
            return None

if __name__ == "__main__":
    sensor = AS5600Sensor(serial_port=LEADER_PORT, baud_rate=115200)

    try:
        while True:
            angles = sensor.read_sensor_data()
            if angles:
                print([round(angle, 2) for angle in angles])
    except KeyboardInterrupt:
        print("\nExiting gracefully...")
        sensor.esp.close()
