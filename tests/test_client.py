"""Unit and integration tests for MeshCore TUI client."""

import os
import sys
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import Config
from src.backend.executor import MeshCoreBackend
from src.ui.widgets import safe_addstr


class TestConfig(unittest.TestCase):
    def test_default_config(self):
        cfg = Config(config_file=None)
        self.assertIsNotNone(cfg.port)
        self.assertEqual(cfg.baudrate, 115200)
        self.assertEqual(cfg.timeout, 10)
        self.assertFalse(cfg.simulation_mode)

    def test_property_setters(self):
        cfg = Config(config_file=None)
        cfg.port = "/dev/ttyACM0"
        cfg.baudrate = 57600
        cfg.simulation_mode = True
        self.assertEqual(cfg.port, "/dev/ttyACM0")
        self.assertEqual(cfg.baudrate, 57600)
        self.assertTrue(cfg.simulation_mode)


class TestBackend(unittest.TestCase):
    def setUp(self):
        self.config = Config(config_file=None)
        self.config.simulation_mode = True
        self.backend = MeshCoreBackend(self.config)

    def test_list_serial_ports(self):
        ports = self.backend.list_serial_ports()
        self.assertIsInstance(ports, list)
        for p in ports:
            self.assertIn("device", p)
            self.assertIn("description", p)
            self.assertIn("is_usb", p)

    def test_simulation_commands(self):
        commands_to_test = [
            (["infos"], "MeshCore Node Information"),
            (["ver"], "Firmware"),
            (["self_telemetry"], "Telemetry Data"),
            (["clock", "sync"], "Clock synchronized"),
            (["reboot"], "Reboot command sent"),
            (["contacts"], "Contacts List"),
            (["contact_info", "BaseStation-1"], "Contact Information"),
            (["disc_path", "Mobile-Bravo"], "Path discovery"),
            (["reset_path", "Mobile-Bravo"], "reset to Flood"),
            (["public", "Test Message"], "[ACK] Public Broadcast sent"),
            (["msg", "Mobile-Bravo", "Direct test"], "[ACK] Direct Message"),
            (["chan", "1", "Channel test"], "[ACK] Channel 1 message sent"),
            (["get_channels"], "Configured Channels"),
            (["sync_msgs"], "Synchronized Messages"),
            (["login", "Rep1", "pass123"], "Successfully logged into repeater"),
            (["logout", "Rep1"], "Logged out of repeater"),
            (["req_status", "Rep1"], "Status of Repeater"),
            (["advert"], "Advertisement packet transmitted"),
            (["scope", "0"], "Flood scope set to '0'"),
            (["get", "name"], "Parameter 'name'"),
            (["set", "name", "NewName"], "Parameter 'name' updated"),
        ]

        for args, expected_substring in commands_to_test:
            ok, out = self.backend.run_cli(args)
            self.assertTrue(ok, f"Command {args} failed: {out}")
            self.assertIn(
                expected_substring,
                out,
                f"Expected '{expected_substring}' in output of {args}, got: {out}",
            )

    def test_test_connection_simulation(self):
        ok, msg = self.backend.test_connection()
        self.assertTrue(ok)
        self.assertIn("Simulation Mode", msg)


class TestCLIExecution(unittest.TestCase):
    def test_find_meshcli(self):
        cfg = Config()
        backend = MeshCoreBackend(cfg)
        self.assertIsNotNone(backend._meshcli_bin)
        self.assertTrue(len(backend._meshcli_bin) > 0)


if __name__ == "__main__":
    unittest.main()
