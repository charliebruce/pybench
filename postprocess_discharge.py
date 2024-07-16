#!/usr/bin/env python3
import csv
import sys

# Post-process the battery discharge data, to extract key parameters

# We have a CSV file, with the following columns:
# time	voltage	current	charge	resistance	status
# Units are seconds, volts, amps, coulombs, ohms, and a string ("discharge" or "discharge_pulse")

# Load the data from the named file
fname = sys.argv[1]
discharge_rate_amps = float(sys.argv[2])
with open(fname, "r") as f:
    reader = csv.DictReader(f)
    # time, voltage, current, charge are all floats, parsed as such
    # resistance is a float (for pulses) or "-" (for normal discharge)
    # status is a string

    # Convert the data to a list of dictionaries, parsing floats as we go
    data = []
    for row in reader:
        row["time"] = float(row["time"])
        row["voltage"] = float(row["voltage"])
        row["current"] = float(row["current"])
        row["charge"] = float(row["charge"])
        if row["resistance"] != "-":
            row["resistance"] = float(row["resistance"])
        data.append(row)

# First, split between discharge and discharge_pulse data
discharge_data = [d for d in data if d["status"] == "discharge"]
discharge_pulse_data = [d for d in data if d["status"] == "discharge_pulse"]

#
# Resistance calculation from pulse data
#

# Take an average of the resistance between the 30% and 70% time points and use that as our nominal resistance
first_pulse_time = discharge_pulse_data[0]["time"]
last_pulse_time = discharge_pulse_data[-1]["time"]

# Find the 30% and 70% time points
thirty_percent_time = first_pulse_time + 0.3 * (last_pulse_time - first_pulse_time)
seventy_percent_time = first_pulse_time + 0.7 * (last_pulse_time - first_pulse_time)

# Average the resistance between these two time points
middle_samples = [d for d in discharge_pulse_data if thirty_percent_time < d["time"] < seventy_percent_time]
resistances = [d["resistance"] for d in middle_samples]
nominal_resistance = sum(resistances) / len(resistances)
print(f"Measured resistance: {nominal_resistance}")


#
# Voltage - SOC curve
#

# From the normal discharge samples, the rate used for the discharge, we can calculate the open-circuit voltage for each sample
ocvs = [x["voltage"] + x["current"] * nominal_resistance for x in discharge_data]

# Take N evenly-spaced samples from the OCV data, and output as a C-style array
N = 20

indices = [int(i * (len(ocvs) - 1) / N) for i in range(N + 1)]

# Sanity check: ensure we capture the entire range
assert indices[0] == 0
assert indices[-1] == len(ocvs) - 1

ocv_samples = [ocvs[i] for i in indices]

print("const float ocv_samples[] = {", end="")
print(", ".join([f"{x:.4f}f" for x in ocv_samples[::-1]]), end="") # Reverse the order so that 0% SOC is at the start
print("};")

#
# Capacity calculation
#

# Output the nominal capacity of the battery
capacity_coulombs = data[-1]["charge"]
capacity_mah = capacity_coulombs / 3600 * 1000
print(f"Measured capacity: {capacity_mah:.1f} mAh.")

# As a sanity check, we can calculate the capacity by taking the nominal discharge rate and multiplying by the time
start_time = discharge_data[0]["time"]
end_time = discharge_data[-1]["time"]
sanity_check_coulombs = discharge_rate_amps * (end_time - start_time) # 1 coulomb = 1 ampere-second
print(f"Sanity check capacity (under-estimate due to pulses): {sanity_check_coulombs / 3600 * 1000 :.1f} mAh.")




