#!/usr/bin/env python3
"""Record Pi diagnostics and send a private heartbeat to kinakuta over SSH."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time


def output(args):
    return subprocess.check_output(args, text=True, timeout=15).strip()


def main():
    os.umask(0o077)
    directory = Path('/home/pi/logs')
    with (directory / 'blackbox-health.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        now = time.time()
        cache = directory / 'blackbox-smart.json'
        smart = json.loads(cache.read_text()) if cache.exists() else {}
        if now - smart.get('sampled_at', 0) >= 300:
            result = subprocess.run([
                'sudo', '-n', '/home/pi/bin/smartctl', '-HAj',
                '/dev/disk/by-id/usb-Argon_Forty_0000000000E4-0:0'],
                capture_output=True, text=True, timeout=20)
            data = json.loads(result.stdout)
            # Bits 0-2 mean the command/device failed; the remaining bits report drive health.
            if result.returncode & 7:
                raise RuntimeError('SMART command failed (status %s)' % result.returncode)
            attributes = {x['id']: x['raw']['value']
                          for x in data.get('ata_smart_attributes', {}).get('table', [])}
            smart = {'sampled_at': now, 'passed': data.get('smart_status', {}).get('passed'),
                     'temperature_c': data.get('temperature', {}).get('current'),
                     'unexpected_power_losses': attributes.get(174),
                     'command_timeouts': attributes.get(188),
                     'reallocated_sectors': attributes.get(5),
                     'uncorrectable_errors': attributes.get(187),
                     'sata_crc_errors': attributes.get(199)}
            cache.write_text(json.dumps(smart) + '\n')
        machine = Path('/etc/machine-id').read_text().strip()
        warnings = output([
            'sudo', '-n', 'journalctl',
            '--file=/var/log/journal/' + machine + '/system.journal',
            '_TRANSPORT=kernel', '--since=-2 minutes', '-p', 'warning',
            '-n', '40', '--no-pager', '-o', 'short-iso'])
        sample = {'sampled_at': now,
                  'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  'uptime_seconds': float(Path('/proc/uptime').read_text().split()[0]),
                  'cpu_c': int(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000,
                  'throttled': int(output(['vcgencmd', 'get_throttled']).split('=')[1], 16),
                  'smart': smart, 'kernel_warnings': warnings.splitlines()}
        encoded = json.dumps(sample) + '\n'
        (directory / 'blackbox-health.json').write_text(encoded)
        subprocess.run([
            'ssh', '-p', '44191', '-o', 'HostKeyAlias=kinakuta', '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
            'mrnugget@kinakuta',
            'python3 /volume1/homes/mrnugget/blackbox-monitor/nas-monitor.py --receive-health'],
            input=encoded, text=True, check=True, timeout=30)


if __name__ == '__main__':
    main()
