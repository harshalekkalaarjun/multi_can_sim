import tkinter as tk
from tkinter import ttk, messagebox
import can
import threading
import time
import psutil  # For monitoring memory usage
from memory_profiler import profile  # For memory profiling

# version : 1.0.1


class PeriodicTask:
    def __init__(self, bus, can_id, data, is_extended, cycle_time, log_lock, task_lock):
        self.bus = bus
        self.can_id = can_id
        self.data = data
        self.is_extended = is_extended
        self.cycle_time = cycle_time
        self.running = True
        self.log_lock = log_lock
        self.task_lock = task_lock
        self.thread = None  # Thread will be created when needed
        self._stop_event = threading.Event()

    def start(self):
        # Start the thread if it's not running
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._run)
            self.thread.daemon = True
            self.thread.start()

    def _run(self):
        while self.running:
            if self.bus is None:
                print("CAN bus is not initialized!")
                time.sleep(1)
                return

            # Lock the CAN bus to ensure thread-safe access
            with self.task_lock:
                message = can.Message(
                    arbitration_id=self.can_id,
                    data=self.data,
                    is_extended_id=self.is_extended,
                )
                try:
                    self.bus.send(message)
                except can.CanError as e:
                    print(f"CAN transmission error: {e}")
                except Exception as e:
                    print(f"Unexpected error during CAN transmission: {e}")

            if self._stop_event.wait(self.cycle_time):  # Wait with timeout
                break

    def stop(self):
        self.running = False
        self._stop_event.set()  # Wake up the thread if sleeping
        if self.thread is not None:
            self.thread.join()  # Wait for the thread to finish


class CyclicScheduler:
    def __init__(self):
        self.tasks = []

    def add_task(self, task_function, cycle_time):
        self.tasks.append((task_function, cycle_time))

    def stop(self):
        self.tasks.clear()
        


    def remove_task(self, task):
        with self.lock:
            if task in self.tasks:
                self.tasks.remove(task)

class MultiCanTransmitterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Multi-CAN Transmitter")
        
        # CAN bus setup
        self.bus = None
        self.periodic_tasks = []
        self.scheduler = CyclicScheduler()

        # Locks for thread safety
        self.log_lock = threading.Lock()  # Lock for the log
        self.task_lock = threading.Lock()  # Lock for CAN bus access


        # Initialize available devices
        self.available_devices = self.get_available_devices()
        self.available_hardware = self.get_available_harsware()

        # Create widgets
        self.create_widgets()

        # Handle window closing event
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        # CAN Message Table
        self.message_table = ttk.Treeview(self.root, columns=("CAN-ID", "Data", "Cycle Time", "ID Type"), show="headings")
        self.message_table.heading("CAN-ID", text="CAN-ID (Hex)")
        self.message_table.heading("Data", text="Data (8 Bytes)")
        self.message_table.heading("Cycle Time", text="Cycle Time (ms)")
        self.message_table.heading("ID Type", text="ID Type")
        self.message_table.grid(row=0, column=0, columnspan=3, padx=10, pady=10, sticky="nsew")

        # Add/Edit Section
        ttk.Label(self.root, text="CAN-ID (Hex):").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.can_id_entry = ttk.Entry(self.root)
        self.can_id_entry.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(self.root, text="Data (8 Bytes):").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        self.data_entry = ttk.Entry(self.root)
        self.data_entry.grid(row=2, column=1, padx=5, pady=5)

        ttk.Label(self.root, text="Cycle Time (ms):").grid(row=3, column=0, padx=5, pady=5, sticky="e")
        self.cycle_time_entry = ttk.Entry(self.root)
        self.cycle_time_entry.grid(row=3, column=1, padx=5, pady=5)

        ttk.Label(self.root, text="ID Type:").grid(row=4, column=0, padx=5, pady=5, sticky="e")
        self.id_type_combobox = ttk.Combobox(self.root, values=["Standard", "Extended"], state="readonly")
        self.id_type_combobox.grid(row=4, column=1, padx=5, pady=5)
        self.id_type_combobox.set("Standard")  # Default to Standard

        ttk.Label(self.root, text="CAN Channel:").grid(row=5, column=0, padx=5, pady=5, sticky="e")
        self.channel_combobox = ttk.Combobox(self.root, values=self.available_devices, state="readonly")
        self.channel_combobox.grid(row=5, column=1, padx=5, pady=5)
        if self.available_devices:
            self.channel_combobox.set(self.available_devices[0])  # Default to the first device

        ttk.Label(self.root, text="CAN Hardware:").grid(row=7, column=0, padx=5, pady=5, sticky="e")
        self.hard_combobox = ttk.Combobox(self.root, values=self.available_hardware, state="readonly")
        self.hard_combobox.grid(row=7, column=1, padx=5, pady=5)
        if self.available_hardware:
            self.hard_combobox.set(self.available_hardware[0])

        ttk.Button(self.root, text="Add Message", command=self.add_message).grid(row=6, column=0, padx=5, pady=5)
        ttk.Button(self.root, text="Remove Message", command=self.remove_message).grid(row=10, column=1, padx=5, pady=5)
        ttk.Button(self.root, text="Rest", command=self.reset).grid(row=10, column=2, padx=5, pady=5)
        # Bitrate Selection
        ttk.Label(self.root, text="Bitrate:").grid(row=6, column=0, padx=5, pady=5, sticky="e")
        self.bitrate_combobox = ttk.Combobox(
            self.root,
            values=["125000", "250000", "500000", "1000000"],  # Common CAN bitrates
            state="readonly"
        )
        self.bitrate_combobox.grid(row=6, column=1, padx=5, pady=5)
        self.bitrate_combobox.set("250000")  # Default to 250000

        # Transmission Buttons
        self.start_button = ttk.Button(self.root, text="Start Cyclic Transmission", command=self.start_cyclic)
        self.start_button.grid(row=7, column=0, padx=10, pady=10)

        self.stop_button = ttk.Button(self.root, text="Stop Transmission", command=self.stop_cyclic, state="disabled")
        self.stop_button.grid(row=10, column=0, padx=10, pady=10)

        # Log Area
        log_frame = ttk.LabelFrame(self.root, text="Log")
        log_frame.grid(row=8, column=0, columnspan=3, padx=10, pady=10, sticky="nsew")
        self.log_text = tk.Text(log_frame, wrap="word", height=10)
        self.log_text.pack(fill="both", expand=True)

    def log(self, message):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        self.root.after(0, lambda: self._append_log(f"{timestamp} - {message}"))

    def _append_log(self, message, max_lines=1000):
        self.log_text.insert("end", f"{message}\n")
        if len(self.log_text.get("1.0", "end-1c").splitlines()) > max_lines:
            self.log_text.delete("1.0", "2.0")  # Remove first line to keep it small
        self.log_text.see("end")

    def get_available_harsware(self):
        hardware = []
        interfaces = can.interface.detect_available_configs()  
        for interface in interfaces:
            try:
                if isinstance(interface, dict):  
                    interface_name = interface.get('interface', '')
                    if isinstance(interface_name, list):
                        for face in interface_name:
                            hardware.append(face)
                    else:
                        hardware.append(interface_name)
            except Exception as e:
                self.log(f"Error detecting devices: {e}")
        if not hardware:
            hardware = ["Manual Input "]
            self.log("No CAN devices detected. Provide manual input.")
        
        return hardware




    def get_available_devices(self):
        devices = []
        interfaces = can.interface.detect_available_configs()
        for interface in interfaces:
            try:
                if isinstance(interface, dict):
                    channel = interface.get('channel', '')
                    print(f"Detected interface with channel: {channel}")
                    if isinstance(channel, list):  
                        for ch in channel:
                            devices.append(ch)
                    else:
                        devices.append(channel)
                else:
                    devices.append("Unknown Device")
            except Exception as e:
                self.log(f"Error detecting devices: {e}")
        if not devices:
            devices = ["Manual Input (Set Channel)"]
            self.log("No CAN devices detected. Provide manual input.")
        return devices




    def setup_can_bus(self):
        if self.bus is not None:
            # Bus is already initialized, no need to initialize again
            return True

        try:
            channel = self.channel_combobox.get()
            if channel == "Manual Input (Set Channel)":
                channel = self.manual_channel_entry.get()  # Add a field for manual input
            if not channel:
                raise ValueError("Please select or enter a valid CAN channel.")
            
            # Retrieve the user-specified bitrate
            bitrate = int(self.bitrate_combobox.get())
            
            face = self.hard_combobox.get()
            
            # Initialize the CAN bus with the specified channel and bitrate
            self.bus = can.interface.Bus(channel=channel, interface=face, bitrate=bitrate)
            print(f"CAN bus initialized on {channel} with bitrate {bitrate}.")
            self.log(f"CAN bus initialized on {channel} with bitrate {bitrate}.")
        except ValueError as ve:
            self.log(f"Error: {ve}")
            messagebox.showwarning("Input Error", str(ve))
            return False
        except can.CanError as e:
            self.log(f"Error initializing CAN bus: {e}")
            messagebox.showerror("Error", f"Failed to initialize CAN bus: {e}")
            return False
        except Exception as e:
            self.log(f"Unexpected error: {e}")
            messagebox.showerror("Error", f"Unexpected error: {e}")
            return False

        return True


    def add_message(self):
        try:
            # Get inputs from the UI
            can_id = int(self.can_id_entry.get(), 16)
            data = [int(x, 16) for x in self.data_entry.get().split()]
            cycle_time = float(self.cycle_time_entry.get()) / 1000  # Convert to seconds
            is_extended = self.id_type_combobox.get() == "Extended"
            self.log(f"Added message with ID: {can_id} Cycle Time: {cycle_time * 1000}ms")

            # Check if the task for this CAN ID already exists
            existing_task = None
            for task in self.periodic_tasks:
                if task.can_id == can_id:
                    existing_task = task
                    break

            if existing_task:
                # Task already exists, update it (or restart if needed)
                existing_task.data = data
                existing_task.cycle_time = cycle_time
                existing_task.is_extended = is_extended
                self.log(f"Updated existing task for CAN-ID: {can_id}")
            else:
                # Create a new task and start its thread
                task = PeriodicTask(self.bus, can_id, data, is_extended, cycle_time, self.log_lock, self.task_lock)
                task.start()  # Start the thread when a new task is created
                self.periodic_tasks.append(task)
                self.log(f"Started new task for CAN-ID: {can_id}")

            # Add to table (or update if exists)
            self.message_table.insert("", "end", values=(hex(can_id), ' '.join(map(hex, data)), str(cycle_time * 1000), self.id_type_combobox.get()))

        except Exception as e:
            self.log(f"Error adding message: {e}")
            messagebox.showerror("Error", f"Failed to add message: {e}")

    def remove_message(self):
        selected_items = self.message_table.selection()  # Support for multiple selection

        if not selected_items:
            messagebox.showwarning("Warning", "No message selected for removal.")
            return

        for selected_item in selected_items:
            # Get the CAN-ID from the selected row
            try:
                can_id, data, cycle_time, id_type = self.message_table.item(selected_item, "values")
                can_id_int = int(can_id, 16)  # Convert CAN-ID from hex to integer

                # Find the corresponding task in the periodic_tasks list
                task_to_remove = None
                for task in self.periodic_tasks:
                    if task.can_id == can_id_int:
                        task_to_remove = task
                        break

                if task_to_remove:
                    # Stop the associated thread
                    task_to_remove.stop()
                    self.periodic_tasks.remove(task_to_remove)
                    self.log(f"Stopped and removed task for CAN-ID: {hex(can_id_int)}")
                else:
                    self.log(f"No task found for CAN-ID: {hex(can_id_int)}")

                # Remove the message from the table
                self.message_table.delete(selected_item)
                self.log(f"Removed message with CAN-ID: {hex(can_id_int)}")
            except Exception as e:
                self.log(f"Error removing message: {e}")

        # Update buttons if no tasks remain
        if not self.periodic_tasks:
            self.stop_button.config(state="disabled")

            
    def start_cyclic(self):
        if self.bus is None:  # Check if the bus is not initialized
            self.log("CAN bus is not initialized! Attempting to initialize...")
            if not self.setup_can_bus():  # Try to initialize CAN bus
                self.log("Failed to initialize CAN bus. Cyclic transmission aborted.")
                return
        self.periodic_tasks = []
        for item in self.message_table.get_children():
            can_id, data, cycle_time, id_type = self.message_table.item(item, "values")
            try:
                # Convert CAN-ID and Data
                can_id_int = int(can_id, 16)
                data_list = [int(x, 16) for x in data.split()]

                # Convert Cycle Time (allow it to be a float if it has a decimal point)
                cycle_time_float = float(cycle_time)  # Allow decimal values
                cycle_time_int = int(cycle_time_float)  # Convert to int for use in periodic task timing

                is_extended = (id_type == "Extended")

                # Create and start the periodic task, passing log_lock and task_lock
                task = PeriodicTask(
                    bus=self.bus,
                    can_id=can_id_int,
                    data=data_list,
                    is_extended=is_extended,
                    cycle_time=cycle_time_float / 1000,  # Convert to seconds
                    log_lock=self.log_lock,  # Pass the log_lock
                    task_lock=self.task_lock  # Pass the task_lock
                )
                task.start()  # Start the cyclic task
                self.periodic_tasks.append(task)
                self.log(f"Started cyclic transmission for CAN-ID={can_id} every {cycle_time_int}ms.")
            except Exception as e:
                self.log(f"Error during cyclic transmission for CAN-ID={can_id}: {e}")
        self.start_button["state"] = "disabled"
        self.stop_button["state"] = "normal"


    def stop_cyclic(self):
        for task in self.periodic_tasks:
            task.stop()
        self.periodic_tasks.clear()
        self.log("Cyclic transmission stopped.")
        self.start_button.config(state="normal")
        self.stop_button.config(state="disabled")



    def reset(self):
        # Step 1: Stop all running threads (periodic tasks)
        for task in self.periodic_tasks:
            task.stop()  # This will signal each task's thread to stop and wait for it to finish
        self.periodic_tasks.clear()  # Clear the list of tasks
        
        # Step 2: Reset the CAN bus if needed (optional, depending on how you manage the CAN bus)
        if self.bus is not None:
            self.bus.shutdown()  # Properly shutdown the CAN bus if it was initialized
            self.bus = None
            self.log("CAN bus reset.")

        # Step 3: Clear the message table in the GUI
        self.message_table.delete(*self.message_table.get_children())
        self.log("Message table cleared.")

        # Step 4: Reset other states if needed (e.g., reset buttons, etc.)
        self.start_button.config(state="normal")  # Enable the "Start Cyclic" button
        self.stop_button.config(state="disabled")  # Disable the "Stop Cyclic" button

        self.log("Application reset.")

        
    def on_closing(self):
        self.log("Exiting application...")
        for task in self.periodic_tasks:
            task.stop()
        self.root.quit()

if __name__ == "__main__":
    root = tk.Tk()
    app = MultiCanTransmitterApp(root)
    root.mainloop()
