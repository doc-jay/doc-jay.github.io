# M18 Battery Diagnostics Script
# Version: 1.0.20
# Date: 2025-10-06
# Author: Grok (generated for xAI)
# Description: Interfaces with Milwaukee M18 battery via Redlink protocol to read/write diagnostic data.
# Dependencies: pyserial, requests, pyreadline3 (optional for Windows), matplotlib (optional for plotting)
# Change Log:
#   1.0.0 (2025-09-14): Initial version with dynamic CSV filename, write_date(), health warnings, menu.
#   1.0.1 (2025-09-14): Fixed health() to convert datetime/list to strings for CSV.
#   1.0.2 (2025-09-14): Ensured all array values are strings for console output.
#   1.0.3 (2025-09-14): Handled invalid date register responses in health().
#   1.0.4 (2025-09-14): Enhanced read_id() to validate date registers strictly.
#   1.0.5 (2025-09-14): Fixed health() to use correct CSV filename, include all 183 registers.
#   1.0.6 (2025-09-14): Removed write_date(), retained all original functions, fixed date errors.
#   1.0.7 (2025-09-14): Fixed 'bat_type' undefined error, added retry logic for serial reads.
#   1.0.8 (2025-09-14): Fixed SyntaxError in data_id for 0x912A, ensured correct CSV filename.
#   1.0.9 (2025-09-14): Fixed 'imbalance' undefined error, corrected register indexing in health().
#   1.0.10 (2025-10-04): Improved readability with grouped console sections, color-coded metrics, CSV summary table.
#   1.0.11 (2025-10-04): Fixed SyntaxError in health() at reg_list.index(40).
#   1.0.12 (2025-10-04): Fixed incorrect register indexing in health() (e.g., Manufacture Date, Charge Count, SoH).
#   1.0.13 (2025-10-04): Fixed SyntaxError in health() for tool_time_index range, salons corrected all register mappings.
#   1.0.14 (2025-10-04): Converted temperatures to Fahrenheit, added ' F' label to console and CSV.
#   1.0.15 (2025-10-04): Added degree symbol '°' before F in console and CSV, updated labels.
#   1.0.16 (2025-10-05): Added empty line separator between Basic Info and Voltage & Temperature sections, fixed plot_voltages condition to check array[1][1].
#   1.0.17 (2025-10-05): Changed CSV filename to 'Milwaukee_Batt_M18_serial#_currentdate.csv' with current date and time.
#   1.0.18 (2025-10-05): Updated CSV filename format to use hyphens for date/time separators (e.g., 2025-10-05_21-14pm), no seconds, lowercase am/pm.
#   1.0.19 (2025-10-05): Added menu option 6 for exporting raw data to dashboard via HTTP POST, with connectivity test (ping and port check) before sending. Updated default dashboard_url to http://172.25.47.113:5002/data.
#   1.0.20 (2025-10-06): Enhanced export_to_dashboard with retries, detailed logging, and confirmed default URL. Increased retries in health() to 5. Updated menu prompt for option 6.

import serial
from serial.tools import list_ports
import time, struct
import argparse
import datetime
import logging
import requests
import csv
import os
import socket
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
try:
    import readline
except ImportError:
    pass

# ANSI color codes for console formatting (works in Windows Terminal)
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

data_matrix = [
    [0x00, 0x00, 0x02], [0x00, 0x02, 0x02], [0x00, 0x04, 0x05], [0x00, 0x0D, 0x04],
    [0x00, 0x11, 0x04], [0x00, 0x15, 0x04], [0x00, 0x19, 0x04], [0x00, 0x23, 0x14],
    [0x00, 0x37, 0x04], [0x00, 0x69, 0x02], [0x00, 0x7B, 0x01], [0x40, 0x00, 0x04],
    [0x40, 0x0A, 0x0A], [0x40, 0x14, 0x02], [0x40, 0x16, 0x02], [0x40, 0x19, 0x02],
    [0x40, 0x1B, 0x02], [0x40, 0x1D, 0x02], [0x40, 0x1F, 0x02], [0x60, 0x00, 0x02],
    [0x60, 0x02, 0x02], [0x60, 0x04, 0x04], [0x60, 0x08, 0x04], [0x60, 0x0C, 0x02],
    [0x90, 0x00, 0x3A], [0x90, 0x3A, 0x3A], [0x90, 0x74, 0x3A], [0x90, 0xAE, 0x3A],
    [0x90, 0xE8, 0x3A], [0x91, 0x22, 0x30], [0x91, 0x52, 0x00], [0xA0, 0x00, 0x06]
]

