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

# For now let's ignore dynamic recovery, temperature, and non-linear effects.

import spd3303x
import sdl1030x
import time
import datetime
import csv
from pprint import pprint

# Battery claimed parameters
nominal_capacity = 850 # mAh
charge_voltage = 4.2 # V
charge_rate = 1 # C
charge_termination = 0.1 # times the charge rate

# Test conditions
discharge_rate = 0.1 # C
pulse_discharge_rate = 1 # C
pulse_settle_time = 3 # seconds
pulse_spacing = 60 # seconds
discharge_termination = 3.0 # V at the nominal discharge rate
number_of_cycles = 1


# Derived parameters
charge_current = nominal_capacity * charge_rate / 1000 # A
charge_termination_current = charge_current * charge_termination # A
discharge_current = nominal_capacity * discharge_rate / 1000 # A
pulse_discharge_current = nominal_capacity * pulse_discharge_rate / 1000 # A

# Misc configuration
psu_ip = "192.168.1.114"
load_ip = "192.168.1.116"

def log_to_file(samples, filename):
    fieldnames = samples[0].keys()
    with open(filename, "w", newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for sample in samples:
            writer.writerow(sample)


def charge_cycle(psu, fname):

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
        estimated_charge = 0

        # Monitor and log the voltage and current
        while True:
            now = time.time()
            dt = now - last_sample_time
            last_sample_time = now
            voltage = float(psu.CH2.measure_voltage())
            current = float(psu.CH2.measure_current())
            estimated_charge += current * dt

            sample = {
                'time': last_sample_time - start_time,
                'voltage': voltage,
                'current': current,
                'charge': estimated_charge, 
                'status': "charging"}
            
            pprint(sample)

            samples.append(sample)
            
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
                print(f"Saved backup data to {fname}")
                last_save_time = time.time()

            # There will be a small delay due to the time it takes to measure, serialise, and save the data.
            # Aim for a 1-second delay between samples.
            delay = 1 - (time.time() - last_sample_time)
            if delay > 0:
                time.sleep(delay)


        psu.CH2.set_output(False)
        print("Charge complete")

        
    
    except Exception as e:
        print(f"Exception: {e}")
    finally:
        psu.CH2.set_output(False)
        print("Finally, PSU output off")
        # Log to a file
        log_to_file(samples, fname)
        print(f"Saved data to {fname}")

        # Coulomb output
        estimated_charge_mah = estimated_charge / 3600 * 1000
        print(f"Estimated charge taken this cycle: {estimated_charge_mah} mAh (coulombs: {estimated_charge})")


def discharge_cycle(load, fname):
    print("Starting discharge cycle...")

    # Log the current and voltage at the start of the discharge cycle
    start_time = time.time()
    last_sample_time = start_time
    samples = []
    last_save_time = start_time
    last_pulse_time = start_time
    estimated_charge = 0

    try:

        # Discharge at the nominal rate
        load.set_source_current(discharge_current)
        load.set_source_state(True)
        time.sleep(1)

        while True:

            # Log the current and voltage
            now = time.time()
            dt = now - last_sample_time
            last_sample_time = now
            voltage = load.measure_voltage()
            current = load.measure_current()
            sample = {
                'time': last_sample_time - start_time,
                'voltage': voltage,
                'current': current,
                'charge': estimated_charge,
                'resistance': '-', # Resistance calculation will be done during the pulse
                'status': "discharge"
            }
            samples.append(sample)
            pprint(sample)

            # Estimate charge based on the current and time. Trapezioidal rule would be more accurate but this is fine
            estimated_charge += current * dt

            # When a pulse is due, log the current and voltage, increase to the pulse rate, measure the voltage again, and calculate the resistance
            if time.time() - last_pulse_time > pulse_spacing:
                last_pulse_time = time.time()

                # Increase the current to the pulse rate
                print(f"Pulse discharge at {pulse_discharge_current}")
                load.set_source_current(pulse_discharge_current)

                # Wait for the current to stabilise
                time.sleep(pulse_settle_time)

                # Measure the voltage and current
                pulse_voltage = load.measure_voltage()
                pulse_current = load.measure_current()

                # Track the charge consumed during the pulse
                estimated_charge += pulse_current * pulse_settle_time

                # Calculate the internal resistance based on the voltage drop and the current increase
                # Let's assume linear behaviour for now
                # Vnominal = Vinternal - Inominal * Rinternal and Vpulse = Vinternal - Ipulse * Rinternal
                # Rinternal = (Vnominal - Vpulse) / (Ipulse - Inominal)
                resistance = (voltage - pulse_voltage) / (pulse_current - discharge_current)
                
                print(f"Internal resistance estimate: {resistance}")

                pulse_sample = {
                    'time': last_sample_time - start_time,
                    'voltage': pulse_voltage,
                    'current': pulse_current,
                    'charge': estimated_charge,
                    'resistance': resistance,
                    'status': "discharge_pulse"
                }
                samples.append(pulse_sample)
                pprint(pulse_sample)

                # Return to the nominal discharge rate
                load.set_source_current(discharge_current)


            # Once per minute, save the data to disk for later analysis
            if time.time() - last_save_time > 60:
                log_to_file(samples, fname)
                print(f"Saved backup data to {fname}")
                last_save_time = time.time()

            # If the voltage has dropped below the termination voltage, terminate the discharge
            if voltage < discharge_termination:
                print("Discharge terminated due to cutoff voltage")
                break

            # Run the update loop every second
            delay = 1 - (time.time() - last_sample_time)
            if delay > 0:
                time.sleep(delay)
            

    except Exception as e:
        print(f"Exception: {e}")
    finally:
        load.set_source_state(False)
        print("Finally, load output off")

        # We work in coulombs (amp-seconds) but milliamp-hours is a more useful unit for batteries
        # 
        estimated_charge_mah = estimated_charge / 3600 * 1000
        print(f"Estimated charge this cycle: {estimated_charge_mah} mAh (coulombs: {estimated_charge})")

        # Log to a file
        log_to_file(samples, fname)
        print(f"Saved data to {fname}")


with spd3303x.SPD3303X.ethernet_device(psu_ip) as psu, sdl1030x.SDL1030X.ethernet_device(load_ip) as load:

    # File name chosen based on the current date and time
    identifier = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    print("Charging...")
    charge_cycle(psu, f"charge_{identifier}.csv")

    time.sleep(5)
    
    print("Discharging...")
    discharge_cycle(load, f"discharge_{identifier}.csv")

