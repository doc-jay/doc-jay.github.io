#!/usr/bin/env python3

# Docker Backup Script
# Version 1.3 - 2025-03-30
# Updated to use CST timezone for timestamps
#
# Usage:
#   - To perform a backup: ./docker_backup.py
#     This creates an incremental backup of /mnt/docker_storage to /mnt/nas/docker/docker_backup_<timestamp>
#   - To restore from a specific backup: ./docker_backup.py --restore <timestamp>
#     Example: ./docker_backup.py --restore 20250329_123456
#     This will restore from /mnt/nas/docker/docker_backup_20250329_123456 to /mnt/docker_storage
#     WARNING: This will overwrite files in /mnt/docker_storage. Use with caution.
#     Note: It is recommended to stop or pause your Docker containers before restoring
#     to prevent data corruption.
#
# Requires pytz library: pip install pytz

import os
import subprocess
import datetime
import logging
import requests
import docker
import glob
import argparse
import pytz

# Define CST timezone (US/Central)
CST = pytz.timezone('US/Central')

def cst_time(*args):
    """Return current time in CST for logging."""
    return datetime.datetime.now(CST).timetuple()

# Set up logging with CST timestamps
logger = logging.getLogger()
handler = logging.FileHandler('/var/log/docker_backup.log')
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S %Z')
formatter.converter = cst_time
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Ntfy settings
NTFY_URL = "http://172.25.47.113:3030"
NTFY_TOPIC = "dockerbu"
NTFY_TOKEN = "secret"

# Backup configuration
SOURCE_DIR = "/mnt/docker_storage"  # Where your Docker persistent data lives
BACKUP_ROOT = "/mnt/docker_bu"     # Where backups will be stored (e.g., NAS)
RETENTION_DAYS = 7  # Number of days to keep backups

# Initialize Docker client
docker_client = docker.from_env()

def send_notification(message, title="Docker Backup"):
    """Send a notification to your ntfy server using the token."""
    headers = {
        "Title": title,
        "Authorization": f"Bearer {NTFY_TOKEN}"
    }
    try:
        response = requests.post(f"{NTFY_URL}/{NTFY_TOPIC}", data=message.encode('utf-8'), headers=headers, timeout=10)
        response.raise_for_status()
        logger.info(f"Notification sent: {message}")
    except requests.RequestException as e:
        logger.error(f"Failed to send notification: {e}")
        print(f"Warning: Notification failed - {e}")

def run_command(command, capture_output=True):
    """Run a shell command and optionally capture output."""
    try:
        if capture_output:
            result = subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            logger.info(f"Command succeeded: {command}")
            logger.debug(f"Output: {result.stdout}")
        else:
            subprocess.run(command, shell=True, check=True)
            logger.info(f"Command succeeded: {command}")
    except subprocess.CalledProcessError as e:
        if capture_output:
            logger.error(f"Command failed: {command} - Error: {e.stderr}")
        else:
            logger.error(f"Command failed: {command}")
        raise

def ensure_backup_dir():
    """Create the backup directory if it doesn’t exist."""
    if not os.path.exists(BACKUP_ROOT):
        os.makedirs(BACKUP_ROOT)
        logger.info(f"Created backup directory: {BACKUP_ROOT}")
        print(f"Created backup directory: {BACKUP_ROOT}")

def get_latest_backup():
    """Find the most recent backup directory."""
    backups = glob.glob(os.path.join(BACKUP_ROOT, "docker_backup_*"))
    if backups:
        return max(backups, key=os.path.getctime)
    return None

def pause_containers():
    """Pause all running Docker containers except ntfy."""
    print("Pausing running containers (excluding ntfy)...")
    paused_containers = []
    try:
        for container in docker_client.containers.list(filters={"status": "running"}):
            if "ntfy" not in container.name.lower():
                container.pause()
                paused_containers.append(container)
                logger.info(f"Paused container: {container.name}")
        print(f"Paused {len(paused_containers)} containers")
        send_notification(f"Paused {len(paused_containers)} containers for backup")
        return paused_containers
    except Exception as e:
        logger.error(f"Failed to pause containers: {e}")
        print(f"Error pausing containers: {e}")
        raise