data_id = [
    [0x0000, 2, "uint", "Cell type"], [0x0002, 2, "uint", "Unknown (always 0)"],
    [0x0004, 5, "sn", "Capacity & Serial number (?)"], [0x000D, 4, "uint", "Unknown (4th code?)"],
    [0x0011, 4, "date", "Manufacture date"], [0x0015, 4, "date", "Date of first charge (Forge)"],
    [0x0019, 4, "date", "Date of last charge (Forge)"], [0x0023, 20, "ascii", "Note (ascii string)"],
    [0x0037, 4, "date", "Current date"], [0x0069, 2, "uint", "Unknown (always 2)"],
    [0x007B, 1, "uint", "Unknown (always 0)"], [0x4000, 4, "uint", "Unknown (Forge)"],
    [0x400A, 10, "cell_v", "Cell voltages (mV)"], [0x4014, 2, "adc_t", "Temperature (°F) (non-Forge)"],
    [0x4016, 2, "uint", "Unknown (Forge)"], [0x4019, 2, "uint", "Unknown (Forge)"],
    [0x401B, 2, "uint", "Unknown (Forge)"], [0x401D, 2, "uint", "Unknown (Forge)"],
    [0x401F, 2, "dec_t", "Temperature (°F) (Forge)"], [0x6000, 2, "uint", "Unknown (Forge)"],
    [0x6002, 2, "uint", "Unknown Anderson (Forge)"], [0x6004, 4, "uint", "Unknown (Forge)"],
    [0x6008, 4, "uint", "Unknown (Forge)"], [0x600C, 2, "uint", "Unknown (Forge)"],
    [0x9000, 4, "date", "Date of first charge (rounded)"], [0x9004, 4, "date", "Date of last tool use (rounded)"],
    [0x9008, 4, "date", "Date of last charge (rounded)"], [0x900C, 4, "date", "Unknown date (often zero)"],
# Line  आप 78
    [0x9010, 2, "uint", "Days since first charge"], [0x9012, 4, "uint", "Total discharge (amp-sec)"],
    [0x9016, 4, "uint", "Total discharge (watt-sec or joules)"], [0x901A, 4, "uint", "Total charge count"],
    [0x901E, 2, "uint", "Dumb charge count (J2>7.1V for >=0.48s)"], [0x9020, 2, "uint", "Redlink (UART) charge count"],
    [0x9022, 2, "uint", "Completed charge count (?)"], [0x9024, 4, "hhmmss", "Total charging time (HH:MM:SS)"],
    [0x9028, 4, "hhmmss", "Time on charger whilst full (HH:MM:SS)"], [0x902C, 2, "uint", "Unknown (almost always 0)"],
    [0x902E, 2, "uint", "Charge started with a cell < 2.5V"], [0x9030, 2, "uint", "Discharge to empty"],
    [0x9032, 2, "uint", "Num. overheat on tool (must be > 10A)"], [0x9034, 2, "uint", "Overcurrent?"],
    [0x9036, 2, "uint", "Low voltage events"], [0x9038, 2, "uint", "Low-voltage bounce? (4 flashing LEDs)"],
    [0x903A, 2, "uint", "Discharge @ 10-20A (seconds)"], [0x903C, 2, "uint", "@ 20-30A (could be watts)"],
    [0x903E, 2, "uint", "@ 30-40A"], [0x9040, 2, "uint", "@ 40-50A"], [0x9042, 2, "uint", "@ 50-60A"],
    [0x9044, 2, "uint", "@ 60-70A"], [0x9046, 2, "uint", "@ 70-80A"], [0x9048, 2, "uint", "@ 80-90A"],
    [0x904A, 2, "uint", "@ 90-100A"], [0x904C, 2, "uint", "@ 100-110A"], [0x904E, 2, "uint", "@ 110-120A"],
    [0x9050, 2, "uint", "@ 120-130A"], [0x9052, 2, "uint", "@ 130-140A"], [0x9054, 2, "uint", "@ 140-150A"],
    [0x9056, 2, "uint", "@ 150-160A"], [0x9058, 2, "uint", "@ 160-170A"], [0x905A, 2, "uint", "@ 170-180A"],
    [0x905C, 2, "uint", "@ 180-190A"], [0x905E, 2, "uint", "@ 190-200A"], [0x9060, 2, "uint", "@ 200-210A"],
    [0x9062, 2, "uint", "Unknown (larger in lower Ah packs)"], [0x9064, 2, "uint", "Discharge @ 10-15A (seconds)"],
    [0x9066, 2, "uint", "@ 15-20A (could be watts)"], [0x9068, 2, "uint", "@ 20-25A"],
    [0x906A, 2, "uint", "@ 25-30A"], [0x906C, 2, "uint", "@ 30-35A"], [0x906E, 2, "uint", "@ 35-40A"],
    [0x9070, 2, "uint", "@ 40-45A"], [0x9072, 2, "uint", "@ 45-50A"], [0x9074, 2, "uint", "@ 50-55A"],
    [0x9076, 2, "uint", "@ 55-60A"], [0x9078, 2, "uint", "@ 60-65A"], [0x907A, 2, "uint", "@ 65-70A"],
    [0x907C, 2, "uint", "@ 70-75A"], [0x907E, 2, "uint", "@ 75-80A"], [0x9080, 2, "uint", "@ 80-85A"],
    [0x9082, 2, "uint", "@ 85-90A"], [0x9084, 2, "uint", "@ 90-95A"], [0x9086, 2, "uint", "@ 95-100A"],
    [0x9088, 2, "uint", "@ 100-105A"], [0x908A, 2, "uint", "@ 105-110A"], [0x908C, 2, "uint", "@ 110-115A"],
    [0x908E, 2, "uint", "@ 115-120A"], [0x9090, 2, "uint", "@ 120-125A"], [0x9092, 2, "uint", "@ 125-130A"],
    [0x9094, 2, "uint", "@ 130-135A"], [0x9096, 2, "uint", "@ 135-140A"], [0x9098, 2, "uint", "@ 140-145A"],
    [0x909A, 2, "uint", "@ 145-150A"], [0x909C, 2, "uint", "@ 150-155A"], [0x909E, 2, "uint", "@ 155-160A"],
    [0x90A0, 2, "uint", "@ 160-165A"], [0x90A2, 2, "uint", "@ 165-170A"], [0x90A4, 2, "uint", "@ 170-175A"],
    [0x90A6, 2, "uint", "@ 175-180A"], [0x90A8, 2, "uint", "@ 180-185A"], [0x90AA, 2, "uint", "@ 185-190A"],
    [0x90AC, 2, "uint", "@ 190-195A"], [0x90AE, 2, "uint", "@ 195-200A"], [0x90B0, 2, "uint", "@ 200A+"],
    [0x90B2, 2, "uint", "Charge started < 17V"], [0x90B4, 2, "uint", "Charge started 17-18V"],
    [0x90B6, 2, "uint", "Charge started 18-19V"], [0x90B8, 2, "uint", "Charge started 19-20V"],
    [0x90BA, 2, "uint", "Charge started 20V+"], [0x90BC, 2, "uint", "Charge ended < 17V"],
    [0x90BE, 2, "uint", "Charge ended 17-18V"], [0x90C0, 2, "uint", "Charge ended 18-19V"],
    [0x90C2, 2, "uint", "Charge ended 19-20V"], [0x90C4, 2, "uint", "Charge ended 20V+"],
    [0x90C6, 2, "uint", "Charge start temp -30C to -20C"], [0x90C8, 2, "uint", "Charge start temp -20C to -10C"],
    [0x90CA, 2, "uint", "Charge start temp -10C to 0C"], [0x90CC, 2, "uint", "Charge start temp 0C to +10C"],
    [0x90CE, 2, "uint", "Charge start temp +10C to +20C"], [0x90D0, 2, "uint", "Charge start temp +20C to +30C"],
    [0x90D2, 2, "uint", "Charge start temp +30C to +40C"], [0x90D4, 2, "uint", "Charge start temp +40C to +50C"],
    [0x90D6, 2, "uint", "Charge start temp +50C to +60C"], [0x90D8, 2, "uint", "Charge start temp +60C to +70C"],
    [0x90DA, 2, "uint", "Charge start temp +70C to +80C"], [0x90DC, 2, "uint", "Charge start temp +80C and over"],
    [0x90DE, 2, "uint", "Charge end temp -30C to -20C"], [0x90E0, 2, "uint", "Charge end temp -20C to -10C"],
    [0x90E2, 2, "uint", "Charge end temp -10C to 0C"], [0x90E4, 2, "uint", "Charge end temp 0C to +10C"],
    [0x90E6, 2, "uint", "Charge end temp +10C to +20C"], [0x90E8, 2, "uint", "Charge end temp +20C to +30C"],
    [0x90EA, 2, "uint", "Charge end temp +30C to +40C"], [0x90EC, 2, "uint", "Charge end temp +40C to +50C"],
    [0x90EE, 2, "uint", "Charge end temp +50C to +60C"], [0x90F0, 2, "uint", "Charge end temp +60C to +70C"],
    [0x90F2, 2, "uint", "Charge end temp +70C to +80C"], [0x90F4, 2, "uint", "Charge end temp +80C and over"],
    [0x90F6, 2, "uint", "Dumb charge time (00:00-14:33)"], [0x90F8, 2, "uint", "Dumb charge time (14:34-29:07)"],
    [0x90FA, 2, "uint", "Dumb charge time (29:08-43:41)"], [0x90FC, 2, "uint", "Dumb charge time (43:42-58:15)"],
    [0x90FE, 2, "uint", "Dumb charge time (58:16-1:12:49)"], [0x9100, 2, "uint", "Dumb charge time (1:12:50-1:27:23)"],
    [0x9102, 2, "uint", "Dumb charge time (1:27:24-1:41:57)"], [0x9104, 2, "uint", "Dumb charge time (1:41:58-1:56:31)"],
    [0x9106, 2, "uint", "Dumb charge time (1:56:32-2:11:05)"], [0x9108, 2, "uint", "Dumb charge time (2:11:06-2:25:39)"],
    [0x910A, 2, "uint", "Dumb charge time (2:25:40-2:40:13)"], [0x910C, 2, "uint", "Dumb charge time (2:40:14-2:54:47)"],
# Line  systolic 130
    [0x910E, 2, "uint", "Dumb charge time (2:54:48-3:09:21)"], [0x9110, 2, "uint", "Dumb charge time (3:09:22-3:23:55)"], 
    [0x9112, 2, "uint", "Redlink charge time (00:00-17:03)"], [0x9114, 2, "uint", "Redlink charge time (17:04-34:07)"],
    [0x9116, 2, "uint", "Redlink charge time (34:08-51:11)"], [0x9118, 2, "uint", "Redlink charge time (51:12-1:08:15)"],
    [0x911A, 2, "uint", "Redlink charge time (1:08:16-1:25:19)"], [0x911C, 2, "uint", "Redlink charge time (1:25:20-1:42:23)"],
    [0x911E, 2, "uint", "Redlink charge time (1:42:24-1:59:27)"], [0x9120, 2, "uint", "Redlink charge time (1:59:28-2:16:31)"],
    [0x9122, 2, "uint", "Redlink charge time (2:16:32-2:33:35)"], [0x9124, 2, "uint", "Redlink charge time (2:33:36-2:50:39)"],
    [0x9126, 2, "uint", "Redlink charge time (2:50:40-3:07:43)"], [0x9128, 2, "uint", "Redlink charge time (3:07:44-3:24:47)"],
    [0x912A, 2, "uint", "Redlink charge time (3:24:48-3:41:51)"], [0x912C, 2, "uint", "Redlink charge time (3:41:52-3:58:55)"],
    [0x912E, 2, "uint", "Completed charge (?)"], [0x9130, 2, "uint", "Unknown"],
    [0x9132, 2, "uint", "Unknown"], [0x9134, 2, "uint", "Unknown"], [0x9136, 2, "uint", "Unknown"],
    [0x9138, 2, "uint", "Unknown"], [0x913A, 2, "uint", "Unknown"], [0x913C, 2, "uint", "Unknown"],
    [0x913E, 2, "uint", "Unknown"], [0x9140, 2, "uint", "Unknown"], [0x9142, 2, "uint", "Unknown"],
    [0x9144, 2, "uint", "Unknown"], [0x9146, 2, "uint", "Unknown"], [0x9148, 2, "uint", "Unknown (days of use?)"],
    [0x914A, 2, "uint", "Unknown"], [0x914C, 2, "uint", "Unknown"], [0x914E, 2, "uint", "Unknown"],
    [0x9150, 2, "uint", "Unknown"]
]

