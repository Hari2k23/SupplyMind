import imaplib
import email
from email.header import decode_header
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import GROQ_MODELS
from utils.logger import log_info, log_error
from utils.groq_helper import groq

load_dotenv()


class EmailMonitor:
    """Shared email monitor that classifies emails as QUOTE or UPDATE."""
    
    def __init__(self):
        self.imap_server = "imap.gmail.com"
        self.imap_port = 993
        self.email_address = os.getenv('GMAIL_USER')
        self.password = os.getenv('GMAIL_APP_PASSWORD')
        

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.processed_emails_file = os.path.join(project_root, 'data', 'processed_emails.json')
        self.stakeholder_contacts_file = os.path.join(project_root, 'data', 'stakeholder_contacts.json')
        
        if not self.email_address or not self.password:
            raise ValueError("Gmail credentials not found in .env file")
        
        log_info("Email Monitor initialized", "EmailMonitor")
    
    
    def _connect_imap(self):
        """Connect to Gmail IMAP server."""
        try:
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            mail.login(self.email_address, self.password)
            return mail
        except Exception as e:
            log_error(f"IMAP connection failed: {e}", "EmailMonitor")
            return None
    
    
    def _load_processed_emails(self):
        """Load processed emails from JSON file."""
        try:
            if os.path.exists(self.processed_emails_file):
                with open(self.processed_emails_file, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        return {}
                    return json.loads(content)
            return {}
        except json.JSONDecodeError:
            log_error("Processed emails file is corrupted, creating new", "EmailMonitor")
            return {}
        except Exception as e:
            log_error(f"Failed to load processed emails: {e}", "EmailMonitor")
            return {}
    

    def _save_processed_email(self, email_id, email_data, email_type):
        """Mark email as processed with type classification."""
        try:
            processed = self._load_processed_emails()
            processed[email_id] = {
                'supplier_email': email_data.get('from', 'unknown'),
                'processed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'subject': email_data.get('subject', ''),
                'item_code': email_data.get('item_code'),
                'email_type': email_type
            }
            
            os.makedirs(os.path.dirname(self.processed_emails_file), exist_ok=True)
            with open(self.processed_emails_file, 'w') as f:
                json.dump(processed, f, indent=2)
            
            log_info(f"Marked email {email_id} as processed (type: {email_type})", "EmailMonitor")
        except Exception as e:
            log_error(f"Failed to save processed email: {e}", "EmailMonitor")
    
    
    def _load_stakeholder_contacts(self):
        """Load list of known supplier and stakeholder emails."""
        try:
            if os.path.exists(self.stakeholder_contacts_file):
                with open(self.stakeholder_contacts_file, 'r') as f:
                    return json.load(f)
            return {'suppliers': [], 'stakeholders': []}
        except Exception as e:
            log_error(f"Failed to load stakeholder contacts: {e}", "EmailMonitor")
            return {'suppliers': [], 'stakeholders': []}
    
    
    def _decode_email_subject(self, subject):
        """Decode email subject."""
        try:
            decoded_parts = decode_header(subject)
            subject_str = ""
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    subject_str += part.decode(encoding or 'utf-8')
                else:
                    subject_str += part
            return subject_str
        except Exception as e:
            log_error(f"Subject decode failed: {e}", "EmailMonitor")
            return subject
    
    
    def _extract_email_body(self, msg):
        """Extract email body from plain text or HTML."""
        body = ""
        
        try:
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))
                    
                    if "attachment" not in content_disposition:
                        if content_type == "text/plain":
                            body = part.get_payload(decode=True).decode()
                            break
                        elif content_type == "text/html" and not body:
                            body = part.get_payload(decode=True).decode()
            else:
                body = msg.get_payload(decode=True).decode()
        except Exception as e:
            log_error(f"Body extraction failed: {e}", "EmailMonitor")
        
        return body
    
    
    def _extract_attachments(self, msg):
        """Extract PDF attachments from email."""
        attachments = []
        
        try:
            if msg.is_multipart():
                for part in msg.walk():
                    content_disposition = str(part.get("Content-Disposition"))
                    
                    if "attachment" in content_disposition:
                        filename = part.get_filename()
                        if filename and filename.lower().endswith('.pdf'):
                            file_data = part.get_payload(decode=True)
                            attachments.append({
                                'filename': filename,
                                'data': file_data
                            })
        except Exception as e:
            log_error(f"Attachment extraction failed: {e}", "EmailMonitor")
        
        return attachments
    
    
    def _classify_email_type(self, subject, body):
        """Classify email as QUOTE or UPDATE using LLM."""
        try:
            prompt = f"""Classify this email as either a QUOTE or an UPDATE.
Subject: {subject}
Body: {body[:500]}
QUOTE: Contains pricing, unit price, total cost, delivery timeline, payment terms, response to RFQ, quotation details
UPDATE: Delivery delay, order confirmation, shipping update, general inquiry or question, issue
Return ONLY one word: "quote" or "update" (lowercase, no explanation)"""

            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["quick"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=10
            )
            
            result = response.choices[0].message.content.strip().lower()
            
            if 'quote' in result:
                return 'quote'
            elif 'update' in result:
                return 'update'
            else:
                return 'quote'
            
        except Exception as e:
            log_error(f"Email classification failed: {e}", "EmailMonitor")
            return 'quote'
    
    
    def _summarize_email_with_llm(self, subject, body, sender_email):
        """Generate a brief summary of the email content using LLM."""
        try:
            prompt = f"""Summarize this supplier email in 1-2 concise sentences.

From: {sender_email}
Subject: {subject}

Body (first 800 chars):
{body[:800]}

Provide a brief summary of what this email is about. Focus on:
- Main purpose (quote, update, delay, confirmation, etc.)
- Key details (pricing, delivery dates, issues, etc.)

Return ONLY the summary (1-2 sentences), no extra text."""

            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["quick"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=100
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            log_error(f"Email summary failed: {e}", "EmailMonitor")
            return f"Email from {sender_email} regarding {subject}"
    
    
    def check_new_emails(self, item_code=None, supplier_email=None, email_type=None):
        """Check inbox for new emails from suppliers with optional filtering."""
        mail = self._connect_imap()
        if not mail:
            return {'new_emails_count': 0, 'emails': [], 'error': 'IMAP connection failed'}
        
        try:
            mail.select('INBOX')
            
            contacts = self._load_stakeholder_contacts()
            supplier_emails = contacts.get('suppliers', [])
            
            if supplier_email:
                supplier_emails = [supplier_email]
            
            processed = self._load_processed_emails()
            new_emails = []
            
            for supp_email in supplier_emails:
                status, messages = mail.search(None, f'FROM {supp_email}')
                
                if status == 'OK':
                    email_ids = messages[0].split()
                    
                    for email_id in email_ids:
                        email_id_str = email_id.decode()
                        
                        if email_id_str in processed:
                            continue
                        
                        status, msg_data = mail.fetch(email_id, '(RFC822)')
                        
                        if status == 'OK':
                            raw_email = msg_data[0][1]
                            msg = email.message_from_bytes(raw_email)
                            
                            from_email = msg.get('From')
                            subject = self._decode_email_subject(msg.get('Subject', ''))
                            date = msg.get('Date')
                            body = self._extract_email_body(msg)
                            attachments = self._extract_attachments(msg)
                            
                            classified_type = self._classify_email_type(subject, body)
                            
                            if email_type and classified_type != email_type:
                                continue
                            
                            # Generate summary using LLM
                            summary = self._summarize_email_with_llm(subject, body, from_email)
                            
                            email_data = {
                                'email_id': email_id_str,
                                'from': from_email,
                                'subject': subject,
                                'received_at': date,
                                'body': body,
                                'attachments': attachments,
                                'item_code': item_code,
                                'email_type': classified_type,
                                'summary': summary
                            }
                            
                            new_emails.append(email_data)
                            
                            self._save_processed_email(email_id_str, email_data, classified_type)
            
            mail.close()
            mail.logout()
            
            log_info(f"Found {len(new_emails)} new emails (type: {email_type or 'all'})", "EmailMonitor")
            
            return {
                'new_emails_count': len(new_emails),
                'emails': new_emails,
                'status': 'success'
            }
            
        except Exception as e:
            log_error(f"Email check failed: {e}", "EmailMonitor")
            import traceback
            traceback.print_exc()
            return {'new_emails_count': 0, 'emails': [], 'error': str(e)}
    
    
    def get_email_summary(self, days=7):
        """Summarize supplier emails from last N days."""
        try:
            processed = self._load_processed_emails()
            
            cutoff_date = datetime.now() - timedelta(days=days)
            
            recent_emails = []
            for email_id, email_data in processed.items():
                try:
                    processed_at = datetime.strptime(email_data['processed_at'], '%Y-%m-%d %H:%M:%S')
                    if processed_at >= cutoff_date:
                        recent_emails.append(email_data)
                except:
                    continue
            
            if not recent_emails:
                return f"No supplier emails in the last {days} days."
            
            summary = f"Supplier Email Summary (Last {days} days):\n\n"
            summary += f"Total emails: {len(recent_emails)}\n\n"
            
            for idx, email_data in enumerate(recent_emails, 1):
                summary += f"{idx}. From: {email_data['supplier_email']}\n"
                summary += f"   Subject: {email_data['subject']}\n"
                summary += f"   Type: {email_data.get('email_type', 'unknown')}\n"
                summary += f"   Date: {email_data['processed_at']}\n\n"
            
            return summary
            
        except Exception as e:
            log_error(f"Email summary failed: {e}", "EmailMonitor")
            return "Error generating email summary."


if __name__ == "__main__":
    print("="*60)
    print("Testing Email Monitor with Classification")
    print("="*60)
    
    monitor = EmailMonitor()
    
    print("\nTest 1: Check for QUOTE emails only")
    print("-"*60)
    result = monitor.check_new_emails(email_type='quote')
    print(f"Quote emails found: {result['new_emails_count']}")
    
    print("\nTest 2: Check for UPDATE emails only")
    print("-"*60)
    result = monitor.check_new_emails(email_type='update')
    print(f"Update emails found: {result['new_emails_count']}")
    
    print("\nTest 3: Check all emails")
    print("-"*60)
    result = monitor.check_new_emails()
    print(f"Total emails: {result['new_emails_count']}")
    
    if result['new_emails_count'] > 0:
        for email in result['emails']:
            print(f"\nFrom: {email['from']}")
            print(f"Subject: {email['subject']}")
            print(f"Type: {email['email_type']}")
            print(f"Summary: {email.get('summary', 'N/A')}")
    
    print("\nTest 4: Get email summary")
    print("-"*60)
    summary = monitor.get_email_summary(days=7)
    print(summary)
    