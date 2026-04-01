"""Data models and dataclasses for the Multi-Agent Procurement System."""
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class DemandForecast:
    """Forecast result from Agent 1"""
    item_code: str
    predicted_demand: int
    confidence: float
    model_used: str
    historical_average: int
    trend: str
    seasonality_detected: bool
    
    def to_dict(self):
        return {
            "item_code": self.item_code,
            "predicted_demand": self.predicted_demand,
            "confidence": self.confidence,
            "model_used": self.model_used,
            "historical_average": self.historical_average,
            "trend": self.trend,
            "seasonality_detected": self.seasonality_detected
        }

@dataclass
class InventoryItem:
    """Represents an item in inventory"""
    item_code: str
    item_name: str
    current_quantity: int
    reorder_point: int
    max_capacity: int
    unit: str
    warehouse_location: str
    last_updated: str
    safety_stock: int = 0  # Minimum safety stock level
    lead_time_days: int = 7  # Lead time for replenishment in days

@dataclass
class ForecastResult:
    """Result from demand forecasting"""
    item_code: str
    item_name: str
    predicted_demand: int
    confidence: float
    historical_average: float
    trend: str                
    lower_bound: int          
    upper_bound: int           

@dataclass
class StockStatus:
    """Current stock status"""
    item_code: str
    item_name: str
    current_quantity: int
    reorder_point: int
    needs_reorder: bool
    shortage_amount: int
    status: str = "UNKNOWN"  # ADEQUATE/LOW/CRITICAL/OUT_OF_STOCK
    priority: str = None  # None/MEDIUM/HIGH/URGENT

@dataclass
class OrderRecommendation:
    """Recommendation on what to order"""
    item_code: str
    item_name: str
    recommended_quantity: int
    reason: str
    urgency: str

@dataclass
class Supplier:
    """Supplier information"""
    supplier_id: str
    supplier_name: str
    contact_email: str
    phone: str
    rating: float
    iso_certified: bool
    years_in_business: int
    location: str
    specialization: str
    payment_terms: str
    delivery_time_days: int

@dataclass
class SupplierQuote:
    """Quote from a supplier"""
    supplier: Supplier
    item_code: str
    item_name: str
    quantity: int
    price_per_unit: float
    total_cost: float
    delivery_days: int
    quoted_date: str

@dataclass
class PurchaseDecision:
    """Final purchase decision"""
    selected_supplier: Supplier
    item_code: str
    item_name: str
    quantity: int
    price_per_unit: float
    total_cost: float
    decision_reason: str
    needs_approval: bool
    estimated_delivery: str

def inventory_from_dict(row: dict) -> InventoryItem:
    """Convert CSV row to InventoryItem object"""
    return InventoryItem(
        item_code=row['item_code'],
        item_name=row['item_name'],
        current_quantity=int(row['current_quantity']),
        reorder_point=int(row['reorder_point']),
        max_capacity=int(row['max_capacity']),
        unit=row['unit'],
        warehouse_location=row['warehouse_location'],
        last_updated=row['last_updated'],
        safety_stock=int(row.get('safety_stock', 0)),  # Default to 0 if not present
        lead_time_days=int(row.get('lead_time_days', 7))  # Default to 7 days if not present
    )

def supplier_from_dict(row: dict) -> Supplier:
    """Convert CSV row to Supplier object"""
    return Supplier(
        supplier_id=row['supplier_id'],
        supplier_name=row['supplier_name'],
        contact_email=row['contact_email'],
        phone=row['phone'],
        rating=float(row['rating']),
        iso_certified=row['iso_certified'].lower() == 'yes',
        years_in_business=int(row['years_in_business']),
        location=row['location'],
        specialization=row['specialization'],
        payment_terms=row['payment_terms'],
        delivery_time_days=int(row['delivery_time_days'])
    )

if __name__ == "__main__":
    item = InventoryItem(
        item_code="ITM001",
        item_name="M8 Screws",
        current_quantity=800,
        reorder_point=1000,
        max_capacity=5000,
        unit="pieces",
        warehouse_location="Warehouse A - Rack 12",
        last_updated="2024-12-06"
    )
    print(f"✓ Created item: {item.item_name}")
    print(f"  Current stock: {item.current_quantity}")
    print(f"  Needs reorder: {item.current_quantity < item.reorder_point}")
