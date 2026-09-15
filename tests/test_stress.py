#!/usr/bin/env python3
"""Negative tests for the measurement harness, separate from codec correctness."""
import os
import subprocess
import sys
import unittest
from unittest.mock import patch
from check_stress import measured, parse, percentile, rss_bytes


def report():
    lines = ["RESULT 1 1 1 1 3 100 1"]
    for name in ["encode", "decode"]:
        lines.append(f"CALLS {name} 2 3 1 4 2")
        lines += [f"HIST {name} {bucket} {2 if bucket == 1 else 0}" for bucket in range(64)]
    return "\n".join(lines)


class StressHarnessTests(unittest.TestCase):
    def test_report_and_quantiles(self):
        result = parse(report(), 1, 1, 1, 2)
        self.assertEqual(result["input_bytes"], 1)
        self.assertEqual(result["encode"]["p99_upper_ns"], 2)
        self.assertEqual(percentile([1, 1, 98], 50), 4)

    def test_platform_units(self):
        self.assertEqual(rss_bytes(2048, "darwin"), 2048)
        self.assertEqual(rss_bytes(2048, "linux"), 2097152)
        with self.assertRaises(RuntimeError): rss_bytes(2048, "win32")

    def test_incomplete_duplicate_unknown_reports(self):
        for text in [report().split("HIST decode 63")[0], report() + "\n" + report(),
                     report() + "\nHIST encode 64 0", report() + "\nUNKNOWN 1"]:
            with self.subTest(text=text[-40:]), self.assertRaises(AssertionError):
                parse(text, 1, 1, 1, 2)

    def test_wrong_totals_and_work(self):
        for before, after in [("RESULT 1 1 1 1", "RESULT 1 1 1 2"),
                              ("3 100 1", "3 100 0"),
                              ("2 3 1 4 2", "2 5 1 4 2"),
                              ("2 3 1 4 2", "2 3 2 4 2"),
                              ("HIST encode 1 2", "HIST encode 1 -1"),
                              ("2 3 1 4 2", "2 3 1 4 4")]:
            with self.subTest(after=after), self.assertRaises(AssertionError):
                parse(report().replace(before, after), 1, 1, 1, 2)

    def test_child_resources(self):
        text, usage = measured([sys.executable, "-c", "print('child')"])
        self.assertEqual(text.strip(), "child")
        self.assertGreater(usage["peak_rss_bytes"], 0)
        self.assertGreaterEqual(usage["cpu_seconds"], 0)

    def test_refuses_failure_signal_and_sanitizer(self):
        for source in ["raise SystemExit(1)", "import os,signal; os.kill(os.getpid(), signal.SIGTERM)",
                       "print('AddressSanitizer')", "print('runtime error: invalid access')"]:
            with self.subTest(source=source), self.assertRaises(AssertionError):
                measured([sys.executable, "-c", source])

    def test_timeout_kills_and_reaps_own_child(self):
        children = []
        original = subprocess.Popen
        def launch(*args, **kwargs):
            child = original(*args, **kwargs)
            children.append(child)
            return child
        with patch("check_stress.subprocess.Popen", side_effect=launch):
            with self.assertRaises(TimeoutError):
                measured([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.03)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].returncode)
        with self.assertRaises(ChildProcessError): os.waitpid(children[0].pid, os.WNOHANG)

    def test_refuses_excessive_output(self):
        with self.assertRaises(AssertionError):
            measured([sys.executable, "-c", "print('X' * 65537)"])


if __name__ == "__main__":
    unittest.main()
