#!/bin/bash

# BorgBackup Script
# Version 1.1 - 2025-03-31
#
# Usage:
#   - To perform a backup: ./borg_bu.sh
#     This creates an incremental backup of /mnt/docker_storage to /mnt/docker_bu/borg_bu_repo.
#     Containers (except ntfy) are paused during the backup for consistency.
#
#   - To list available repositories and archives for restore:
#     1. List all archives in the repository:
#        export BORG_PASSPHRASE="your_passphrase"  # Or use BORG_PASSCOMMAND
#        /usr/local/bin/borg list /mnt/docker_bu/borg_bu_repo
#     2. To see the contents of a specific archive:
#        /usr/local/bin/borg list /mnt/docker_bu/borg_bu_repo::archive_name
#     Example:
#        export BORG_PASSPHRASE="MySuperSecretPass123!"
#        /usr/local/bin/borg list /mnt/docker_bu/borg_bu_repo
#        # Output: docker-20250331_153051 Mon 2025-03-31 15:30:53
#        /usr/local/bin/borg list /mnt/docker_bu/borg_bu_repo::docker-20250331_153051
#
#   - To restore from a specific archive: ./borg_bu.sh --restore <archive_name>
#     Example: ./borg_bu.sh --restore docker-20250331_153051
#     This will restore the specified archive to /mnt/docker_storage_restore.
#     WARNING: This will overwrite files in the restore directory. Use with caution.
#     Note: Stop or pause your Docker containers before restoring to prevent data corruption.
#
# Requires: BorgBackup 1.4.0, docker, curl (for ntfy)

# Configuration
BORG="/usr/local/bin/borg"
REPO="/mnt/docker_bu/borg_bu_repo"
SOURCE="/mnt/docker_storage"
RESTORE_DIR="/mnt/docker_storage/borg_restore"
ARCHIVE_NAME="docker-$(date -d 'today' +%Y%m%d_%H%M%S)"
NTFY_URL="http://ip:port"
NTFY_TOPIC="borgbu"
NTFY_TOKEN="secret"
LOG="/var/log/borg_backup.log"

# Set Borg passphrase (secure this for production)
export BORG_PASSPHRASE="cat /root/borg_pass"

# Ensure log directory exists
mkdir -p /var/log

send_ntfy() {
    local title="$1"
    local message="$2"
    curl -H "Authorization: Bearer $NTFY_TOKEN" -H "Title: $title" -d "$message" "$NTFY_URL/$NTFY_TOPIC"
}

pause_containers() {
    echo "$(date -d 'today' +'%Y-%m-%d %H:%M:%S %Z') - Pausing running containers (excluding ntfy)..." | tee -a "$LOG"
    RUNNING_CONTAINERS=$(docker ps -q --filter "status=running" | grep -v "$(docker ps -q --filter name=ntfy 2>/dev/null)")
    if [ -n "$RUNNING_CONTAINERS" ]; then
        echo "$RUNNING_CONTAINERS" | xargs -r docker pause 2>&1 | tee -a "$LOG"
        send_ntfy "Containers Paused" "Paused $(echo "$RUNNING_CONTAINERS" | wc -l) containers for backup"
    else
        echo "No containers to pause" | tee -a "$LOG"
    fi
    echo "$RUNNING_CONTAINERS"
}

unpause_containers() {
    local containers="$1"
    if [ -n "$containers" ]; then
        echo "$(date -d 'today' +'%Y-%m-%d %H:%M:%S %Z') - Unpausing containers..." | tee -a "$LOG"
        echo "$containers" | xargs -r docker unpause 2>&1 | tee -a "$LOG"
        send_ntfy "Containers Unpaused" "Unpaused $(echo "$containers" | wc -l) containers after backup"
    fi
}

