"""Alert contract tests; real NAS connectivity is checked separately during deployment."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('nas_monitor', Path(__file__).with_name('nas-monitor.py'))
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.backups = self.directory / 'backups'
        self.backups.mkdir()
        self.now = time.time()
        self.http_ok = True
        self.health = {'received_at': self.now, 'throttled': 0, 'cpu_c': 60,
                       'smart': {'passed': True, 'temperature_c': 61, 'sampled_at': self.now}}
        self.save(self.backups / 'latest.json', {'verified_at': self.now})
        self.save(self.backups / 'status.json', {'state': 'success', 'at': self.now})

    def save(self, path, value):
        path.write_text(json.dumps(value))

    def run_check(self):
        self.save(self.directory / 'latest-health.json', self.health)
        argv = ['nas-monitor.py', '--directory', str(self.directory), '--backup-root', str(self.backups)]
        with patch('sys.argv', argv), patch.object(monitor.time, 'time', return_value=self.now), \
                patch.object(monitor.socket, 'create_connection'), \
                patch.object(monitor.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0 if self.http_ok else 22)), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            result = monitor.main()
        return result, json.loads(output.getvalue().splitlines()[-1])

    def test_outage_debounce_repeat_and_recovery(self):
        self.assertEqual(self.run_check()[0], 0)
        self.http_ok = False
        self.assertEqual(self.run_check()[1]['active_alerts'], [])
        self.assertEqual(self.run_check()[1]['active_alerts'], [])
        code, result = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(result['active_alerts'], ['homeassistant_http', 'prometheus'])
        self.assertTrue(result['checks']['lan_reachable'])  # Services failed, not LAN.
        self.assertEqual(self.run_check()[0], 0)  # Do not email every minute.
        self.now += 6 * 3600 + 1
        self.health['received_at'] = self.now
        self.health['smart']['sampled_at'] = self.now
        self.assertEqual(self.run_check()[0], 1)
        self.http_ok = True
        self.assertNotEqual(self.run_check()[1]['active_alerts'], [])
        self.assertEqual(self.run_check()[1]['active_alerts'], [])
        events = [json.loads(line) for line in (self.directory / 'events.jsonl').read_text().splitlines()]
        self.assertEqual(len(events), 3)
        self.assertEqual(events[-1]['message'], 'All Blackbox checks recovered.')

    def test_transient_failure_resets_and_backup_failure_is_independent_of_age(self):
        self.http_ok = False
        self.assertEqual(self.run_check()[0], 0)
        self.http_ok = True
        self.assertEqual(self.run_check()[0], 0)
        self.http_ok = False
        self.assertEqual(self.run_check()[1]['active_alerts'], [])
        self.assertEqual(self.run_check()[1]['active_alerts'], [])
        self.http_ok = True
        self.save(self.backups / 'status.json', {'state': 'failed', 'at': self.now})
        for _ in range(2):
            self.assertEqual(self.run_check()[0], 0)
        code, result = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(result['active_alerts'], ['backup_job'])
        self.assertTrue(result['checks']['backup_fresh'])

    def test_freshness_temperature_and_voltage_boundaries(self):
        self.health['received_at'] = self.now - 179
        self.health['smart']['sampled_at'] = self.now - 899
        self.health['smart']['temperature_c'] = 69
        self.save(self.backups / 'latest.json', {'verified_at': self.now - 36 * 3600 + 1})
        self.save(self.backups / 'status.json', {'state': 'running', 'at': self.now - 3 * 3600 + 1})
        self.assertTrue(all(self.run_check()[1]['checks'].values()))
        for field, value, check in [
            ('received_at', self.now - 180, 'health_heartbeat'),
            ('cpu_c', 80, 'pi_voltage_temperature'),
            ('throttled', 0x10000, 'pi_voltage_temperature'),
        ]:
            original = self.health[field]
            self.health[field] = value
            self.assertFalse(self.run_check()[1]['checks'][check], field)
            self.health[field] = original
        for field, value in [('sampled_at', self.now - 900), ('sampled_at', self.now + 1),
                             ('temperature_c', 70), ('passed', False)]:
            original = self.health['smart'][field]
            self.health['smart'][field] = value
            self.assertFalse(self.run_check()[1]['checks']['ssd_health_temperature'], field)
            self.health['smart'][field] = original
        self.save(self.backups / 'latest.json', {'verified_at': self.now - 36 * 3600})
        self.save(self.backups / 'status.json', {'state': 'running', 'at': self.now - 3 * 3600})
        checks = self.run_check()[1]['checks']
        for name in ['backup_fresh', 'backup_job']:
            self.assertFalse(checks[name], name)


if __name__ == '__main__':
    unittest.main()
