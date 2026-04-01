import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.base_agent import BaseAgent
from utils.logger import log_info, log_error
from utils.email_helper import EmailHelper
from utils.groq_helper import groq
from config.settings import GROQ_MODELS, COMPANY_NAME, COMPANY_EMAIL, TEST_MODE
from datetime import datetime, timedelta

class RFQGenerator(BaseAgent):
    """Generate professional RFQ emails using AI and send to suppliers."""
    def __init__(self):
        super().__init__(
            name="Agent 5 - RFQ Generator",
            role="RFQ Specialist and Procurement Communication Manager",
            goal="Generate professional RFQ emails and coordinate with suppliers",
            backstory="Expert in supplier communication with 12 years in procurement and vendor management"
        )
        
        try:
            self.email_helper = EmailHelper()
            log_info("Email helper initialized", agent=self.name)
        except ValueError as e:
            log_error(f"Email helper initialization failed: {e}", agent=self.name)
            self.email_helper = None

        self.company_name = COMPANY_NAME
        self.company_email = COMPANY_EMAIL
        self.test_mode = TEST_MODE


        self.test_recipients = [
            'nextgen.components1@gmail.com',
            'pioneer.machineparts@gmail.com'
        ]

    def execute(self, item_code: str, item_name: str, quantity: int, 
                suppliers: list, delivery_days: int = 14) -> dict:
        """Generate and send RFQ emails to suppliers."""
        self.log_start(f"Generating RFQ for {item_code} - {item_name}")

        if not self.email_helper:
            self.log_error("RFQ generation", "Email helper not initialized")
            return {'status': 'error', 'error': 'Email helper not initialized', 'emails_sent': 0}

        try:
            # Generate RFQ content using AI
            rfq_body = self._generate_rfq_content(
                item_code, item_name, quantity, delivery_days
            )

            # Validate RFQ content
            if not self._validate_rfq_content(rfq_body):
                log_error("RFQ validation failed - regenerating", agent=self.name)
                # Try one more time
                rfq_body = self._generate_rfq_content(
                    item_code, item_name, quantity, delivery_days
                )
                if not self._validate_rfq_content(rfq_body):
                    log_error("RFQ validation failed again - using fallback", agent=self.name)
                    # Use fallback if validation fails twice
                    rfq_body = self._fallback_rfq_template(item_code, item_name, quantity, delivery_days)

            subject = f"RFQ: {item_name} - {quantity} units"

            # Determine recipients based on test mode
            if self.test_mode:
                recipient_emails = self.test_recipients
                log_info(f"TEST MODE: Sending to {len(recipient_emails)} test recipients", agent=self.name)
            else:
                # Production mode: use actual supplier emails
                recipient_emails = [s['contact_email'] for s in suppliers if s.get('contact_email')]
                log_info(f"PRODUCTION MODE: Sending to {len(recipient_emails)} actual suppliers", agent=self.name)

            if not recipient_emails:
                self.log_error("RFQ generation", "No valid email addresses found")
                return {'status': 'error', 'error': 'No valid email addresses', 'emails_sent': 0}

            log_info(f"Sending RFQ to {len(recipient_emails)} suppliers", agent=self.name)

            send_results = self.email_helper.send_bulk_email(
                recipients=recipient_emails,
                subject=subject,
                body=rfq_body
            )

            result = {
                'item_code': item_code,
                'item_name': item_name,
                'quantity': quantity,
                'delivery_days': delivery_days,
                'suppliers_contacted': len(recipient_emails),
                'emails_sent': len(send_results['success']),
                'emails_failed': len(send_results['failed']),
                'success_list': send_results['success'],
                'failed_list': send_results['failed'],
                'rfq_subject': subject,
                'rfq_body': rfq_body,
                'test_mode': self.test_mode
            }

            self.log_complete("RFQ generation", 
                            f"Sent to {len(send_results['success'])}/{len(recipient_emails)} suppliers")

            return result

        except Exception as e:
            self.log_error("RFQ generation", str(e))
            return {'status': 'error', 'error': str(e), 'emails_sent': 0}

    def _validate_rfq_content(self, rfq_body: str) -> bool:
        """Validate that RFQ content contains essential keywords."""
        # Convert to lowercase for case-insensitive checking
        body_lower = rfq_body.lower()

        # Essential keywords that MUST be present
        required_keywords = [
            'price',      # Must ask for pricing
            'quotation',  # Must mention quotation/quote
            'delivery'    # Must mention delivery timeline
        ]

        # Check if all required keywords are present
        for keyword in required_keywords:
            if keyword not in body_lower:
                log_error(f"RFQ missing required keyword: {keyword}", agent=self.name)
                return False

        # Additional checks
        # Check minimum length (RFQ should not be too short)
        if len(rfq_body) < 150:
            log_error("RFQ content too short", agent=self.name)
            return False

        log_info("RFQ content validation passed", agent=self.name)
        return True

    def _generate_rfq_content(self, item_code: str, item_name: str, 
                            quantity: int, delivery_days: int) -> str:
        """Generate professional RFQ email body using Groq AI."""
        required_date = (datetime.now() + timedelta(days=delivery_days)).strftime('%B %d, %Y')

        prompt = f"""Generate a professional Request for Quotation (RFQ) email for a manufacturing company.

Item Details:
Item Name: {item_name}
Quantity Required: {quantity} units
Required Delivery Date: {required_date}

Company Details:
Sender: Procurement Team
Company: {self.company_name}
Contact: {self.company_email}

The email MUST:
- Be professional and concise
- DO NOT mention the item code ({item_code}) anywhere - it's internal only
- Clearly request: unit price, total cost, delivery time, payment terms, quality certifications
- Provide 7 days deadline for quote submission
- Be friendly but professional in tone
- Return ONLY the email body (no subject line)
- Keep it under 200 words
- MUST include the words "price", "quotation", and "delivery" somewhere in the email
- Write naturally as if a procurement manager is writing to a supplier."""

        try:
            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["reasoning"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=600
            )

            email_body = response.choices[0].message.content.strip()
            log_info("RFQ content generated using AI", agent=self.name)
            return email_body

        except Exception as e:
            log_error(f"AI content generation failed: {e}", agent=self.name)
            # Return fallback template
            return self._fallback_rfq_template(item_code, item_name, quantity, delivery_days)

    def _fallback_rfq_template(self, item_code: str, item_name: str, 
                             quantity: int, delivery_days: int) -> str:
        """Fallback RFQ template if AI generation fails."""
        required_date = (datetime.now() + timedelta(days=delivery_days)).strftime('%B %d, %Y')

        return f"""Dear Supplier,

We are requesting a quotation for the following requirement:

Item: {item_name}
Quantity: {quantity} units
Required Delivery Date: {required_date}

Please provide your best quotation including:

- Unit price per piece
- Total cost
- Delivery timeline
- Payment terms
- Quality certifications (ISO, if applicable)

Kindly submit your quotation within 7 days.

For any queries, contact us at {self.company_email}

Best regards,
Procurement Team
{self.company_name}"""

