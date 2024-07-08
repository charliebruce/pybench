# Battery test script, for SPD3303X and SDL1030X

# Wire with CH2 of the SPD3303X, in parallel with SDL1030X, across the battery.
# Optionally, connect the Joulescope to the battery for coulomb counting.

# Note that the Siglent PSU does not allow us to measure current or voltage when its output is off.
# This means we need either the SDL1030X or the Joulescope to measure the battery's voltage and current during discharge.

# For a given battery sample, we want to measure:
# - Capacity
# - Charge curve (voltage vs. time)
# - Discharge curve (open-circuit equivalent voltage vs. time)
# - Internal resistance

import spd3303x
#import sdl1030x
import time
import datetime

# Battery claimed parameters
nominal_capacity = 850 # mAh
charge_voltage = 4.2 # V
charge_rate = 1 # C
charge_termination = 0.1 # times the charge rate

# Test conditions
discharge_rate = 0.1 # C
pulse_discharge_rate = 1 # C
discharge_termination = 3.0 # V at the nominal discharge rate
number_of_cycles = 1

# File name chosen based on the current date and time
identifier = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
fname = f"charge_{identifier}.csv"

# Derived parameters
charge_current = nominal_capacity * charge_rate / 1000 # A
charge_termination_current = charge_current * charge_termination # A

# Misc configuration
psu_ip = "192.168.1.114"
load_ip = "192.168.1.115" # TODO: Change this to the SDL1030X's IP address

def log_to_file(data, filename):
    with open(filename, "w") as f:
        f.write("time,voltage,current,phase\n")
        for sample in samples:
            f.write(f"{sample[0]},{sample[1]},{sample[2]},{sample[3]}\n")

with spd3303x.SPD3303X.ethernet_device(psu_ip) as psu:#, sdl1030x.SDL1030X.ethernet_device(load_ip) as load:

    try:
        # Charge with a constant-voltage, current limited to the charge rate
        psu.CH2.set_voltage(charge_voltage)
        psu.CH2.set_current(charge_current)
  
        psu.CH2.set_output(True)
        start_time = time.time()

        print(f"Charging begun, will log to {fname}")

        samples = []
        last_save_time = start_time
        last_sample_time = start_time

        # Monitor and log the voltage and current
        while True:
            last_sample_time = time.time()
            voltage = float(psu.CH2.measure_voltage())
            current = float(psu.CH2.measure_current())
            print(f"Voltage: {voltage}, Current: {current}")

            samples.append((last_sample_time - start_time, voltage, current, "charge"))
            
            # Terminate charge when current drops below the charge termination rate
            if current < charge_termination_current:
                print(f"Terminating charge due to cutoff current reached, charged for {time.time() - start_time} seconds")
                break

            # For safety, terminate charge after 3 hours regardless of current
            if time.time() - start_time > 3 * 3600:
                print(f"Terminating charge due to timeout, charged for {time.time() - start_time} seconds")
                break

            # Every minute, save the data to disk for later analysis
            if time.time() - last_save_time > 60:
                log_to_file(samples, fname)
                last_save_time = time.time()

            # There will be a small delay due to the time it takes to measure, serialise, and save the data.
            # Aim for a 1-second delay between samples.
            delay = 1 - (time.time() - last_sample_time)
            if delay > 0:
                time.sleep(delay)


        psu.CH2.set_output(False)
        print("Charge complete")

        # Log to a file
        log_to_file(samples, fname)
    
    except Exception as e:
        print(f"Exception: {e}")
    finally:
        psu.CH2.set_output(False)
        print("Finally, PSU output off")
