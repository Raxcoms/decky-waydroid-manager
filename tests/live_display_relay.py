"""Relay a hardware smoke test through a temporary native app scope."""

import importlib.machinery
import importlib.util
from pathlib import Path
import socket
import sys

script = Path(__file__).resolve().parents[1] / "bin/waydroid-wayland-relay"
loader = importlib.machinery.SourceFileLoader("smoke_relay", str(script))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = module
loader.exec_module(module)

with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
    listener.bind(sys.argv[1])
    listener.listen(4)
    listener.setblocking(False)
    relay = module.Relay(listener, sys.argv[2])
    try:
        while True:
            relay.step()
    finally:
        relay.close()
