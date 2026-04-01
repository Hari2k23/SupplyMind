import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base_agent import BaseAgent
from models.data_models import StockStatus, InventoryItem, inventory_from_dict
import pandas as pd


class StockMonitor(BaseAgent):
    """Monitor current inventory levels and check against reorder points."""
    def __init__(self):
        super().__init__(
            name="Agent 2 - Stock Monitor",
            role="Inventory Stock Monitor",
            goal="Monitor current stock levels and identify items needing reorder",
            backstory="Experienced warehouse manager with 15 years tracking inventory levels"
        )
    
    def execute(self, item_code: str) -> dict:
        """Check stock level for specific item.
        
        Args:
            item_code: Item code to check 
        
        Returns:
            Dict with stock_status and inventory_item objects, or error dict
        """
        self.log_start(f"Checking stock for {item_code}")
        
        # Load current inventory
        df = self.load_csv('current_inventory.csv')
        
        if df.empty:
            self.log_error("Stock Check", "No inventory data found")
            return {
                "error": "no_inventory_data",
                "message": "Inventory database is empty or could not be loaded"
            }
        
        # Find the item
        item_data = df[df['item_code'] == item_code]
        
        if len(item_data) == 0:
            self.log_error("Stock Check", f"Item {item_code} not found in inventory")
            return {
                "error": "item_not_found",
                "message": f"Item {item_code} not found in inventory database"
            }
        
        # Convert to objects
        item_row = item_data.iloc[0].to_dict()
        inventory_item = inventory_from_dict(item_row)
        
        # Calculate stock status
        current_qty = inventory_item.current_quantity
        reorder_point = inventory_item.reorder_point
        safety_stock = inventory_item.safety_stock
        
        # Fix: Use <= for reorder point (trigger AT reorder point, not just below)
        needs_reorder = current_qty <= reorder_point
        shortage = max(0, reorder_point - current_qty)
        
        # Determine status and priority based on stock levels
        if current_qty <= 0:
            status = "OUT_OF_STOCK"
            priority = "URGENT"
        elif current_qty < safety_stock:
            status = "CRITICAL"
            priority = "URGENT"
        elif current_qty < reorder_point * 0.5:
            status = "LOW"
            priority = "HIGH"
        elif current_qty <= reorder_point:
            status = "LOW"
            priority = "MEDIUM"
        else:
            status = "ADEQUATE"
            priority = None
        
        # Create stock status
        stock_status = StockStatus(
            item_code=inventory_item.item_code,
            item_name=inventory_item.item_name,
            current_quantity=current_qty,
            reorder_point=reorder_point,
            needs_reorder=needs_reorder,
            shortage_amount=shortage,
            status=status,
            priority=priority
        )
        
        # Log result
        status_msg = "NEEDS REORDER" if needs_reorder else "Stock OK"
        self.log_complete(
            "Stock Check",
            f"{inventory_item.item_name}: {current_qty} units (Reorder: {reorder_point}) - {status_msg}"
        )
        
        return {
            "stock_status": stock_status,
            "inventory_item": inventory_item
        }
    
    def check_all_low_stock_items(self) -> list:
        """Check all items and return those below reorder point.
        
        Returns:
            List of StockStatus objects for items needing reorder
        """
        self.log_start("Checking all items for low stock")
        
        df = self.load_csv('current_inventory.csv')
        
        if df.empty:
            self.log_error("Bulk Check", "No inventory data")
            return []
        
        low_stock_items = []
        
        for _, row in df.iterrows():
            item_dict = row.to_dict()
            current_qty = int(item_dict['current_quantity'])
            reorder_point = int(item_dict['reorder_point'])
            safety_stock = int(item_dict.get('safety_stock', 0))
            
            if current_qty <= reorder_point:
                # Determine status and priority
                if current_qty <= 0:
                    status = "OUT_OF_STOCK"
                    priority = "URGENT"
                elif current_qty < safety_stock:
                    status = "CRITICAL"
                    priority = "URGENT"
                elif current_qty < reorder_point * 0.5:
                    status = "LOW"
                    priority = "HIGH"
                else:
                    status = "LOW"
                    priority = "MEDIUM"
                
                stock_status = StockStatus(
                    item_code=item_dict['item_code'],
                    item_name=item_dict['item_name'],
                    current_quantity=current_qty,
                    reorder_point=reorder_point,
                    needs_reorder=True,
                    shortage_amount=reorder_point - current_qty,
                    status=status,
                    priority=priority
                )
                low_stock_items.append(stock_status)
        
        self.log_complete(
            "Bulk Check",
            f"Found {len(low_stock_items)} items below reorder point"
        )
        
        return low_stock_items
    
    def get_stock_summary(self) -> dict:
        """Get summary of entire inventory.
        
        Returns:
            Dictionary with summary statistics
        """
        df = self.load_csv('current_inventory.csv')
        
        if df.empty:
            return {"error": "No inventory data"}
        
        total_items = len(df)
        items_below_reorder = len(df[df['current_quantity'] < df['reorder_point']])
        items_ok = total_items - items_below_reorder
        
        avg_stock_level = df['current_quantity'].mean()
        total_capacity = df['max_capacity'].sum()
        total_current = df['current_quantity'].sum()
        capacity_utilization = (total_current / total_capacity * 100) if total_capacity > 0 else 0
        
        return {
            "total_items": total_items,
            "items_needing_reorder": items_below_reorder,
            "items_stock_ok": items_ok,
            "reorder_percentage": round(items_below_reorder / total_items * 100, 1),
            "avg_stock_level": round(avg_stock_level, 0),
            "capacity_utilization": round(capacity_utilization, 1)
        }
    
    def get_critical_shortages(self, threshold_percentage: float = 50.0) -> list:
        """Get items with critical shortages below threshold percentage.
        
        Args:
            threshold_percentage: Percentage of reorder point to consider critical
        
        Returns:
            List of critically short items
        """
        df = self.load_csv('current_inventory.csv')
        
        if df.empty:
            return []
        
        critical_items = []
        
        for _, row in df.iterrows():
            item_dict = row.to_dict()
            current_qty = int(item_dict['current_quantity'])
            reorder_point = int(item_dict['reorder_point'])
            safety_stock = int(item_dict.get('safety_stock', 0))
            
            critical_threshold = reorder_point * (threshold_percentage / 100)
            
            if current_qty < critical_threshold:
                # Determine status and priority
                if current_qty <= 0:
                    status = "OUT_OF_STOCK"
                    priority = "URGENT"
                elif current_qty < safety_stock:
                    status = "CRITICAL"
                    priority = "URGENT"
                elif current_qty < reorder_point * 0.5:
                    status = "LOW"
                    priority = "HIGH"
                else:
                    status = "LOW"
                    priority = "MEDIUM"
                
                stock_status = StockStatus(
                    item_code=item_dict['item_code'],
                    item_name=item_dict['item_name'],
                    current_quantity=current_qty,
                    reorder_point=reorder_point,
                    needs_reorder=True,
                    shortage_amount=reorder_point - current_qty,
                    status=status,
                    priority=priority
                )
                critical_items.append(stock_status)
        
        return critical_items


