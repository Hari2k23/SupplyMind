import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import os
import json
from datetime import datetime
from dotenv import load_dotenv
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.template_manager import TemplateManager
from utils.logger import log_info, log_error

load_dotenv()


class NotificationManager:
    """Manage stakeholder notifications via email with rate limiting."""

    def __init__(self):
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.email_address = os.getenv('GMAIL_USER')
        self.password = os.getenv('GMAIL_APP_PASSWORD')

        self.template_manager = TemplateManager()

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.notification_logs_file = os.path.join(project_root, 'data', 'notification_logs.json')
        self.stakeholder_contacts_file = os.path.join(project_root, 'data', 'stakeholder_contacts.json')

        stakeholders = self._load_stakeholder_emails()

        self.event_stakeholder_map = {
            'rfq_sent': stakeholders,
            'quote_received': stakeholders,
            'quote_parsed': stakeholders,
            'po_created': stakeholders,
            'po_approved': stakeholders,
            'po_rejected': stakeholders,
            'delivery_expected': stakeholders,
            'delivery_delayed': stakeholders,
            'budget_exceeded': stakeholders,
            'supplier_update_received': stakeholders,
            'verification_complete': stakeholders,
            'mismatch_email_to_supplier': ['supplier_email'],
            'final_report': stakeholders
        }

        self.last_notification_time = {}
        self.rate_limit_seconds = 60

        if not self.email_address or not self.password:
            raise ValueError("Gmail credentials not found in .env file")

        log_info("Notification Manager initialized", "NotificationManager")

    def _load_stakeholder_emails(self):
        """Load stakeholder email list from stakeholder_contacts.json."""
        try:
            if os.path.exists(self.stakeholder_contacts_file):
                with open(self.stakeholder_contacts_file, 'r') as f:
                    contacts = json.load(f)
                emails = contacts.get('stakeholders', [])
                if emails:
                    return emails
            log_error("No stakeholders found in contacts file, using fallback", "NotificationManager")
            return [os.getenv('STAKEHOLDER_EMAIL', '717822i216@kce.ac.in')]
        except Exception as e:
            log_error(f"Failed to load stakeholder contacts: {e}", "NotificationManager")
            return [os.getenv('STAKEHOLDER_EMAIL', '717822i216@kce.ac.in')]

    def _load_notification_logs(self):
        """Load notification history."""
        try:
            if os.path.exists(self.notification_logs_file):
                with open(self.notification_logs_file, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        return {}
                    return json.loads(content)
            return {}
        except json.JSONDecodeError:
            log_error("Notification logs file is corrupted, creating new", "NotificationManager")
            return {}
        except Exception as e:
            log_error(f"Failed to load notification logs: {e}", "NotificationManager")
            return {}

    def _save_notification_log(self, notification_id, log_data):
        """Save notification log."""
        try:
            logs = self._load_notification_logs()
            logs[notification_id] = log_data

            os.makedirs(os.path.dirname(self.notification_logs_file), exist_ok=True)
            with open(self.notification_logs_file, 'w') as f:
                json.dump(logs, f, indent=2)

            log_info(f"Saved notification log: {notification_id}", "NotificationManager")
        except Exception as e:
            log_error(f"Failed to save notification log: {e}", "NotificationManager")

    def _check_rate_limit(self, event_type, event_data=None):
        """Check if event is rate limited."""
        now = datetime.now()

        item_name = ''
        if event_data:
            if event_type == 'quote_received':
                item_name = event_data.get('supplier_name', '') or event_data.get('item_name', '')
            else:
                item_name = event_data.get('item_name', '') or event_data.get('item_code', '')
        rate_key = f"{event_type}:{item_name}" if item_name else event_type

        if rate_key in self.last_notification_time:
            time_diff = (now - self.last_notification_time[rate_key]).total_seconds()

            high_priority = ['budget_exceeded', 'delivery_delayed', 'po_approved',
                             'verification_complete', 'final_report', 'rfq_sent',
                             'po_created', 'po_rejected']

            if event_type not in high_priority and time_diff < self.rate_limit_seconds:
                return False, rate_key

        return True, rate_key

    def _update_rate_limit(self, rate_key):
        """Update rate limit timestamp."""
        self.last_notification_time[rate_key] = datetime.now()

    def _send_email(self, recipients, subject, body, event_type, attachment_path=None):
        """Send email notification with optional attachment."""
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email_address
            msg['To'] = ', '.join(recipients)
            msg['Subject'] = subject

            msg.attach(MIMEText(body, 'plain'))

            if attachment_path and os.path.exists(attachment_path):
                with open(attachment_path, 'rb') as f:
                    pdf_attachment = MIMEApplication(f.read(), _subtype='pdf')
                    pdf_attachment.add_header('Content-Disposition', 'attachment',
                                              filename=os.path.basename(attachment_path))
                    msg.attach(pdf_attachment)

            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.email_address, self.password)
            server.send_message(msg)
            server.quit()

            log_info(f"Email sent to {len(recipients)} recipients", "NotificationManager")

            notification_id = f"{event_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            log_data = {
                'notification_id': notification_id,
                'event_type': event_type,
                'sent_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'recipients': recipients,
                'subject': subject,
                'status': 'sent',
                'error_message': None
            }
            self._save_notification_log(notification_id, log_data)

            return True

        except Exception as e:
            log_error(f"Email send failed: {e}", "NotificationManager")

            notification_id = f"{event_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            log_data = {
                'notification_id': notification_id,
                'event_type': event_type,
                'sent_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'recipients': recipients,
                'subject': subject,
                'status': 'failed',
                'error_message': str(e)
            }
            self._save_notification_log(notification_id, log_data)

            return False

    def send_event_notification(self, event_type, event_data):
        """Send notification for an event with rate limiting."""
        allowed, rate_key = self._check_rate_limit(event_type, event_data)
        if not allowed:
            log_info(f"Event {event_type} rate limited", "NotificationManager")
            return {
                'status': 'rate_limited',
                'message': 'Notification rate limited'
            }

        recipients = self.event_stakeholder_map.get(event_type, [])

        if event_type == 'mismatch_email_to_supplier':
            recipients = [event_data.get('supplier_email', '717822i216@kce.ac.in')]

        if not recipients:
            log_error(f"No recipients for event: {event_type}", "NotificationManager")
            return {
                'status': 'failed',
                'error': 'No recipients configured'
            }

        subject = self.template_manager.get_subject(event_type, event_data)
        body = self.template_manager.render(event_type, event_data)

        attachment_path = event_data.get('report_path') if event_type == 'final_report' else None

        success = self._send_email(recipients, subject, body, event_type, attachment_path)

        if success:
            self._update_rate_limit(rate_key)
            return {
                'status': 'success',
                'recipients': recipients,
                'event_type': event_type
            }
        else:
            return {
                'status': 'failed',
                'error': 'Email send failed'
            }


if __name__ == "__main__":
    manager = NotificationManager()

    result = manager.send_event_notification('rfq_sent', {
        'item_name': 'M8 Screws',
        'quantity': 2536,
        'suppliers_contacted': 5,
        'emails_sent': 5
    })
    print(f"Status: {result['status']}")
    