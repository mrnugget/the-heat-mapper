#!/usr/bin/env python3
"""Run once per minute on kinakuta; --receive-health accepts a Pi heartbeat on stdin."""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value) + '\n')
    temporary.replace(path)


def read_json(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def append(path, value):
    with path.open('a') as stream:
        stream.write(json.dumps(value, sort_keys=True) + '\n')


def command_ok(args):
    try:
        return subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=8).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--backup-root', type=Path,
                        default=Path.home() / 'blackbox-backups/automatic')
    parser.add_argument('--host', default='192.168.1.49')
    parser.add_argument('--receive-health', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    directory = args.directory
    directory.mkdir(parents=True, exist_ok=True)
    now = time.time()
    day = datetime.datetime.now().strftime('%Y-%m-%d')
    lock_name = 'receive.lock' if args.receive_health else 'check.lock'
    with (directory / lock_name).open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if args.receive_health:
            sample = json.loads(sys.stdin.read(65537))
            sample['received_at'] = now
            append(directory / ('health-' + day + '.jsonl'), sample)
            write_json(directory / 'latest-health.json', sample)
            return

        # DSM restricts ICMP ping to root. TCP checks work as the normal NAS user
        # and separate reachable ports from application HTTP readiness.
        ports = {}
        for port in (22, 9090, 8123):
            try:
                with socket.create_connection((args.host, port), timeout=3):
                    ports[port] = True
            except OSError:
                ports[port] = False
        checks = {'lan_reachable': any(ports.values()), 'ssh_port': ports[22]}
        checks['prometheus'] = command_ok([
            'curl', '--fail', '--silent', '--max-time', '5',
            'http://' + args.host + ':9090/-/ready'])
        checks['homeassistant_http'] = command_ok([
            'curl', '--fail', '--silent', '--max-time', '5', '--resolve',
            'blackbox.dingo-cobra.ts.net:8123:' + args.host,
            'https://blackbox.dingo-cobra.ts.net:8123/'])
        health = read_json(directory / 'latest-health.json')
        checks['health_heartbeat'] = 0 <= now - health.get('received_at', 0) < 180
        checks['pi_voltage_temperature'] = bool(health) and (
            health.get('throttled') == 0 and health.get('cpu_c', 100) < 80)
        smart = health.get('smart', {})
        checks['ssd_health_temperature'] = (
            smart.get('passed') is True and smart.get('temperature_c', 100) < 70
            and 0 <= now - smart.get('sampled_at', 0) < 900)
        backup = read_json(args.backup_root / 'latest.json')
        status = read_json(args.backup_root / 'status.json')
        checks['backup_fresh'] = 0 <= now - backup.get('verified_at', 0) < 36 * 3600
        checks['backup_job'] = status.get('state') == 'success' or (
            status.get('state') == 'running' and 0 <= now - status.get('at', 0) < 3 * 3600)

        previous = read_json(directory / 'state.json')
        counts = previous.get('counts', {})
        active = set(previous.get('active', []))
        for name, ok in checks.items():
            count = counts.get(name, 0)
            count = max(0, count) + 1 if not ok else min(0, count) - 1
            counts[name] = max(-3, min(3, count))
            if count >= 3:
                active.add(name)
            elif count <= -2:
                active.discard(name)
        active = sorted(active)
        announced = previous.get('announced', [])
        last_alert = previous.get('last_alert', 0)
        exit_code = 0
        if active != announced or (active and now - last_alert >= 6 * 3600):
            message = ('Failing checks: ' + ', '.join(active)) if active else 'All Blackbox checks recovered.'
            append(directory / 'events.jsonl', {'at': now, 'message': message})
            print(message, flush=True)
            # DSM Task Scheduler can email failed-run output. No custom DSM package
            # or notification credentials are needed. Recovery is recorded locally.
            exit_code = 1 if active else 0
            announced = active
            last_alert = now
        write_json(directory / 'state.json', {
            'at': now, 'counts': counts, 'active': active,
            'announced': announced, 'last_alert': last_alert})
        append(directory / ('checks-' + day + '.jsonl'), {'at': now, 'checks': checks})
        print(json.dumps({'checks': checks, 'active_alerts': active}), flush=True)
        for pattern in ('health-????-??-??.jsonl', 'checks-????-??-??.jsonl'):
            for path in directory.glob(pattern):
                if now - path.stat().st_mtime > 30 * 86400:
                    path.unlink()
        return exit_code


if __name__ == '__main__':
    sys.exit(main())
