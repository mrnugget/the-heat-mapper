# Blackbox automatic recovery backups and monitoring

## Jobs and locations

- Pi backup: `backup-blackbox.sh`, daily at 04:10 Europe/Berlin in pi's crontab.
- Pi diagnostics: `blackbox-health.py`, every minute. SMART reads every five minutes.
- NAS checks: `/volume1/homes/mrnugget/blackbox-monitor/nas-monitor.py`, every minute
  using DSM Task Scheduler. Independent runs observed at 15:52 and 15:53 CET on
  November 2, 2026, with all nine checks passing. Email delivery is not yet verified.
- NAS backups: `/volume1/homes/mrnugget/blackbox-backups/automatic/<UTC timestamp>`.
- Pi copies: `/home/pi/pi_backup/automatic/<UTC timestamp>`.
- Manual November 2 backups on the Pi, Mac and NAS are separate and never pruned.

Backups run without stopping services. Successful NAS backups retain the latest
14 automatic versions; the Pi retains two NAS-verified versions. Failed local
runs and unpublished `.partial` NAS directories remain for diagnosis and are not
counted as valid backups. Inspect/remove those manually if repeated failures
consume space. Log files on the Pi are `/home/pi/logs/blackbox-backup-*.log`.

The NAS gets the archives, this `RECOVERY.md`, `completed.txt`, `SHA256SUMS`, and
its own `verification.log`. A directory is published and `latest.json` updated
only after hashes, gzip/tar reads and extracted SQLite integrity checks pass.
`status.json` tracks job state independently of the last verified backup.
Retention runs only after a new backup passes; there is no delete-before-copy.

## Coverage and limitations

`system-and-apps.tar.gz` contains paths relative to `/`, with Linux numeric
ownership, modes, ACLs and extended attributes: `/etc`, `/boot/firmware`, `/root`,
`/usr/local`, `/opt`, user cron, Mosquitto persisted state, Tailscale state, the
Grafana volume, and `/home/pi`. This includes Home Assistant `.storage`, secrets,
TLS/SSH keys, working trees/untracked configuration, Homepage, and meter scripts.

Home Assistant and Grafana databases use SQLite's online backup API, not copies
of live database/WAL files. `prometheus-snapshot.tar.gz` contains a native TSDB
snapshot including head data. `metadata.tar.gz` records container/volume settings,
image/package versions, boot settings, disk identifiers, cron and TSDB blocks.

Excluded: old `pi_backup`, `.amp`, caches (`.cache`, `.npm`, `.bun`, `.nvm`,
`.vscode-server`), Amp runner sockets, HA logs/runtime lock and Homepage logs.
Docker image layers, container writable layers, OS binaries, most other `/var/lib`
data and the separate tinybox machine are not backed up. Images/packages must
remain obtainable for rebuilding. Other configuration is copied live; snapshots
of separate databases are not one atomic whole-system snapshot. MQTT contains
its last persisted checkpoint; Tailscale state is copied live.

This is **not a bootable disk image or a complete service restore rehearsal**.
NAS verification restores/checks the SQLite files, not running applications.

## Security

Archives contain unencrypted secrets. SSH protects transfer, directory mode 700
and file mode 600 restrict access. NAS encryption at rest has not been verified.
Never publish these archives. SSH uses existing keys and strict host-key checking;
do not disable it to resolve a connection failure.

## Restore

1. On an isolated replacement system, verify `SHA256SUMS`, gzip and tar reads.
   Extract first to a private staging directory, not over a live host.
2. Install compatible 64-bit Linux and Docker. Consult the saved image/package
   inventory. Pi 5 requires suitable power/cooling, boot files and EEPROM settings;
   the backup does not prove Pi 5 boot compatibility.
3. Restore home/application files with numeric ownership preserved on Linux.
   Merge required host configuration deliberately: do not blindly overwrite
   `/etc`, boot files, fstab or disk identifiers on replacement hardware.
4. Keep target services stopped while restoring HA configuration/database and
   Grafana's volume. Remove stale WAL/SHM from the target before placing the
   restored databases; never mix database states.
5. Restore Prometheus block directories into an **empty TSDB directory**. The
   current container uses `/prometheus/data`, so blocks belong in the volume's
   `data/` subdirectory, not its root. Preserve ownership. Do not merge with an
   existing TSDB or unrelated WAL. Start with the recorded Prometheus version.
6. Recreate containers from Compose and saved metadata, restore MQTT, meter units,
   cron and TLS renewal. Review Pi/case-specific services for the new hardware.
7. Keep the old server offline before reusing its hostname, address, Tailscale
   identity, publishers or automations. Alternatively enroll a new Tailscale node.
8. Use the meter units' permanent `/dev/serial/by-id` reader paths, not ttyUSB numbers.
9. Verify HA reaches RUNNING, Grafana queries work, Prometheus has historical and
   fresh data, targets are up, meter assignments are correct, tinybox telemetry
   arrives, and cron/TLS renewal work. Re-enable backup/monitoring jobs deliberately.

## NAS monitoring and alerts

Checks: LAN TCP reachability, SSH TCP port, Prometheus readiness, HA HTTPS front page (with
certificate verification), received Pi diagnostics, voltage/throttling flags,
CPU temperature below 80°C, SSD SMART health/temperature below 70°C, backup job
status, and backup age below 36 hours. HA HTTP availability alone does **not**
prove HA is RUNNING or that integrations work. No automatic restarts are issued.
DSM disallows ICMP ping for this user, so LAN reachability means at least one of
ports 22/9090/8123 accepts a TCP connection. Closed ports/firewalls cannot be
distinguished from a down host by that check alone.

Three consecutive failing runs alert; two healthy runs recover. Unresolved alerts
repeat every six hours. An alert run prints the failing checks and exits with
status 1, allowing DSM Task Scheduler to email its failed-run output. Normal runs
exit 0; recovery is logged, not emailed. **Email delivery requires enabling the
task's email option and testing the NAS's mail configuration.** DSM 7 rejects
plain-text custom `synodsmnotify` messages; this script does not rely on that CLI.
`events.jsonl` records alert/recovery events, not proof of email delivery.
`checks-YYYY-MM-DD.jsonl` and `health-YYYY-MM-DD.jsonl` retain 30 days on the NAS.
The health samples include uptime/boot ID, temperatures, raw throttle flags,
SMART counters and up to 40 recent kernel warnings. This is periodic sampling,
not lossless remote syslog: the final seconds of a hard failure can still be lost.

### Enable the independent NAS task

DSM → Control Panel → Task Scheduler → Create → Scheduled Task → User-defined script.
Name: `Blackbox monitoring`. User: `mrnugget`. Run daily, every one minute,
throughout the day (first run 00:00, last run 23:59). User-defined script:

```sh
/usr/bin/python3 /volume1/homes/mrnugget/blackbox-monitor/nas-monitor.py
```

Enable **Send run details by email**, choose your recipient, and select **Send
run details only when the script terminates abnormally**. Confirm the NAS email
test succeeds. The one-minute task must be enabled separately by an administrator;
copying the script or running it once does not install its schedule.

The NAS must run this independently: triggering checks from the Pi would stop
the checks at exactly the time the Pi fails. Check `state.json`'s `at` timestamp
advances without a manual invocation. A failed NAS or network path can also
prevent checks/notifications; there is no external monitor of the NAS itself.
