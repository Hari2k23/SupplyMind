import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import log_info, log_error

class TemplateManager:
    """Manage email notification templates for procurement events."""
    
    def __init__(self):
        self.name = "TemplateManager"
        log_info("Template Manager initialized", self.name)
    
    
    def get_subject(self, event_type, event_data):
        """Get email subject for event type."""
        
        subjects = {
            'rfq_sent': f"RFQ Sent - {event_data.get('item_name', 'Item')}",
            'quote_received': f"New Quote Received - {event_data.get('item_name', 'Item')}",
            'quote_received_batch': f"{event_data.get('quote_count', 0)} New Quotes Received - {event_data.get('item_name', 'Items')}",
            'quote_parsed': f"Quote Processed - {event_data.get('item_name', 'Item')}",
            'po_created': f"Purchase Order Created - {event_data.get('po_number', 'PO')}",
            'po_approved': f"Purchase Order Approved - {event_data.get('po_number', 'PO')}",
            'po_rejected': f"Purchase Order Rejected - {event_data.get('po_number', 'PO')}",
            'delivery_expected': f"Delivery Expected - {event_data.get('item_name', 'Item')}",
            'delivery_delayed': f"URGENT: Delivery Delayed - {event_data.get('item_name', 'Item')}",
            'budget_exceeded': f"ALERT: Budget Exceeded - {event_data.get('item_name', 'Item')}",
            

            'verification_complete': f"Verification Complete - PO {event_data.get('po_number', 'N/A')} - {event_data.get('match_result', 'N/A')}",
            'mismatch_email_to_supplier': f"Discrepancy in PO {event_data.get('po_number', 'N/A')}",
            'final_report': f"Delivery Quality Report - PO {event_data.get('po_number', 'N/A')}",
            'supplier_update_received': f"Supplier Update - {event_data.get('supplier_email', 'Supplier')}"
        }
        
        return subjects.get(event_type, f"Procurement Notification - {event_type}")
    
    
    def render(self, event_type, event_data):
        """Render email body template."""
        
        templates = {
            'rfq_sent': self._template_rfq_sent,
            'quote_received': self._template_quote_received,
            'quote_received_batch': self._template_quote_received_batch,
            'quote_parsed': self._template_quote_parsed,
            'po_created': self._template_po_created,
            'po_approved': self._template_po_approved,
            'po_rejected': self._template_po_rejected,
            'delivery_expected': self._template_delivery_expected,
            'delivery_delayed': self._template_delivery_delayed,
            'budget_exceeded': self._template_budget_exceeded,
            

            'verification_complete': self._template_verification_complete,
            'mismatch_email_to_supplier': self._template_mismatch_email,
            'final_report': self._template_final_report,
            'supplier_update_received': self._template_supplier_update
        }
        
        template_func = templates.get(event_type)
        
        if template_func:
            return template_func(event_data)
        else:
            return self._template_default(event_type, event_data)
    
    
    def _template_rfq_sent(self, data):
        """Template for RFQ sent notification."""
        return f"""Dear Team,

RFQs have been successfully sent for procurement.

Item: {data.get('item_name', 'N/A')}
Quantity Required: {data.get('quantity', 'N/A')} units
Suppliers Contacted: {data.get('suppliers_contacted', 0)}
Emails Delivered: {data.get('emails_sent', 0)}

The system will monitor responses and notify you when quotes are received.


Automated notification from Procurement System
Timestamp: {data.get('timestamp', 'N/A')}"""
    
    
    def _template_quote_received(self, data):
        """Template for single quote received notification."""
        return f"""Dear Team,

A new quote has been received from a supplier.

Item: {data.get('item_name', 'N/A')}
Supplier: {data.get('supplier_name', 'N/A')}
Unit Price: Rs.{data.get('unit_price', 0)}
Delivery Timeline: {data.get('delivery_days', 'N/A')} days
Received At: {data.get('timestamp', 'N/A')}

This quote has been automatically processed and is ready for comparison.


Automated notification from Procurement System"""
    
    
    def _template_quote_received_batch(self, data):
        """Template for batched quote notifications."""
        quotes_text = "\n".join([
            f"  - {q.get('supplier_name', 'Unknown')}: Rs.{q.get('unit_price', 0)} ({q.get('delivery_days', 'N/A')} days)"
            for q in data.get('quotes', [])
        ])
        
        return f"""Dear Team,

Multiple quotes have been received for the same item.

Item: {data.get('item_name', 'N/A')}
Total Quotes Received: {data.get('quote_count', 0)}

Quote Summary:
{quotes_text}

All quotes have been processed and are ready for comparison.


Automated notification from Procurement System"""
    
    
    def _template_quote_parsed(self, data):
        """Template for quote parsed notification."""
        return f"""Dear Team,

A supplier quote has been successfully parsed and processed.

Item: {data.get('item_name', 'N/A')}
Supplier: {data.get('supplier_name', 'N/A')}

Quote Details:
- Unit Price: Rs.{data.get('unit_price', 0)}
- Total Cost: Rs.{data.get('total_cost', 0)}
- Delivery: {data.get('delivery_days', 'N/A')} days
- Payment Terms: {data.get('payment_terms', 'N/A')}

The quote is now available for decision making.


Automated notification from Procurement System"""
    
    
    def _template_po_created(self, data):
        """Template for PO created notification."""
        return f"""Dear Team,

A new Purchase Order has been created.

Purchase Order: {data.get('po_number', 'N/A')}
Supplier: {data.get('supplier_name', 'N/A')}
Item: {data.get('item_name', 'N/A')}
Quantity: {data.get('quantity', 'N/A')} units
Total Cost: Rs.{data.get('total_cost', 0):,.2f}
Expected Delivery: {data.get('expected_delivery_date', 'N/A')}

Status: Pending Approval

Next Steps: The PO is awaiting management approval before proceeding.


Automated notification from Procurement System"""
    
    
    def _template_po_approved(self, data):
        """Template for PO approved notification."""
        return f"""Dear Team,

A Purchase Order has been APPROVED and will proceed to fulfillment.

Purchase Order: {data.get('po_number', 'N/A')}
Supplier: {data.get('supplier_name', 'N/A')}
Item: {data.get('item_name', 'N/A')}
Quantity: {data.get('quantity', 'N/A')} units
Total Cost: Rs.{data.get('total_cost', 0):,.2f}
Expected Delivery: {data.get('expected_delivery_date', 'N/A')}

Status: APPROVED

Next Steps: Supplier will be notified and order will be processed.


Automated notification from Procurement System"""
    
    
    def _template_po_rejected(self, data):
        """Template for PO rejected notification."""
        return f"""Dear Team,

A Purchase Order has been REJECTED.

Purchase Order: {data.get('po_number', 'N/A')}
Item: {data.get('item_name', 'N/A')}
Supplier: {data.get('supplier_name', 'N/A')}
Total Cost: Rs.{data.get('total_cost', 0):,.2f}

Rejection Reason: {data.get('rejection_reason', 'Not specified')}

Status: REJECTED

Next Steps: Please review alternative suppliers or adjust requirements.


Automated notification from Procurement System"""
    
    
    def _template_delivery_expected(self, data):
        """Template for delivery expected notification."""
        return f"""Dear Team,

Delivery is expected soon for the following order.

Item: {data.get('item_name', 'N/A')}
Purchase Order: {data.get('po_number', 'N/A')}
Supplier: {data.get('supplier_name', 'N/A')}
Quantity: {data.get('quantity', 'N/A')} units
Expected Delivery Date: {data.get('expected_delivery_date', 'N/A')}

Please ensure warehouse team is prepared to receive this shipment.


Automated notification from Procurement System"""
    
    
    def _template_delivery_delayed(self, data):
        """Template for delivery delayed notification."""
        return f"""URGENT NOTIFICATION

Delivery has been DELAYED for the following order.

Item: {data.get('item_name', 'N/A')}
Purchase Order: {data.get('po_number', 'N/A')}
Supplier: {data.get('supplier_name', 'N/A')}
Original Delivery Date: {data.get('original_delivery_date', 'N/A')}
New Expected Date: {data.get('new_delivery_date', 'N/A')}
Delay Reason: {data.get('delay_reason', 'Not specified')}

Action Required: Please contact supplier to confirm new timeline.


Automated notification from Procurement System"""
    
    
    def _template_budget_exceeded(self, data):
        """Template for budget exceeded notification."""
        return f"""BUDGET ALERT

The following procurement request EXCEEDS the available budget.

Item: {data.get('item_name', 'N/A')}
Total Cost: Rs.{data.get('total_cost', 0):,.2f}
Available Budget: Rs.{data.get('budget_available', 0):,.2f}
Excess Amount: Rs.{data.get('excess_amount', 0):,.2f}

Status: REQUIRES APPROVAL

Action Required: Management approval needed to proceed with this purchase.


Automated notification from Procurement System"""
    
    

    
    def _template_verification_complete(self, data):
        """Template for Agent 8 verification alert."""
        mismatch_details = ""
        if data.get('mismatch_count', 0) > 0:
            mismatch_details = "\n\nMismatches Detected:\n"
            for m in data.get('mismatches', []):
                mismatch_details += f"- {m.get('field', 'N/A')}: PO={m.get('po_value', 'N/A')}, Delivery={m.get('delivery_value', 'N/A')}, Invoice={m.get('invoice_value', 'N/A')}\n"
        
        status_message = "✓ All documents match - No action required." if data.get('match_result') == 'PASS' else "⚠ Mismatches detected - Exception handler will analyze."
        
        return f"""Dear Team,

Document Verification Complete

Purchase Order: {data.get('po_number', 'N/A')}
Item: {data.get('item_name', 'N/A')}
Verification Result: {data.get('match_result', 'N/A')}
Mismatches Found: {data.get('mismatch_count', 0)}
{mismatch_details}
Verified At: {data.get('verified_at', 'N/A')}

{status_message}


Automated notification from Agent 8 - Document Verification"""
    
    
    def _template_mismatch_email(self, data):
        """Template for Agent 9 email to supplier — uses LLM-generated content."""
        return data.get('email_body', 'Discrepancy detected in delivery. Please review.')
    
    
    def _template_final_report(self, data):
        """Template for Agent 11 final report notification."""
        return f"""Dear Team,

Delivery Quality Report Generated

Purchase Order: {data.get('po_number', 'N/A')}
Item: {data.get('item_name', 'N/A')}
Supplier: {data.get('supplier_name', 'N/A')}
Verification Status: {data.get('verification_status', 'N/A')}

A comprehensive quality report has been generated covering:
- Purchase Order details
- Supplier information
- Document verification results
- Exception analysis (if any)
- Data storage summary
- Document evidence (delivery note & invoice images)

The full PDF report is attached to this email.

Generated at: {data.get('generated_at', 'N/A')}


Automated notification from Agent 11 - Quality Report Generator"""
    
    
    def _template_supplier_update(self, data):
        """Template for Agent 7 supplier update notification."""
        return f"""Dear Team,

Supplier Update Received

From: {data.get('supplier_email', 'N/A')}
Subject: {data.get('subject', 'N/A')}
Received: {data.get('received_at', 'N/A')}

Summary:
{data.get('summary', 'N/A')}


Automated notification from Agent 7 - Communication Orchestrator"""
    
    
    def _template_default(self, event_type, data):
        """Default template for unknown event types."""
        return f"""Dear Team,

A procurement event has occurred.

Event Type: {event_type}
Details: {str(data)}

Please check the procurement system for more information.


Automated notification from Procurement System"""