def unpause_containers(paused_containers):
    """Unpause the paused containers."""
    print("Unpausing containers...")
    for container in paused_containers:
        try:
            container.unpause()
            logger.info(f"Unpaused container: {container.name}")
        except Exception as e:
            logger.error(f"Failed to unpause container {container.name}: {e}")
            print(f"Error unpausing {container.name}: {e}")
    print(f"Unpaused {len(paused_containers)} containers")
    send_notification(f"Unpaused {len(paused_containers)} containers after backup")

def backup_docker_data():
    """Backup Docker data while containers are paused, using incremental rsync."""
    paused_containers = pause_containers()
    try:
        print("Starting backup...")
        # Use CST for timestamp
        timestamp = datetime.datetime.now(CST).strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(BACKUP_ROOT, f"docker_backup_{timestamp}")
        latest_backup = get_latest_backup()
        if latest_backup:
            rsync_cmd = f"rsync -rhv --no-owner --no-group --progress --link-dest={latest_backup} {SOURCE_DIR}/ {backup_dir}/"
            logger.info(f"Starting incremental backup from {SOURCE_DIR} to {backup_dir} using link-dest {latest_backup}")
        else:
            rsync_cmd = f"rsync -rhv --no-owner --no-group --progress {SOURCE_DIR}/ {backup_dir}/"
            logger.info(f"Starting full backup from {SOURCE_DIR} to {backup_dir}")
        send_notification("Starting Docker data backup")
        run_command(rsync_cmd, capture_output=False)
        logger.info("Backup completed successfully")
        send_notification("Docker data backup completed")
        print("Backup completed successfully")
    finally:
        unpause_containers(paused_containers)

def restore_docker_data(restore_timestamp):
    """Restore Docker data from a specific backup timestamp to the original path."""
    restore_dir = os.path.join(BACKUP_ROOT, f"docker_backup_{restore_timestamp}")
    if not os.path.exists(restore_dir):
        print(f"Error: Backup directory {restore_dir} does not exist.")
        logger.error(f"Backup directory {restore_dir} does not exist.")
        exit(1)
    print("WARNING: This will overwrite files in", SOURCE_DIR, "with the backup from", restore_dir)
    print("Ensure that your Docker containers are stopped or paused to avoid data corruption.")
    confirm = input("Are you sure you want to proceed? (y/N): ")
    if confirm.lower() == 'y':
        logger.info(f"Starting restore from {restore_dir} to {SOURCE_DIR}")
        print("Starting restore...")
        rsync_cmd = f"rsync -rhv --no-owner --no-group --progress {restore_dir}/ {SOURCE_DIR}/"
        try:
            run_command(rsync_cmd, capture_output=False)
            logger.info("Restore completed successfully")
            print("Restore completed successfully")
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            print(f"Restore failed: {e}")
    else:
        print("Restore cancelled.")

def cleanup_old_backups():
    """Delete backups older than RETENTION_DAYS."""
    print("Cleaning up old backups...")
    # Use CST for current time
    cutoff_time = datetime.datetime.now(CST) - datetime.timedelta(days=RETENTION_DAYS)
    for folder in os.listdir(BACKUP_ROOT):
        folder_path = os.path.join(BACKUP_ROOT, folder)
        if os.path.isdir(folder_path):
            try:
                # Parse timestamp and localize to CST
                timestamp_str = folder.split('_')[-1]
                folder_time = datetime.datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                folder_time = CST.localize(folder_time)
                if folder_time < cutoff_time:
                    run_command(f"rm -rf {folder_path}", capture_output=True)
                    logger.info(f"Deleted old backup: {folder_path}")
                    print(f"Deleted old backup: {folder_path}")
            except ValueError:
                logger.warning(f"Skipped invalid folder name: {folder}")
                print(f"Skipped invalid folder name: {folder}")

def main():
    parser = argparse.ArgumentParser(description="Docker Backup Script")
    parser.add_argument("--restore", help="Restore from a specific backup timestamp (e.g., 20250329_123456)")
    args = parser.parse_args()

    if args.restore:
        restore_docker_data(args.restore)
    else:
        print("Docker backup script started")
        try:
            ensure_backup_dir()
            backup_docker_data()
            cleanup_old_backups()
            logger.info("Backup process completed")
            send_notification("Docker backup process finished successfully")
            print("Backup process completed successfully")
        except Exception as e:
            error_msg = f"Backup process failed: {e}"
            logger.error(error_msg)
            send_notification(error_msg, title="Docker Backup Error")
            print(error_msg)
            raise

if __name__ == "__main__":
    main()
