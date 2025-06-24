import serial
import time
import numpy as np
from threading import Lock
import threading

class CalibrationDataGenerator:
    """
    Collects AS5600 readings in two poses and writes the averaged 12 values
    (six from each pose) into Calibration_Data.txt.
    """

    def __init__(self, serial_port='/dev/ttyUSB0', baud_rate=115200,
                 samples=10, sample_delay=0.05):
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.samples = samples
        self.sample_delay = sample_delay
        self.ser = None
        self.values = []
        self.values_lock = Lock()
        self._open_serial()
        self.read_thread = threading.Thread(target=self._read_one_raw, daemon=True)
        self.read_thread.start()
    # def _open_serial(self):
    #     try:
    #         self.ser = serial.Serial(self.serial_port, self.baud_rate, timeout=1)
    #         self.ser.flushInput()  # Clear any existing input
    #         time.sleep(2)  # Give time for the serial device to reset
    #     except Exception as e:
    #         raise IOError(f"Could not open serial port {self.serial_port}: {e}")
    def _open_serial(self):
        try:
            self.ser = serial.Serial(self.serial_port, self.baud_rate, timeout=1)
            time.sleep(2)  # Give time for the device to reset
        except Exception as e:
            raise IOError(f"Could not open serial port {self.serial_port}: {e}")

    def _close_serial(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def _read_one_raw(self):
        """
        Reads one line from serial and returns six integers or None if malformed.
        """
        # line = self.ser.readline().decode('utf-8', errors='ignore').strip()
        while True:
            try:
                # values = list(map(int, line.split(',')))
                # if len(values) == 6:
                #     return values
                data = self.ser.readline().decode('utf-8').strip()
                values = list(map(int, data.split(",")))
                # print(f"Raw data read: {values}")  # Debug output
                with self.values_lock:
                    if len(values) != 6:
                        raise ValueError(f"Expected 6 values, got {len(values)}: {values}")

                    self.values = values
                # return values if len(values) == 6 else None
            except ValueError as e:
                print(f"ValueError: {e} - Data may be malformed or not six integers.")
            time.sleep(0.01)  # Small delay to avoid busy waiting
         
    
    def _get_one_raw(self):
        """
        Reads one line from serial and returns six integers or None if malformed.
        This is a blocking call that waits for valid data.
        """
        with self.values_lock:
            return self.values

    def _average_readings(self):
        """
        Averages `samples` number of valid 6-element readings.
        """
        readings = []
        while len(readings) < self.samples:
            val = self._get_one_raw()
            print(f"Read: {val}")  # Debug output
            if val:
                readings.append(val)
            time.sleep(self.sample_delay)
        arr = np.array(readings, dtype=np.int64)
        avg = np.round(arr.mean(axis=0)).astype(int)
        return avg.tolist()

    def generate(self, output_file='Calibration_Data.txt'):
        print("\n=== CALIBRATION DATA GENERATION ===\n")

        # ---------- ZERO POSE ----------
        input("1) Move arm to ZERO pose and press ENTER to start sampling...")
        # self._open_serial()
        zero_vals = self._average_readings()
        # self._close_serial()
        print("   Zero pose average:", zero_vals)

        # ---------- ROTATED POSE ----------
        input("\n2) Move arm to 90° pose and press ENTER to start sampling...")
        # self._open_serial()
        rotated_vals = self._average_readings()
        print("   90° pose average:", rotated_vals)

        # ---------- SAVE TO FILE ----------
        with open(output_file, 'w') as f:
            f.write(",".join(map(str, zero_vals)) + "\n")
            f.write(",".join(map(str, rotated_vals)) + "\n")

        print(f"\n✓ Calibration data saved to '{output_file}'.")


if __name__ == "__main__":
    generator = CalibrationDataGenerator(
        serial_port='/dev/ttyUSB0',
        baud_rate=115200,
        samples=10,
        sample_delay=0.05
    )
    generator.generate()
    generator._close_serial()
    

