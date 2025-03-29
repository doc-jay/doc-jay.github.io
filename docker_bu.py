#!/usr/bin/env python3

# Docker Backup Script
# Version 1.1 - 2025-03-29
# Updated to exclude ntfy from pausing and prevent rsync chown errors

import os
import subprocess
import datetime
import logging
import requests
import docker

# Setup logging to track the backup process
logging.basicConfig(
    filename='/var/log/docker_backup.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Ntfy settings
NTFY_URL = "http://172.25.47.113:3030"
NTFY_TOPIC = "dockerbu"
NTFY_TOKEN = "secret"

# Backup configuration
SOURCE_DIR = "/mnt/docker_storage"  # Where your Docker persistent data lives
BACKUP_ROOT = "/mnt/docker_bu"     # Where backups will be stored (e.g., NAS)
DATE = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP_DIR = os.path.join(BACKUP_ROOT, f"docker_backup_{DATE}")
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
        logging.info(f"Notification sent: {message}")
    except requests.RequestException as e:
        logging.error(f"Failed to send notification: {e}")
        print(f"Warning: Notification failed - {e}")

def run_command(command, capture_output=True):
    """Run a shell command and optionally capture output."""
    try:
        if capture_output:
            result = subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            logging.info(f"Command succeeded: {command}")
            logging.debug(f"Output: {result.stdout}")
        else:
            subprocess.run(command, shell=True, check=True)
            logging.info(f"Command succeeded: {command}")
    except subprocess.CalledProcessError as e:
        if capture_output:
            logging.error(f"Command failed: {command} - Error: {e.stderr}")
        else:
            logging.error(f"Command failed: {command}")
        raise

def ensure_backup_dir():
    """Create the backup directory if it doesn’t exist."""
    if not os.path.exists(BACKUP_ROOT):
        os.makedirs(BACKUP_ROOT)
        logging.info(f"Created backup directory: {BACKUP_ROOT}")
        print(f"Created backup directory: {BACKUP_ROOT}")

def pause_containers():
    """Pause all running Docker containers except ntfy."""
    print("Pausing running containers (excluding ntfy)...")
    paused_containers = []
    try:
        for container in docker_client.containers.list(filters={"status": "running"}):
            if "ntfy" not in container.name.lower():
                container.pause()
                paused_containers.append(container)
                logging.info(f"Paused container: {container.name}")
        print(f"Paused {len(paused_containers)} containers")
        send_notification(f"Paused {len(paused_containers)} containers for backup")
        return paused_containers
    except Exception as e:
        logging.error(f"Failed to pause containers: {e}")
        print(f"Error pausing containers: {e}")
        raise

def unpause_containers(paused_containers):
    """Unpause the paused containers."""
    print("Unpausing containers...")
    for container in paused_containers:
        try:
            container.unpause()
            logging.info(f"Unpaused container: {container.name}")
        except Exception as e:
            logging.error(f"Failed to unpause container {container.name}: {e}")
            print(f"Error unpausing {container.name}: {e}")
    print(f"Unpaused {len(paused_containers)} containers")
    send_notification(f"Unpaused {len(paused_containers)} containers after backup")

def backup_docker_data():
    """Backup Docker data while containers are paused."""
    paused_containers = pause_containers()
    try:
        print("Starting backup...")
        # Modified rsync command to exclude owner and group preservation
        rsync_cmd = f"rsync -rhv --no-owner --no-group --progress {SOURCE_DIR}/ {BACKUP_DIR}/"
        logging.info(f"Starting backup from {SOURCE_DIR} to {BACKUP_DIR}")
        send_notification("Starting Docker data backup")
        run_command(rsync_cmd, capture_output=False)
        logging.info("Backup completed successfully")
        send_notification("Docker data backup completed")
        print("Backup completed successfully")
    finally:
        unpause_containers(paused_containers)

def cleanup_old_backups():
    """Delete backups older than RETENTION_DAYS."""
    print("Cleaning up old backups...")
    cutoff_time = datetime.datetime.now() - datetime.timedelta(days=RETENTION_DAYS)
    for folder in os.listdir(BACKUP_ROOT):
        folder_path = os.path.join(BACKUP_ROOT, folder)
        if os.path.isdir(folder_path):
            try:
                folder_time = datetime.datetime.strptime(folder.split('_')[-2] + folder.split('_')[-1], "%Y%m%d_%H%M%S")
                if folder_time < cutoff_time:
                    run_command(f"rm -rf {folder_path}", capture_output=True)
                    logging.info(f"Deleted old backup: {folder_path}")
                    print(f"Deleted old backup: {folder_path}")
            except ValueError:
                logging.warning(f"Skipped invalid folder name: {folder}")
                print(f"Skipped invalid folder name: {folder}")

def main():
    """Main function to run the backup process."""
    print("Docker backup script started")
    try:
        ensure_backup_dir()
        backup_docker_data()
        cleanup_old_backups()
        logging.info("Backup process completed")
        send_notification("Docker backup process finished successfully")
        print("Backup process completed successfully")
    except Exception as e:
        error_msg = f"Backup process failed: {e}"
        logging.error(error_msg)
        send_notification(error_msg, title="Docker Backup Error")
        print(error_msg)
        raise

if __name__ == "__main__":
    main()
