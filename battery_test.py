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

import dp8xx
import sdl1030x
import time
import datetime
import csv
import traceback
import tqdm

# Battery parameters
import spec_velo2_4v35 as spec

# Test parameters not specified in the datasheet
pulse_discharge_current = 2 * spec.discharge_current
pulse_settle_time = 2 # seconds
pulse_spacing = 120 # seconds
number_of_cycles = 2
rest_charge_to_discharge = 60 * 5 # seconds
rest_discharge_to_charge = 60 * 5 # seconds

# Misc calibration
test_lead_resistance = 0.05 # measured by short circuiting the leads, putting a known current through, and measuring the voltage drop

def mah_to_coulombs(mah):
    # one milliamp hour is 1/1000 of an amp for 3600 seconds
    return mah / 1000 * 3600
def coulombs_to_mah(coulombs):
    # one coulomb is one ampere-second
    return coulombs / 3600 * 1000
    
# Misc configuration
psu_ip = "10.0.0.10"
load_ip = "10.0.0.11"

def log_to_file(samples, filename):
    fieldnames = samples[0].keys()
    with open(filename, "w", newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for sample in samples:
            writer.writerow(sample)


def charge_cycle(psu, fname):

    # TODO: Trickle charging when low voltage?
    
    failed = False

    try:
        # Charge with a constant-voltage, current limited to the charge rate
        # CH1 is used to control a relay which connects the PSU to the battery
        # CH2 is used to charge the battery
        # The reason a relay is used is because the PSU has an approx 38mA leakage current in to its supply when off
        # which would affect the discharge measurements. 
        # This could alternatively be reduced to a ~1mA output by setting to 4.2v 0.0001A, but the relay guarantees 0 leakage.
        psu.CH1.set_voltage(12) # Relay control voltage
        psu.CH1.set_current(1)
        psu.CH2.set_voltage(spec.charge_voltage)
        psu.CH2.set_current(spec.charge_current)
  
        psu.CH1.set_output(True) # Power the relay
        time.sleep(1) # Allow the relay to switch
        psu.CH2.set_output(True) # Turn on the charger output
        start_time = time.time()
        print(f"Charging begun, will log to {fname}")

        samples = []
        last_save_time = start_time
        last_sample_time = start_time
        estimated_charge = 0

        progbar = tqdm.tqdm(total=spec.nominal_capacity_mah, unit="mAh", unit_scale=True, desc="Charge starting...")
        progbar.update(0)

        time.sleep(1) # Allow the PSU to start up before entering the loop

        # Monitor and log the voltage and current
        while True:
            now = time.time()
            dt = now - last_sample_time
            last_sample_time = now

            cur_values = psu.CH2.measure_all()
            
            voltage = cur_values['voltage']
            current = cur_values['current']
            estimated_charge += current * dt

            sample = {
                'time': last_sample_time - start_time,
                'voltage': voltage,
                'current': current,
                'charge': estimated_charge, 
                'status': "charging"
            }
            samples.append(sample)

            # Show a status line and progress bar in the console
            charge_mah = coulombs_to_mah(estimated_charge)            
            progbar.n = min(charge_mah, spec.nominal_capacity_mah) # prevent the progress bar from going over the nominal capacity
            progbar.set_description(f"Charging: {current*1000:.1f}mA, {voltage:.3f}V, {charge_mah:.1f}mAh")
            
            # Terminate charge when current drops below the charge termination rate
            if current < spec.charge_termination_current:
                print(f"\nTerminating charge due to cutoff current reached, charged for {time.time() - start_time} seconds")
                break

            # For safety, terminate charge after 3 hours regardless of current
            if time.time() - start_time > 3 * 3600:
                print(f"\nTerminating charge due to timeout, charged for {time.time() - start_time} seconds")
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


        psu.CH1.set_output(False) # Disconnect the relay
        #psu.CH2.set_output(False)
        psu.CH2.set_current(0) # Temporary workaround for the PSU leakage current issue
        print("\nCharge complete")

        
    
    except Exception as e:
        print(f"\nException: {e}")
        traceback.print_exc()
        failed=True
    finally:
        psu.CH1.set_output(False) # Disconnect the relay
        #psu.CH2.set_output(False)
        psu.CH2.set_current(0) # Temporary workaround for the PSU leakage current issue
        print("\nFinally, PSU output zeroed. FIX ME: DISABLE PSU ONCE RELAY IS ADDED.")
        # Log to a file
        log_to_file(samples, fname)
        print(f"Saved data to {fname}")

        # Coulomb output
        print(f"Estimated charge taken this cycle: {coulombs_to_mah(estimated_charge)} mAh (coulombs: {estimated_charge})")

    return not failed

def discharge_cycle(load, fname):
    print("Starting discharge cycle...")

    failed=False

    # Log the current and voltage at the start of the discharge cycle
    start_time = time.time()
    last_sample_time = start_time
    samples = []
    last_save_time = start_time
    last_pulse_time = start_time
    estimated_charge = 0

    try:

        progbar = tqdm.tqdm(total=spec.nominal_capacity_mah, unit="mAh", unit_scale=True, desc="Discharge starting...")
        progbar.update(0)

        # Discharge at the nominal rate
        load.set_source_current(spec.discharge_current)
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
            
            # Show a status line and progress bar in the console
            charge_mah = coulombs_to_mah(estimated_charge)
            progbar.n = min(charge_mah, spec.nominal_capacity_mah) # prevent the progress bar from going over the nominal capacity
            progbar.set_description(f"Discharging: {current*1000:.1f}mA, {voltage:.3f}V, {charge_mah:.1f}mAh")


            # Estimate charge based on the current and time. Trapezioidal rule would be more accurate but this is fine
            estimated_charge += current * dt

            # When a pulse is due, log the current and voltage, increase to the pulse rate, measure the voltage again, and calculate the resistance
            if time.time() - last_pulse_time > pulse_spacing:
                last_pulse_time = time.time()

                # Increase the current to the pulse rate
                progbar.set_description(f"Discharge pulse: {pulse_discharge_current*1000:.1f}mA...")
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
                resistance = (voltage - pulse_voltage) / (pulse_current - spec.discharge_current)
                
                pulse_sample = {
                    'time': last_sample_time - start_time,
                    'voltage': pulse_voltage,
                    'current': pulse_current,
                    'charge': estimated_charge,
                    'resistance': resistance,
                    'status': "discharge_pulse"
                }
                samples.append(pulse_sample)

                # Return to the nominal discharge rate
                load.set_source_current(spec.discharge_current)

                # Prevent the coulomb counting from adding at the nominal rate for the duration of the pulse
                last_sample_time = time.time()


            # Once per minute, save the data to disk for later analysis
            if time.time() - last_save_time > 60:
                log_to_file(samples, fname)
                last_save_time = time.time()

            # If the average voltage over the last N samples has dropped below the termination voltage, terminate the discharge
            # This improves noise/pulse-loading immunity and makes the termination more predictable
            num_samples_required = 20
            if len(samples) >= num_samples_required and sum([sample['voltage'] for sample in samples[-num_samples_required:]]) / num_samples_required < spec.discharge_termination_voltage:
                print("\nDischarge terminated due to cutoff voltage")
                break

            # Run the update loop every second
            delay = 1 - (time.time() - last_sample_time)
            if delay > 0:
                time.sleep(delay)
            

    except Exception as e:
        print(f"\nException: {e}")
        traceback.print_exc()
        failed=True
    finally:
        load.set_source_state(False)
        print("\nFinally, load output off")

        # We work in coulombs (amp-seconds) but milliamp-hours is a more useful unit for batteries
        # 
        print(f"Estimated charge this cycle: {coulombs_to_mah(estimated_charge)} mAh (coulombs: {estimated_charge})")

        # Log to a file
        log_to_file(samples, fname)
        print(f"Saved data to {fname}")

    return not failed


with dp8xx.DP8xx.ethernet_device(psu_ip) as psu, sdl1030x.SDL1030X.ethernet_device(load_ip) as load:

    # Estimate the total runtime as a rough guide
    # Below is in units of amps, seconds
    cycle_time = (mah_to_coulombs(spec.nominal_capacity_mah) / spec.discharge_current) + (mah_to_coulombs(spec.nominal_capacity_mah) / spec.charge_current) + rest_charge_to_discharge + rest_discharge_to_charge
    total_time = cycle_time * number_of_cycles
    print(f"Estimated runtime per cycle: {cycle_time/3600:.1f} hours, total runtime: {total_time/3600:.1f} hours")

    # File name chosen based on the current date and time
    identifier = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # Collect any information that might be useful for later analysis
    slug = input("Enter a short description of the battery (will be the start of the filename): ")
    user_info = input("Enter any information that might be useful for later analysis: ")

    with open(f"{slug}_{identifier}_info.txt", "w") as f:
        # Log all the key parameters to a text file for later reference
        f.write(f"Test started at {datetime.datetime.now()}\n")
        f.write(f"User info: {user_info}\n")
        f.write(f"Identifier: {identifier}\n")
        f.write(f"Nominal capacity: {spec.nominal_capacity_mah} mAh\n")
        f.write(f"Charge voltage: {spec.charge_voltage} V\n")
        f.write(f"Charge current: {spec.charge_current*1000:.1f} mA\n")
        f.write(f"Charge termination: {spec.charge_termination_current*1000:.1f} mA\n")
        f.write(f"Discharge current: {spec.discharge_current*1000:.1f} mA\n")
        f.write(f"Pulse discharge current: {pulse_discharge_current*1000:.1f} mA\n")
        f.write(f"Pulse settle time: {pulse_settle_time} s\n")
        f.write(f"Pulse spacing: {pulse_spacing} s\n")
        f.write(f"Number of cycles: {number_of_cycles}\n")
        f.write(f"Rest time between charge and discharge: {rest_charge_to_discharge} s\n")

    for cycle in range(1, number_of_cycles+1):
        
        print(f"Charge cycle {cycle}...")
        if not charge_cycle(psu, f"{slug}_chg{cycle}_{identifier}.csv"):
            print("Charge cycle failed!")
            break

        print(f"Resting between charge and discharge...")
        time.sleep(rest_charge_to_discharge)
        
        print(f"Discharge cycle {cycle}...")
        if not discharge_cycle(load, f"{slug}_dis{cycle}_{identifier}.csv"):
            print("Discharge cycle failed!")
            break

        print(f"Resting between discharge and charge...")
        time.sleep(rest_discharge_to_charge)

    # Finally turn off all the hardware
    psu.CH1.set_output(False)
    psu.CH2.set_output(False)