if __name__ == "__main__":
    print("="*60)
    print("Testing Agent 5 - RFQ Generator and Email Sender")
    print("="*60)

    agent = RFQGenerator()

    print(f"\nTest Mode: {agent.test_mode}")
    print(f"Company Name: {agent.company_name}")
    print(f"Company Email: {agent.company_email}")

    # Test supplier list (with your real test emails)
    test_suppliers = [
        {
            'supplier_name': 'NextGen Components',
            'contact_email': 'nextgen.components1@gmail.com',
            'location': 'Mumbai',
            'risk_level': 'Low Risk'
        },
        {
            'supplier_name': 'Pioneer Machineparts',
            'contact_email': 'pioneer.machineparts@gmail.com',
            'location': 'Delhi',
            'risk_level': 'Low Risk'
        }
    ]

    # Test 1: RFQ Content Generation
    print("\n" + "="*60)
    print("Test 1: RFQ Content Generation")
    print("-" * 60)

    if agent.email_helper:
        print("\n✓ Email helper initialized")
        print(f"✓ Sender email: {agent.email_helper.sender_email}")

        rfq_content = agent._generate_rfq_content(
            item_code='ITM001',
            item_name='M8 Screws',
            quantity=2536,
            delivery_days=14
        )

        print(f"\n✓ Generated RFQ Email Body:\n")
        print("-" * 60)
        print(rfq_content)
        print("-" * 60)

        # Test validation
        is_valid = agent._validate_rfq_content(rfq_content)
        print(f"\n✓ RFQ Validation: {'PASSED' if is_valid else 'FAILED'}")
    else:
        print("✗ Email helper not initialized. Check .env credentials.")

    # Test 2: Different delivery days
    print("\n" + "="*60)
    print("Test 2: RFQ with Different Delivery Timeline")
    print("-" * 60)

    if agent.email_helper:
        rfq_content_urgent = agent._generate_rfq_content(
            item_code='ITM009',
            item_name='Electric Motors',
            quantity=50,
            delivery_days=7
        )

        print(f"\n✓ Generated RFQ for Urgent Delivery (7 days):\n")
        print("-" * 60)
        print(rfq_content_urgent)
        print("-" * 60)

        is_valid = agent._validate_rfq_content(rfq_content_urgent)
        print(f"\n✓ RFQ Validation: {'PASSED' if is_valid else 'FAILED'}")

    # Test 3: Full execution (TEST MODE - REAL EMAILS)
    print("\n" + "="*60)
    print("Test 3: Full RFQ Execution")
    print("-" * 60)

    if agent.email_helper:
        result = agent.execute(
            item_code='ITM001',
            item_name='M8 Screws',
            quantity=2536,
            suppliers=test_suppliers,
            delivery_days=14
        )

        if result:
            print(f"\n✓ Execution Results:")
            print(f"  Test Mode: {result['test_mode']}")
            print(f"  Item: {result['item_name']}")
            print(f"  Quantity: {result['quantity']} units")
            print(f"  Delivery Days: {result['delivery_days']}")
            print(f"  Suppliers Contacted: {result['suppliers_contacted']}")
            print(f"  Emails Sent: {result['emails_sent']}")
            print(f"  Emails Failed: {result['emails_failed']}")

            if result['success_list']:
                print(f"\n  ✓ Successfully sent to:")
                for email in result['success_list']:
                    print(f"    - {email}")

            if result['failed_list']:
                print(f"\n  ✗ Failed to send to:")
                for email in result['failed_list']:
                    print(f"    - {email}")

            print(f"\n  Email Subject: {result['rfq_subject']}")
        else:
            print("✗ RFQ execution failed")
    else:
        print("✗ Email helper not initialized")

    # Test 4: Output structure verification
    print("\n" + "="*60)
    print("Test 4: Output Structure Verification")
    print("-" * 60)

    if result:
        print("\nChecking required output fields:")
        expected_fields = ['item_code', 'item_name', 'quantity', 'delivery_days',
                          'suppliers_contacted', 'emails_sent', 'success_list', 
                          'rfq_subject', 'rfq_body', 'test_mode']

        for field in expected_fields:
            status = "✓" if field in result else "✗"
            print(f"  {status} {field}")

    print("\n" + "="*60)
    print("Agent 5 testing complete")
    print("="*60)
    