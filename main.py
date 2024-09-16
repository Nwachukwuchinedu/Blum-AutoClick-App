import os
import mss
import time
import requests
import random
import uuid
import sys 
import math
import keyboard
import cv2
import numpy as np
import pygetwindow as gw
import win32api
import win32con
import warnings
import tkinter as tk
from tkinter import messagebox, simpledialog
from tkinter import ttk
from pywinauto import Application
import threading

CHECK_INTERVAL = 5

warnings.filterwarnings("ignore", category=UserWarning, module='pywinauto')

def list_windows_by_title(title_keywords):
    windows = gw.getAllWindows()
    filtered_windows = []
    for window in windows:
        for keyword in title_keywords:
            if keyword.lower() in window.title.lower():
                filtered_windows.append((window.title, window._hWnd))
                break
    return filtered_windows

class Logger:
    def __init__(self, prefix=None, text_widget=None):
        self.prefix = prefix
        self.text_widget = text_widget

    def log(self, data: str):
        if self.prefix:
            message = f"{self.prefix} {data}"
        else:
            message = data

        if self.text_widget:
            self.text_widget.insert(tk.END, message + "\n")
            self.text_widget.yview(tk.END)  # Auto-scroll to the end
        else:
            print(message)

def resource_path(relative_path):
        #Get the absolute path to the resource, works for dev and PyInstaller.
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_path, relative_path)

