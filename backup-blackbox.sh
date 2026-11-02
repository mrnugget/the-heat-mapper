#!/usr/bin/env bash
# Daily, online recovery backup. Only this job's automatic backups are pruned.
set -euo pipefail
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
exec 9>/home/pi/logs/blackbox-backup.lock
flock -n 9 || exit 0
run=$(date -u +%Y%m%dT%H%M%SZ)
root=/home/pi/pi_backup/automatic
dest="$root/$run"
stage="$dest/staging"
nas=/volume1/homes/mrnugget/blackbox-backups/automatic
snapshot=''
ssh=(ssh -p 44191 -o HostKeyAlias=kinakuta -o BatchMode=yes
     -o StrictHostKeyChecking=yes -o ConnectTimeout=10
     -o ServerAliveInterval=15 -o ServerAliveCountMax=3 mrnugget@kinakuta)
mkdir -p "$stage"
exec > >(tee -a "/home/pi/logs/blackbox-backup-$run.log") 2>&1

nas_status() {
    "${ssh[@]}" python3 - "$nas" "$1" "$run" <<'PY'
import json, os, sys, time
from pathlib import Path
os.umask(0o077)
root, state, run = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
root.mkdir(parents=True, exist_ok=True)
path = root / 'status.tmp'
path.write_text(json.dumps({'state': state, 'run': run, 'at': time.time()}) + '\n')
path.replace(root / 'status.json')
PY
}