class M18:
    SYNC_BYTE = 0xAA
    CAL_CMD = 0x55
    CONF_CMD = 0x60
    SNAP_CMD = 0x61
    KEEPALIVE_CMD = 0x62
    CUTOFF_CURRENT = 300
    MAX_CURRENT = 6000
    ACC = 4
    PRINT_TX = False
    PRINT_RX = False
    PRINT_TX_SAVE = False
    PRINT_RX_SAVE = False

    def txrx_print(self, enable=True):
        self.PRINT_TX = enable
        self.PRINT_RX = enable

    def txrx_save_and_set(self, enable=True):
        self.PRINT_TX_SAVE = self.PRINT_TX
        self.PRINT_RX_SAVE = self.PRINT_RX
        self.txrx_print(enable)

    def txrx_restore(self):
        self.PRINT_TX = self.PRINT_TX_SAVE
        self.PRINT_RX = self.PRINT_RX_SAVE

    def __init__(self, port=None):
        if port is None:
            print("*** NO PORT SPECIFIED ***")
            print("Available serial ports (choose one that says USB somewhere):")
            ports = list_ports.comports()
            i = 1
            for p in ports:
                print(f" {i}: {p.device} - {p.manufacturer} - {p.description}")
                i += 1
            port_id = 0
            while (port_id < 1) or (port_id >= i):
                user_port = input(f"Choose a port (1-{i-1}): ")
                try:
                    port_id = int(user_port)
                except ValueError:
                    print("Invalid input. Please enter a number")
            p = ports[port_id - 1]
            print(f"You selected \"{p.device} - {p.manufacturer} - {p.description}\"")
            print(f"In future, use \"m18_battery_diagnostics.py --port {p.device}\" to avoid this menu")
            input("Press Enter to continue")
            port = p.device
        self.port = serial.Serial(port, baudrate=4800, timeout=0.8, stopbits=2)
        self.idle()
        
    def idle(self):  # <--- Add/correct this method here (indented under the class)
        try:
            self.cmd(0xB0, 0x00, 0x00, 0x00)
        except Exception as e:
            print(f"idle: Failed with error: {e}")


    def reset(self):
        self.ACC = 4
        self.port.break_condition = True
        self.port.dtr = True
        time.sleep(0.3)
        self.port.break_condition = False
        self.port.dtr = False
        time.sleep(0.3)
        self.send(struct.pack('>B', self.SYNC_BYTE))
        try:
            response = self.read_response(1)
        except:
            return False
        time.sleep(0.01)
        if response and response[0] == self.SYNC_BYTE:
            return True
        else:
            print(f"Unexpected response: {response}")
            return False

    def update_acc(self):
        acc_values = [0x04, 0x0C, 0x1C]
        current_index = acc_values.index(self.ACC)
        next_index = (current_index + 1) % len(acc_values)
        self.ACC = acc_values[next_index]

    def reverse_bits(self, byte):
        return int(f"{byte:08b}"[::-1], 2)

    def checksum(self, payload):
        checksum = 0
        for byte in payload:
            checksum += byte & 0xFFFF
        return checksum

    def add_checksum(self, lsb_command):
        lsb_command += struct.pack(">H", self.checksum(lsb_command))
        return lsb_command

    def send(self, command):
        self.port.reset_input_buffer()
        debug_print = " ".join(f"{byte:02X}" for byte in command)
        msb = bytearray(self.reverse_bits(byte) for byte in command)
        if self.PRINT_TX:
            print(f"Sending: {debug_print}")
        self.port.write(msb)

    def send_command(self, command):
        self.send(self.add_checksum(command))

    def read_response(self, size):
        msb_response = self.port.read(1)
        if not msb_response or len(msb_response) < 1:
            raise ValueError("Empty response")
        if self.reverse_bits(msb_response[0]) == 0x82:
            msb_response += self.port.read(1)
        else:
            msb_response += self.port.read(size-1)
        lsb_response = bytearray(self.reverse_bits(byte) for byte in msb_response)
        debug_print = " ".join(f"{byte:02X}" for byte in lsb_response)
        if self.PRINT_RX:
            print(f"Received: {debug_print}")
        return lsb_response

    def configure(self, state):
        self.ACC = 4
        self.send_command(struct.pack('>BBBHHHBB', self.CONF_CMD, self.ACC, 8,
                                    self.CUTOFF_CURRENT, self.MAX_CURRENT, self.MAX_CURRENT, state, 13))
        return self.read_response(5)

    def get_snapchat(self):
        self.send_command(struct.pack('>BBB', self.SNAP_CMD, self.ACC, 0))
        self.update_acc()
        return self.read_response(8)

    def keepalive(self):
        self.send_command(struct.pack('>BBB', self.KEEPALIVE_CMD, self.ACC, 0))
        return self.read_response(9)

    def calibrate(self):
        self.send_command(struct.pack('>BBB', self.CAL_CMD, self.ACC, 0))
        self.update_acc()
        return self.read_response(8)

    def simulate(self):
        print("Simulating charger communication")
        self.txrx_save_and_set(True)
        self.reset()
        self.configure(2)
        self.get_snapchat()
        time.sleep(0.6)
        self.keepalive()
        self.configure(1)
        self.get_snapchat()
        try:
            while True:
                time.sleep(0.5)
                self.keepalive()
        except KeyboardInterrupt:
            print("\nSimulation aborted by user. Exiting gracefully...")
        finally:
            self.idle()
            self.txrx_restore()

    def simulate_for(self, duration):
        print(f"Simulating charger communication for {duration} seconds...")
        begin_time = time.time()
        self.reset()
        self.configure(2)
        self.get_snapchat()
        time.sleep(0.6)
        self.keepalive()
        self.configure(1)
        self.get_snapchat()
        try:
            while (time.time() - begin_time) < duration:
                time.sleep(0.5)
                self.keepalive()
        except KeyboardInterrupt:
            print("\nSimulation aborted by user. Exiting gracefully...")
        finally:
            self.idle()
            print(f"Duration: ", time.time() - begin_time)

    def debug(self, a, b, c, length):
        rx_debug = self.PRINT_RX
        tx_debug = self.PRINT_TX
        self.PRINT_TX = False
        self.PRINT_RX = False
        self.reset()
        self.PRINT_TX = tx_debug
        data = self.cmd(a, b, c, length)
        data_print = " ".join(f"{byte:02X}" for byte in data)
        print(f"Response from: 0x{(a * 0x100 + b):04X}:", data_print)
        self.idle()
        self.PRINT_RX = rx_debug

    def try_cmd(self, cmd, msb, lsb, len, ret_len=0):
        self.txrx_save_and_set(False)
        if ret_len == 0:
            ret_len = len + 5
        self.reset()
        self.send_command(struct.pack('>BBBBBB', cmd, 0x04, 0x03, msb, lsb, len))
        data = self.read_response(ret_len)
        data_print = " ".join(f"{byte:02X}" for byte in data)
        print(f"Response from: 0x{(msb * 0x100 + lsb):04X}:", data_print)
        self.idle()
        self.txrx_restore()

    def cmd(self, a, b, c, length, command=0x01):
        self.send_command(struct.pack('>BBBBBB', command, 0x04, 0x03, a, b, c))
        return self.read_response(length)

    def brute(self, a, b, len=0xFF, command=0x01):
        self.reset()
        try:
            for i in range(len):
                ret = self.cmd(a, b, i, i+5, command)
                if ret[0] == 0x81:
                    data_print = " ".join(f"{byte:02X}" for byte in ret)
                    print(f"Valid response from: 0x{(a * 0x100 + b):04X} with length: 0x{i:02X}:", data_print)
        except KeyboardInterrupt:
            print("\nSimulation aborted by user. Exiting gracefully...")
        finally:
            self.idle()

    def full_brute(self, start=0, stop=0xFFFF, len=0xFF):
        try:
            for addr in range(start, stop):
                msb = (addr >> 8) & 0xFF
                lsb = addr & 0xFF
                self.brute(msb, lsb, len, 0x01)
                if (addr % 256) == 0:
                    print(f"addr = 0x{addr:04X} ", datetime.datetime.now())
        except KeyboardInterrupt:
            print("\nSimulation aborted by user. Exiting gracefully...")
            print(f"\nStopped at address: 0x{addr:04X}")
        finally:
            self.idle()

    def wcmd(self, a, b, c, length):
        self.send_command(struct.pack('>BBBBBB', 0x01, 0x05, 0x03, a, b, c))
        return self.read_response(length)

    def write_message(self, message):
        try:
            if len(message) > 0x14:
                print("ERROR: Message too long!")
                return
            print(f"Writing \"{message}\" to memory")
            self.reset()
            message = message.ljust(0x14, '-')
            for i, char in enumerate(message):
                self.wcmd(0, 0x23 + i, ord(char), 2)
        except Exception as e:
            print(f"write_message: Failed with error: {e}")

    def calculate_temperature(self, adc_value):
        R1 = 10e3
        R2 = 20e3
        T1 = 50
        T2 = 35
        adc1 = 0x0180
        adc2 = 0x022E
        m = (T2 - T1) / (R2 - R1)
        b = T1 - m * R1
        resistance = R1 + (adc_value - adc1) * (R2 - R1) / (adc2 - adc1)
        temperature_c = m * resistance + b
        temperature_f = (temperature_c * 9 / 5) + 32
        return round(temperature_f, 2)

    def bytes2dt(self, time_bytes):
        try:
            epoch_time = int.from_bytes(time_bytes, 'big')
            if epoch_time < 0 or epoch_time > 0x7FFFFFFF:
                return None
            dt = datetime.datetime.fromtimestamp(epoch_time, tz=datetime.timezone.utc)
            return dt
        except (ValueError, TypeError, OverflowError):
            return None

    def read_all(self):
        try:
            self.reset()
            for addr_h, addr_l, length in data_matrix:
                response = self.cmd(addr_h, addr_l, length, (length + 5))
                if response and len(response) >= 4 and response[0] == 0x81:
                    data = response[3:3 + length]
                    data_print = " ".join(f"{byte:02X}" for byte in data)
                    print(f"Response from: 0x{(addr_h * 0x100 + addr_l):04X}:", data_print)
                else:
                    data_print = " ".join(f"{byte:02X}" for byte in response)
                    print(f"Invalid response from: 0x{(addr_h * 0x100 + addr_l):04X} Response: {data_print}")
            self.idle()
        except Exception as e:
            print(f"read_all: Failed with error: {e}")

    def read_all_spreadsheet(self):
        try:
            self.reset()
            for addr_h, addr_l, length in data_matrix:
                response = self.cmd(addr_h, addr_l, length, (length + 5))
                if response and len(response) >= 4 and response[0] == 0x81:
                    data = response[3:3 + length]
                    data_print = ",".join(f"{byte:02X}" for byte in data)
                    print(f"0x{(addr_h * 0x100 + addr_l):04X},{data_print}")
                else:
                    print(f"0x{(addr_h * 0x100 + addr_l):04X},Invalid")
            self.idle()
        except Exception as e:
            print(f"read_all_spreadsheet: Failed with error: {e}")

    def read_id(self, id_array=[], force_refresh=True, output="label", csv_path=None, retries=3):
        """
        Read data by ID. Default is print all
        # id_array - array of registers to print
        # force_refresh - force a read of all registers to ensure they're up to date
        # output - ["label" | "raw" | "array" | "form" | "csv"]
        # csv_path - custom CSV path; if None for output='csv', uses serial_number_year_month_day.csv
        # retries - number of retry attempts for failed reads
        """
        if output not in ["label", "raw", "array", "form", "csv"]:
            print(f"Unrecognised 'output' = {output}. Please choose \"label\", \"raw\", \"array\", \"form\", or \"csv\"")
            output = "label"
        
        array = []
        csv_data = []
        
        try:
            # Get serial number and manufacture date for CSV filename
            serial_number = None
            manufacture_date = None
            if output == "csv" and csv_path is None:
                for attempt in range(retries):
                    try:
                        self.reset()
                        response = self.cmd(0x00, 0x04, 0x05, 10)
                        if response and len(response) >= 4 and response[0] == 0x81:
                            data = response[3:8]
                            serial_number = int.from_bytes(data[2:5], 'big')
                        response = self.cmd(0x00, 0x11, 0x04, 9)
                        if response and len(response) >= 4 and response[0] == 0x81:
                            data = response[3:7]
                            manufacture_date = self.bytes2dt(data)
                            if manufacture_date:
                                manufacture_date = manufacture_date.strftime('%Y_%m_%d')
                        if serial_number and manufacture_date:
                            csv_path = f"{serial_number}_{manufacture_date}.csv"
                            break
                        print(f"Retry {attempt+1}/{retries} for serial number/manufacture date failed")
                        time.sleep(0.5)
                    except Exception as e:
                        print(f"Retry {attempt+1}/{retries} failed: {e}")
                        time.sleep(0.5)
                if not csv_path:
                    csv_path = 'battery_diagnostics.csv'
                    print("Warning: Using default CSV path due to failed reads")
            
            self.reset()
            if force_refresh:
                for addr_h, addr_l, length in data_matrix:
                    for attempt in range(retries):
                        try:
                            response = self.cmd(addr_h, addr_l, length, (length + 5))
                            break
                        except Exception as e:
                            print(f"Retry {attempt+1}/{retries} for 0x{addr_h:02X}{addr_l:02X} failed: {e}")
                            time.sleep(0.5)
                self.idle()
                time.sleep(0.1)
            
            now = datetime.datetime.now()
            formatted_time = now.strftime("%Y-%m-%d %H:%M:%S")
            if output == "label":
                print(formatted_time)
                print("ID ADDR LEN TYPE LABEL VALUE")
            elif output == "raw":
                print(formatted_time)
            elif output in ["array", "form"]:
                array.append(formatted_time)
            elif output == "csv":
                csv_data.append(["Timestamp", formatted_time])
                csv_data.append(["ID", "Address", "Length", "Type", "Label", "Value"])
            
            self.reset()
            for i in id_array or range(0, len(data_id)):
                addr = data_id[i][0]
                addr_h = (addr >> 8) & 0xFF
                addr_l = addr & 0xFF
                length = data_id[i][1]
                type = data_id[i][2]
                label = data_id[i][3]
                response = None
                for attempt in range(retries):
                    try:
                        response = self.cmd(addr_h, addr_l, length, (length + 5))
                        break
                    except Exception as e:
                        print(f"Retry {attempt+1}/{retries} for ID {i} (0x{addr:04X}) failed: {e}")
                        time.sleep(0.5)
                if response and len(response) >= 4 and response[0] == 0x81 and len(response[3:]) >= length:
                    data = response[3:(3+length)]
                    match type:
                        case "uint":
                            array_value = value = int.from_bytes(data, 'big')
                        case "date":
                            array_value = self.bytes2dt(data)
                            value = array_value.strftime('%Y-%m-%d %H:%M:%S') if array_value else "------"
                        case "hhmmss":
                            dur = int.from_bytes(data, 'big')
                            mm, ss = divmod(dur, 60)
                            hh, mm = divmod(mm, 60)
                            array_value = value = f"{hh}:{mm:02d}:{ss:02d}"
                        case "ascii":
                            try:
                                str_val = data.decode('utf-8')
                                array_value = value = f'"{str_val}"'
                            except UnicodeDecodeError:
                                array_value = value = "------"
                        case "sn":
                            btype = int.from_bytes(data[0:2], 'big')
                            serial = int.from_bytes(data[2:5], 'big')
                            if output in ["label", "array", "csv"]:
                                array_value = f"Type: {btype:3d}, Serial: {serial:d}"
                                value = f"Type: {btype:3d}, Serial: {serial:d}"
                            else:
                                value = f"{btype}\n{serial}"
                        case "adc_t":
                            array_value = value = self.calculate_temperature(int.from_bytes(data, 'big'))
                        case "dec_t":
                            temp_c = data[0] + data[1]/256
                            temp_f = (temp_c * 9/5) + 32  # Convert to Fahrenheit
                            array_value = value = f"{temp_f:.2f}"
                        case "cell_v":
                            array_value = cv = [int.from_bytes(data[i:i+2], 'big') for i in range(0, 10, 2)]
                            if output == "label":
                                value = f"1: {cv[0]:4d}, 2: {cv[1]:4d}, 3: {cv[2]:4d}, 4: {cv[3]:4d}, 5: {cv[4]:4d}"
                            elif output == "raw":
                                value = f"{cv[0]:4d}\n{cv[1]:4d}\n{cv[2]:4d}\n{cv[3]:4d}\n{cv[4]:4d}"
                            elif output == "csv":
                                value = f"1: {cv[0]:4d}, 2: {cv[1]:4d}, 3: {cv[2]:4d}, 4: {cv[3]:4d}, 5: {cv[4]:4d}"
                else:
                    array_value = None
                    value = "------"
                
                if output == "label":
                    print(f"{i:3d} 0x{addr:04X} {length:2d} {type:>6} {label:<39} {value:<}")
                elif output == "raw":
                    print(value)
                elif output == "array":
                    array.append([i, array_value])
                elif output == "form":
                    array.append(value)
                elif output == "csv":
                    csv_data.append([i, f"0x{addr:04X}", length, type, label, value])
                
            if output == "csv":
                try:
                    if not os.access(os.path.dirname(csv_path) or '.', os.W_OK):
                        print(f"Error: No write permission for {csv_path}")
                        return
                    mode = 'a' if os.path.exists(csv_path) else 'w'
                    with open(csv_path, mode, newline='', encoding='utf-8') as file:
                        writer = csv.writer(file)
                        if mode == 'w':
                            writer.writerow(["Timestamp", formatted_time])
                            writer.writerow(["ID", "Address", "Length", "Type", "Label", "Value"])
                        else:
                            writer.writerow([])
                            writer.writerow(["Timestamp", formatted_time])
                        for row in csv_data[2:]:
                            writer.writerow(row)
                    print(f"Data appended to {csv_path}")
                except IOError as e:
                    print(f"Error writing CSV file: {e}")
                
            if output in ["array", "form"] and array:
                return array
                
            self.idle()
        except Exception as e:
            print(f"read_id: Failed with error: {e}")

    def plot_voltages(self):
        try:
            import matplotlib.pyplot as plt
            array = self.read_id(id_array=[12], output="array", retries=3)
            if not array or len(array) < 2 or not isinstance(array[1][1], list):
                print("Failed to read cell voltages")
                return
            voltages = array[1][1]
            plt.bar(range(1, 6), voltages, color='#1f77b4')
            plt.xlabel("Cell Number")
            plt.ylabel("Voltage (mV)")
            plt.title("Battery Cell Voltages")
            plt.axhline(y=sum(voltages)/len(voltages), color='r', linestyle='--', label='Average')
            plt.legend()
            plt.show()
        except ImportError:
            print("Install matplotlib: pip install matplotlib")
        except Exception as e:
            print(f"plot_voltages: Failed with error: {e}")

    def health(self, force_refresh=True, verbose=False, return_data=False):
        """
        Generate a health report with grouped, color-coded console output and CSV summary.
        # force_refresh - force a read of all registers
        # verbose - if True, print all 183 registers in console; if False, show summary only
        # return_data - if True, returnellett a dict with 'summary' and 'registers' instead of printing
        """
        reg_list = list(range(0, len(data_id)))  # Read all registers
        self.txrx_save_and_set(True)  # Enable debug for troubleshooting
        csv_data = []
        summary_data = [["Summary", "Timestamp", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")]]
        warnings = []
        
        try:
            print("Reading battery. This will take 10-20sec\n")
            array = self.read_id(reg_list, force_refresh, "array", retries=5)  # Increased to 5
            if not array or len(array) < len(reg_list) + 1:
                raise ValueError("Incomplete data from read_id")
            
            # Get serial number and manufacture date for CSV filename
            serial_number = None
            manufacture_date = None
            bat_type = "Unknown"
            bat_text = [0, "Unknown"]
            sn_index = next((i for i, x in enumerate(data_id) if x[0] == 0x0004), None)  # ID 2
            logger.debug(f" Battery Text Index: {sn_index}, Value: {array[sn_index + 1][1] if sn_index is not None else 'None'}")
            if sn_index is not None and isinstance(array[sn_index + 1][1], str):
                bat_text = array[sn_index + 1][1].split(', ')
                if len(bat_text) >= 2 and 'Type: ' in bat_text[0] and 'Serial: ' in bat_text[1]:
                    bat_type = bat_text[0].split('Type: ')[1].strip()
                    serial_number = bat_text[1].split('Serial: ')[1].strip()
                    bat_lookup = {
                        "37": [2, "2Ah CP (5s1p 18650)"], "40": [5, "5Ah XC (5s2p 18650)"], "165": [5, "5Ah XC (5s2p 18650)"],
                        "46": [6, "6Ah XC (5s2p 18650)"], "104": [3, "3Ah HO (5s1p 21700)"], "106": [4, "6Ah HO (5s2p 21700)"],
                        "107": [8, "8Ah HO (5s2p 21700)"], "108": [12, "12Ah HO (5s3p 21700)"],
                        "383": [12, "12Ah Forge (5s3p 21700 tabless)"], "384": [12, "12Ah Forge (5s3p 21700 tabless)"]
                    }
                    bat_text = bat_lookup.get(bat_type, [0, "Unknown"])
            logger.debug(f"E-Serial: {serial_number or 'None'}, Type: {bat_type}")
            date_index = next((i for i, x in enumerate(data_id) if x[0] == 0x0011), None)  # ID 4
            if date_index is not None and isinstance(array[date_index + 1][1], datetime.datetime):
                manufacture_date = array[date_index + 1][1].strftime('%Y_%m_%d')
            current_datetime = datetime.datetime.now().strftime('%Y-%m-%d_%I-%M%p').lower()
            csv_path = f"Milwaukee_Batt_M18_{serial_number or 'unknown'}_{current_datetime}.csv"
            
            # Process all registers for CSV
            csv_data.append(["ID", "Address", "Length", "Type", "Label", "Value"])
            for i, (reg_id, value) in enumerate(array[1:]):
                addr = data_id[reg_id][0]
                length = data_id[reg_id][1]
                type = data_id[reg_id][2]
                label = data_id[reg_id][3]
                if type == "date" and isinstance(value, datetime.datetime):
                    formatted_value = value.strftime('%Y-%m-%d %H:%M:%S')
                elif type == "cell_v" and isinstance(value, list):
                    formatted_value = f"1: {value[0]:4d}, 2: {value[1]:4d}, 3: {value[2]:4d}, 4: {value[3]:4d}, 5: {value[4]:4d}"
                elif type == "hhmmss" and isinstance(value, (int, str)):
                    formatted_value = str(value)
                elif type == "ascii" and isinstance(value, str):
                    formatted_value = f'"{value}"'
                elif type == "sn" and isinstance(value, str):
                    formatted_value = value
                elif isinstance(value, (int, float)):
                    formatted_value = str(value)
                else:
                    formatted_value = "------"
                csv_data.append([reg_id, f"0x{addr:04X}", length, type, label, formatted_value])
                if verbose:
                    print(f"{reg_id:3d} 0x{addr:04X} {length:2d} {type:>6} {label:<39} {formatted_value:<}")
            
            # Additional health metrics
            imbalance = 0
            cell_v_index = next((i for i, x in enumerate(data_id) if x[0] == 0x400A), None)  # ID 12
            logger.debug(f"Cell Voltage Index: {cell_v_index}, Value: {array[cell_v_index + 1][1] if cell_v_index is not None else 'None'}")
            if cell_v_index is not None and isinstance(array[cell_v_index + 1][1], list) and len(array[cell_v_index + 1][1]) == 5:
                imbalance = max(array[cell_v_index + 1][1]) - min(array[cell_v_index + 1][1])
                summary_data.append(["Summary", "Cell Imbalance (mV)", str(imbalance)])
                summary_data.append(["Summary", "Cell Voltages (mV)", ", ".join(map(str, array[cell_v_index + 1][1]))])
                summary_data.append(["Summary", "Pack Voltage", f"{sum(array[cell_v_index + 1][1])/1000:.2f} V"])
                if imbalance > 100:
                    warnings.append("High cell imbalance (>100 mV). Consider using a balancing charger.")
            else:
                logger.debug(f"Cell voltages invalid: {array[cell_v_index + 1][1] if cell_v_index is not None else 'None'}")
                summary_data.append(["Summary", "Cell Imbalance (mV)ibas", "------"])
                summary_data.append(["Summary", "Cell Voltages (mV)", "------"])
                summary_data.append(["Summary", "Pack Voltage", "------"])
            
            discharge_index = next((i for i, x in enumerate(data_id) if x[0] == 0x9012), None)  # ID 29
            logger.debug(f"Discharge Index: {discharge_index}, Value: {array[discharge_index + 1][1] if discharge_index is not None else 'None'}")
            total_discharge_cycles = 0
            soh = 0
            if discharge_index is not None and isinstance(array[discharge_index + 1][1], (int, float)):
                if bat_text[0] != 0:
                    total_discharge_cycles = array[discharge_index + 1][1] / 3600 / bat_text[0]
                    soh = max(0, 100 - (total_discharge_cycles / 500 * 100))
                    summary_data.append(["Summary", "Total Discharge (Ah)", f"{array[discharge_index + 1][1]/3600:.2f}"])
                    summary_data.append(["Summary", "Total Discharge Cycles", f"{total_discharge_cycles:.2f}"])
                    summary_data.append(["Summary", "Estimated SoH (%)", f"{soh:.1f}"])
                    logger.debug(f"Total Discharge (Ah): {array[discharge_index + 1][1]/3600:.2f}, Cycles: {total_discharge_cycles:.2f}, SoH: {soh:.1f}")
                    if soh < 50:
                        warnings.append("Low SoH (<50%). Battery may need replacement soon.")
            
            low_voltage_index = next((i for i, x in enumerate(data_id) if x[0] == 0x9030), None)  # ID 39
            low_voltage_event_index = next((i for i, x in enumerate(data_id) if x[0] == 0x9036), None)  # ID 42
            logger.debug(f"Low Voltage Index: {low_voltage_index}, Value: {array[low_voltage_index + 1][1] if low_voltage_index is not None else 'None'}")
            logger.debug(f"Low Voltage Event Index: {low_voltage_event_index}, Value: {array[low_voltage_event_index + 1][1] if low_voltage_event_index is not None else 'None'}")
            if low_voltage_index is not None and low_voltage_event_index is not None and (array[low_voltage_index + 1][1] or array[low_voltage_event_index + 1][1]):
                warnings.append("Avoid deep discharges to extend battery life.")
            
            tool_time_start = next((i for i, x in enumerate(data_id) if x[0] == 0x903A), None)
            tool_time_end = next((i for i, x in enumerate(data_id) if x[0] == 0x9060), None)
            tool_time_index = list(range(tool_time_start, tool_time_end + 1)) if tool_time_start is not None and tool_time_end is not None else []
            tool_time = sum(array[i + 1][1] for i in tool_time_index if isinstance(array[i + 1][1], (int, float))) if tool_time_index else 0
            logger.debug(f"Tool Time: {tool_time}")
            summary_data.append(["Summary", "Total Time on Tool (>10A)", str(datetime.timedelta(seconds=tool_time)) if tool_time else "------"])
            
            # Console output for summary
            if not return_data:
                print(f"{YELLOW}=== BASIC INFO ==={RESET}")
                print(f"Type: {bat_type} [{bat_text[1]}] {GREEN}✓{RESET}")
                summary_data.append(["Summary", "Type", f"{bat_type} [{bat_text[1]}]"])
                print(f"E-Serial: {serial_number or '------'}")
                summary_data.append(["Summary", "E-Serial", str(serial_number) if serial_number else "------"])
                if date_index is not None:
                    manufacture_date_str = array[date_index + 1][1].strftime('%Y-%m - %d') if isinstance(array[date_index + 1][1], datetime.datetime) else str(array[date_index + 1][1] or "------")
                    print(f"Manufacture Date: {manufacture_date_str}")
                    summary_data.append(["Summary", "Manufacture Date", manufacture_date_str])
                current_date_index = next((i for i, x in enumerate(data_id) if x[0] == 0x0037), None)  # ID 8
                logger.debug(f"Current Date Index: {current_date_index}, Value: {array[current_date_index + 1][1] if current_date_index is not None else 'None'}")
                if current_date_index is not None:
                    current_date_str = array[current_date_index + 1][1].strftime('%Y-%m-%d %H:%M:%S') if isinstance(array[current_date_index + 1][1], datetime.datetime) else str(array[current_date_index + 1][1] or "------")
                    print(f"Current Date: {current_date_str}")
                    summary_data.append(["Summary", "Current Date", current_date_str])
                days_index = next((i for i, x in enumerate(data_id) if x[0] == 0x9010), None)  # ID 28
                logger.debug(f"Days Index: {days_index}, Value: {array[days_index + 1][1] if days_index is not None else 'None'}")
                if days_index is not None:
                    days_since_first = array[days_index + 1][1] or "------"
                    print(f"Days Since First Charge: {days_since_first} days{' (New battery)' if isinstance(days_since_first, (int, float)) and days_since_first < 30 else ''}")
                    summary_data.append(["Summary", "Days Since First Charge", str(days_since_first)])
                
                print(f"\n{YELLOW}=== VOLTAGE & TEMPERATURE ==={RESET}")
                if cell_v_index is not None and isinstance(array[cell_v_index + 1][1], list) and len(array[cell_v_index + 1][1]) == 5:
                    print(f"Pack Voltage: {sum(array[cell_v_index + 1][1])/1000:.2f} V")
                    print(f"Cell Voltages (mV): {', '.join(map(str, array[cell_v_index + 1][1]))}")
                    print(f"Cell Imbalance: {imbalance} mV {GREEN if imbalance <= 100 else YELLOW}✓{RESET if imbalance <= 100 else '⚠ (Consider balancing charger)'}")
                else:
                    print(f"Pack Voltage: ------")
                    print(f"Cell Voltages (mV): ------")
                    print(f"Cell Imbalance: ------")
                
                temp_non_forge_index = next((i for i, x in enumerate(data_id) if x[0] == 0x4014), None)  # ID 13
                temp_forge_index = next((i for i, x in enumerate(data_id) if x[0] == 0x401F), None)  # ID 18
                logger.debug(f"Temp non-Forge Index: {temp_non_forge_index}, Value: {array[temp_non_forge_index + 1][1] if temp_non_forge_index is not None else 'None'}")
                logger.debug(f"Temp Forge Index: {temp_forge_index}, Value: {array[temp_forge_index + 1][1] if temp_forge_index is not None else 'None'}")
                temp_non_forge = array[temp_non_forge_index + 1][1] if temp_non_forge_index is not None and array[temp_non_forge_index + 1][1] is not None else "Not available"
                temp_forge = array[temp_forge_index + 1][1] if temp_forge_index is not None and array[temp_forge_index + 1][1] is not None else "Not available"
                print(f"Temperature (non-Forge): {temp_non_forge} °F" if temp_non_forge != "Not available" else "Not available")
                print(f" Temperature (Forge): {temp_forge} °F" if temp_forge != "Not available" else "Not available")
                summary_data.append(["Summary", "Temperature (non-Forge)", str(temp_non_forge) + " °F" if temp_non_forge != "Not available" else "Not available"])
                summary_data.append(["Summary", "Temperature (Forge)", str(temp_forge) + " °F" if temp_forge != "Not available" else "Not available"])
                
                print(f"\n{YELLOW}=== CHARGING STATS ==={RESET}")
                redlink_index = next((i for i, x in enumerate(data_id) if x[0] == 0x9020), None)  # ID 33
                dumb_index = next((i for i, x in enumerate(data_id) if x[0] == 0x901E), None)  # ID 32
                total_index = next((i for i, x in enumerate(data_id) if x[0] == 0x901A), None)  # ID 31
                logger.debug(f"Total Charge Index: {total_index}, Value: {array[total_index + 1][1] if total_index is not None else 'None'}")
                logger.debug(f"Redlink Index: {redlink_index}, Value: {array[redlink_index + 1][1] if redlink_index is not None else 'None'}")
                logger.debug(f"Dumb Index: {dumb_index}, Value: {array[dumb_index + 1][1] if dumb_index is not None else 'None'}")
                charge_count = "------"
                if redlink_index is not None and dumb_index is not None and total_index is not None and all(isinstance(array[x + 1][1], (int, float)) for x in [redlink_index, dumb_index, total_index]):
                    charge_count = f"{array[total_index + 1][1]} (Redlink: {array[redlink_index + 1][1]}, Dumb: {array[dumb_index + 1][1]})"
                    print(f"Total Charge Count: {charge_count}")
                summary_data.append(["Summary", "Total Charge Count", str(charge_count)])
                time_charge_index = next((i for i, x in enumerate(data_id) if x[0] == 0x9024), None)  # ID 35
                logger.debug(f"Time Charge Index: {time_charge_index}, Value: {array[time_charge_index + 1][1] if time_charge_index is not None else 'None'}")
                time_charge = array[time_charge_index + 1][1] if time_charge_index is not None and array[time_charge_index + 1][1] is not None else "------"
                print(f"Total Charge Time: {time_charge}")
                summary_data.append(["Summary", "Total Charge Time", str(time_charge)])
                time_idle_index = next((i for i, x in enumerate(data_id) if x[0] == 0x9028), None)  # ID 36
                logger.debug(f"Time Idle Index: {time_idle_index}, Value: {array[time_idle_index + 1][1] if time_idle_index is not None else 'None'}")
                time_idle = array[time_idle_index + 1][1] if time_idle_index is not None and array[time_idle_index + 1][1] is not None else "------"
                print(f"Time Idling on Charger: {time_idle} {YELLOW + '⚠ ( Remove after full charge)' if isinstance(time_idle, str) and int(time_idle.split(':')[0]) > 100 else ''}{RESET}")
                if isinstance(time_idle, str) and int(time_idle.split(':')[0]) > 100:
                    warnings.append("High idle time on charger. Remove after full charge.")
                summary_data.append(["Summary", "Time Idling on Charger", str(time_idle)])
                low_v_charge_index = next((i for i, x in enumerate(data_id) if x[0] == 0x902E), None)  # ID 38
                logger.debug(f"Low Voltage Charge Index: {low_v_charge_index}, Value: {array[low_v_charge_index + 1][1] if low_v_charge_index is not None else 'None'}")
                low_v_charge = array[low_v_charge_index + 1][1] if low_v_charge_index is not None and array[low_v_charge_index + 1][1] is not None else "------"
                print(f"Low-Voltage Charges: {low_v_charge} {GREEN + '✓' if low_v_charge == 0 else YELLOW + '⚠'}{RESET}")
                summary_data.append(["Summary", "Low-Voltage Charges", str(low_v_charge)])
                
                print(f"\n{YELLOW}=== TOOL USE STATS ==={RESET}")
                total_discharge = "------"
                if discharge_index is not None and isinstance(array[discharge_index + 1][1], (int, float)):
                    total_discharge = f"{array[discharge_index + 1][1]/3600:.2f} Ah"
                    print(f"Total Discharge: {total_discharge}")
                    print(f"Estimated Cycles: {total_discharge_cycles:.2f}")
                    print(f"SoH: {soh:.1f}% {GREEN if soh >= 50 else YELLOW}✓{RESET if soh >= 50 else '⚠ (Consider replacement)'}")
                summary_data.append(["Summary", "Total Discharge (Ah)", total_discharge])
                summary_data.append(["Summary", "Total Discharge Cycles", f"{total_discharge_cycles:.2f}"])
                summary_data.append(["Summary", "Estimated SoH (%)", f"{soh:.1f}"])
                low_voltage_value = array[low_voltage_index + 1][1] if low_voltage_index is not None else 0
                print(f"Discharge to Empty: {low_voltage_value or '------'} {YELLOW + '⚠ (Avoid deep discharges)' if low_voltage_value > 0 else ''}{RESET}")
                summary_data.append(["Summary", "Discharge to Empty", str(low_voltage_value or "------")])
                overheat_index = next((i for i, x in enumerate(data_id) if x[0] == 0x9032), None)  # ID 40
                overheat_value = array[overheat_index + 1][1] if overheat_index is not None else 0
                print(f"Overheat Events: {overheat_value or '------'} {GREEN + '✓' if overheat_value == 0 else YELLOW + '⚠'}{RESET}")
                summary_data.append(["Summary", "Overheat Events", str(overheat_value or "------")])
                low_voltage_event_value = array[low_voltage_event_index + 1][1] if low_voltage_event_index is not None else 0
                print(f"Low Voltage Events: {low_voltage_event_value or '------'} {YELLOW + '⚠' if low_voltage_event_value > 0 else ''}{RESET}")
                summary_data.append(["Summary", "Low Voltage Events", str(low_voltage_event_value or "------")])
                print(f"Total Time on Tool (>10A): {str(datetime.timedelta(seconds=tool_time)) if tool_time else '------'}")
                if tool_time:
                    for i, j in enumerate(tool_time_index):
                        amp_range = f"{i*10 + 10}-{(i+1)*10 + 10}A"
                        label = f"Time @ {amp_range:>8}:"
                        t = array[j + 1][1]
                        hhmmss = str(datetime.timedelta(seconds=t)) if isinstance(t, (int, float)) else "------"
                        pct = round((t / tool_time) * 100) if tool_time and isinstance(t, (int, float)) else 0
                        bar = "X" * pct
                        print(f"{label} {hhmmss} {pct:2d}% {bar}")
                    # Handle >200A
                    high_amp_index = next((k for k, x in enumerate(data_id) if x[0] == 0x90B0), None)  # 0x90B0 is @ 200A+
                    if high_amp_index is not None:
                        amp_range = ">200A"
                        label = f"Time @ {amp_range:>8}:"
                        t = array[high_amp_index + 1][1]
                        hhmmss = str(datetime.timedelta(seconds=t)) if isinstance(t, (int, float)) else "------"
                        pct = round((t / tool_time) * 100) if tool_time and isinstance(t, (int, float)) else 0
                        bar = "X" * pct
                        print(f"{label} {hhmmss} {pct:2d}% {bar}")
                
                if warnings:
                    print(f"\n{YELLOW}Warnings:{RESET}")
                    for w in warnings:
                        print(f" - {w}")
                    summary_data.append(["Summary", "Warnings", "; ".join(warnings)])
                
                try:
                    with open(csv_path, 'w', newline='', encoding='utf-8') as file:
                        writer = csv.writer(file)
                        for row in summary_data:
                            writer.writerow(row)
                        writer.writerow([])  # Separator
                        for row in csv_data:
                            writer.writerow(row)
                    print(f"Health data written to {csv_path}")
                except IOError as e:
                    print(f"Error writing CSV: {e}")
                
                if verbose:
                    print(f"\n{YELLOW}=== FULL REGISTER DATA ==={RESET}")
                else:
                    print(f"[Full 183 Registers Exported to CSV]")
            
            if return_data:
                # Convert datetime objects in registers to strings for JSON-safe export
                converted_registers = []
                for reg_id, value in array[1:]:
                    if isinstance(value, datetime.datetime):
                        value = value.strftime('%Y-%m-%d %H:%M:%S')
                    elif isinstance(value, list):
                        value = [str(v) for v in value]  # Convert lists to strings
                    converted_registers.append([reg_id, value])
                return {'summary': {row[1]: row[2] for row in summary_data[1:] if len(row) == 3}, 'registers': converted_registers, 'timestamp': summary_data[0][2]}
        except Exception as e:
            print(f"health: Failed with error: {e}")
            print("Check battery is connected and you have correct serial port")
            if return_data:
                return None
        finally:
            self.txrx_restore()
        if return_data:
            return None

    def export_to_dashboard(self, dashboard_url='http://172.25.47.113:5002/data'):
        """
        Export raw battery data to the dashboard running in a Docker container.
        Performs a connectivity test before sending data.
        """
        try:
            from urllib.parse import urlparse
            parsed_url = urlparse(dashboard_url)
            host = parsed_url.hostname
            port = parsed_url.port or 5002

            print(f"Testing connection to {host}:{port}...")
            try:
                socket.gethostbyname(host)
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(5)
                s.connect((host, port))
                s.close()
                print(f"Connection to {host}:{port} successful!")
            except Exception as e:
                print(f"Connection test failed: {e}")
                print("Check network/firewall between host and Docker.")
                return

            print("Reading battery data for export...")
            data = self.health(return_data=True, force_refresh=True, verbose=False)
            if not data:
                print("Failed to read battery data. Check battery connection, serial port, and increase retries in health() if needed.")
                return
            print(f"Data read successfully: {data}")  # Debug print

            print(f"Sending data to {dashboard_url}...")
            for attempt in range(3):
                try:
                    response = requests.post(dashboard_url, json=data, timeout=10)
                    print(f"Response status: {response.status_code}, Content: {response.text}")
                    if response.status_code == 200:
                        print("Data exported successfully!")
                        return
                    else:
                        print(f"Failed. Status code: {response.status_code}")
                except requests.RequestException as e:
                    print(f"Attempt {attempt+1}/3 failed: {e}")
                    time.sleep(2)
            print("All attempts failed. Test the endpoint with curl.")
        except Exception as e:
            print(f"Export failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="M18 Battery Diagnostics")
    parser.add_argument("--port", type=str, help="Serial port (e.g., COM7)")
    args = parser.parse_args()
    m = M18(args.port)
    print("\nMenu:")
    print("1. Health report (with CSV)")
    print("2. Read all registers (CSV)")
    print("3. Plot cell voltages")
    print("4. Write message to 0x0023")
    print("5. Submit form")
    print("6. Export to dashboard")
    print("7. Exit")
    while True:
        choice = input("Choose an option (1-7): ").strip()
        if choice == '1':
            m.health(force_refresh=True, verbose=False)
        elif choice == '2':
            csv_path = input("Enter CSV path (default: all_registers.csv): ") or 'all_registers.csv'
            m.read_id(output="csv", csv_path=csv_path)
        elif choice == '3':
            m.plot_voltages()
        elif choice == '4':
            message = input("Enter message (max 20 chars): ")
            m.write_message(message)
        elif choice == '5':
            array = m.read_id(output="form")
            if array:
                print("Form submitted with data:")
                print(array)
            else:
                print("Failed to read data for form.")
        elif choice == '6':
            dashboard_url = input("Enter dashboard URL (default: http://172.25.47.113:5002/data): ") or 'http://172.25.47.113:5002/data'
            m.export_to_dashboard(dashboard_url)
        elif choice == '7':
            print("Exiting...")
            break
        else:
            print("Invalid choice. Try again.")
# Line 1004
