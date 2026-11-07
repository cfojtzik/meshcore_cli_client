"""Minimal MeshCore companion emulator (binary protocol over TCP) for tests."""

import os
import struct
import threading
import time


def _pad(text, size):
    data = text.encode("utf-8")[:size]
    return data + b"\0" * (size - len(data))


def contact_record(key_hex, name, node_type=2, last_advert=None):
    return (
        bytes.fromhex(key_hex)
        + bytes([node_type, 0, 255])
        + b"\0" * 64
        + _pad(name, 32)
        + struct.pack("<I", int(last_advert or time.time()))
        + struct.pack("<ii", 0, 0)
        + struct.pack("<I", int(time.time()))
    )


class FakeCompanion:
    def __init__(self, saved_contacts=(), manual_add=True):
        import socket
        self._server = socket.socket()
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.tcp_port = self._server.getsockname()[1]
        self.master = None
        self._slave = None
        self._connected = threading.Event()
        self.saved = dict(saved_contacts)  # key -> name
        self.manual_add = manual_add
        self.commands = []
        self._lock = threading.Lock()
        self._closed = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _send(self, payload):
        frame = b">" + struct.pack("<H", len(payload)) + payload
        with self._lock:
            try:
                os.write(self.master, frame)
            except OSError:
                pass

    def push_advert(self, key_hex):
        """Known contact heard again: PUSH_CODE_ADVERT (0x80)."""
        self._send(b"\x80" + bytes.fromhex(key_hex))

    def push_new_advert(self, key_hex, name, node_type=2):
        """Unknown node in manual-add mode: PUSH_CODE_NEW_ADVERT (0x8A)."""
        self._send(b"\x8a" + contact_record(key_hex, name, node_type))

    def _handle(self, payload):
        cmd = payload[0]
        self.commands.append(cmd)
        if cmd == 1:  # APP_START -> SELF_INFO
            self._send(
                b"\x05" + bytes([1, 20, 22]) + bytes.fromhex("11" * 32)
                + struct.pack("<ii", 0, 0) + bytes([0, 0, 0, 1 if self.manual_add else 0])
                + struct.pack("<II", 869525, 250000) + bytes([11, 5]) + b"FakeNode"
            )
        elif cmd == 22:  # DEVICE_QUERY -> DEVICE_INFO
            self._send(
                b"\x0d" + bytes([8, 50, 8]) + struct.pack("<I", 0)
                + _pad("01 Jan 2026", 12) + _pad("Fake", 40) + _pad("v1.0", 20)
            )
        elif cmd == 4:  # GET_CONTACTS
            self._send(b"\x02" + struct.pack("<I", len(self.saved)))
            for key, name in self.saved.items():
                self._send(b"\x03" + contact_record(key, name))
            self._send(b"\x04" + struct.pack("<I", int(time.time())))
        elif cmd == 31:  # GET_CHANNEL
            idx = payload[1]
            if idx == 0:
                self._send(b"\x12" + bytes([0]) + _pad("Public", 32) + b"\0" * 16)
            else:
                self._send(b"\x01\x02")
        elif cmd == 10:  # SYNC_NEXT_MESSAGE
            self._send(b"\x0a")
        elif cmd == 40:  # GET_CUSTOM_VARS
            self._send(b"\x15")
        elif cmd == 5:  # GET_DEVICE_TIME
            self._send(b"\x09" + struct.pack("<I", int(time.time())))
        else:
            self._send(b"\x00")

    def _run(self):
        conn, _ = self._server.accept()
        self._conn = conn
        self.master = conn.fileno()
        self._connected.set()
        buffer = b""
        while not self._closed:
            try:
                chunk = os.read(self.master, 4096)
            except OSError:
                return
            if not chunk:
                return
            buffer += chunk
            while True:
                start = buffer.find(b"<")
                if start < 0 or len(buffer) < start + 3:
                    break
                size = struct.unpack("<H", buffer[start + 1:start + 3])[0]
                if len(buffer) < start + 3 + size:
                    break
                payload = buffer[start + 3:start + 3 + size]
                buffer = buffer[start + 3 + size:]
                if payload:
                    self._handle(payload)

    def close(self):
        self._closed = True
        for sock in (getattr(self, "_conn", None), self._server):
            try:
                if sock is not None:
                    sock.close()
            except OSError:
                pass
