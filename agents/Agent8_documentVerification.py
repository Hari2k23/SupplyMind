import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.groq_helper import groq
from utils.logger import log_info, log_error
from config.settings import GROQ_MODELS
from agents.Agent7_communicationOrchestrator import CommunicationOrchestrator
import json
import base64
from datetime import datetime


class DocumentVerificationAgent:
    """Extract data from delivery notes and invoices using vision AI and perform 3-way matching."""
    
    def __init__(self):
        self.name = "Agent 8 - Document Verification"
        log_info("Document Verification Agent initialized", self.name)
        
        self.agent7 = CommunicationOrchestrator()
        
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.po_file = os.path.join(project_root, 'data', 'purchase_orders.json')
    
    def _load_purchase_order(self, po_number):
        """Load PO data from JSON."""
        try:
            if os.path.exists(self.po_file):
                with open(self.po_file, 'r') as f:
                    pos = json.load(f)
                    return pos.get(po_number)
            return None
        except Exception as e:
            log_error(f"Failed to load PO: {e}", self.name)
            return None
    
    
    def _image_to_base64(self, image_path):
        """Convert image to base64."""
        try:
            with open(image_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            log_error(f"Image encoding failed: {e}", self.name)
            return None
    
    
    def extract_document_data(self, image_path, document_type='invoice'):
        """Extract structured data from document image using Groq vision."""
        log_info(f"Extracting data from {document_type}: {image_path}", self.name)
        
        base64_image = self._image_to_base64(image_path)
        
        if not base64_image:
            return {
                'status': 'failed',
                'error': 'Image encoding failed'
            }
        
        prompt = f"""Extract ALL fields from this {document_type} image and return ONLY a JSON object.

Required fields to extract:
- item_name: Product/item name
- item_code: SKU or item code
- quantity: Number of units
- unit_price: Price per unit (numeric only, no currency symbols)
- total_amount: Total cost (numeric only)
- supplier_name: Vendor/supplier name
- invoice_number or delivery_note_number: Document ID
- date: Document date

Additional fields if present:
- delivery_date: Expected or actual delivery date
- payment_terms: Payment conditions
- tax_amount: Tax/GST amount

CRITICAL RULES:
1. Return ONLY valid JSON, no markdown, no explanation
2. If text is unclear/illegible, set value as "UNCLEAR"
3. All numeric values must be numbers only (no Rs, INR, commas)
4. If field not found, set as null

Example output:
{{
  "item_name": "M8 Screws",
  "item_code": "ITM001",
  "quantity": 2300,
  "unit_price": 7.80,
  "total_amount": 17940.00,
  "supplier_name": "NextGen Components",
  "invoice_number": "INV-2024-001",
  "date": "2024-01-15",
  "clarity_issues": ["unit_price slightly blurry"]
}}"""
        
        try:
            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["vision"],
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                temperature=0.1,
                max_tokens=1000
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Log the raw response for debugging
            log_info(f"Vision API raw response: {result_text[:200]}", self.name)
            
            # Check if response is empty
            if not result_text:
                raise ValueError("Vision API returned empty response")
            
            # Clean markdown if present
            if result_text.startswith('```json'):
                result_text = result_text.replace('```json', '').replace('```', '').strip()
            
            extracted_data = json.loads(result_text)
            extracted_data['status'] = 'success'
            extracted_data['document_type'] = document_type
            
            log_info(f"Successfully extracted data from {document_type}", self.name)
            return extracted_data
            
        except Exception as e:
            log_error(f"Data extraction failed: {e}", self.name)
            return {
                'status': 'failed',
                'error': str(e)
            }
    
    
    def perform_3way_match(self, po_number, delivery_note_path, invoice_path):
        """Perform 3-way matching: PO vs Delivery Note vs Invoice."""
        log_info(f"Performing 3-way match for PO: {po_number}", self.name)
        
        # Load PO data
        po_data = self._load_purchase_order(po_number)
        
        if not po_data:
            return {
                'status': 'failed',
                'error': f'PO {po_number} not found'
            }
        
        # Extract delivery note data
        delivery_data = self.extract_document_data(delivery_note_path, 'delivery_note')
        
        if delivery_data['status'] != 'success':
            return {
                'status': 'failed',
                'error': 'Delivery note extraction failed',
                'details': delivery_data
            }
        
        # Extract invoice data
        invoice_data = self.extract_document_data(invoice_path, 'invoice')
        
        if invoice_data['status'] != 'success':
            return {
                'status': 'failed',
                'error': 'Invoice extraction failed',
                'details': invoice_data
            }
        
        # Perform matching
        mismatches = []
        
        # Check item name/code
        if po_data['item_code'] != delivery_data.get('item_code'):
            mismatches.append({
                'field': 'item_code',
                'po_value': po_data['item_code'],
                'delivery_value': delivery_data.get('item_code'),
                'invoice_value': invoice_data.get('item_code')
            })
        
        # Check quantity
        po_qty = po_data['quantity']
        delivery_qty = delivery_data.get('quantity')
        invoice_qty = invoice_data.get('quantity')
        
        if po_qty != delivery_qty or po_qty != invoice_qty or delivery_qty != invoice_qty:
            mismatches.append({
                'field': 'quantity',
                'po_value': po_qty,
                'delivery_value': delivery_qty,
                'invoice_value': invoice_qty
            })
        
        # Check unit price
        po_price = po_data['unit_price']
        invoice_price = invoice_data.get('unit_price')
        
        if po_price != invoice_price:
            price_diff = abs(po_price - invoice_price) if invoice_price else 0
            # Allow 1 paisa tolerance
            if price_diff > 0.01:
                mismatches.append({
                    'field': 'unit_price',
                    'po_value': po_price,
                    'delivery_value': 'N/A',
                    'invoice_value': invoice_price
                })
        
        # Check total amount
        po_total = po_data['total_cost']
        invoice_total = invoice_data.get('total_amount')
        
        if invoice_total:
            total_diff = abs(po_total - invoice_total)
            # Allow Rs.1 tolerance
            if total_diff > 1.0:
                mismatches.append({
                    'field': 'total_amount',
                    'po_value': po_total,
                    'delivery_value': 'N/A',
                    'invoice_value': invoice_total
                })
        
        # Determine match status
        match_status = "PASS" if len(mismatches) == 0 else "FAIL"
        
        result = {
            'status': 'success',
            'po_number': po_number,
            'match_result': match_status,
            'mismatches': mismatches,
            'mismatch_count': len(mismatches),
            'po_data': po_data,
            'delivery_data': delivery_data,
            'invoice_data': invoice_data,
            'verified_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        log_info(f"3-way match result: {match_status} ({len(mismatches)} mismatches)", self.name)
        
        # Send quick alert via Agent 7
        self._send_verification_alert(result)
        
        return result
    
    
    def _send_verification_alert(self, verification_result):
        """Send quick verification alert via Agent 7."""
        event_data = {
            'po_number': verification_result['po_number'],
            'match_result': verification_result['match_result'],
            'mismatch_count': verification_result['mismatch_count'],
            'mismatches': verification_result['mismatches'],
            'item_name': verification_result['po_data']['item_name'],
            'verified_at': verification_result['verified_at']
        }
        
        try:
            self.agent7.send_notification('verification_complete', event_data)
            log_info("Verification alert sent via Agent 7", self.name)
        except Exception as e:
            log_error(f"Failed to send verification alert: {e}", self.name)


if __name__ == "__main__":
    print("="*60)
    print("Testing Agent 8 - Document Verification")
    print("="*60)
    
    agent = DocumentVerificationAgent()
    
    # Test with sample images
    print("\nTest 1: Extract invoice data")
    print("-"*60)
    
    # You'll need to provide actual image paths
    # invoice_result = agent.extract_document_data('data/documents/sample_invoice.jpg', 'invoice')
    
    print("\nTest 2: Perform 3-way match")
    print("-"*60)
    
    # match_result = agent.perform_3way_match(
    #     'PO-ITM001-20240115_120000',
    #     'data/documents/delivery_note.jpg',
    #     'data/documents/invoice.jpg'
    # )
    
    print("\nAgent 8 test structure ready (provide actual images to test)")
    