"""Unit and integration tests for MeshCore TUI client."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.assertEqual(cfg.refresh_interval, 5)

    def test_refresh_interval_getter_is_robust_and_clamped(self):
        cfg = Config(config_file=None)
        cases = (
            (None, 5),
            ("invalid", 5),
            (float("inf"), 5),
            (-10, 1),
            (0, 1),
            (1, 1),
            ("42", 42),
            (300, 300),
            (301, 300),
        )
        for raw_value, expected in cases:
            with self.subTest(raw_value=raw_value, expected=expected):
                cfg.data["refresh_interval"] = raw_value
                self.assertEqual(cfg.refresh_interval, expected)

    def test_refresh_interval_setter_persists(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.json"
            cfg = Config(config_file=config_file)
            cfg.refresh_interval = 30
            self.assertEqual(Config(config_file=config_file).refresh_interval, 30)

            cfg.refresh_interval = 0
            self.assertEqual(Config(config_file=config_file).refresh_interval, 1)
            cfg.refresh_interval = 301
            self.assertEqual(Config(config_file=config_file).refresh_interval, 300)

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
            (["public", "Test Message"], "[Sent] Public Broadcast sent"),
            (["msg", "Mobile-Bravo", "Direct test"], "[ACK] Direct Message"),
            (["chan", "1", "Channel test"], "[Sent] Channel 1 message sent"),
            (["get_channels"], "Configured Channels"),
            (["sync_msgs"], "Synchronized Messages"),
            (["login", "Rep1", "pass123"], "Successfully logged into repeater"),
            (["logout", "Rep1"], "Logged out of repeater"),
            (["req_status", "Rep1"], "Status of Repeater"),
            (["card"], "Own Node Card"),
            (["export_contact", "BaseStation-1"], "Contact Card for 'BaseStation-1'"),
            (["req_neighbours", "BaseStation-1"], "Neighbours of Repeater"),
            (["req_telemetry", "Sensor-Weather"], "Telemetry Data for 'Sensor-Weather'"),
            (["trace", "BaseStation-1"], "Traceroute for 'BaseStation-1'"),
            (["cmd", "BaseStation-1", "status"], "Remote command 'status'"),
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

    def test_unknown_simulation_command(self):
        ok, out = self.backend.run_cli(["definitely_not_a_meshcore_command"])
        self.assertFalse(ok)
        self.assertIn("Unknown simulation command", out)

    def test_set_channel_is_stateful(self):
        ok, out = self.backend.run_cli(["set_channel", "7", "Operations", "SecretOpsKey"])
        self.assertTrue(ok, out)

        ok, out = self.backend.run_cli(["get_channels"])
        self.assertTrue(ok, out)
        self.assertIn("[CH 7] Name: Operations | Key: SecretOpsKey", out)

        ok, out = self.backend.run_cli(["set_channel", "7", "Operations-Renamed", "NewOpsKey"])
        self.assertTrue(ok, out)
        ok, out = self.backend.run_cli(["get_channels"])
        self.assertTrue(ok, out)
        self.assertIn("[CH 7] Name: Operations-Renamed | Key: NewOpsKey", out)
        self.assertNotIn("Name: Operations |", out)
        self.assertEqual(out.count("[CH 7]"), 1)

        ok, _ = self.backend.run_cli(["set_channel", "8", "Invalid"])
        self.assertFalse(ok)

    def test_remove_channel_is_stateful_by_number_and_exact_name(self):
        ok, out = self.backend.run_cli(["remove_channel", "1"])
        self.assertTrue(ok, out)
        self.assertNotIn(1, [channel["num"] for channel in self.backend._sim_channels])

        ok, out = self.backend.run_cli(["get_channels"])
        self.assertTrue(ok, out)
        self.assertNotIn("[CH 1]", out)
        for target in ("1", "Emergency"):
            ok, out = self.backend.run_cli(["chan", target, "nach dem Löschen"])
            self.assertFalse(ok)
            self.assertIn("Invalid channel", out)

        ok, out = self.backend.run_cli(["remove_channel", "Local-Team"])
        self.assertTrue(ok, out)
        self.assertNotIn(2, [channel["num"] for channel in self.backend._sim_channels])
        ok, out = self.backend.run_cli(["get_channels"])
        self.assertTrue(ok, out)
        self.assertNotIn("Name: Local-Team", out)
        ok, out = self.backend.run_cli(["chan", "Local-Team", "nach dem Löschen"])
        self.assertFalse(ok)

        ok, out = self.backend.run_cli(["set_channel", "7", "Operations"])
        self.assertTrue(ok, out)
        ok, out = self.backend.run_cli(["remove_channel", "7"])
        self.assertTrue(ok, out)
        self.assertNotIn(7, [channel["num"] for channel in self.backend._sim_channels])

    def test_remove_channel_rejects_public_unknown_and_inexact_targets(self):
        channels_before = [dict(channel) for channel in self.backend._sim_channels]
        invalid_args = (
            ["remove_channel"],
            ["remove_channel", "0"],
            ["remove_channel", "Public (Default)"],
            ["remove_channel", "-1"],
            ["remove_channel", "8"],
            ["remove_channel", "7"],
            ["remove_channel", "emergency"],
            ["remove_channel", "Emer"],
            ["remove_channel", "Unknown"],
        )
        for args in invalid_args:
            with self.subTest(args=args):
                ok, out = self.backend.run_cli(args)
                self.assertFalse(ok)
                self.assertIn("Invalid channel", out)
                self.assertEqual(self.backend._sim_channels, channels_before)

    def test_add_pending_rejects_unknown_contact(self):
        contacts_before = [dict(contact) for contact in self.backend._sim_contacts]
        heard_before = [dict(node) for node in self.backend._sim_heard]

        ok, out = self.backend.run_cli(["add_pending", "Not-Heard-Anywhere"])
        self.assertFalse(ok)
        self.assertIn("does not exist", out)
        self.assertEqual(self.backend._sim_contacts, contacts_before)
        self.assertEqual(self.backend._sim_heard, heard_before)

    def test_msg_optional_ack_and_unknown_contact(self):
        ok, out = self.backend.run_cli(["msg", "-a", "Mobile-Bravo", "Acknowledged test"])
        self.assertTrue(ok, out)
        self.assertIn("to 'Mobile-Bravo'", out)
        self.assertIn("Acknowledged test", out)
        self.assertNotIn("to '-a'", out)

        for args in (
            ["msg", "Unknown-Contact", "Hello"],
            ["msg", "-a", "Unknown-Contact", "Hello"],
        ):
            with self.subTest(args=args):
                ok, out = self.backend.run_cli(args)
                self.assertFalse(ok)
                self.assertIn("Unknown destination/contact", out)

    def test_channel_names_and_numbers_are_validated(self):
        for target in ("1", "Emergency"):
            with self.subTest(target=target):
                ok, out = self.backend.run_cli(["chan", target, "Channel test"])
                self.assertTrue(ok, out)
                self.assertTrue(out.startswith("[Sent]"))
                self.assertNotIn("[ACK]", out)

        for target in ("8", "Not-A-Channel"):
            with self.subTest(target=target):
                ok, out = self.backend.run_cli(["chan", target, "Channel test"])
                self.assertFalse(ok)
                self.assertIn("Invalid channel", out)

    def test_test_connection_simulation(self):
        ok, msg = self.backend.test_connection()
        self.assertTrue(ok)
        self.assertIn("Simulation Mode", msg)


class TestCLIExecution(unittest.TestCase):
    @staticmethod
    def _make_backend(port="/dev/ttyMock0"):
        cfg = Config(config_file=None)
        cfg.port = port
        return MeshCoreBackend(cfg)

    @patch("src.backend.executor.subprocess.run")
    def test_zero_exit_application_errors(self, mock_run):
        backend = self._make_backend()
        error_outputs = (
            "Error: command failed",
            "Error sending message: EventType.ERROR",
            "Error setting channel",
            "Error while requesting channel info",
            "Error removing contact: EventType.ERROR",
            "Unknown destination: Nobody",
            "Unknown contact: Nobody",
            "Invalid channel: 8",
            "No ack received",
            "Login failed : Error or Timeout waiting response",
            "Bad path format xyz",
            "Timeout",
            "Problem while executing msg",
            "Contact 'Nobody' does not exist",
            "Traceback (most recent call last):\n  File \"meshcli\", line 1",
            '{"error": "command failed"}',
            '{"ack": false}',
        )
        for output in error_outputs:
            with self.subTest(output=output):
                mock_run.return_value = subprocess.CompletedProcess(
                    args=["meshcli"], returncode=0, stdout=output, stderr=""
                )
                ok, out = backend.run_cli(["msg", "Nobody", "Hello"])
                self.assertFalse(ok)
                self.assertIn(output.splitlines()[0], out)

    @patch("src.backend.executor.subprocess.run")
    def test_zero_exit_error_on_stderr(self, mock_run):
        backend = self._make_backend()
        mock_run.return_value = subprocess.CompletedProcess(
            args=["meshcli"],
            returncode=0,
            stdout="Command output",
            stderr="Error: could not open port /dev/ttyMock0",
        )

        ok, out = backend.run_cli(["infos"])
        self.assertFalse(ok)
        self.assertIn("Command output", out)
        self.assertIn("could not open port", out)

    @patch("src.backend.executor.subprocess.run")
    def test_connection_to_nonexistent_port_fails(self, mock_run):
        port = "/dev/definitely-not-a-meshcore-port"
        backend = self._make_backend(port)
        mock_run.return_value = subprocess.CompletedProcess(
            args=["meshcli"],
            returncode=0,
            stdout="",
            stderr=f"serial.serialutil.SerialException: could not open port {port}",
        )

        ok, out = backend.test_connection()
        self.assertFalse(ok)
        self.assertIn(port, out)
        mock_run.assert_called_once()

    @patch("src.backend.executor.subprocess.run")
    def test_normal_output_containing_error_words_is_successful(self, mock_run):
        backend = self._make_backend()
        normal_outputs = (
            "Message sent: 'error, Timeout and No ack received are only message text'.",
            "Contact Information:\nTimeout: 120s",
            '{"ack": true, "text": "No error in the message"}',
        )
        for output in normal_outputs:
            with self.subTest(output=output):
                mock_run.return_value = subprocess.CompletedProcess(
                    args=["meshcli"], returncode=0, stdout=output, stderr=""
                )
                ok, out = backend.run_cli(["infos"])
                self.assertTrue(ok, out)
                self.assertEqual(out, output)

    def test_find_meshcli(self):
        cfg = Config()
        backend = MeshCoreBackend(cfg)
        self.assertIsNotNone(backend._meshcli_bin)
        self.assertTrue(len(backend._meshcli_bin) > 0)


if __name__ == "__main__":
    unittest.main()
