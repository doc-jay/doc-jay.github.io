#!/usr/bin/env python3

import os
import subprocess
import zipfile
import datetime
import logging
import argparse
import shutil
from pathlib import Path

class RsyncBackupTool:
    def __init__(self, source_dirs, dest_dir, retain_months=3, retain_weeks=4, retain_days=7, excludes=None, retain_logs=10):
        self.source_dirs = [Path(src).resolve() for src in source_dirs]
        self.dest_dir = Path(dest_dir).resolve()
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        self.timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.retain_months = retain_months
        self.retain_weeks = retain_weeks
        self.retain_days = retain_days
        self.excludes = excludes or []
        self.retain_logs = retain_logs
        self.unzipped_days = 10  # Keep unzipped for 10 days

        # Ntfy settings
        self.ntfy_url = "http://172.25.47.113:3030"
        self.ntfy_topic = "grokbu"
        self.ntfy_token = "tk_50vh37nty27lm1wgbgu65kzgln69q"

        # Fixed log directory
        self.log_dir = Path("/var/log/grok_bu_logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup logging
        log_filename = self.log_dir / f"backup_{self.timestamp}.log"
        logging.basicConfig(
            filename=log_filename,
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s"
        )

    def rsync_copy(self, source, dest, incremental=False, previous_backup=None):
        try:
            dest.mkdir(parents=True, exist_ok=True)
            rsync_cmd = ["rsync", "-rltD", "--progress"]
            if incremental and previous_backup and Path(previous_backup).exists():
                rsync_cmd.extend(["--link-dest", str(Path(previous_backup).resolve())])
            if self.excludes:
                for exclude in self.excludes:
                    rsync_cmd.extend(["--exclude", exclude])
            rsync_cmd.append("--ignore-errors")
            source_str = str(source) + "/" if source.is_dir() else str(source)
            rsync_cmd.extend([source_str, str(dest)])
            
            logging.info(f"Executing rsync command: {' '.join(rsync_cmd)}")
            result = subprocess.run(rsync_cmd, check=True, text=True, capture_output=True)
            logging.info(f"rsync output for {source}: {result.stdout}")
            if result.stderr:
                logging.warning(f"rsync warnings for {source}: {result.stderr}")
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"rsync failed for {source}: {e.stderr} (exit code: {e.returncode})")
            logging.error(f"Failed command: {' '.join(rsync_cmd)}")
            return False

    def archive_directory(self, directory):
        """Convert a directory to a .zip file and delete the original."""
        zip_path = self.dest_dir / f"{directory.name}.zip"
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(directory):
                    for file in files:
                        file_path = Path(root) / file
                        rel_path = file_path.relative_to(directory)
                        zipf.write(file_path, rel_path)
                        logging.info(f"Archived {rel_path} into {zip_path}")
            shutil.rmtree(directory)
            logging.info(f"Converted {directory} to {zip_path}")
            return zip_path
        except Exception as e:
            logging.error(f"Failed to archive {directory}: {str(e)}")
            return None

    def send_ntfy_notification(self, message):
        if not self.ntfy_token:
            logging.warning("Ntfy notification skipped: Token not provided.")
            return

        ntfy_endpoint = f"{self.ntfy_url}/{self.ntfy_topic}"
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        curl_cmd = [
            "curl",
            "-d", message,
            "-u", f":{self.ntfy_token}",
            "-H", f"Title: Full backup completed on {current_time}" if "Full" in message else f"Title: Incremental backup completed on {current_time}",
            "-H", "Tags: file_folder",
            ntfy_endpoint
        ]
        
        try:
            logging.info(f"Sending ntfy notification: {' '.join(curl_cmd)}")
            result = subprocess.run(curl_cmd, check=True, text=True, capture_output=True)
            logging.info(f"ntfy response: {result.stdout}")
            if result.stderr:
                logging.warning(f"ntfy warnings: {result.stderr}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to send ntfy notification: {e.stderr} (exit code: {e.returncode})")

    def get_latest_backup(self):
        """Find the most recent backup directory."""
        backups = sorted(
            [f for f in self.dest_dir.glob("*_backup_*") if f.is_dir()],
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        return backups[0] if backups else None

    def cleanup_old_backups(self):
        now = datetime.datetime.now()
        backups = sorted(
            [f for f in self.dest_dir.glob("*_backup_*") if f.is_dir() or f.suffix == ".zip"],
            key=lambda x: x.stat().st_mtime
        )
        backup_times = {}
        for backup in backups:
            try:
                timestamp_str = backup.name.split("_")[2].replace(".zip", "")
                backup_time = datetime.datetime.strptime(timestamp_str, "%Y%m%d")
                backup_times[backup] = backup_time
            except (IndexError, ValueError):
                logging.warning(f"Skipping {backup} - invalid timestamp format")
                continue

        if not backup_times:
            return

        daily_cutoff = now - datetime.timedelta(days=self.retain_days)
        weekly_cutoff = now - datetime.timedelta(weeks=self.retain_weeks)
        monthly_cutoff = now - datetime.timedelta(days=self.retain_months * 30)
        unzipped_cutoff = now - datetime.timedelta(days=self.unzipped_days)

        monthly_kept, weekly_kept, daily_kept = [], [], []
        for backup, backup_time in sorted(backup_times.items(), key=lambda x: x[1], reverse=True):
            backup_date = backup_time.date()
            week_start = backup_date - datetime.timedelta(days=backup_date.weekday())
            month_start = backup_date.replace(day=1)

            # Archive directories older than 10 days
            if backup.is_dir() and backup_time < unzipped_cutoff:
                archived = self.archive_directory(backup)
                if archived:
                    backup = archived

            # Retention logic
            if backup_time > monthly_cutoff and month_start not in [d.replace(day=1) for d in monthly_kept]:
                if len(monthly_kept) < self.retain_months:
                    monthly_kept.append(backup_date)
                    continue
            if backup_time > weekly_cutoff and week_start not in [d - datetime.timedelta(days=d.weekday()) for d in weekly_kept]:
                if len(weekly_kept) < self.retain_weeks:
                    weekly_kept.append(backup_date)
                    continue
            if backup_time > daily_cutoff:
                if len(daily_kept) < self.retain_days:
                    daily_kept.append(backup_date)
                    continue

            # Remove if not kept
            logging.info(f"Removing old backup: {backup}")
            if backup.is_dir():
                shutil.rmtree(backup)
            else:
                os.remove(backup)

        logging.info(f"Kept {len(monthly_kept)} monthly, {len(weekly_kept)} weekly, {len(daily_kept)} daily backups")

    def cleanup_old_logs(self):
        logs = sorted([f for f in self.log_dir.glob("backup_*.log") if f.is_file()], key=lambda x: x.stat().st_mtime, reverse=True)
        if len(logs) <= self.retain_logs:
            return
        for old_log in logs[self.retain_logs:]:
            logging.info(f"Removing old log file: {old_log}")
            os.remove(old_log)

    def backup(self):
        """Automatically decide between full or incremental backup."""
        latest_backup = self.get_latest_backup()
        
        if not latest_backup:
            # First run: full backup
            backup_name = f"full_backup_{self.timestamp}"
            backup_dir = self.dest_dir / backup_name
            logging.info(f"No previous backups found, starting full backup to {backup_dir}")
        else:
            # Subsequent runs: incremental backup
            backup_name = f"incr_backup_{self.timestamp}"
            backup_dir = self.dest_dir / backup_name
            logging.info(f"Found previous backup {latest_backup}, starting incremental backup to {backup_dir}")

        try:
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            backup_dir.mkdir()

            all_success = True
            for source_dir in self.source_dirs:
                if not source_dir.exists():
                    logging.warning(f"Source {source_dir} does not exist, skipping.")
                    continue
                dest_subdir = backup_dir / source_dir.name
                if not self.rsync_copy(source_dir, dest_subdir, incremental=bool(latest_backup), previous_backup=latest_backup):
                    all_success = False
                    logging.warning(f"Continuing despite rsync failure for {source_dir}")

            if not all_success:
                logging.warning("Some rsync operations failed, but proceeding with backup")

            if not latest_backup and not any(backup_dir.rglob("*")):
                logging.info("No files copied in full backup, removing empty directory.")
                shutil.rmtree(backup_dir)
                return None
            elif latest_backup and not any(backup_dir.rglob("*")):
                logging.info("No changes detected in incremental backup, removing empty directory.")
                shutil.rmtree(backup_dir)
                return None

            backup_type = "Full" if not latest_backup else "Incremental"
            logging.info(f"{backup_type} backup completed to: {backup_dir}")
            print(f"{backup_type} backup completed to: {backup_dir}")

            self.send_ntfy_notification(f"{backup_type} backup completed: {backup_dir}")

            self.cleanup_old_backups()
            self.cleanup_old_logs()
            return backup_dir
        except Exception as e:
            logging.error(f"{backup_type} backup failed: {str(e)}")
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            raise

    def verify_backup(self, backup_path):
        backup_path = Path(backup_path)
        if not backup_path.exists():
            logging.error(f"Backup {backup_path} not found.")
            print(f"Backup {backup_path} not found.")
            return False
        if backup_path.is_dir():
            files = list(backup_path.rglob("*"))
            if not files:
                logging.error(f"Backup directory {backup_path} is empty.")
                print(f"Backup directory {backup_path} is empty.")
                return False
            logging.info(f"Backup directory {backup_path} verified: contains {len(files)} items.")
            print(f"Backup directory {backup_path} verified.")
        else:  # .zip
            logging.info(f"Backup file {backup_path} exists.")
            print(f"Backup file {backup_path} verified.")
        return True

def main():
    parser = argparse.ArgumentParser(description="Awesome rsync Backup Script with Excludes, Log Retention, and Ntfy Notifications")
    parser.add_argument("sources", nargs="+", help="One or more source directories to back up")
    parser.add_argument("destination", help="Destination directory for backups")
    parser.add_argument("--backup", action="store_true", help="Perform an automatic full or incremental backup")
    parser.add_argument("--verify", help="Verify a specific backup directory or file")
    parser.add_argument("--retain-months", type=int, default=3, help="Number of months to retain backups (default: 3)")
    parser.add_argument("--retain-weeks", type=int, default=4, help="Number of weeks to retain backups (default: 4)")
    parser.add_argument("--retain-days", type=int, default=7, help="Number of days to retain backups (default: 7)")
    parser.add_argument("--exclude", action="append", help="Directories or files to exclude (can be used multiple times)")
    parser.add_argument("--retain-logs", type=int, default=10, help="Number of log files to retain (default: 10)")
    args = parser.parse_args()

    backup_tool = RsyncBackupTool(
        args.sources, args.destination,
        retain_months=args.retain_months,
        retain_weeks=args.retain_weeks,
        retain_days=args.retain_days,
        excludes=args.exclude,
        retain_logs=args.retain_logs
    )

    if args.backup:
        backup_tool.backup()
    elif args.verify:
        backup_tool.verify_backup(args.verify)
    else:
        print("Please specify --backup or --verify <backup_path>")

if __name__ == "__main__":
    main()
