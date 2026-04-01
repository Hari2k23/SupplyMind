import json
import os
import sys
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.groq_helper import groq
from utils.logger import log_info, log_error
from config.settings import GROQ_MODELS
from utils.email_monitor import EmailMonitor
from utils.quote_parser import QuoteParser

BUDGET_LIMIT = 50000
APPROVAL_THRESHOLD = 10000


ALWAYS_REQUIRE_APPROVAL = True

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PO_FILE = os.path.join(PROJECT_ROOT, 'data', 'purchase_orders.json')
QUOTES_FILE = os.path.join(PROJECT_ROOT, 'data', 'quotes_collected.json')

def load_purchase_orders():
    """Load purchase orders from JSON file."""
    if os.path.exists(PO_FILE):
        try:
            with open(PO_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_purchase_order(po_data):
    """Save purchase order to JSON file."""
    pos = load_purchase_orders()
    po_id = po_data['po_number']
    pos[po_id] = po_data

    os.makedirs('data', exist_ok=True)
    with open(PO_FILE, 'w') as f:
        json.dump(pos, f, indent=2)
    return po_id

def load_quotes():
    """Load quotes from JSON file."""
    if os.path.exists(QUOTES_FILE):
        try:
            with open(QUOTES_FILE, 'r') as f:
                content = f.read().strip()
                if not content:
                    return {}
                return json.loads(content)
        except json.JSONDecodeError:
            return {}
    return {}

def _derive_supplier_name(supplier_email, llm_name):
    """Derive correct supplier name from email key, falling back to LLM extract."""
    import re as _re

    # Extract display name and email address
    match = _re.match(r'^([^<]+?)\s*<([^>]+)>', supplier_email)
    if match:
        email_display = match.group(1).strip()
        email_addr = match.group(2).strip()
    else:
        email_display = ''
        email_addr = supplier_email.strip()

    # Build a richer name from the email username (e.g. pioneer.machineparts -> Pioneer Machineparts)
    username_name = ''
    if email_addr and '@' in email_addr:
        username = email_addr.split('@')[0]
        # Split by dots, underscores, hyphens and title-case each part
        parts = _re.split(r'[._\-]+', username)
        # Filter out numeric-only parts
        parts = [p.title() for p in parts if p and not p.isdigit()]
        username_name = ' '.join(parts)

    # Decide best name: prefer the longer/richer source
    derived_name = ''
    if email_display and username_name:
        # If username gives a richer name (more words), use it
        if len(username_name.split()) > len(email_display.split()):
            derived_name = username_name
        else:
            derived_name = email_display
    elif email_display:
        derived_name = email_display
    elif username_name:
        derived_name = username_name

    # If we have a derived name from email, check if LLM name matches the sender
    if derived_name:
        derived_words = set(derived_name.lower().split())
        llm_words = set((llm_name or '').lower().split())
        if not derived_words.intersection(llm_words):
            log_info(f"Correcting supplier name: LLM said '{llm_name}', derived '{derived_name}'", "Agent6")
            return derived_name

    return llm_name or derived_name or 'Unknown'


def save_quote(supplier_email, quote_data):
    """Save quote to JSON file."""
    quotes = load_quotes()

    # Derive correct supplier name from email key, don't blindly trust LLM
    correct_name = _derive_supplier_name(supplier_email, quote_data.get('supplier_name', 'Unknown'))

    if supplier_email not in quotes:
        quotes[supplier_email] = {
            'supplier_name': correct_name,
            'quotes': []
        }
    else:
        # Also fix existing wrong names
        quotes[supplier_email]['supplier_name'] = correct_name

    quotes[supplier_email]['quotes'].append({
        'item_code': quote_data.get('item_code'),
        'item_name': quote_data.get('item_name'),
        'unit_price': quote_data.get('unit_price'),
        'quantity': quote_data.get('quantity'),
        'total_cost': quote_data.get('total_cost'),
        'delivery_days': quote_data.get('delivery_days'),
        'payment_terms': quote_data.get('payment_terms'),
        'quality_certs': quote_data.get('quality_certs'),
        'risk_score': quote_data.get('risk_score', 0),
        'received_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

    os.makedirs('data', exist_ok=True)
    with open(QUOTES_FILE, 'w') as f:
        json.dump(quotes, f, indent=2)

    log_info(f"Saved quote from {supplier_email} (name: {correct_name})", "Agent6")

def normalize_score(value, min_val, max_val, invert=False):
    """Normalize a value to 0-1 range."""
    if max_val == min_val:
        # All values are the same, return neutral score
        return 0.5

    normalized = (value - min_val) / (max_val - min_val)
    return 1 - normalized if invert else normalized

def generate_justification(comparison_data, selected_supplier):
    """Generate AI justification for supplier selection."""
    try:
        prompt = f"""Generate a brief 2-3 sentence justification for why this supplier was selected.

Selected Supplier: {selected_supplier['supplier_name']}
Price: Rs.{selected_supplier['unit_price']:,.2f}
Delivery: {selected_supplier['delivery_days']} days

Other quotes:
{json.dumps(comparison_data, indent=2)}

Write a concise, professional explanation focusing on the best balance of price, delivery speed, and supplier reliability."""

        response = groq.client.chat.completions.create(
            model=GROQ_MODELS["quick"],
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        log_error(f"Error generating justification: {e}", "Agent 6")
        return f"Selected based on optimal balance of price (Rs.{selected_supplier['unit_price']:,.2f}), delivery time ({selected_supplier['delivery_days']} days), and supplier reliability."

class DecisionAgent:
    """Analyze quotes, select best supplier, and create purchase orders."""

    def __init__(self):
        self.name = "Agent 6 - Decision Agent"
        log_info("Decision Agent initialized", self.name)

        self.email_monitor = EmailMonitor()
        self.quote_parser = QuoteParser()

    def check_and_parse_quotes(self, item_code, force_recheck=False):
        """Check inbox for quote emails and parse them.
        
        If no new emails are found, falls back to recently-collected quotes
        from quotes_collected.json (within the last 7 days).
        If force_recheck=True, clears processed state for quote emails and re-scans.
        """
        log_info(f"Checking inbox for quotes related to {item_code}", self.name)

        if force_recheck:
            self._clear_processed_quotes()

        inbox_result = self.email_monitor.check_new_emails(
            item_code=item_code,
            email_type='quote'
        )

        if inbox_result['new_emails_count'] > 0:
            parsed_quotes = []
            emails_summary = []

            for email_data in inbox_result['emails']:
                body_preview = email_data.get('body', '')[:200]

                emails_summary.append({
                    'from': email_data['from'],
                    'subject': email_data['subject'],
                    'summary': body_preview,
                    'received_at': email_data['received_at']
                })

                quote_data = self.quote_parser.parse_email_quote(email_data)

                if quote_data['parsing_status'] == 'success':
                    parsed_quote = quote_data['quote_data']
                    parsed_quote['contact_email'] = email_data['from']

                    save_quote(email_data['from'], parsed_quote)

                    parsed_quotes.append(parsed_quote)
                    log_info(f"Successfully parsed quote from {parsed_quote['supplier_name']}", self.name)
                else:
                    log_error(f"Failed to parse quote from {email_data['from']}", self.name)

            return {
                'quotes_found': inbox_result['new_emails_count'],
                'parsed_quotes': parsed_quotes,
                'status': 'success',
                'emails_summary': emails_summary
            }

        log_info("No new emails, checking previously collected quotes", self.name)
        existing_quotes = self._get_recent_collected_quotes(item_code)
        if existing_quotes:
            return {
                'quotes_found': len(existing_quotes),
                'parsed_quotes': existing_quotes,
                'status': 'from_cache',
                'emails_summary': []
            }

        return {
            'quotes_found': 0,
            'parsed_quotes': [],
            'status': 'no_quotes',
            'emails_summary': []
        }

    def _clear_processed_quotes(self):
        """Clear processed email IDs for quote-type emails so they can be re-scanned."""
        try:
            processed = self.email_monitor._load_processed_emails()
            cleared = {k: v for k, v in processed.items() if v.get('email_type') != 'quote'}
            os.makedirs(os.path.dirname(self.email_monitor.processed_emails_file), exist_ok=True)
            with open(self.email_monitor.processed_emails_file, 'w') as f:
                json.dump(cleared, f, indent=2)
            log_info("Cleared processed quote emails for re-scan", self.name)
        except Exception as e:
            log_error(f"Failed to clear processed quotes: {e}", self.name)

    def _get_recent_collected_quotes(self, item_code=None):
        """Get recently collected quotes from quotes_collected.json."""
        try:
            quotes = load_quotes()
            if not quotes:
                return []

            all_parsed = []
            for supplier_email, supplier_data in quotes.items():
                supplier_name = supplier_data.get('supplier_name', 'Unknown')
                for q in supplier_data.get('quotes', []):
                    received = q.get('received_at', '')
                    if received:
                        try:
                            dt = datetime.strptime(received, '%Y-%m-%d %H:%M:%S')
                            if (datetime.now() - dt).days > 7:
                                continue
                        except ValueError:
                            pass

                    if item_code and q.get('item_code') and q['item_code'] != item_code:
                        continue

                    all_parsed.append({
                        'supplier_name': supplier_name,
                        'item_name': q.get('item_name', 'Unknown'),
                        'unit_price': q.get('unit_price', 0),
                        'delivery_days': q.get('delivery_days', 0),
                        'quantity': q.get('quantity', 0),
                        'total_cost': q.get('total_cost', 0),
                        'payment_terms': q.get('payment_terms', 'N/A'),
                        'quality_certs': q.get('quality_certs', 'N/A'),
                        'contact_email': supplier_email
                    })

            return all_parsed
        except Exception as e:
            log_error(f"Failed to load collected quotes: {e}", self.name)
            return []

    def execute(self, quotes, item_code, item_name, quantity):
        """Analyze quotes and select best supplier."""

        log_info(f"Analyzing {len(quotes)} quotes for {item_name}", self.name)

        if not quotes or len(quotes) == 0:
            return {
                "error": "No quotes received for comparison",
                "status": "failed"
            }

        comparison_table = []

        for quote in quotes:
            total_cost = quote['unit_price'] * quantity
            comparison_table.append({
                'supplier_name': quote['supplier_name'],
                'unit_price': quote['unit_price'],
                'total_cost': total_cost,
                'delivery_days': quote['delivery_days'],
                'quality_score': quote.get('quality_score', 0),
                'payment_terms': quote.get('payment_terms', 'N/A'),
                'quality_certs': quote.get('quality_certs', 'N/A'),
                'contact_email': quote.get('contact_email', 'N/A')
            })

        prices = [q['total_cost'] for q in comparison_table]
        deliveries = [q['delivery_days'] for q in comparison_table]
        qualities = [q['quality_score'] for q in comparison_table]

        min_price, max_price = min(prices), max(prices)
        min_delivery, max_delivery = min(deliveries), max(deliveries)
        min_quality, max_quality = min(qualities), max(qualities)

        PRICE_WEIGHT = 0.30
        DELIVERY_WEIGHT = 0.30
        QUALITY_WEIGHT = 0.40

        # Verify weights sum to 1.0
        assert PRICE_WEIGHT + DELIVERY_WEIGHT + QUALITY_WEIGHT == 1.0, "Weights must sum to 1.0"

        for quote in comparison_table:
            price_norm = normalize_score(quote['total_cost'], min_price, max_price, invert=True)
            delivery_norm = normalize_score(quote['delivery_days'], min_delivery, max_delivery, invert=True)
            quality_norm = normalize_score(quote['quality_score'], min_quality, max_quality, invert=False)

            total_score = (PRICE_WEIGHT * price_norm +
                           DELIVERY_WEIGHT * delivery_norm +
                           QUALITY_WEIGHT * quality_norm) * 100

            quote['score'] = round(total_score, 2)

        comparison_table.sort(key=lambda x: x['score'], reverse=True)
        selected_supplier = comparison_table[0]

        log_info(f"Selected supplier: {selected_supplier['supplier_name']} (Score: {selected_supplier['score']})", self.name)

        total_cost = selected_supplier['total_cost']

        if total_cost <= BUDGET_LIMIT:
            budget_status = "within_budget"
        else:
            budget_status = "exceeds_budget"

        # Approval logic
        if ALWAYS_REQUIRE_APPROVAL:
            approval_status = "needs_approval"
            approval_reason = "Mandatory approval required (company policy)"
        else:
            if total_cost > APPROVAL_THRESHOLD:
                approval_status = "needs_approval"
                approval_reason = f"Amount exceeds threshold (Rs.{total_cost:,.2f} > Rs.{APPROVAL_THRESHOLD:,.2f})"
            else:
                approval_status = "auto_approved"
                approval_reason = f"Auto-approved (Rs.{total_cost:,.2f} <= Rs.{APPROVAL_THRESHOLD:,.2f})"

        justification = generate_justification(comparison_table, selected_supplier)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        po_number = f"PO-{item_code}-{timestamp}"
        expected_delivery_date = (datetime.now() + timedelta(days=selected_supplier['delivery_days'])).strftime("%Y-%m-%d")

        po_data = {
            "po_number": po_number,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "supplier_name": selected_supplier['supplier_name'],
            "contact_email": selected_supplier['contact_email'],
            "item_code": item_code,
            "item_name": item_name,
            "quantity": quantity,
            "unit_price": selected_supplier['unit_price'],
            "total_cost": total_cost,
            "delivery_days": selected_supplier['delivery_days'],
            "expected_delivery_date": expected_delivery_date,
            "payment_terms": selected_supplier['payment_terms'],
            "quality_certifications": selected_supplier['quality_certs'],
            "budget_status": budget_status,
            "approval_status": approval_status,
            "approval_reason": approval_reason,
            "justification": justification,
            "score": selected_supplier['score'],
            "status": "pending_approval" if approval_status == "needs_approval" else "approved"
        }

        result = {
            "po_data": po_data,
            "comparison_table": comparison_table,
            "selected_supplier": selected_supplier['supplier_name'],
            "total_quotes_analyzed": len(quotes),
            "budget_status": budget_status,
            "approval_status": approval_status,
            "needs_user_approval": approval_status == "needs_approval"
        }

        return result

    def approve_purchase_order(self, po_data, approved=True):
        """Approve or reject purchase order."""
        if approved:
            po_data['status'] = 'approved'
            po_data['approved_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_info(f"Purchase Order {po_data['po_number']} APPROVED", self.name)
        else:
            po_data['status'] = 'rejected'
            po_data['rejected_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_info(f"Purchase Order {po_data['po_number']} REJECTED", self.name)

        po_id = save_purchase_order(po_data)
        log_info(f"Saved to {PO_FILE}", self.name)
        return po_id

if __name__ == "__main__":
    print("="*60)
    print("Testing Agent 6 - Decision Agent with Email Monitoring")
    print("="*60)

    agent = DecisionAgent()

    print("\nTest 1: Check inbox for quotes")
    print("-"*60)
    result = agent.check_and_parse_quotes('ITM001')
    print(f"Quotes found: {result['quotes_found']}")
    print(f"Quotes parsed: {len(result['parsed_quotes'])}")

    if result['emails_summary']:
        print("\nEmail Summaries:")
        for email_sum in result['emails_summary']:
            print(f" From: {email_sum['from']}")
            print(f" Summary: {email_sum['summary']}\n")

    print("\nTest 2: Quote comparison with manual data")
    print("-"*60)

    test_quotes = [
        {
            'supplier_name': 'NextGen Components',
            'contact_email': 'nextgen.components1@gmail.com',
            'unit_price': 12.50,
            'delivery_days': 10,
            'payment_terms': 'Net 30',
            'quality_certs': 'ISO 9001',
            'risk_score': 15.2
        },
        {
            'supplier_name': 'Pioneer Machineparts',
            'contact_email': 'pioneer.machineparts@gmail.com',
            'unit_price': 11.80,
            'delivery_days': 14,
            'payment_terms': 'Net 45',
            'quality_certs': 'ISO 9001, ISO 14001',
            'risk_score': 22.5
        }
    ]

    result = agent.execute(
        quotes=test_quotes,
        item_code='ITM001',
        item_name='M8 Screws',
        quantity=2536
    )

    if result and 'error' not in result:
        print(f"\nSelected: {result['selected_supplier']}")
        print(f"Total Cost: Rs.{result['po_data']['total_cost']:,.2f}")
        print(f"Needs Approval: {result['needs_user_approval']}")

    print("\n" + "="*60)
    print("Agent 6 testing complete")
    print("="*60)