restore_backup() {
    local archive_name="$1"
    if [ -z "$archive_name" ]; then
        echo "Error: Please specify an archive name to restore (e.g., --restore docker-20250331_153051)" | tee -a "$LOG"
        send_ntfy "Restore Failed" "No archive name specified for restore"
        exit 1
    fi

    echo "$(date -d 'today' +'%Y-%m-%d %H:%M:%S %Z') - Starting restore from $REPO::$archive_name to $RESTORE_DIR" | tee -a "$LOG"
    echo "WARNING: This will overwrite files in $RESTORE_DIR. Ensure Docker containers are stopped or paused to avoid data corruption." | tee -a "$LOG"
    read -p "Are you sure you want to proceed? (y/N): " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "Restore cancelled" | tee -a "$LOG"
        send_ntfy "Restore Cancelled" "User cancelled restore operation"
        exit 0
    fi

    mkdir -p "$RESTORE_DIR"
    $BORG extract --progress "$REPO::$archive_name" 2>&1 | tee -a "$LOG"
    if [ $? -eq 0 ]; then
        echo "$(date -d 'today' +'%Y-%m-%d %H:%M:%S %Z') - Restore completed successfully to $RESTORE_DIR" | tee -a "$LOG"
        send_ntfy "Restore Succeeded" "Restored $archive_name to $RESTORE_DIR"
    else
        echo "$(date -d 'today' +'%Y-%m-%d %H:%M:%S %Z') - Restore failed" | tee -a "$LOG"
        ERROR_MSG=$(tail -n 10 "$LOG")
        send_ntfy "Restore Failed" "Restore of $archive_name failed. Last 10 lines:\n$ERROR_MSG"
        exit 1
    fi
}

if [ "$1" = "--restore" ]; then
    restore_backup "$2"
    exit 0
fi

if [ ! -d "$REPO" ]; then
    echo "$(date -d 'today' +'%Y-%m-%d %H:%M:%S %Z') - Initializing Borg repository at $REPO" | tee -a "$LOG"
    $BORG init --encryption=repokey-blake2 "$REPO" 2>&1 | tee -a "$LOG"
    if [ $? -eq 0 ]; then
        send_ntfy "Borg Repository Initialized" "Created new repository at $REPO"
    else
        send_ntfy "Borg Initialization Failed" "Failed to initialize repository at $REPO. Check $LOG"
        exit 1
    fi
fi

PAUSED_CONTAINERS=$(pause_containers)

echo "$(date -d 'today' +'%Y-%m-%d %H:%M:%S %Z') - Starting backup to $REPO::$ARCHIVE_NAME" | tee -a "$LOG"
$BORG create --stats --progress "$REPO::$ARCHIVE_NAME" "$SOURCE" 2>&1 | tee -a "$LOG"
BACKUP_STATUS=$?
unpause_containers "$PAUSED_CONTAINERS"

if [ $BACKUP_STATUS -eq 0 ]; then
    echo "$(date -d 'today' +'%Y-%m-%d %H:%M:%S %Z') - Backup completed successfully" | tee -a "$LOG"
    send_ntfy "Backup Succeeded" "Backup of $SOURCE to $REPO::$ARCHIVE_NAME completed"
else
    echo "$(date -d 'today' +'%Y-%m-%d %H:%M:%S %Z') - Backup failed" | tee -a "$LOG"
    ERROR_MSG=$(tail -n 10 "$LOG")
    send_ntfy "Backup Failed" "Backup of $SOURCE to $REPO::$ARCHIVE_NAME failed. Last 10 lines:\n$ERROR_MSG"
    exit 1
fi

echo "$(date -d 'today' +'%Y-%m-%d %H:%M:%S %Z') - Pruning old backups" | tee -a "$LOG"
$BORG prune --keep-daily 7 "$REPO" 2>&1 | tee -a "$LOG"
if [ $? -eq 0 ]; then
    send_ntfy "Prune Succeeded" "Old backups pruned, keeping 7 daily"
else
    send_ntfy "Prune Failed" "Failed to prune old backups. Check $LOG"
fi
