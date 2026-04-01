import re
import json
from io import BytesIO
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.groq_helper import groq
from config.settings import GROQ_MODELS
from utils.logger import log_info, log_error

try:
    import PyPDF2 # type: ignore
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    log_error("PyPDF2 not installed, PDF parsing will be disabled", "QuoteParser")


class QuoteParser:
    """Parse supplier quotes from email body and PDF attachments using LLM."""

    def __init__(self):
        self.name = "QuoteParser"
        log_info("Quote Parser initialized", self.name)


    def _extract_pdf_text(self, pdf_data):
        """Extract text from PDF bytes."""
        if not PDF_AVAILABLE:
            log_error("PyPDF2 not available for PDF parsing", self.name)
            return None

        try:
            pdf_file = BytesIO(pdf_data)
            pdf_reader = PyPDF2.PdfReader(pdf_file)

            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text()

            return text
        except Exception as e:
            log_error(f"PDF text extraction failed: {e}", self.name)
            return None


    def _extract_quantity_from_context(self, text):
        """Extract quantity from email text before LLM parsing."""
        try:
            quantity_patterns = [
                r'quantity[:\s]+(\d+)',
                r'qty[:\s]+(\d+)',
                r'(\d+)\s*units?',
                r'(\d+)\s*pieces?',
                r'(\d+)\s*pcs',
                r'order\s+quantity[:\s]+(\d+)',
                r'required[:\s]+(\d+)'
            ]

            text_lower = text.lower()

            for pattern in quantity_patterns:
                match = re.search(pattern, text_lower)
                if match:
                    quantity = int(match.group(1))
                    log_info(f"Extracted quantity from context: {quantity}", self.name)
                    return quantity

            return None

        except Exception as e:
            log_error(f"Quantity extraction failed: {e}", self.name)
            return None

    def _parse_quote_with_llm(self, text, supplier_email, extracted_quantity=None):
        """Use LLM to extract quote information from text."""

        quantity_hint = f"\nNote: Quantity detected as {extracted_quantity} units from context." if extracted_quantity else ""

        prompt = f"""Extract quote information from this supplier email/document.

    Supplier Email: {supplier_email}{quantity_hint}

    Email/Document Content:
    {text[:4000]}

    Extract the following information and return ONLY a JSON object:
    {{
    "supplier_name": "extracted company name",
    "unit_price": extracted price as float (remove currency symbols),
    "total_cost": calculated total or extracted total as float,
    "delivery_days": extracted delivery timeline in days (convert 'weeks' to days, '2 weeks' = 14),
    "payment_terms": "extracted payment terms like Net 30",
    "quality_certs": "extracted certifications like ISO 9001",
    "item_name": "extracted item/product name",
    "quantity": extracted quantity as integer,
    "notes": "any special notes or conditions"
    }}

    Rules:
    - CRITICAL: Quantity is REQUIRED. If not found in text, use null and explain in notes
    - If unit_price is missing but total_cost and quantity exist, calculate: unit_price = total_cost / quantity
    - If total_cost is missing but unit_price and quantity exist, calculate: total_cost = unit_price * quantity
    - Convert delivery timelines to days: "2 weeks" = 14, "1 week" = 7, "10 working days" = 10
    - Extract only ISO certifications, BIS, CE, API standards
    - If information is not found, use null
    - Remove all currency symbols from prices (Rs., INR, etc.)

    Return ONLY the JSON object, no explanation."""

        try:
            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["reasoning"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500
            )

            result_text = response.choices[0].message.content.strip()
            
            log_info(f"Raw LLM response: {result_text[:200]}", self.name)
            
            if not result_text:
                log_error("Empty response from LLM", self.name)
                return None
                
            if '```' in result_text:
                parts = result_text.split('```')
                for part in parts:
                    part = part.strip()
                    if part.startswith('json'):
                        part = part[4:].strip()
                    if part and (part.startswith('{') or part.startswith('[')):
                        result_text = part
                        break
            
            result_text = result_text.strip()
            
            if not result_text.startswith('{'):
                log_error(f"Response doesn't look like JSON: {result_text[:100]}", self.name)
                return None

            quote_data = json.loads(result_text)

            if (quote_data.get('quantity') is None or quote_data.get('quantity') == 0) and extracted_quantity:
                log_info(f"Using context-extracted quantity: {extracted_quantity}", self.name)
                quote_data['quantity'] = extracted_quantity

            required_fields = ['supplier_name', 'unit_price', 'delivery_days', 'quantity']
            for field in required_fields:
                if field not in quote_data or quote_data[field] is None:
                    log_error(f"Missing required field: {field}", self.name)
                    return None

            return quote_data

        except json.JSONDecodeError as e:
            log_error(f"LLM quote parsing failed: {e}", self.name)
            log_error(f"Response was: {result_text[:500] if 'result_text' in locals() else 'No response'}", self.name)
            return None
        except Exception as e:
            log_error(f"LLM quote parsing failed: {e}", self.name)
            return None

    def parse_email_quote(self, email_data):
        """
        Parse quote from email body or PDF attachment

        Args:
            email_data: Dictionary with email details from EmailMonitor

        Returns:
            Dictionary with parsed quote data
        """
        supplier_email = email_data.get('from', '')
        body = email_data.get('body', '')
        attachments = email_data.get('attachments', [])

        extracted_quantity = self._extract_quantity_from_context(body)

        quote_data = None

        if body:
            log_info(f"Parsing quote from email body", self.name)
            quote_data = self._parse_quote_with_llm(body, supplier_email, extracted_quantity)

        if not quote_data and attachments:
            for attachment in attachments:
                log_info(f"Parsing quote from PDF: {attachment['filename']}", self.name)
                pdf_text = self._extract_pdf_text(attachment['data'])

                if pdf_text:
                    if not extracted_quantity:
                        extracted_quantity = self._extract_quantity_from_context(pdf_text)

                    quote_data = self._parse_quote_with_llm(pdf_text, supplier_email, extracted_quantity)
                    if quote_data:
                        break

        if quote_data:
            return {
                'quote_data': quote_data,
                'email_metadata': {
                    'received_at': email_data.get('received_at'),
                    'email_id': email_data.get('email_id'),
                    'subject': email_data.get('subject')
                },
                'parsing_status': 'success'
            }
        else:
            return {
                'quote_data': None,
                'email_metadata': {
                    'received_at': email_data.get('received_at'),
                    'email_id': email_data.get('email_id'),
                    'subject': email_data.get('subject')
                },
                'parsing_status': 'manual_review_needed',
                'error': 'Failed to extract quote information (quantity may be missing)'
            }


    def parse_manual_quote(self, quote_text, supplier_name=None):
        """Parse quote from email body text."""
        log_info("Parsing manually pasted quote", self.name)

        extracted_quantity = self._extract_quantity_from_context(quote_text)

        quote_data = self._parse_quote_with_llm(quote_text, supplier_name or "Unknown", extracted_quantity)

        if quote_data:
            return {
                'quote_data': quote_data,
                'parsing_status': 'success'
            }
        else:
            return {
                'quote_data': None,
                'parsing_status': 'failed',
                'error': 'Failed to parse quote text (quantity may be missing)'
            }