finish() {
    code=$?
    trap - EXIT
    if (( code != 0 )); then
        echo "FAILED: backup $run (exit $code); previous verified backups are untouched"
        nas_status failed || true
    fi
    sudo -n rm -rf -- "$stage"
    if [[ "$snapshot" =~ ^[0-9]{8}T[0-9]{6}Z-[a-f0-9]+$ ]]; then
        sudo -n rm -rf -- "/var/lib/docker/volumes/the-heat-mapper_prometheus/_data/data/snapshots/$snapshot"
    fi
    exit "$code"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Starting backup $run"
(( $(df -Pk "$root" | awk 'NR==2 {print $4}') > 10 * 1024 * 1024 ))
nas_status running
curl -fsS --max-time 15 http://localhost:9090/api/v1/status/flags |
    python3 -c 'import json,sys; assert json.load(sys.stdin)["data"]["storage.tsdb.path"] == "data/", "Recheck Prometheus TSDB location"'
mkdir -p "$dest/metadata"
curl -fsS --max-time 180 -X POST \
    'http://localhost:9090/api/v1/admin/tsdb/snapshot?skip_head=false' > "$dest/metadata/prometheus-snapshot.json"
snapshot=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["status"]=="success"; print(d["data"]["name"])' "$dest/metadata/prometheus-snapshot.json")
[[ "$snapshot" =~ ^[0-9]{8}T[0-9]{6}Z-[a-f0-9]+$ ]]

echo 'Copying configuration and persistent files'
sudo -n rsync -aHAX --numeric-ids --relative \
    /etc /boot/firmware /var/lib/tailscale /var/lib/mosquitto /var/spool/cron /root /usr/local /opt "$stage/"
sudo -n rsync -aHAX --numeric-ids --relative \
    --exclude='/home/pi/pi_backup/' --exclude='/home/pi/.amp/' \
    --exclude='/home/pi/.cache/' --exclude='/home/pi/.npm/' \
    --exclude='/home/pi/.bun/' --exclude='/home/pi/.nvm/' \
    --exclude='/home/pi/.vscode-server/' --exclude='/home/pi/.local/share/amp/runner/' \
    --exclude='/home/pi/homeassistantconfig/home-assistant_v2.db*' \
    --exclude='/home/pi/homeassistantconfig/home-assistant.log*' \
    --exclude='/home/pi/homeassistantconfig/.ha_run.lock' \
    --exclude='/home/pi/homepage/config/logs/' /home/pi "$stage/"
sudo -n mkdir -p "$stage/var/lib/docker/volumes/the-heat-mapper_grafana/_data"
sudo -n rsync -aHAX --numeric-ids --exclude='grafana.db*' \
    /var/lib/docker/volumes/the-heat-mapper_grafana/_data/ \
    "$stage/var/lib/docker/volumes/the-heat-mapper_grafana/_data/"

echo 'Online SQLite backups and integrity checks'
sudo -n python3 - "$stage" <<'PY'
import os, sqlite3, sys
from pathlib import Path
for name in ['/home/pi/homeassistantconfig/home-assistant_v2.db',
             '/var/lib/docker/volumes/the-heat-mapper_grafana/_data/grafana.db']:
    source = Path(name)
    target = Path(sys.argv[1]) / source.relative_to('/')
    with sqlite3.connect('file:' + name + '?mode=ro', uri=True, timeout=60) as src:
        with sqlite3.connect(target) as dst:
            src.backup(dst, pages=1024, sleep=0.05)
            assert dst.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    stat = source.stat()
    os.chown(target, stat.st_uid, stat.st_gid)
    os.chmod(target, stat.st_mode & 0o777)
    print(source.name + ': integrity_check=ok', flush=True)
PY

docker inspect $(docker ps -aq) > "$dest/metadata/containers.json"
docker image ls --digests --no-trunc > "$dest/metadata/images.txt"
docker volume inspect $(docker volume ls -q) > "$dest/metadata/volumes.json"
dpkg-query -W -f='${binary:Package}\t${Version}\n' > "$dest/metadata/packages.tsv"
crontab -l > "$dest/metadata/pi-crontab.txt"
lsblk -o NAME,SIZE,MODEL,SERIAL,FSTYPE,UUID,PARTUUID,MOUNTPOINTS > "$dest/metadata/storage.txt"
vcgencmd bootloader_config > "$dest/metadata/bootloader.txt"
systemctl list-unit-files --state=enabled --no-pager > "$dest/metadata/enabled-units.txt"
docker exec the-heat-mapper-prometheus-1 promtool tsdb list "/prometheus/data/snapshots/$snapshot" > "$dest/metadata/prometheus-blocks.txt"

echo 'Compressing recovery archives'
sudo -n tar --acls --xattrs --numeric-owner -C "$stage" -cf - . | nice -n 10 gzip -1 > "$dest/system-and-apps.tar.gz"
sudo -n tar --acls --xattrs --numeric-owner \
    -C "/var/lib/docker/volumes/the-heat-mapper_prometheus/_data/data/snapshots/$snapshot" -cf - . |
    nice -n 10 gzip -1 > "$dest/prometheus-snapshot.tar.gz"
tar -C "$dest" -czf "$dest/metadata.tar.gz" metadata
cp /home/pi/the-heat-mapper/BACKUP-RECOVERY.md "$dest/RECOVERY.md"
gzip -t "$dest/system-and-apps.tar.gz" "$dest/prometheus-snapshot.tar.gz" "$dest/metadata.tar.gz"
date --iso-8601=seconds > "$dest/completed.txt"
(cd "$dest"; sha256sum system-and-apps.tar.gz prometheus-snapshot.tar.gz metadata.tar.gz RECOVERY.md completed.txt > SHA256SUMS)

echo 'Transferring to a private, unpublished NAS directory'
"${ssh[@]}" "umask 077; mkdir '$nas/.$run.partial'"
tar -C "$dest" -cf - system-and-apps.tar.gz prometheus-snapshot.tar.gz metadata.tar.gz RECOVERY.md completed.txt SHA256SUMS |
    "${ssh[@]}" "umask 077; tar -xf - -C '$nas/.$run.partial'"
echo 'Verifying the NAS copy, including extracted SQLite databases'
"${ssh[@]}" python3 - "$nas" "$run" <<'PY'
import contextlib, json, os, re, shutil, sqlite3, subprocess, sys, tarfile, tempfile, time
from pathlib import Path
os.umask(0o077)
root, run = Path(sys.argv[1]), sys.argv[2]
partial = root / ('.' + run + '.partial')
with (partial / 'verification.log').open('w') as log:
    with contextlib.redirect_stdout(log):
        subprocess.run(['sha256sum', '-c', 'SHA256SUMS'], cwd=partial, stdout=log, stderr=log, check=True)
        for name in ['system-and-apps.tar.gz', 'prometheus-snapshot.tar.gz', 'metadata.tar.gz']:
            subprocess.run(['gzip', '-t', str(partial / name)], stderr=log, check=True)
            subprocess.run(['tar', '-tzf', str(partial / name)], stdout=subprocess.DEVNULL, stderr=log, check=True)
            print(name + ': gzip and tar checks passed')
        wanted = {'./home/pi/homeassistantconfig/home-assistant_v2.db': 'ha.db',
                  './var/lib/docker/volumes/the-heat-mapper_grafana/_data/grafana.db': 'grafana.db'}
        with tempfile.TemporaryDirectory(prefix='.verify-', dir=root) as tmp:
            found = set()
            with tarfile.open(partial / 'system-and-apps.tar.gz', 'r|gz') as archive:
                for member in archive:
                    if member.name in wanted:
                        assert member.isfile()
                        target = Path(tmp) / wanted[member.name]
                        with archive.extractfile(member) as src, target.open('wb') as dst:
                            shutil.copyfileobj(src, dst)
                        with sqlite3.connect('file:' + str(target) + '?mode=ro', uri=True) as db:
                            assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
                        found.add(member.name)
                        print(wanted[member.name] + ': extracted integrity_check=ok')
            assert found == set(wanted), 'Missing database backup'
        print('Verified at ' + time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
partial.rename(root / run)
latest = root / 'latest.tmp'
latest.write_text(json.dumps({'run': run, 'verified_at': time.time()}) + '\n')
latest.replace(root / 'latest.json')
# Only our timestamped automatic backups, never manual offdevice-* backups.
completed = sorted(p for p in root.iterdir() if re.fullmatch(r'\d{8}T\d{6}Z', p.name)
                   and p.is_dir() and not p.is_symlink() and (p / 'verification.log').is_file())
for old in completed[:-14]:
    shutil.rmtree(old)
print('NAS verification passed; published ' + run, flush=True)
PY
nas_status success
touch "$dest/NAS-VERIFIED"
python3 - "$root" <<'PY'
import re, shutil, sys, time
from pathlib import Path
root = Path(sys.argv[1])
completed = sorted(p for p in root.iterdir() if re.fullmatch(r'\d{8}T\d{6}Z', p.name)
                   and p.is_dir() and not p.is_symlink() and (p / 'NAS-VERIFIED').is_file())
for old in completed[:-2]:
    shutil.rmtree(old)
for log in Path('/home/pi/logs').glob('blackbox-backup-????????T??????Z.log'):
    if time.time() - log.stat().st_mtime > 30 * 86400:
        log.unlink()
PY
echo "SUCCESS: verified backup $run on kinakuta"
