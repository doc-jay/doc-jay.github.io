#!/usr/bin/env python3

import os
import subprocess
import datetime
import logging
import requests

# Setup logging
logging.basicConfig(
    filename='/var/log/docker_backup.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Configuration
SOURCE_DIR = "/mnt/docker_storage"  # Your Docker persistent data location
BACKUP_ROOT = "/mnt/pve/backup/docker"  # Proxmox backup area for Docker
DATE = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP_DIR = os.path.join(BACKUP_ROOT, f"docker_backup_{DATE}")
RETENTION_DAYS = 7  # Keep backups for 7 days
NTFY_URL = "https://ntfy.example.com/your_topic"  # Replace with your ntfy server URL

def send_notification(message, title="Docker Backup"):
    """Send a notification to ntfy server."""
    try:
        headers = {"Title": title}
        response = requests.post(NTFY_URL, data=message.encode('utf-8'), headers=headers)
        response.raise_for_status()
        logging.info(f"Notification sent: {message}")
    except requests.RequestException as e:
        logging.error(f"Failed to send notification: {e}")

def run_command(command):
    """Execute a shell command and log the result."""
    try:
        subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logging.info(f"Command succeeded: {command}")
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {command} - Error: {e}")
        raise

def ensure_backup_dir():
    """Create backup directory if it doesn't exist."""
    if not os.path.exists(BACKUP_ROOT):
        os.makedirs(BACKUP_ROOT)
        logging.info(f"Created backup root directory: {BACKUP_ROOT}")

def backup_docker_data():
    """Backup Docker persistent data using rsync."""
    rsync_cmd = f"rsync -avh --progress {SOURCE_DIR}/ {BACKUP_DIR}/"
    logging.info(f"Starting backup of {SOURCE_DIR} to {BACKUP_DIR}")
    send_notification("Starting Docker data backup")
    run_command(rsync_cmd)
    logging.info("Docker data backup completed")
    send_notification("Docker data backup completed successfully")

def cleanup_old_backups():
    """Remove backups older than RETENTION_DAYS."""
    cutoff_time = datetime.datetime.now() - datetime.timedelta(days=RETENTION_DAYS)
    for folder in os.listdir(BACKUP_ROOT):
        folder_path = os.path.join(BACKUP_ROOT, folder)
        if os.path.isdir(folder_path):
            folder_time = datetime.datetime.strptime(folder.split('_')[-2] + folder.split('_')[-1], "%Y%m%d_%H%M%S")
            if folder_time < cutoff_time:
                run_command(f"rm -rf {folder_path}")
                logging.info(f"Removed old backup: {folder_path}")

def main():
    try:
        ensure_backup_dir()
        backup_docker_data()
        cleanup_old_backups()
        logging.info("Docker backup process completed successfully")
        send_notification("Docker backup process completed")
    except Exception as e:
        logging.error(f"Backup failed: {e}")
        send_notification(f"Docker backup failed: {str(e)}", title="Docker Backup Error")
        raise

if __name__ == "__main__":
    main()
