"""Process supervision without starting servers or running migrations."""

import os
import subprocess
import threading
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from config import web_runtime


class WebRuntimeTests(SimpleTestCase):
    def test_worker_defaults_off_and_requires_explicit_flag(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(web_runtime.worker_requested())
        with patch.dict(os.environ, {"PAYSTACK_LIVE_ENABLED": "True"}):
            self.assertTrue(web_runtime.worker_requested())

    def test_web_command_keeps_hosting_port_and_existing_tuning(self):
        with patch.dict(os.environ, {"PORT": "8080", "WEB_CONCURRENCY": "3"}):
            command = web_runtime.web_command()
        self.assertIn("0.0.0.0:8080", command)
        self.assertEqual(command[command.index("--workers") + 1], "3")

    @patch("config.web_runtime.subprocess.Popen")
    def test_dead_worker_stops_web_and_exits_nonzero(self, popen):
        worker, web = Mock(), Mock()
        worker.poll.return_value = 1
        web.poll.return_value = None
        popen.side_effect = [worker, web]
        self.assertEqual(web_runtime.supervise([["worker"], ["web"]], threading.Event()), 1)
        web.terminate.assert_called_once()
        web.wait.assert_called_once()

    @patch("config.web_runtime.subprocess.Popen")
    def test_shutdown_terminates_and_reaps_children(self, popen):
        process = popen.return_value
        process.poll.return_value = None
        stopped = threading.Event()
        stopped.set()
        self.assertEqual(web_runtime.supervise([["web"]], stopped), 0)
        process.terminate.assert_called_once()
        process.wait.assert_called_once()

    @patch("config.web_runtime.subprocess.Popen")
    def test_shutdown_kills_child_if_graceful_stop_times_out(self, popen):
        process = popen.return_value
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("web", 25), 0]
        stopped = threading.Event()
        stopped.set()
        web_runtime.supervise([["web"]], stopped)
        process.kill.assert_called_once()

    @patch("config.web_runtime.subprocess.run")
    @patch("config.web_runtime.supervise")
    def test_failed_migrations_never_start_web_or_worker(self, supervise, run):
        run.return_value.returncode = 1
        self.assertEqual(web_runtime.main(), 1)
        supervise.assert_not_called()

    @patch("config.web_runtime.subprocess.run")
    @patch("config.web_runtime.supervise", return_value=0)
    def test_worker_is_included_only_when_enabled(self, supervise, run):
        run.return_value.returncode = 0
        with patch.dict(os.environ, {"PAYSTACK_LIVE_ENABLED": "False"}):
            web_runtime.main()
            self.assertEqual(len(supervise.call_args.args[0]), 1)
        with patch.dict(os.environ, {"PAYSTACK_LIVE_ENABLED": "True"}):
            web_runtime.main()
            commands = supervise.call_args.args[0]
            self.assertEqual(len(commands), 2)
            self.assertIn("process_paystack_live_events", commands[0])
