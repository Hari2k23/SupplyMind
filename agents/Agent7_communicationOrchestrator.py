import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.email_monitor import EmailMonitor
from utils.notification_helper import NotificationManager
from utils.logger import log_info, log_error
import json
from datetime import datetime


class CommunicationOrchestrator:
    """Handle stakeholder notifications and inbox monitoring for updates."""
    
    def __init__(self):
        self.name = "Agent 7 - Communication Orchestrator"
        log_info("Communication Orchestrator initialized", self.name)
        
        self.email_monitor = EmailMonitor()
        self.notification_manager = NotificationManager()
        
    def send_notification(self, event_type, event_data):
        """Send notification to stakeholders based on event type."""
        log_info(f"Sending notification for event: {event_type}", self.name)
        
        result = self.notification_manager.send_event_notification(event_type, event_data)
        
        if result['status'] == 'success':
            log_info(f"Notification sent to {len(result['recipients'])} recipients", self.name)
        elif result['status'] in ('rate_limited', 'batched'):
            log_info(f"Notification {result['status']}: {result.get('message', '')}", self.name)
        else:
            log_error(f"Notification failed: {result.get('error')}", self.name)
        
        return result
    
    
    def auto_notify_quotes(self, parsed_quotes, item_name):
        """Automatically send notifications for each parsed quote."""
        for quote in parsed_quotes:
            self.send_notification('quote_received', {
                'item_name': item_name or quote.get('item_name', 'Item'),
                'supplier_name': quote['supplier_name'],
                'unit_price': quote['unit_price'],
                'delivery_days': quote['delivery_days'],
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
    
    
    def check_inbox_for_updates(self, item_code=None):
        """Check inbox for UPDATE emails."""
        log_info("Checking inbox for update emails", self.name)
        
        result = self.email_monitor.check_new_emails(
            item_code=item_code,
            email_type='update'
        )
        
        if result['new_emails_count'] > 0:
            log_info(f"Found {result['new_emails_count']} update emails", self.name)
            
            # Auto-notify for each update
            for email_data in result['emails']:
                self.send_notification('supplier_update_received', {
                    'supplier_email': email_data['from'],
                    'subject': email_data['subject'],
                    'received_at': email_data['received_at'],
                    'summary': email_data.get('summary') or email_data['body'][:200]
                })
        else:
            log_info("No new update emails found", self.name)
        
        return result
    
    
    def get_notification_history(self, limit=10):
        """Retrieve recent notification history."""
        try:
            if not os.path.exists(self.notification_logs_file):
                return []
            
            with open(self.notification_logs_file, 'r') as f:
                logs = json.load(f)
            
            sorted_logs = sorted(
                logs.items(),
                key=lambda x: x[1].get('sent_at', ''),
                reverse=True
            )
            
            return [log[1] for log in sorted_logs[:limit]]
            
        except Exception as e:
            log_error(f"Failed to retrieve notification history: {e}", self.name)
            return []
    
    
    def summarize_supplier_emails(self, days=7):
        """Summarize all supplier emails from last N days."""
        log_info(f"Summarizing supplier emails from last {days} days", self.name)
        
        result = self.email_monitor.get_email_summary(days)
        
        return result


if __name__ == "__main__":
    print("="*60)
    print("Testing Agent 7 - Communication Orchestrator")
    print("="*60)
    
    agent = CommunicationOrchestrator()
    
    print("\nTest 1: Send RFQ notification")
    print("-"*60)
    
    rfq_event = {
        'item_name': 'M8 Screws',
        'quantity': 2536,
        'suppliers_contacted': 5,
        'emails_sent': 5,
        'success_list': [
            'nextgen.components1@gmail.com',
            'pioneer.machineparts@gmail.com'
        ],
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    result1 = agent.send_notification('rfq_sent', rfq_event)
    if result1['status'] == 'success':
        print("SUCCESS: RFQ notification sent")
        print(f"Recipients: {', '.join(result1['recipients'])}")
    else:
        print(f"FAILED: {result1.get('error')}")
    
    print("\nTest 2: Send Quote Received notification")
    print("-"*60)
    
    quote_event = {
        'item_name': 'M8 Screws',
        'supplier_name': 'NextGen Components',
        'unit_price': 12.50,
        'delivery_days': 10,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    result2 = agent.send_notification('quote_received', quote_event)
    if result2['status'] == 'success':
        print("SUCCESS: Quote notification sent")
    else:
        print(f"FAILED: {result2.get('error')}")
    
    print("\nTest 3: Check inbox for update emails")
    print("-"*60)
    
    inbox_result = agent.check_inbox_for_updates()
    print(f"Update emails found: {inbox_result['new_emails_count']}")
    
    if inbox_result['new_emails_count'] > 0:
        for email in inbox_result['emails']:
            print(f"  - From: {email['from']}")
            print(f"    Subject: {email['subject']}")
            print(f"    Summary: {email.get('summary', 'N/A')}")
    
    print("\nTest 4: Get notification history")
    print("-"*60)
    
    history = agent.get_notification_history(limit=5)
    print(f"Recent notifications: {len(history)}")
    for idx, notif in enumerate(history, 1):
        print(f"\n{idx}. Event: {notif['event_type']}")
        print(f"   Sent at: {notif['sent_at']}")
        print(f"   Status: {notif['status']}")
    
    print("\nTest 5: Summarize supplier emails")
    print("-"*60)
    
    summary = agent.summarize_supplier_emails(days=7)
    print("Email Summary:")
    print(summary)
    
    print("\n" + "="*60)
    print("Agent 7 testing complete")
    print("="*60)
