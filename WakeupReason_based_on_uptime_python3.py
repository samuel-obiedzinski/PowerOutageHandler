#!/usr/bin/python3

from urllib.request import urlopen

def GetRouterUptime():
    try:
        # source of uptime of different device, for example router
        with urlopen("http://192.168.1.1:3400/") as f:
            data = f.read(100)
            return int(data.decode('utf-8'))
    except Exception:
        return 0

def GetSystemUptime():
    try:
        with open('/proc/uptime', 'r') as f:
            data = f.readline().split(' ', 1)[0]
            with open('/tmp/poh_uptime', 'w') as uptime:
                uptime.write(data)
            return int(float(data))
    except Exception as e:
        return 0

if GetSystemUptime() < 120 and GetRouterUptime() < 120:
    print("(master power)")
else:
    print("(user)")