class AutoClicker:
    def __init__(self, hwnd, target_colors_hex, nearby_colors_hex, threshold, logger, target_percentage, collect_freeze):
        self.hwnd = hwnd
        self.target_colors_hex = target_colors_hex
        self.nearby_colors_hex = nearby_colors_hex
        self.threshold = threshold
        self.logger = logger
        self.target_percentage = target_percentage
        self.collect_freeze = collect_freeze
        self.running = False
        self.clicked_points = []
        self.iteration_count = 0
        self.last_check_time = time.time()
        self.last_freeze_check_time = time.time()
        self.freeze_cooldown_time = 0

    @staticmethod
    def hex_to_hsv(hex_color):
        hex_color = hex_color.lstrip('#')
        h_len = len(hex_color)
        rgb = tuple(int(hex_color[i:i + h_len // 3], 16) for i in range(0, h_len, h_len // 3))
        rgb_normalized = np.array([[rgb]], dtype=np.uint8)
        hsv = cv2.cvtColor(rgb_normalized, cv2.COLOR_RGB2HSV)
        return hsv[0][0]

    @staticmethod
    def click_at(x, y):
        try:
            if not (0 <= x < win32api.GetSystemMetrics(0) and 0 <= y < win32api.GetSystemMetrics(1)):
                raise ValueError(f"Off-screen coordinates: ({x}, {y})")
            win32api.SetCursorPos((x, y))
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, x, y, 0, 0)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, x, y, 0, 0)
        except Exception as e:
            print(f"Error setting cursor position: {e}")

    def start_clicker(self):
        self.running = True
        self.logger.log("Auto-clicker started.")

    def stop_clicker(self):
        self.running = False
        self.logger.log("Auto-clicker stopped.")

    def is_near_color(self, hsv_img, center, target_hsvs, radius=8):
        x, y = center
        height, width = hsv_img.shape[:2]
        for i in range(max(0, x - radius), min(width, x + radius + 1)):
            for j in range(max(0, y - radius), min(height, y + radius + 1)):
                distance = math.sqrt((x - i) ** 2 + (y - j) ** 2)
                if distance <= radius:
                    pixel_hsv = hsv_img[j, i]
                    for target_hsv in target_hsvs:
                        if np.allclose(pixel_hsv, target_hsv, atol=[1, 50, 50]):
                            return True
        return False

    def check_and_click_play_button(self, sct, monitor):
        current_time = time.time()
        if current_time - self.last_check_time >= CHECK_INTERVAL:
            self.last_check_time = current_time
            templates = [
                cv2.imread(resource_path(os.path.join("template_png", "template_play_button.png")), cv2.IMREAD_GRAYSCALE),
                cv2.imread(resource_path(os.path.join("template_png", "template_play_button1.png")), cv2.IMREAD_GRAYSCALE),
                cv2.imread(resource_path(os.path.join("template_png", "close_button.png")), cv2.IMREAD_GRAYSCALE),
                cv2.imread(resource_path(os.path.join("template_png", "captcha.png")), cv2.IMREAD_GRAYSCALE)
            ]

            for template in templates:
                if template is None:
                    self.logger.log("Unable to load template file.")
                    continue

                template_height, template_width = template.shape

                img = np.array(sct.grab(monitor))
                img_gray = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)

                res = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
                loc = np.where(res >= self.threshold)

                matched_points = list(zip(*loc[::-1]))

                if matched_points:
                    pt_x, pt_y = matched_points[0]
                    cX = pt_x + template_width // 2 + monitor["left"]
                    cY = pt_y + template_height // 2 + monitor["top"]

                    self.click_at(cX, cY)
                    self.logger.log(f'Button pressed: {cX} {cY}')
                    self.clicked_points.append((cX, cY))
                    break 

    def click_color_areas(self):
        app = Application().connect(handle=self.hwnd)
        window = app.window(handle=self.hwnd)
        window.set_focus()

        target_hsvs = [self.hex_to_hsv(color) for color in self.target_colors_hex]
        nearby_hsvs = [self.hex_to_hsv(color) for color in self.nearby_colors_hex]

        with mss.mss() as sct:
            while True:
                if self.running:
                    rect = window.rectangle()
                    monitor = {
                        "top": rect.top,
                        "left": rect.left,
                        "width": rect.width(),
                        "height": rect.height()
                    }
                    img = np.array(sct.grab(monitor))
                    img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

                    for target_hsv in target_hsvs:
                        lower_bound = np.array([max(0, target_hsv[0] - 1), 30, 30])
                        upper_bound = np.array([min(179, target_hsv[0] + 1), 255, 255])
                        mask = cv2.inRange(hsv, lower_bound, upper_bound)
                        contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

                        num_contours = len(contours)
                        num_to_click = int(num_contours * self.target_percentage)
                        contours_to_click = random.sample(contours, num_to_click)

                        for contour in reversed(contours_to_click):
                            if cv2.contourArea(contour) < 6:
                                continue

                            M = cv2.moments(contour)
                            if M["m00"] == 0:
                                continue
                            cX = int(M["m10"] / M["m00"]) + monitor["left"]
                            cY = int(M["m01"] / M["m00"]) + monitor["top"]

                            if not self.is_near_color(hsv, (cX - monitor["left"], cY - monitor["top"]), nearby_hsvs):
                                continue

                            if any(math.sqrt((cX - px) ** 2 + (cY - py) ** 2) < 35 for px, py in self.clicked_points):
                                continue
                            cY += 5
                            self.click_at(cX, cY)
                            self.logger.log(f'Clicked: {cX} {cY}')
                            self.clicked_points.append((cX, cY))

                    if self.collect_freeze:
                        self.check_and_click_freeze_button(sct, monitor)
                    self.check_and_click_play_button(sct, monitor)
                    time.sleep(0.1)
                    self.iteration_count += 1
                    if self.iteration_count >= 5:
                        self.clicked_points.clear()
                        self.iteration_count = 0

    def check_and_click_freeze_button(self, sct, monitor):
        freeze_colors_hex = ["#82dce9", "#55ccdc"] 
        freeze_hsvs = [self.hex_to_hsv(color) for color in freeze_colors_hex]
        current_time = time.time()
        if current_time - self.last_freeze_check_time >= 1 and current_time >= self.freeze_cooldown_time:
            self.last_freeze_check_time = current_time
            img = np.array(sct.grab(monitor))
            img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
            for freeze_hsv in freeze_hsvs:
                lower_bound = np.array([max(0, freeze_hsv[0] - 1), 30, 30])
                upper_bound = np.array([min(179, freeze_hsv[0] + 1), 255, 255])
                mask = cv2.inRange(hsv, lower_bound, upper_bound)
                contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
                if contours:
                    contour = contours[0]
                    if cv2.contourArea(contour) >= 6:
                        M = cv2.moments(contour)
                        if M["m00"] != 0:
                            cX = int(M["m10"] / M["m00"]) + monitor["left"]
                            cY = int(M["m01"] / M["m00"]) + monitor["top"]
                            self.click_at(cX, cY)
                            self.logger.log(f'Clicked Freeze Button: {cX} {cY}')
                            self.freeze_cooldown_time = current_time + 5
                            break

