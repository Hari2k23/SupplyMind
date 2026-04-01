import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.groq_helper import groq
from utils.logger import log_info, log_error
from config.settings import GROQ_MODELS
from agents.Agent7_communicationOrchestrator import CommunicationOrchestrator
import json
from datetime import datetime
from xhtml2pdf import pisa
from io import BytesIO
import base64


class QualityReportGenerator:
    """
    Agent 11 - Quality Report Generator
    Creates comprehensive PDF reports of entire delivery flow
    PO creation → Supplier selection → Verification → Storage
    """

    def __init__(self):
        self.name = "Agent 11 - Quality Report Generator"
        log_info("Quality Report Generator initialized", self.name)

        self.agent7 = CommunicationOrchestrator()
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.reports_dir = os.path.join(project_root, 'data', 'reports')

        os.makedirs(self.reports_dir, exist_ok=True)

    def generate_executive_summary(self, full_data):
        """Generate executive summary using LLM"""
        try:
            po_data = full_data['po_data']
            verification = full_data['verification_result']

            prompt = f"""Generate a concise executive summary (2-3 sentences) for this procurement delivery report.

PO Number: {po_data['po_number']}
Item: {po_data['item_name']}
Quantity: {po_data['quantity']} units
Supplier: {po_data['supplier_name']}
Total Cost: Rs.{po_data['total_cost']:,.2f}
Verification Result: {verification['match_result']}
Mismatches: {verification['mismatch_count']}

Write a professional summary covering:
1. What was ordered
2. Verification outcome
3. Key highlights or concerns

Keep it brief and factual."""

            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["reasoning"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=200
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            log_error(f"Summary generation failed: {e}", self.name)
            return f"Procurement report for {po_data['item_name']} - {verification['match_result']}"

    def generate_findings_section(self, full_data):
        """Generate detailed findings using LLM"""
        try:
            verification = full_data['verification_result']
            exception_analysis = full_data.get('exception_analysis')

            findings_data = {
                'verification_status': verification['match_result'],
                'mismatches': verification['mismatches'],
                'exception_action': exception_analysis.get('recommended_action') if exception_analysis else None
            }

            prompt = f"""Generate a detailed findings section for a procurement report.

Verification Data:
{json.dumps(findings_data, indent=2)}

Write 2-3 paragraphs covering:
1. Verification process and results
2. Any discrepancies found (be specific)
3. Actions taken or recommended

Be professional and thorough."""

            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["reasoning"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=400
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            log_error(f"Findings generation failed: {e}", self.name)
            return "Verification completed. See details below."

    def _image_to_base64_data_uri(self, image_path):
        """Convert image to base64 data URI for embedding in HTML"""
        try:
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            return f"data:image/jpeg;base64,{image_data}"
        except Exception as e:
            log_error(f"Image encoding failed: {e}", self.name)
            return None

    def create_html_report(self, full_data, delivery_note_path, invoice_path):
        """Create HTML report from template"""

        po_data = full_data['po_data']
        verification = full_data['verification_result']
        storage_result = full_data.get('storage_result', {})
        exception_analysis = full_data.get('exception_analysis')

        # Generate LLM content
        executive_summary = self.generate_executive_summary(full_data)
        findings = self.generate_findings_section(full_data)

        # Embed images as base64
        delivery_img = self._image_to_base64_data_uri(delivery_note_path)
        invoice_img = self._image_to_base64_data_uri(invoice_path)

        # Build mismatch table
        mismatch_rows = ""
        if verification['mismatches']:
            for m in verification['mismatches']:
                mismatch_rows += f"""
                <tr>
                    <td>{m['field']}</td>
                    <td>{m.get('po_value', 'N/A')}</td>
                    <td>{m.get('delivery_value', 'N/A')}</td>
                    <td>{m.get('invoice_value', 'N/A')}</td>
                </tr>
                """
        else:
            mismatch_rows = "<tr><td colspan='4'>No mismatches detected</td></tr>"

        # Exception analysis section
        exception_section = ""
        if exception_analysis:
            exception_section = f"""
            <div class="section">
                <h2>Exception Analysis</h2>
                <p><strong>Recommended Action:</strong> {exception_analysis['recommended_action']}</p>
                <p><strong>Financial Impact:</strong> Rs.{exception_analysis.get('total_financial_impact', 0):,.2f}</p>
                <p><strong>Supplier Reputation:</strong> {exception_analysis['supplier_reputation']['mismatch_rate']}% mismatch rate</p>
                <p><strong>Explanation:</strong> {exception_analysis.get('explanation', 'N/A')}</p>
            </div>
            """

        # Image section
        image_section = ""
        if delivery_img and invoice_img:
            image_section = f"""
            <div class="section">
                <h2>Document Evidence</h2>
                <div style="margin-bottom: 20px;">
                    <h3>Delivery Note</h3>
                    <img src="{delivery_img}" style="max-width: 100%; border: 1px solid #ddd;">
                </div>
                <div>
                    <h3>Invoice</h3>
                    <img src="{invoice_img}" style="max-width: 100%; border: 1px solid #ddd;">
                </div>
            </div>
            """

        html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    margin: 40px;
                    color: #333;
                }}
                .header {{
                    text-align: center;
                    border-bottom: 3px solid #2c3e50;
                    padding-bottom: 20px;
                    margin-bottom: 30px;
                }}
                .header h1 {{
                    color: #2c3e50;
                    margin: 0;
                }}
                .header p {{
                    color: #7f8c8d;
                    margin: 5px 0;
                }}
                .section {{
                    margin-bottom: 30px;
                    padding: 20px;
                    background: #f8f9fa;
                    border-left: 4px solid #3498db;
                }}
                .section h2 {{
                    color: #2c3e50;
                    margin-top: 0;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin: 15px 0;
                }}
                th, td {{
                    padding: 12px;
                    text-align: left;
                    border-bottom: 1px solid #ddd;
                }}
                th {{
                    background-color: #3498db;
                    color: white;
                }}
                tr:hover {{
                    background-color: #f5f5f5;
                }}
                .status-pass {{
                    color: #27ae60;
                    font-weight: bold;
                }}
                .status-fail {{
                    color: #e74c3c;
                    font-weight: bold;
                }}
                .footer {{
                    margin-top: 50px;
                    padding-top: 20px;
                    border-top: 2px solid #ddd;
                    text-align: center;
                    color: #7f8c8d;
                    font-size: 12px;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Delivery Quality Report</h1>
                <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p>PO Number: {po_data['po_number']}</p>
            </div>

            <div class="section">
                <h2>Executive Summary</h2>
                <p>{executive_summary}</p>
            </div>

            <div class="section">
                <h2>Purchase Order Details</h2>
                <table>
                    <tr><th>Field</th><th>Value</th></tr>
                    <tr><td>PO Number</td><td>{po_data['po_number']}</td></tr>
                    <tr><td>Item Name</td><td>{po_data['item_name']}</td></tr>
                    <tr><td>Item Code</td><td>{po_data['item_code']}</td></tr>
                    <tr><td>Supplier</td><td>{po_data['supplier_name']}</td></tr>
                    <tr><td>Quantity Ordered</td><td>{po_data['quantity']} units</td></tr>
                    <tr><td>Unit Price</td><td>Rs.{po_data['unit_price']}</td></tr>
                    <tr><td>Total Cost</td><td>Rs.{po_data['total_cost']:,.2f}</td></tr>
                    <tr><td>Expected Delivery</td><td>{po_data.get('expected_delivery_date', 'N/A')}</td></tr>
                </table>
            </div>

            <div class="section">
                <h2>Verification Results</h2>
                <p><strong>Status:</strong> <span class="{'status-pass' if verification['match_result'] == 'PASS' else 'status-fail'}">{verification['match_result']}</span></p>
                <p><strong>Mismatches Found:</strong> {verification['mismatch_count']}</p>

                <h3>3-Way Match Details</h3>
                <table>
                    <tr>
                        <th>Field</th>
                        <th>PO Value</th>
                        <th>Delivery Note</th>
                        <th>Invoice</th>
                    </tr>
                    {mismatch_rows}
                </table>
            </div>

            {exception_section}

            <div class="section">
                <h2>Findings & Recommendations</h2>
                <p>{findings}</p>
            </div>

            <div class="section">
                <h2>Data Storage Summary</h2>
                <p><strong>Goods Receipt ID:</strong> {storage_result.get('receipt_id', 'N/A')}</p>
                <p><strong>Inventory Updated:</strong> {'Yes' if storage_result.get('inventory_updated') else 'No'}</p>
                <p><strong>Payment Record ID:</strong> {storage_result.get('payment_id', 'N/A')}</p>
                <p><strong>Documents Saved:</strong> {'Yes' if storage_result.get('documents_saved') else 'No'}</p>
            </div>

            {image_section}

            <div class="footer">
                <p>This report was automatically generated by the Multi-Agent Procurement System</p>
                <p>Agent 11 - Quality Report Generator</p>
            </div>
        </body>
        </html>
        """

        return html_template

    def generate_report(self, full_data, delivery_note_path, invoice_path):
        """
        Generate complete PDF report

        Args:
            full_data: Dictionary containing all workflow data
            delivery_note_path: Path to delivery note image
            invoice_path: Path to invoice image

        Returns:
            Path to generated PDF
        """
        log_info(f"Generating quality report for PO: {full_data['po_data']['po_number']}", self.name)

        try:
            # Create HTML
            html_content = self.create_html_report(full_data, delivery_note_path, invoice_path)

            # Generate PDF filename
            po_number = full_data['po_data']['po_number']
            pdf_filename = f"{po_number}_delivery_report.pdf"
            pdf_path = os.path.join(self.reports_dir, pdf_filename)

            # Convert HTML to PDF using xhtml2pdf
            with open(pdf_path, 'wb') as pdf_file:
                pisa_status = pisa.CreatePDF(
                    html_content,
                    dest=pdf_file
                )

            if pisa_status.err:
                log_error(f"PDF generation had errors", self.name)
                return None

            log_info(f"PDF report generated: {pdf_path}", self.name)

            # Send report via Agent 7
            self._send_report_notification(full_data, pdf_path)

            return pdf_path

        except Exception as e:
            log_error(f"Report generation failed: {e}", self.name)
            return None

    def _send_report_notification(self, full_data, pdf_path):
        """Send final report notification via Agent 7"""
        po_data = full_data['po_data']
        verification = full_data['verification_result']

        event_data = {
            'po_number': po_data['po_number'],
            'item_name': po_data['item_name'],
            'supplier_name': po_data['supplier_name'],
            'verification_status': verification['match_result'],
            'report_path': pdf_path,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        try:
            self.agent7.send_notification('final_report', event_data)
            log_info("Final report notification sent via Agent 7", self.name)
        except Exception as e:
            log_error(f"Failed to send report notification: {e}", self.name)


if __name__ == "__main__":
    print("="*60)
    print("Testing Agent 11 - Quality Report Generator")
    print("="*60)

    agent = QualityReportGenerator()

    # Mock full workflow data
    mock_data = {
        'po_data': {
            'po_number': 'PO-ITM001-20240115',
            'item_code': 'ITM001',
            'item_name': 'M8 Screws',
            'supplier_name': 'NextGen Components',
            'quantity': 2300,
            'unit_price': 7.80,
            'total_cost': 17940.00,
            'expected_delivery_date': '2024-01-25'
        },
        'verification_result': {
            'match_result': 'PASS',
            'mismatch_count': 0,
            'mismatches': [],
            'verified_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        },
        'storage_result': {
            'receipt_id': 'GR-PO-ITM001-20240115',
            'inventory_updated': True,
            'payment_id': 'PAY-PO-ITM001-20240115',
            'documents_saved': True
        }
    }

    print("\nTest: Generate HTML preview")
    print("-"*60)


    print("\nAgent 11 test structure ready (provide actual images for full PDF generation)")
