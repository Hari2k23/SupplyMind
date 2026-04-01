import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import log_info, log_error
import json
import csv
import shutil
from datetime import datetime, timedelta


class DataStorageAgent:
    """
    Agent 10 - Data Storage Agent
    Saves verified delivery data to JSON files
    Updates inventory (CSV), logs receipts, tracks supplier history
    """

    def __init__(self):
        self.name = "Agent 10 - Data Storage"
        log_info("Data Storage Agent initialized", self.name)

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.goods_receipts_file = os.path.join(project_root, 'data', 'goods_receipts.json')
        self.inventory_csv_file = os.path.join(project_root, 'data', 'current_inventory.csv')
        self.payments_due_file = os.path.join(project_root, 'data', 'payments_due.json')
        self.documents_dir = os.path.join(project_root, 'data', 'documents')

        # Ensure directories exist
        os.makedirs('data', exist_ok=True)
        os.makedirs(self.documents_dir, exist_ok=True)

    def _load_json_file(self, filepath):
        """Load JSON file"""
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        # File is empty, return empty structure
                        return {} if 'receipts' in filepath or 'payments' in filepath else []
                    return json.loads(content)
            return {} if 'receipts' in filepath or 'payments' in filepath else []
        except json.JSONDecodeError:
            # File exists but is empty or invalid, return empty structure
            log_info(f"Initializing empty {os.path.basename(filepath)}", self.name)
            return {} if 'receipts' in filepath or 'payments' in filepath else []
        except Exception as e:
            log_error(f"Failed to load {filepath}: {e}", self.name)
            return {} if 'receipts' in filepath or 'payments' in filepath else []

    def _load_inventory_csv(self):
        """Load inventory from CSV file"""
        try:
            if not os.path.exists(self.inventory_csv_file):
                log_error("Inventory CSV file not found", self.name)
                return []
            
            inventory = []
            with open(self.inventory_csv_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    inventory.append(row)
            
            log_info(f"Loaded {len(inventory)} items from CSV", self.name)
            return inventory
        
        except Exception as e:
            log_error(f"Failed to load CSV: {e}", self.name)
            return []

    def _save_inventory_csv(self, inventory):
        """Save inventory back to CSV file"""
        try:
            if not inventory:
                log_error("No inventory data to save", self.name)
                return False
            
            # Get fieldnames from first item
            fieldnames = list(inventory[0].keys())
            
            with open(self.inventory_csv_file, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(inventory)
            
            log_info("Saved inventory to CSV", self.name)
            return True
        
        except Exception as e:
            log_error(f"Failed to save CSV: {e}", self.name)
            return False

    def _save_json_file(self, filepath, data):
        """Save JSON file"""
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            log_info(f"Saved data to {filepath}", self.name)
            return True
        except Exception as e:
            log_error(f"Failed to save {filepath}: {e}", self.name)
            return False

    def save_goods_receipt(self, verification_result, exception_analysis=None):
        """
        Save goods receipt record

        Args:
            verification_result: Output from Agent 8
            exception_analysis: Optional output from Agent 9

        Returns:
            Receipt ID
        """
        log_info(f"Saving goods receipt for PO: {verification_result['po_number']}", self.name)

        receipts = self._load_json_file(self.goods_receipts_file)

        po_data = verification_result['po_data']
        delivery_data = verification_result['delivery_data']

        receipt_id = f"GR-{verification_result['po_number']}-{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        receipt_record = {
            'receipt_id': receipt_id,
            'po_number': verification_result['po_number'],
            'supplier_name': po_data['supplier_name'],
            'item_code': po_data['item_code'],
            'item_name': po_data['item_name'],
            'ordered_quantity': po_data['quantity'],
            'received_quantity': delivery_data.get('quantity', po_data['quantity']),
            'unit_price': po_data['unit_price'],
            'total_cost': po_data['total_cost'],
            'verification_status': verification_result['match_result'],
            'mismatch_count': verification_result['mismatch_count'],
            'mismatches': verification_result['mismatches'],
            'received_date': datetime.now().strftime('%Y-%m-%d'),
            'verified_at': verification_result['verified_at'],
            'exception_action': exception_analysis.get('recommended_action') if exception_analysis else None,
            'financial_impact': exception_analysis.get('total_financial_impact', 0.0) if exception_analysis else 0.0
        }

        receipts[receipt_id] = receipt_record

        if self._save_json_file(self.goods_receipts_file, receipts):
            log_info(f"Goods receipt saved: {receipt_id}", self.name)
            return receipt_id
        else:
            return None

    def update_inventory(self, verification_result):
        """
        Update inventory CSV with received quantity

        Args:
            verification_result: Output from Agent 8

        Returns:
            Updated inventory record
        """
        log_info(f"Updating inventory for item: {verification_result['po_data']['item_code']}", self.name)

        # Load inventory from CSV
        inventory = self._load_inventory_csv()
        
        if not inventory:
            log_error("Failed to load inventory CSV", self.name)
            return None

        item_code = verification_result['po_data']['item_code']
        item_name = verification_result['po_data']['item_name']
        received_qty = verification_result['delivery_data'].get('quantity', verification_result['po_data']['quantity'])

        # Find item in inventory
        item_found = False
        current_stock = 0
        
        for item in inventory:
            if item['item_code'] == item_code:
                old_stock = int(item['current_quantity'])
                new_stock = old_stock + received_qty
                item['current_quantity'] = str(new_stock)
                item['last_updated'] = datetime.now().strftime('%Y-%m-%d')
                current_stock = new_stock
                log_info(f"Updated stock: {old_stock} → {current_stock}", self.name)
                item_found = True
                break

        # If item not found, create new entry
        if not item_found:
            log_info(f"Item {item_code} not found - creating new inventory entry", self.name)
            
            # Create new row matching CSV structure
            new_item = {
                'item_code': item_code,
                'item_name': item_name,
                'current_quantity': str(received_qty),
                'reorder_point': '100',  # Default
                'max_capacity': '5000',  # Default
                'unit': 'pieces',  # Default
                'warehouse_location': 'Warehouse A - Pending',  # Default
                'last_updated': datetime.now().strftime('%Y-%m-%d')
            }
            inventory.append(new_item)
            current_stock = received_qty
            log_info(f"Created new inventory item: {item_code} with initial stock {received_qty}", self.name)

        # Save back to CSV
        if self._save_inventory_csv(inventory):
            return {
                'item_code': item_code,
                'quantity_added': received_qty,
                'new_stock_level': current_stock,
                'newly_created': not item_found
            }
        else:
            return None

    def create_payment_record(self, verification_result, exception_analysis=None):
        """
        Create payment due record

        Args:
            verification_result: Output from Agent 8
            exception_analysis: Optional output from Agent 9

        Returns:
            Payment record ID
        """
        log_info(f"Creating payment record for PO: {verification_result['po_number']}", self.name)

        payments = self._load_json_file(self.payments_due_file)

        po_data = verification_result['po_data']
        invoice_data = verification_result['invoice_data']

        payment_id = f"PAY-{verification_result['po_number']}-{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Calculate actual payment amount (deduct if mismatch)
        base_amount = po_data['total_cost']
        deduction = 0.0

        if exception_analysis:
            if exception_analysis['recommended_action'] == 'accept_with_deduction':
                deduction = exception_analysis.get('total_financial_impact', 0.0)

        final_amount = base_amount - deduction

        payment_record = {
            'payment_id': payment_id,
            'po_number': verification_result['po_number'],
            'supplier_name': po_data['supplier_name'],
            'invoice_number': invoice_data.get('invoice_number', 'N/A'),
            'base_amount': base_amount,
            'deduction': deduction,
            'final_amount': final_amount,
            'payment_terms': po_data.get('payment_terms', 'Net 30'),
            'due_date': self._calculate_due_date(po_data.get('payment_terms', 'Net 30')),
            'status': 'pending',
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        payments[payment_id] = payment_record

        if self._save_json_file(self.payments_due_file, payments):
            log_info(f"Payment record created: {payment_id}", self.name)
            return payment_id
        else:
            return None

    def _calculate_due_date(self, payment_terms):
        """Calculate payment due date from terms"""
        # Extract days from "Net 30", "Net 45" etc
        days = 30  # Default
        if 'Net' in payment_terms:
            try:
                days = int(payment_terms.split()[-1])
            except:
                pass

        due_date = datetime.now() + timedelta(days=days)
        return due_date.strftime('%Y-%m-%d')

    def save_document_images(self, po_number, delivery_note_path, invoice_path):
        """
        Save delivery note and invoice images to documents folder

        Args:
            po_number: Purchase order number
            delivery_note_path: Source path of delivery note image
            invoice_path: Source path of invoice image

        Returns:
            Dictionary with saved paths
        """
        log_info(f"Saving document images for PO: {po_number}", self.name)

        try:
            # Create PO-specific folder
            po_folder = os.path.join(self.documents_dir, po_number)
            os.makedirs(po_folder, exist_ok=True)

            # Copy delivery note
            delivery_dest = os.path.join(po_folder, f"{po_number}_delivery_note.jpg")
            shutil.copy2(delivery_note_path, delivery_dest)

            # Copy invoice
            invoice_dest = os.path.join(po_folder, f"{po_number}_invoice.jpg")
            shutil.copy2(invoice_path, invoice_dest)

            log_info(f"Documents saved to {po_folder}", self.name)

            return {
                'delivery_note_path': delivery_dest,
                'invoice_path': invoice_dest,
                'folder': po_folder
            }

        except Exception as e:
            log_error(f"Failed to save documents: {e}", self.name)
            return None

    def execute(self, verification_result, delivery_note_path, invoice_path, exception_analysis=None):
        """
        Main execution: Save all data

        Args:
            verification_result: Output from Agent 8
            delivery_note_path: Path to delivery note image
            invoice_path: Path to invoice image
            exception_analysis: Optional output from Agent 9

        Returns:
            Dictionary with all save results
        """
        log_info("Executing data storage workflow", self.name)

        # Save goods receipt
        receipt_id = self.save_goods_receipt(verification_result, exception_analysis)

        # Update inventory
        inventory_update = self.update_inventory(verification_result)

        # Create payment record
        payment_id = self.create_payment_record(verification_result, exception_analysis)

        # Update approved supplier database for future discovery loops (only if PASS or accepted with deduction)
        match_status = verification_result.get('match_result', 'FAIL')
        if match_status == 'PASS' or (exception_analysis and exception_analysis.get('recommended_action') == 'accept_with_deduction'):
            self.update_supplier_history(verification_result, exception_analysis)

        # Save document images
        document_paths = self.save_document_images(
            verification_result['po_number'],
            delivery_note_path,
            invoice_path
        )

        result = {
            'status': 'success',
            'receipt_id': receipt_id,
            'inventory_updated': inventory_update is not None,
            'inventory_details': inventory_update,
            'payment_id': payment_id,
            'documents_saved': document_paths is not None,
            'document_paths': document_paths,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        log_info("Data storage complete", self.name)

        return result

    def update_supplier_history(self, verification_result, exception_analysis=None):
        """
        Add the purchase details to supplier_history.json
        """
        log_info("Updating supplier history...", self.name)
        try:
            history_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'supplier_history.json')
            
            history_data = {}
            if os.path.exists(history_path):
                with open(history_path, 'r') as f:
                    try:
                        history_data = json.load(f)
                    except json.JSONDecodeError:
                        history_data = {}
                    
            po_data = verification_result.get('po_data', {})
            delivery_data = verification_result.get('delivery_data', {})
            supplier_name = po_data.get('supplier_name')
            item_name = po_data.get('item_name')
            
            if not supplier_name or not item_name:
                return False
                
            exceptions_text = "None"
            compensation_text = "None"
            
            if exception_analysis:
                exceptions_text = exception_analysis.get('root_cause_analysis', "None")
                compensation_text = exception_analysis.get('recommended_action', "None")
            elif verification_result.get('mismatch_count', 0) > 0:
                exceptions_text = str(verification_result.get('mismatches', "Mismatches found"))
                
            # Inherit static supplier attributes like ISO certification from previous historical records
            rating = 4.0
            iso_cert = False
            years_biz = 1
            
            for records in history_data.values():
                found_match = False
                for exist_row in records:
                    if exist_row.get('supplier_name') == supplier_name:
                        if 'rating' in exist_row:
                            rating = exist_row['rating']
                        if 'has_iso_certification' in exist_row:
                            iso_cert = exist_row['has_iso_certification']
                        if 'years_in_business' in exist_row:
                            years_biz = exist_row['years_in_business']
                        found_match = True
                        break
                if found_match:
                    break

            new_record = {
                'supplier_name': supplier_name,
                'contact_email': po_data.get('contact_email', 'contact@' + str(supplier_name).replace(' ', '').lower() + '.com'),
                'unit_price': po_data.get('unit_price', 0.0),
                'quantity_bought': delivery_data.get('quantity', po_data.get('quantity', 0)),
                'total_price': po_data.get('total_cost', 0.0),
                'exceptions_handled': exceptions_text,
                'compensation': compensation_text,
                'rating': rating,
                'has_iso_certification': iso_cert,
                'years_in_business': years_biz
            }
            
            if item_name not in history_data:
                history_data[item_name] = []
            history_data[item_name].append(new_record)
            
            with open(history_path, 'w') as f:
                json.dump(history_data, f, indent=4)
                
            log_info(f"Appended latest order history for {supplier_name} to supplier_history.json", self.name)
            return True
            
        except Exception as e:
            log_error(f"Failed to update supplier history: {e}", self.name)
            return False


if __name__ == "__main__":
    print("="*60)
    print("Testing Agent 10 - Data Storage")
    print("="*60)

    agent = DataStorageAgent()

    # Mock verification result
    mock_verification = {
        'status': 'success',
        'po_number': 'PO-ITM001-20240115',
        'match_result': 'PASS',
        'mismatches': [],
        'mismatch_count': 0,
        'po_data': {
            'po_number': 'PO-ITM001-20240115',
            'supplier_name': 'NextGen Components',
            'item_code': 'ITM001',
            'item_name': 'M8 Screws',
            'quantity': 2300,
            'unit_price': 7.80,
            'total_cost': 17940.00,
            'payment_terms': 'Net 30'
        },
        'delivery_data': {
            'quantity': 2300,
            'item_code': 'ITM001'
        },
        'invoice_data': {
            'invoice_number': 'INV-2024-001',
            'total_amount': 17940.00
        },
        'verified_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    print("\nTest: Save goods receipt")
    print("-"*60)
    receipt_id = agent.save_goods_receipt(mock_verification)
    print(f"Receipt ID: {receipt_id}")

    print("\nTest: Update inventory")
    print("-"*60)
    inventory_result = agent.update_inventory(mock_verification)
    print(json.dumps(inventory_result, indent=2))

    print("\nTest: Create payment record")
    print("-"*60)
    payment_id = agent.create_payment_record(mock_verification)
    print(f"Payment ID: {payment_id}")

    print("\n" + "="*60)
    print("Agent 10 testing complete")
    print("="*60)
    