if __name__ == "__main__":
    print("="*60)
    print("Testing Template Manager")
    print("="*60)
    
    manager = TemplateManager()
    
    # Test 1: RFQ sent template
    print("\nTest 1: RFQ Sent Template")
    print("-"*60)
    subject = manager.get_subject('rfq_sent', {'item_name': 'M8 Screws'})
    body = manager.render('rfq_sent', {
        'item_name': 'M8 Screws',
        'quantity': 2536,
        'suppliers_contacted': 5,
        'emails_sent': 5,
        'timestamp': '2026-01-14 10:30:00'
    })
    print(f"Subject: {subject}")
    print(f"\n{body}")
    
    # Test 2: Quote received template
    print("\n" + "="*60)
    print("Test 2: Quote Received Template")
    print("-"*60)
    subject = manager.get_subject('quote_received', {'item_name': 'M8 Screws'})
    body = manager.render('quote_received', {
        'item_name': 'M8 Screws',
        'supplier_name': 'NextGen Components',
        'unit_price': 12.50,
        'delivery_days': 10,
        'timestamp': '2026-01-14 11:00:00'
    })
    print(f"Subject: {subject}")
    print(f"\n{body}")
    
    # Test 3: PO created template
    print("\n" + "="*60)
    print("Test 3: PO Created Template")
    print("-"*60)
    subject = manager.get_subject('po_created', {'po_number': 'PO-ITM001-20260114'})
    body = manager.render('po_created', {
        'po_number': 'PO-ITM001-20260114',
        'supplier_name': 'NextGen Components',
        'item_name': 'M8 Screws',
        'quantity': 2536,
        'total_cost': 31700,
        'expected_delivery_date': '2026-01-24'
    })
    print(f"Subject: {subject}")
    print(f"\n{body}")
    
    # Test 4: NEW - Verification complete template
    print("\n" + "="*60)
    print("Test 4: Verification Complete Template")
    print("-"*60)
    subject = manager.get_subject('verification_complete', {
        'po_number': 'PO-ITM001-20260114',
        'match_result': 'PASS'
    })
    body = manager.render('verification_complete', {
        'po_number': 'PO-ITM001-20260114',
        'item_name': 'M8 Screws',
        'match_result': 'PASS',
        'mismatch_count': 0,
        'mismatches': [],
        'verified_at': '2026-01-15 14:30:00'
    })
    print(f"Subject: {subject}")
    print(f"\n{body}")
    
    # Test 5: NEW - Final report template
    print("\n" + "="*60)
    print("Test 5: Final Report Template")
    print("-"*60)
    subject = manager.get_subject('final_report', {'po_number': 'PO-ITM001-20260114'})
    body = manager.render('final_report', {
        'po_number': 'PO-ITM001-20260114',
        'item_name': 'M8 Screws',
        'supplier_name': 'NextGen Components',
        'verification_status': 'PASS',
        'generated_at': '2026-01-15 15:00:00'
    })
    print(f"Subject: {subject}")
    print(f"\n{body}")
    
    print("\n" + "="*60)
    print("Template Manager testing complete")
    print("="*60)
    