#!/usr/bin/env python3
"""Check independent test expectations and failure reproduction, not codec code."""
import io
from contextlib import redirect_stdout
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zlib
import check_fuzz
from check_large import verify_encoded


class OracleTests(unittest.TestCase):
    def test_framing_boundaries_and_limits(self):
        for wrapped in [False, True]:
            plain = b"oracle bytes\0" * 19
            writer = zlib.compressobj(wbits=15 if wrapped else -15)
            packed = writer.compress(plain) + writer.flush()
            self.assertEqual(check_fuzz.oracle(packed + packed, wrapped, len(packed), len(plain)),
                             (True, plain, len(packed)))
            self.assertFalse(check_fuzz.oracle(packed, wrapped, len(packed) - 1, len(plain))[0])
            self.assertFalse(check_fuzz.oracle(packed, wrapped, len(packed), len(plain) - 1)[0])
            self.assertFalse(check_fuzz.oracle(packed[:-1], wrapped, len(packed), len(plain))[0])

    def test_empty_dictionary_corrupt_and_expansion(self):
        packed = zlib.compress(b"")
        self.assertEqual(check_fuzz.oracle(packed, True, len(packed), 0), (True, b"", len(packed)))
        self.assertFalse(check_fuzz.oracle(b"not zlib", True, 8, 65536)[0])
        writer = zlib.compressobj(zdict=b"dictionary")
        packed = writer.compress(b"dictionary") + writer.flush()
        self.assertFalse(check_fuzz.oracle(packed, True, len(packed), 65536)[0])
        packed = zlib.compress(b"A" * 1048576)
        self.assertFalse(check_fuzz.oracle(packed, True, len(packed), 65536)[0])
        for limit in [-1, 65537]:
            with self.assertRaises(AssertionError): check_fuzz.oracle(packed, True, len(packed), limit)

    def test_seeded_records_and_metadata_bounds(self):
        first = list(check_fuzz.cases(19510001, 256))
        self.assertEqual(first, list(check_fuzz.cases(19510001, 256)))
        self.assertNotEqual(first, list(check_fuzz.cases(19510002, 256)))
        for index, (record, valid) in enumerate(first):
            fields = struct.unpack_from("<9I", record)
            identity, wrapped, accepted, size, decoded, consumed, input_limit, output_limit, seed = fields
            self.assertEqual((identity, accepted), (index, valid))
            self.assertIn(wrapped, [0, 1])
            self.assertLessEqual(size, 262144)
            self.assertLessEqual(decoded, 65536)
            self.assertLessEqual(consumed, size)
            self.assertEqual(len(record), 36 + size + decoded)
            self.assertGreater(seed, 0)
            result = check_fuzz.oracle(record[36:36 + size], wrapped, input_limit, output_limit)
            self.assertEqual(result, (bool(valid), record[36 + size:], consumed))

    def test_failed_child_retains_exact_reproducer(self):
        for failure in [subprocess.CompletedProcess([], -11, b"CASE 0\n", b"crash"),
                        subprocess.TimeoutExpired("driver", 30)]:
            with tempfile.TemporaryDirectory(prefix="luce-fuzz-unit-") as temporary:
                with patch.object(check_fuzz, "ROOT", Path(temporary)):
                    mock = patch.object(check_fuzz.subprocess, "run", side_effect=failure) if isinstance(failure, Exception) else patch.object(check_fuzz.subprocess, "run", return_value=failure)
                    with mock, redirect_stdout(io.StringIO()), self.assertRaises((AssertionError, subprocess.TimeoutExpired)):
                        check_fuzz.check("unused-driver", count=1)
                saved = list((Path(temporary) / "build/fuzz-failures").glob("*.bin"))
                self.assertEqual(len(saved), 1)
                expected = check_fuzz.MAGIC + struct.pack("<I", 1) + next(check_fuzz.cases(19510001, 1))[0]
                self.assertEqual(saved[0].read_bytes(), expected)

    def test_missing_success_and_sanitizer_are_failures(self):
        for output, error in [(b"", b""), (b"PASS batch 1\n", b"AddressSanitizer"),
                              (b"PASS batch 1\n", b"runtime error: invalid")]:
            with tempfile.TemporaryDirectory(prefix="luce-fuzz-unit-") as temporary:
                with patch.object(check_fuzz, "ROOT", Path(temporary)), patch.object(check_fuzz.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output, error)):
                    with redirect_stdout(io.StringIO()), self.assertRaises(AssertionError): check_fuzz.check("unused-driver", count=1)

    def test_read_only_reproducer_preserves_original_failure(self):
        transcript = io.StringIO()
        failure = subprocess.CompletedProcess([], -11, b"CASE 0\n", b"crash")
        with patch.object(check_fuzz.subprocess, "run", return_value=failure), patch.object(Path, "mkdir", side_effect=PermissionError("read-only bundle")):
            with redirect_stdout(transcript), self.assertRaises(AssertionError) as caught:
                check_fuzz.check("unused-driver", count=1)
        self.assertIn("-11", str(caught.exception))
        self.assertIn("FUZZ seed=19510001 cases=1", transcript.getvalue())
        self.assertIn("batch_sha256=", transcript.getvalue())
        self.assertIn("REPRO_UNAVAILABLE", transcript.getvalue())

    def test_large_bounded_oracle_and_negatives(self):
        for window in [-15, 15]:
            plain = b"abc\0" * 65537
            writer = zlib.compressobj(wbits=window)
            packed = writer.compress(plain) + writer.flush()
            verify_encoded(io.BytesIO(plain), io.BytesIO(packed), window, len(plain))
            for expected, data, limit in [(plain, packed[:-1], len(plain)),
                                          (plain, packed + b"trailer", len(plain)),
                                          (b"wrong bytes", packed, len(plain)),
                                          (plain, packed, len(plain) - 1)]:
                with self.assertRaises((AssertionError, zlib.error)):
                    verify_encoded(io.BytesIO(expected), io.BytesIO(data), window, limit)


if __name__ == "__main__":
    unittest.main()