def run_auto_clicker(target_percentage, collect_freeze, text_widget):
    title_keywords = ["Blum", "Telegram"]
    windows = list_windows_by_title(title_keywords)

    if not windows:
        print("No suitable windows found.")
        return

    print("Available windows to choose from: ")
    for i, (title, _) in enumerate(windows):
        print(f"{i + 1}: {title}")

    choice = int(simpledialog.askstring("Input", "Enter the window number where the Blum bot opens: ")) - 1
    if choice < 0 or choice >= len(windows):
        print("Wrong choice.")
        return

    hwnd = windows[choice][1]

    logger_instance = Logger("[BlumAutoClicker]", text_widget)
    logger_instance.log("Welcome to Auto Click for Blum")
    logger_instance.log('Press Start to begin the auto-clicker')

    target_colors_hex = ["#c9e100", "#bae70e"]
    nearby_colors_hex = ["#abff61", "#87ff27"]
    threshold = 0.8

    auto_clicker_instance = AutoClicker(
        hwnd, target_colors_hex, nearby_colors_hex, threshold, logger_instance, target_percentage, collect_freeze
    )

    # Run auto-clicker on a separate thread
    def start_clicker():
        auto_clicker_instance.start_clicker()
        auto_clicker_instance.click_color_areas()

    # Start and Stop buttons for GUI control
    def on_start():
        threading.Thread(target=start_clicker).start()

    def on_stop():
        auto_clicker_instance.stop_clicker()

    return on_start, on_stop

import os
import requests
import tkinter as tk
from tkinter import messagebox, simpledialog
import sys
import socket

# File to store the verified key locally
KEY_FILE = 'activation_key.txt'

# Declare root as a global variable
root = None

# Function to check if the key is already verified
def check_stored_key():
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, 'r') as file:
            key = file.read().strip()
        return key
    return None

# Function to store the verified key locally
def store_verified_key(key):
    with open(KEY_FILE, 'w') as file:
        file.write(key)

# Function to get the IP address of the device
def get_ip_address():
    try:
        # Get the hostname of the machine
        hostname = socket.gethostname()
        # Get the IP address corresponding to the hostname
        ip_address = socket.gethostbyname(hostname)
        return ip_address
    except socket.error as e:
        messagebox.showerror("Error", f"Failed to get IP address: {e}")
        return None

# Function to get the device_id from the server (in this case, using IP address)
def get_device_id_from_server(key):
    ip_address = get_ip_address()
    if not ip_address:
        return None

    try:
        response = requests.get(f'https://blum-auto-clicker.onrender.com/get-device-id/{key}')
        if response.status_code == 200:
            data = response.json()
            if data.get('used'):
                messagebox.showerror("Error", "This activation key has already been used!")
                return None
            return data.get('device_id')
        elif response.status_code == 404:
            messagebox.showerror("Error", "Key not found in server database!")
        else:
            messagebox.showerror("Error", "Error retrieving device ID!")
    except requests.exceptions.RequestException as e:
        messagebox.showerror("Error", f"Failed to connect to server: {e}")
    return None

def verify_activation_key():
    key = entry_key.get()  # Assuming you're retrieving the key from an input field

    if not key:
        messagebox.showerror("Error", "Please enter a valid activation key")
        return

    device_id = get_device_id_from_server(key)
    if not device_id:
        return

    try:
        # Send the key and device_id (IP address) to the Express server for validation
        ip_address = get_ip_address()
        if not ip_address:
            return

        response = requests.post('https://blum-auto-clicker.onrender.com/validate-key', json={'key': key, 'device_id': device_id, 'ip_address': ip_address})

        # Check the response from the server
        if response.status_code == 200:
            messagebox.showinfo("Success", "Key validated successfully! Redirecting...")
            store_verified_key(key)
            open_main_interface()
        elif response.status_code == 404:
            messagebox.showerror("Error", "Invalid activation key!")
        elif response.status_code == 400:
            messagebox.showerror("Error", response.json().get('message', 'Unknown error'))
        else:
            messagebox.showerror("Error", "Unknown error occurred!")
    except requests.exceptions.RequestException as e:
        messagebox.showerror("Error", f"Failed to connect to server: {e}")

