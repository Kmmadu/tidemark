import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

def send_email_alert(subject, body):
    """Send email alert using SMTP"""
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    sender_email = os.getenv("SMTP_USER")
    sender_password = os.getenv("SMTP_PASSWORD")
    recipient_email = os.getenv("ALERT_RECIPIENT")
    
    if not all([smtp_server, sender_email, sender_password, recipient_email]):
        logger.warning("Email credentials missing, skipping email alert")
        return
    
    try:
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = recipient_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        
        logger.info(f"Email alert sent: {subject}")
    except Exception as e:
        logger.error(f"Failed to send email alert: {e}")

def send_slack_alert(message):
    """Send alert to Slack webhook"""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return
    
    try:
        payload = {"text": message}
        response = requests.post(webhook_url, json=payload, timeout=5)
        if response.status_code == 200:
            logger.info("Slack alert sent")
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")

def alert_backup_failure(device_name: str, error_msg: str):
    """Alert when backup fails"""
    subject = f"[FAILURE] Backup failed for {device_name}"
    body = f"""
Device: {device_name}
Error: {error_msg}
Time: {datetime.now()}

Please check connectivity and device credentials.
    """
    send_email_alert(subject, body)
    send_slack_alert(f"❌ Backup FAILED: {device_name}\nError: {error_msg}")

def alert_config_changed(device_name: str, diff: str):
    """Alert when configuration changes"""
    subject = f"[CHANGE] Configuration changed on {device_name}"
    diff_preview = diff[:1000]  # Limit diff length - extract to variable
    body = f"""
Device: {device_name}
Time: {datetime.now()}

Changes detected:
{diff_preview}

Review and verify if this change was authorized.
    """
    send_email_alert(subject, body)
    send_slack_alert(f"🔄 Config CHANGED: {device_name}")

def send_alert(subject, body):
    """Generic alert via all channels"""
    send_email_alert(subject, body)
    send_slack_alert(f"*{subject}*\n{body}")