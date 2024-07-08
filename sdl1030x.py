import pyvisa
import numpy as np
import time
import xdrlib
import logging
import socket
import vxi11

consoleHandler = logging.StreamHandler()
logger = logging.getLogger("sdl1030x")
logger.addHandler(consoleHandler)
logger.setLevel(logging.DEBUG)


class SDL1030X(object):

    KNOWN_MODELS = ["SDL1030X"]

    @classmethod
    def usb_device(cls, visa_rscr: str = None):
        return USBDevice(visa_rscr)

    @classmethod
    def ethernet_device(cls, host: str):
        return EthernetDevice(host)
    
    def measure_voltage(self):
        return float(self.query(f"MEAS:VOLT:DC?"))

    def measure_current(self):
        return float(self.query(f"MEAS:CURR:DC?"))
    
    def measure_power(self):
        return float(self.query(f"MEAS:POW:DC?"))
    
    def measure_resistance(self):
        return float(self.query(f"MEAS:RES:DC?"))
    
    def measure_external(self):
        return float(self.query(f"MEAS:EXT?"))
    
    def set_source_state(self, enabled):
        self.write(f"SOUR:INP:STAT {1 if enabled else 0}")

    def get_source_state(self):
        return bool(self.query(f"SOUR:INP:STAT?"))
    
    def set_source_mode(self, mode):
        modes = ["CC", "CV", "CP", "CR", "LED"]
        assert mode in modes, "Invalid mode, valid modes are: " + ", ".join(modes)
        self.write(f"SOUR:FUNC {mode}")

    def get_source_mode(self):
        # Will return one of "CURRENT", "VOLTAGE", "POWER", "RESISTANCE", "LED"
        return self.query(f"SOUR:FUNC?")
    
    def set_source_current(self, current):

        if current < 0:
            raise ValueError("Current must be positive")
        
        if current not in ["MIN", "MAX", "DEF"]:
            assert type(current) in [int, float], "Current must be a number"
        
        self.write(f"SOUR:CURR:LEV:IMM {current}")

    def get_source_current(self):
        return float(self.query(f"SOUR:CURR:LEV:IMM?"))
    
    def set_source_voltage(self, voltage):
        if voltage < 0:
            raise ValueError("Voltage must be positive")
        
        if voltage not in ["MIN", "MAX", "DEF"]:
            assert type(voltage) in [int, float], "Voltage must be a number"
        
        self.write(f"SOUR:VOLT:LEV:IMM {voltage}")

    def get_source_voltage(self):
        return float(self.query(f"SOUR:VOLT:LEV:IMM?"))
    


    def __enter__(self):
        try:
            dsc = self.query("*IDN?")
        except pyvisa.errors.VisaIOError:
            self._inst.close()
            raise
        identity_items = dsc.split(",")
        mnf, model, _, _ = identity_items
        logger.debug(f"Discovered {model} by {mnf}")
        if model not in self.KNOWN_MODELS:
            raise Exception(f"Device {model} not supported")
        # TODO: Expose features of the device
        return self

    def __exit__(self, *args):
        self._inst.close()


class USBDevice(SDL1030X):
    def __init__(self, visa_rscr: str = None):
        self._visa_rscr = visa_rscr

    def __enter__(self):
        rm = pyvisa.ResourceManager("@py")
        if self._visa_rscr is None:
            logger.debug("Trying to auto-detect USB device")
            resources = rm.list_resources()
            for res_str in resources:
                if "SPD3XID" in res_str:
                    self._visa_rscr = res_str
            if self._visa_rscr is None:
                raise Exception("No device found")

        self._inst = rm.open_resource(self._visa_rscr)
        self._inst.write_termination = "\n"
        self._inst.read_termination = "\n"
        return super().__enter__()

    def write(self, cmd: str):
        self._inst.write(cmd)
        time.sleep(0.1)

    def query(self, cmd: str):
        self.write(cmd)
        rep = self._inst.read()
        time.sleep(0.1)
        return rep


class EthernetDevice(SDL1030X):
    def __init__(self, host: str):
        self._host = host

    def __enter__(self):
        try:
            logger.debug(f"Trying to resolve host {self._host}")
            ip_addr = socket.gethostbyname(self._host)
        except socket.gaierror:
            logger.error(f"Couldn't resolve host {self._host}")

        self._inst = vxi11.Instrument(ip_addr)
        return super().__enter__()

    def write(self, cmd: str):
        self._inst.write(cmd)
        time.sleep(0.1)

    def query(self, cmd: str):
        return self._inst.ask(cmd)