"""Test doubles: a scriptable stand-in for the parts of psutil the collectors use."""

from types import SimpleNamespace as NS


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class FakePsutil:
    def __init__(self):
        self.percpu = [10.0, 30.0, 50.0, 70.0]
        self.logical, self.physical = 4, 2
        self.freq = NS(current=2300.0, min=0.0, max=2300.0)
        self.vmem = NS(total=16 * 2**30, available=6 * 2**30, used=10 * 2**30, percent=62.5)
        self.swap = NS(total=4 * 2**30, used=2**30, free=3 * 2**30, percent=25.0)
        self.partitions = [
            NS(device="C:\\", mountpoint="C:\\", fstype="NTFS", opts="rw,fixed"),
            NS(device="E:\\", mountpoint="E:\\", fstype="", opts="cdrom"),
        ]
        self.usage = {"C:\\": NS(total=1000, used=400, free=600, percent=40.0)}
        self.io = NS(read_bytes=0, write_bytes=0)
        self.nic_stats = {
            "Wi-Fi": NS(isup=True, speed=866),
            "Loopback Pseudo-Interface 1": NS(isup=True, speed=1073),
            "Bluetooth": NS(isup=False, speed=3),
        }
        self.nic_io = {
            "Wi-Fi": NS(bytes_recv=0, bytes_sent=0),
            "Loopback Pseudo-Interface 1": NS(bytes_recv=0, bytes_sent=0),
            "Bluetooth": NS(bytes_recv=0, bytes_sent=0),
        }
        self.nic_addrs = {
            "Wi-Fi": [NS(family=2, address="192.168.1.20"), NS(family=-1, address="aa-bb-cc-dd-ee-ff")],
        }

    # CPU
    def cpu_percent(self, interval=None, percpu=False):
        return list(self.percpu) if percpu else sum(self.percpu) / len(self.percpu)

    def cpu_count(self, logical=True):
        return self.logical if logical else self.physical

    def cpu_freq(self):
        return self.freq

    # Memory
    def virtual_memory(self):
        return self.vmem

    def swap_memory(self):
        return self.swap

    # Storage
    def disk_partitions(self, all=False):
        return self.partitions

    def disk_usage(self, path):
        if path not in self.usage:
            raise PermissionError("device not ready")
        return self.usage[path]

    def disk_io_counters(self, perdisk=False):
        return self.io

    # Network
    def net_if_stats(self):
        return self.nic_stats

    def net_io_counters(self, pernic=False):
        return self.nic_io

    def net_if_addrs(self):
        return self.nic_addrs
