import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.groq_helper import groq
from utils.logger import log_info, log_error
from config.settings import GROQ_MODELS, ACCEPT_THRESHOLD, REJECT_THRESHOLD
from agents.Agent7_communicationOrchestrator import CommunicationOrchestrator
import json
from datetime import datetime


class ExceptionHandler:
    """Analyze mismatches, check supplier history, and generate recommendations."""
    
    def __init__(self):
        self.name = "Agent 9 - Exception Handler"
        log_info("Exception Handler initialized", self.name)
        
        self.agent7 = CommunicationOrchestrator()
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.supplier_history_file = os.path.join(project_root, 'data', 'supplier_history.json')
        
        # Decision thresholds
        self.ACCEPT_THRESHOLD = ACCEPT_THRESHOLD
        self.REJECT_THRESHOLD = REJECT_THRESHOLD
    
    
    def _load_supplier_history(self):
        """Load supplier mismatch history."""
        try:
            if os.path.exists(self.supplier_history_file):
                with open(self.supplier_history_file, 'r') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            log_error(f"Failed to load supplier history: {e}", self.name)
            return {}
    
    
    def _save_supplier_history(self, supplier_name, mismatch_data):
        """Update supplier history with new mismatch."""
        try:
            history = self._load_supplier_history()
            
            if supplier_name not in history:
                history[supplier_name] = {
                    'total_orders': 0,
                    'total_mismatches': 0,
                    'mismatch_incidents': []
                }
            
            history[supplier_name]['total_orders'] += 1
            history[supplier_name]['total_mismatches'] += 1
            history[supplier_name]['mismatch_incidents'].append(mismatch_data)
            
            # Keep only last 10 incidents
            if len(history[supplier_name]['mismatch_incidents']) > 10:
                history[supplier_name]['mismatch_incidents'] = history[supplier_name]['mismatch_incidents'][-10:]
            
            os.makedirs('data', exist_ok=True)
            with open(self.supplier_history_file, 'w') as f:
                json.dump(history, f, indent=2)
            
            log_info(f"Updated supplier history for {supplier_name}", self.name)
            
        except Exception as e:
            log_error(f"Failed to save supplier history: {e}", self.name)
    
    
    def _check_supplier_reputation(self, supplier_name):
        """Check if supplier has history of issues."""
        history = self._load_supplier_history()
        
        if supplier_name not in history:
            return {
                'is_repeat_offender': False,
                'total_mismatches': 0,
                'mismatch_rate': 0.0
            }
        
        supplier_data = history[supplier_name]
        total_orders = supplier_data['total_orders']
        total_mismatches = supplier_data['total_mismatches']
        
        mismatch_rate = (total_mismatches / total_orders * 100) if total_orders > 0 else 0
        
        # Recent 6 months check
        recent_incidents = supplier_data['mismatch_incidents'][-6:]
        is_repeat_offender = len(recent_incidents) >= 3
        
        return {
            'is_repeat_offender': is_repeat_offender,
            'total_mismatches': total_mismatches,
            'total_orders': total_orders,
            'mismatch_rate': round(mismatch_rate, 2),
            'recent_incidents': len(recent_incidents)
        }
    
    
    def analyze_mismatch(self, verification_result):
        """Analyze verification mismatches (quantities, prices) and quality defects."""
        log_info(f"Analyzing issues for PO: {verification_result['po_number']}", self.name)
        
        # Check for quality defects even if 3-way match passed
        quality_defect_rate = 0.0
        if 'quality_inspection' in verification_result:
            quality_defect_rate = verification_result['quality_inspection'].get('defect_rate', 0.0)
            log_info(f"Quality defect rate detected: {quality_defect_rate*100}%", self.name)

        if verification_result['match_result'] == 'PASS' and quality_defect_rate < 0.05:
            return {
                'status': 'no_action_needed',
                'message': 'No significant mismatches or quality defects detected'
            }
        
        mismatches = verification_result.get('mismatches', [])
        po_data = verification_result['po_data']
        supplier_name = po_data['supplier_name']
        
        # Calculate financial impact for each mismatch
        analyses = []
        total_financial_impact = 0.0
        
        for mismatch in mismatches:
            field = mismatch['field']
            
            if field == 'quantity':
                expected = mismatch['po_value']
                actual_delivery = mismatch['delivery_value']
                actual_invoice = mismatch['invoice_value']
                
                # Use delivery qty as actual
                actual = actual_delivery if actual_delivery else actual_invoice
                
                if actual and expected:
                    diff = expected - actual
                    diff_percent = abs(diff / expected * 100)
                    financial_impact = abs(diff * po_data['unit_price'])
                    
                    analyses.append({
                        'field': 'quantity',
                        'expected': expected,
                        'actual': actual,
                        'difference': diff,
                        'difference_percent': round(diff_percent, 2),
                        'financial_impact': round(financial_impact, 2)
                    })
                    
                    total_financial_impact += financial_impact
            
            elif field == 'unit_price':
                expected_price = mismatch['po_value']
                actual_price = mismatch['invoice_value']
                
                if actual_price and expected_price:
                    price_diff = actual_price - expected_price
                    price_diff_percent = abs(price_diff / expected_price * 100)
                    financial_impact = abs(price_diff * po_data['quantity'])
                    
                    analyses.append({
                        'field': 'unit_price',
                        'expected': expected_price,
                        'actual': actual_price,
                        'difference': price_diff,
                        'difference_percent': round(price_diff_percent, 2),
                        'financial_impact': round(financial_impact, 2)
                    })
                    
                    total_financial_impact += financial_impact
            
            elif field == 'total_amount':
                expected_total = mismatch['po_value']
                actual_total = mismatch['invoice_value']
                
                if actual_total and expected_total:
                    total_diff = actual_total - expected_total
                    total_diff_percent = abs(total_diff / expected_total * 100)
                    
                    analyses.append({
                        'field': 'total_amount',
                        'expected': expected_total,
                        'actual': actual_total,
                        'difference': total_diff,
                        'difference_percent': round(total_diff_percent, 2),
                        'financial_impact': abs(total_diff)
                    })
        
        # Calculate max discrepancy percentage
        max_discrepancy_percent = max([a['difference_percent'] for a in analyses]) if analyses else 0
        
        # Check supplier reputation
        reputation = self._check_supplier_reputation(supplier_name)
        
        # Apply decision rules (considering both mismatches and quality)
        is_high_discrepancy = max_discrepancy_percent > self.REJECT_THRESHOLD
        is_high_defects = quality_defect_rate > 0.30  # Threshold for quality rejection
        
        if max_discrepancy_percent < self.ACCEPT_THRESHOLD and quality_defect_rate < 0.05 and not reputation['is_repeat_offender']:
            recommended_action = "accept_with_deduction"
            escalation_flag = "auto_resolve"
        elif is_high_discrepancy or is_high_defects or reputation['is_repeat_offender']:
            recommended_action = "reject_shipment"
            escalation_flag = "needs_human_approval"
        else:
            recommended_action = "escalate_to_manager"
            escalation_flag = "needs_human_approval"
        
        # Generate explanation using LLM
        explanation = self._generate_explanation(
            analyses, 
            recommended_action, 
            reputation, 
            supplier_name
        )
        
        # Generate email draft to supplier
        email_draft = self._generate_supplier_email(
            po_data,
            analyses,
            recommended_action
        )
        
        result = {
            'status': 'analysis_complete',
            'po_number': verification_result['po_number'],
            'supplier_name': supplier_name,
            'mismatch_analyses': analyses,
            'max_discrepancy_percent': round(max_discrepancy_percent, 2),
            'total_financial_impact': round(total_financial_impact, 2),
            'supplier_reputation': reputation,
            'recommended_action': recommended_action,
            'escalation_flag': escalation_flag,
            'explanation': explanation,
            'email_draft': email_draft,
            'analyzed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Update supplier history
        mismatch_record = {
            'po_number': verification_result['po_number'],
            'date': datetime.now().strftime('%Y-%m-%d'),
            'discrepancy_percent': max_discrepancy_percent,
            'financial_impact': total_financial_impact,
            'action_taken': recommended_action
        }
        self._save_supplier_history(supplier_name, mismatch_record)
        
        # Send email via Agent 7 if action is to contact supplier
        if recommended_action in ['accept_with_deduction', 'reject_shipment']:
            self._send_supplier_email(supplier_name, po_data, email_draft)
        
        log_info(f"Analysis complete: {recommended_action}", self.name)
        
        return result
    
    
    def _generate_explanation(self, analyses, recommended_action, reputation, supplier_name):
        """Generate natural language explanation for the recommendation."""
        try:
            analyses_text = json.dumps(analyses, indent=2)
            reputation_text = json.dumps(reputation, indent=2)
            
            prompt = f"""Generate a brief, professional explanation (2-3 sentences) for why this recommendation was made.

Supplier: {supplier_name}
Recommended Action: {recommended_action}

Mismatch Details:
{analyses_text}

Supplier Reputation:
{reputation_text}

Write a concise explanation covering:
1. What the main discrepancy is
2. Why this action is recommended
3. Any relevant supplier history context

Keep it professional and factual."""
            
            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["reasoning"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=300
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            log_error(f"Explanation generation failed: {e}", self.name)
            return f"Discrepancy detected. Recommended action: {recommended_action} based on threshold analysis and supplier history."
    
    
    def _generate_supplier_email(self, po_data, analyses, recommended_action):
        """Generate email draft to send to supplier."""
        try:
            analyses_text = json.dumps(analyses, indent=2)
            
            prompt = f"""Generate a professional email to the supplier about a delivery/invoice mismatch.

PO Number: {po_data['po_number']}
Item: {po_data['item_name']}
Supplier: {po_data['supplier_name']}
Recommended Action: {recommended_action}

Discrepancies Found:
{analyses_text}

Write a polite but firm email that:
1. References the PO number
2. States the specific discrepancies found
3. Requests explanation or correction
4. Mentions next steps based on action ({recommended_action})

Keep tone professional, not accusatory. Format as a complete email with subject line."""
            
            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["reasoning"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=500
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            log_error(f"Email draft generation failed: {e}", self.name)
            return f"Subject: Discrepancy in PO {po_data['po_number']}\n\nDear Supplier,\n\nWe have identified discrepancies in the delivery for PO {po_data['po_number']}. Please review and respond."
    
    
    def _send_supplier_email(self, supplier_name, po_data, email_draft):
        """Send email to supplier via Agent 7."""
        event_data = {
            'supplier_name': supplier_name,
            'supplier_email': po_data.get('contact_email', 'unknown'),
            'po_number': po_data['po_number'],
            'item_name': po_data['item_name'],
            'email_body': email_draft
        }
        
        try:
            self.agent7.send_notification('mismatch_email_to_supplier', event_data)
            log_info(f"Mismatch email sent to {supplier_name} via Agent 7", self.name)
        except Exception as e:
            log_error(f"Failed to send supplier email: {e}", self.name)


if __name__ == "__main__":
    print("="*60)
    print("Testing Agent 9 - Exception Handler")
    print("="*60)
    
    agent = ExceptionHandler()
    
    # Mock verification result from Agent 8
    mock_verification = {
        'status': 'success',
        'po_number': 'PO-ITM001-20240115',
        'match_result': 'FAIL',
        'mismatches': [
            {
                'field': 'quantity',
                'po_value': 2300,
                'delivery_value': 2250,
                'invoice_value': 2250
            }
        ],
        'po_data': {
            'po_number': 'PO-ITM001-20240115',
            'supplier_name': 'NextGen Components',
            'contact_email': 'nextgen.components1@gmail.com',
            'item_name': 'M8 Screws',
            'quantity': 2300,
            'unit_price': 7.80,
            'total_cost': 17940.00
        }
    }
    
    print("\nTest: Analyze mismatch")
    print("-"*60)
    
    result = agent.analyze_mismatch(mock_verification)
    print(json.dumps(result, indent=2))
