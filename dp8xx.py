import pyvisa
import numpy as np
import time
import xdrlib
import logging
import socket
import vxi11

consoleHandler = logging.StreamHandler()
logger = logging.getLogger("dp8xx")
logger.addHandler(consoleHandler)
logger.setLevel(logging.DEBUG)


class DP8xx(object):
    KNOWN_MODELS = [
        "DP832A",
    ]

    MANUFACTURERS = {
        "RIGOL TECHNOLOGIES": "Rigol",
    }

    @classmethod
    def usb_device(cls, visa_rscr: str = None):
        return USBDevice(visa_rscr)

    @classmethod
    def ethernet_device(cls, host: str):
        return EthernetDevice(host)

    class Channel(object):
        def __init__(self, chan_no: int, dev):
            self._name = f"CH{chan_no}"
            self._source_name = f"SOUR{chan_no}"
            self._dev = dev

        def set_output(self, status: bool):
            self._dev.write(f"OUTP {self._name},{'ON' if status else 'OFF'}")

    class ControlledChannel(Channel):
        def set_voltage(self, voltage: float):
            self._dev.write(f"{self._source_name}:VOLT {voltage:.3f}")

        def set_current(self, current: float):
            self._dev.write(f"{self._source_name}:CURR {current:.3f}")

        def get_voltage(self):
            return self._dev.query(f"{self._source_name}:VOLT?")

        def get_current(self):
            return self._dev.query(f"{self._source_name}:CURR?")

        def measure_voltage(self):
            return self._dev.query(f"MEAS:VOLT? {self._name}")

        def measure_current(self):
            return self._dev.query(f"MEAS:CURR? {self._name}")

        def measure_power(self):
            return self._dev.query(f"MEAS:POWE? {self._name}")
        
        def measure_all(self):
            result = self._dev.query(f"MEAS:ALL? {self._name}")
            voltage, current, power = result.split(",")
            return {'voltage': float(voltage), 'current': float(current), 'power': float(power)}


    def __enter__(self):
        try:
            dsc = self.query("*IDN?")
        except pyvisa.errors.VisaIOError:
            self._inst.close()
            raise
        identity_items = dsc.split(",")
        mnf, model, sernum, fwver = identity_items
        logger.debug(f"Discovered {model} by {mnf}, serial number {sernum}, firmware {fwver}")
        if model not in self.KNOWN_MODELS:
            raise Exception(f"Device {model} not tested, your mileage may vary. Add to the list if it works.")
        self.CH1 = DP8xx.ControlledChannel(1, self)
        self.CH2 = DP8xx.ControlledChannel(2, self)
        self.CH3 = DP8xx.ControlledChannel(3, self)
        return self

    def __exit__(self, *args):
        self._inst.close()


class USBDevice(DP8xx):
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


class EthernetDevice(DP8xx):
    def __init__(self, host: str):
        self._host = host

    def __enter__(self):
        try:
            logger.debug(f"Trying to resolve host {self._host}")
            ip_addr = socket.gethostbyname(self._host)
        except socket.gaierror:
            logger.error(f"Couldn't resolve host {self._host}")

        self._inst = vxi11.Instrument(ip_addr)
        self._inst.timeout = 20 # seconds, default is 10s but some issues seen
        return super().__enter__()

    def write(self, cmd: str):
        self._inst.write(cmd)

    def query(self, cmd: str):
        return self._inst.ask(cmd)