# Test the stock monitor
if __name__ == "__main__":
    print("Testing Agent 2 - Stock Monitor")

    monitor = StockMonitor()

    print("\nChecking stock (ITM009)...")
    result = monitor.execute("ITM009")

    if result:
        # Check for error
        if result.get('error'):
            print(f"Error: {result['message']}")
        else:
            stock_status = result['stock_status']
            inventory_item = result['inventory_item']

            print("\nStock Status:")
            print(f"Item Code: {stock_status.item_code}")
            print(f"Item Name: {stock_status.item_name}")
            print(f"Current Quantity: {stock_status.current_quantity} units")
            print(f"Reorder Point: {stock_status.reorder_point} units")
            print(f"Needs Reorder: {stock_status.needs_reorder}")
            print(f"Shortage Amount: {stock_status.shortage_amount} units")

            print("\nInventory Details:")
            print(f"Max Capacity: {inventory_item.max_capacity} units")
            print(f"Unit: {inventory_item.unit}")
            print(f"Warehouse Location: {inventory_item.warehouse_location}")
            print(f"Last Updated: {inventory_item.last_updated}")

            print("\nContext for Agent 3:")
            print(f"current_quantity: {stock_status.current_quantity}")
            print(f"needs_reorder: {stock_status.needs_reorder}")
            print(f"shortage_amount: {stock_status.shortage_amount}")
            print(f"max_capacity: {inventory_item.max_capacity}")
    else:
        print("Stock check failed")

    print("\nChecking all items for low stock...")
    low_stock = monitor.check_all_low_stock_items()

    if low_stock:
        print(f"Items below reorder point: {len(low_stock)}")
        for item in low_stock:
            print(f"{item.item_name} ({item.item_code}): "
                  f"{item.current_quantity}/{item.reorder_point} units "
                  f"(Short by {item.shortage_amount})")
    else:
        print("All items have adequate stock")

    print("\nInventory Summary:")
    summary = monitor.get_stock_summary()
    print(f"Total Items: {summary['total_items']}")
    print(f"Items Needing Reorder: {summary['items_needing_reorder']} "
          f"({summary['reorder_percentage']}%)")
    print(f"Items with OK Stock: {summary['items_stock_ok']}")
    print(f"Average Stock Level: {summary['avg_stock_level']} units")
    print(f"Warehouse Capacity Used: {summary['capacity_utilization']}%")

    print("\nCritical Shortages (below 50% of reorder point):")
    critical = monitor.get_critical_shortages(50.0)

    if critical:
        print(f"Critical items: {len(critical)}")
        for item in critical:
            pct = (item.current_quantity / item.reorder_point * 100) if item.reorder_point > 0 else 0
            print(f"{item.item_name}: {item.current_quantity} units "
                  f"({pct:.0f}% of reorder point)")
    else:
        print("No critical shortages found")

    print("\nAgent 2 test complete!")
    