if __name__ == "__main__":
    print("="*60)
    print("Testing Quote Parser")
    print("="*60)

    parser = QuoteParser()

    # Test 1: Parse email quote
    print("\nTest 1: Parse Email Quote")
    print("-"*60)

    test_email = {
        'from': 'nextgen.components1@gmail.com',
        'subject': 'RE: RFQ for M8 Screws',
        'body': """Hello,

Thank you for your RFQ. Here are our quote details:

Item: M8 Screws
Unit Price: Rs. 12.50
Quantity: 2536 units
Total Cost: Rs. 31,700
Delivery Timeline: 10 days
Payment Terms: Net 30
Quality Certifications: ISO 9001:2015

Best regards,
NextGen Components""",
        'attachments': [],
        'received_at': '2026-01-14 10:30:00',
        'email_id': 'test123'
    }

    result = parser.parse_email_quote(test_email)
    print(f"Parsing Status: {result['parsing_status']}")
    if result['parsing_status'] == 'success':
        print("\nExtracted Quote Data:")
        quote = result['quote_data']
        print(f"Supplier: {quote['supplier_name']}")
        print(f"Item: {quote['item_name']}")
        print(f"Unit Price: Rs.{quote['unit_price']}")
        print(f"Quantity: {quote['quantity']}")
        print(f"Total: Rs.{quote['total_cost']}")
        print(f"Delivery: {quote['delivery_days']} days")
        print(f"Payment: {quote['payment_terms']}")
        print(f"Certs: {quote['quality_certs']}")

    # Test 2: Parse manual quote
    print("\n" + "="*60)
    print("Test 2: Parse Manual Quote Text")
    print("-"*60)

    manual_text = """Quote from Pioneer Machineparts:
Unit Rate: Rs. 11.80
Order Quantity: 2536 pcs
Total Amount: Rs. 29,924.80
Delivery: 14 working days
Payment: Net 45 days
Certifications: ISO 9001, ISO 14001"""

    result2 = parser.parse_manual_quote(manual_text, "pioneer.machineparts@gmail.com")
    print(f"Parsing Status: {result2['parsing_status']}")
    if result2['parsing_status'] == 'success':
        print("\nExtracted Quote Data:")
        quote = result2['quote_data']
        print(f"Supplier: {quote['supplier_name']}")
        print(f"Unit Price: Rs.{quote['unit_price']}")
        print(f"Quantity: {quote['quantity']}")
        print(f"Delivery: {quote['delivery_days']} days")

    # Test 3: Test quantity extraction
    print("\n" + "="*60)
    print("Test 3: Quantity Extraction from Context")
    print("-"*60)

    test_texts = [
        "We need 500 units of this product",
        "Quantity: 1000 pieces required",
        "Order qty: 250",
        "Required: 750 pcs for delivery"
    ]

    for text in test_texts:
        qty = parser._extract_quantity_from_context(text)
        print(f"Text: '{text}'")
        print(f"Extracted Quantity: {qty}\n")

    print("\n" + "="*60)
    print("Quote Parser testing complete")
    print("="*60)
    