# Function to open the main interface (Blum Auto Clicker)
def open_main_interface():
    global root
    if root is not None:
        root.destroy()  # Close the activation window
    main()  # Call the Blum Auto Clicker main interface

# Blum Auto Clicker Main Interface
def main():
    global root
    root = tk.Tk()
    root.title("Blum Auto Clicker")
    root.configure(bg="white")

    root.geometry("400x500")  # Increased height for log display

    # Define the GUI layout
    title_label = tk.Label(root, text="Auto Clicker for Blum", font=("Montserrat", 16, "bold"), bg="white")
    title_label.pack(pady=10)

    target_percentage = simpledialog.askfloat("Input", "Enter Target Percentage (0-1):", minvalue=0.0, maxvalue=1.0)
    if target_percentage is None:
        messagebox.showinfo("Cancelled", "Operation cancelled.")
        return

    collect_freeze = messagebox.askyesno("Input", "Collect Freeze?")

    # Create a Text widget for logs
    log_text = tk.Text(root, height=15, width=50, wrap=tk.WORD)
    log_text.pack(pady=10)

    # Create and start the auto-clicker
    on_start, on_stop = run_auto_clicker(target_percentage, collect_freeze, log_text)

    # Start button with black background and white text
    start_button = tk.Button(root, text="Start", command=on_start, bg="black", fg="white", font=("Montserrat", 12), borderwidth=0, relief="flat")
    start_button.pack(pady=5)

    # Stop button with black background and white text
    stop_button = tk.Button(root, text="Stop", command=on_stop, bg="black", fg="white", font=("Montserrat", 12), borderwidth=0, relief="flat")
    stop_button.pack(pady=5)

    # Key press handling using keyboard library
    def handle_key_presses():
        keyboard.add_hotkey('s', on_start)
        keyboard.add_hotkey('e', on_stop)
        log_text.insert(tk.END, "Press 'S' to start and 'E' to stop the auto-clicker.\n")
        log_text.yview(tk.END)  # Auto-scroll to the end

    handle_key_presses()

    root.mainloop()

# Placeholder for auto-clicker logic

# Function to prompt for key verification if no key is stored
def prompt_for_key_verification():
    global root, entry_key

    root = tk.Tk()
    root.title("Blum Auto Clicker - Activation")

    # Create label and entry for activation key
    label = tk.Label(root, text="Enter Activation Key:")
    label.pack(pady=10)

    entry_key = tk.Entry(root, width=30)
    entry_key.pack(pady=10)

    # Create a button to verify the key
    btn_verify = tk.Button(root, text="Verify Key", command=verify_activation_key)
    btn_verify.pack(pady=20)

    # Add a "Quit" button to allow the user to exit without verifying
    btn_quit = tk.Button(root, text="Quit", command=sys.exit)  # Ensure that clicking quit terminates the program
    btn_quit.pack(pady=5)

    root.geometry("300x200")

    # Bind the close window event to ensure app closes completely when "X" is clicked
    root.protocol("WM_DELETE_WINDOW", sys.exit)

    root.mainloop()

# Check for a stored key on startup
stored_key = check_stored_key()

if stored_key:
    # Retrieve device_id from the server using the stored key
    device_id = get_device_id_from_server(stored_key)
    if device_id:
        try:
            ip_address = get_ip_address()
            if not ip_address:
                raise ValueError("Failed to get IP address")

            response = requests.post('https://blum-auto-clicker.onrender.com/validate-key', json={'key': stored_key, 'device_id': device_id, 'ip_address': ip_address})
            if response.status_code == 200:
                print("Key is valid. Opening Blum Auto Clicker...")
                open_main_interface()
            else:
                print("Stored key is not valid or has expired. Please re-enter the key.")
                prompt_for_key_verification()
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Error", f"Failed to connect to server: {e}")
            prompt_for_key_verification()
    else:
        prompt_for_key_verification()
else:
    prompt_for_key_verification()
