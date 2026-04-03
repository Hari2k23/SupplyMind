import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base_agent import BaseAgent
from agents.Agent1_complete import DataHarmonizerAndForecaster
from agents.Agent2_stockMonitor import StockMonitor
from models.data_models import OrderRecommendation
from config.settings import SAFETY_BUFFER, GROQ_MODELS
from utils.groq_helper import groq

# Define constants with explanations (removing magic numbers)
SAFETY_STOCK_PERCENTAGE = 0.2  # 20% buffer added to forecast for demand uncertainty
MINIMUM_ORDER_QUANTITY = 100   # Minimum vendor order quantity requirement


class ReplenishmentAdvisor(BaseAgent):
    """Calculate optimal order quantities based on forecasts and current stock."""
    
    def __init__(self):
        super().__init__(
            name="Agent 3 - Replenishment Advisor",
            role="Replenishment Planning Advisor",
            goal="Calculate optimal order quantities based on forecast and current stock",
            backstory="Supply chain expert with 12 years experience in inventory optimization"
        )
        
        self.forecaster = DataHarmonizerAndForecaster()
        self.stock_monitor = StockMonitor()
    
    def execute(self, item_code: str, forecast_days: int = 30, **kwargs) -> dict:
        """Calculate optimal order quantity for item."""
        self.log_info(f"Replenishment execute called for {item_code} (forecast_days={forecast_days})")
        
        if 'lead_time_days' in kwargs:
            self.log_warning(f"Legacy argument 'lead_time_days' intercepted: {kwargs['lead_time_days']}")
        
        self.log_start(f"Calculating replenishment for {item_code}")

        forecast_result = self.forecaster.execute(item_code)
        
        if not forecast_result or forecast_result.get('error'):
            self.log_error("Replenishment", f"Failed to get forecast: {forecast_result.get('error') if forecast_result else 'Unknown error'}")
            return {
                "error": "forecast_failed",
                "message": f"Could not generate demand forecast: {forecast_result.get('error', 'Unknown error')}"
            }
        
        # Extract forecast object from pipeline result
        forecast = forecast_result['forecast']
        context = forecast_result['context']
        
        stock_result = self.stock_monitor.execute(item_code)
        if not stock_result:
            self.log_error("Replenishment", "Failed to get stock status")
            return {
                "error": "stock_check_failed",
                "message": "Could not retrieve stock information for this item"
            }
        
        # Check if stock_result contains error
        if stock_result.get('error'):
            return stock_result  # Pass through the error from Agent 2
        
        stock_status = stock_result['stock_status']
        inventory_item = stock_result['inventory_item']
        
        # Calculate order quantity based on Agent 1's forecast and Agent 2's stock data
        order_calc = self._calculate_order_quantity(
            forecast=forecast,
            stock_status=stock_status,
            inventory_item=inventory_item,
            forecast_days=forecast_days
        )
        
        urgency = self._determine_urgency(
            stock_status=stock_status,
            forecast=forecast,
            lead_time_days=inventory_item.lead_time_days # Use lead time from inventory item
        )
        
        reasoning = self._generate_reasoning(
            forecast=forecast,
            stock_status=stock_status,
            order_calc=order_calc,
            urgency=urgency,
            forecast_model=forecast.model_used,
            forecast_confidence=forecast.confidence
        )
        
        recommendation = OrderRecommendation(
            item_code=item_code,
            item_name=stock_status.item_name,
            recommended_quantity=order_calc['final_quantity'],
            reason=reasoning,
            urgency=urgency
        )
        
        self.log_complete(
            "Replenishment",
            f"{stock_status.item_name}: Order {order_calc['final_quantity']} units - "
            f"Urgency: {urgency} (Forecast: {forecast.model_used}, {forecast.confidence*100:.0f}% confidence)"
        )
        
        return {
            "recommendation": recommendation,
            "calculation_details": order_calc,
            "forecast_data": forecast,
            "stock_data": stock_status,
            # UPDATED: Include Agent 1 pipeline details for transparency
            "forecast_model": forecast.model_used,
            "forecast_confidence": forecast.confidence,
            "forecast_trend": forecast.trend,
            "model_comparison": forecast_result.get('model_comparison', []),
            "data_quality": {
                "months_of_data": context.get('months_of_data', 0),
                "cleaning_report": forecast_result.get('cleaning_report', {})
            }
        }
    
    def _calculate_order_quantity(self, forecast, stock_status, inventory_item, forecast_days: int):
        """Calculate order quantity based on forecast and current stock."""
        predicted_demand = forecast.predicted_demand
        current_stock = stock_status.current_quantity
        
        # Base need: How much we're short by
        base_need = max(0, predicted_demand - current_stock)
        
        # Safety stock: Buffer for uncertainty (20% of predicted demand)
        safety_stock = max(SAFETY_BUFFER, int(predicted_demand * SAFETY_STOCK_PERCENTAGE))
        
        # Lead time demand: Coverage during delivery period
        daily_demand = predicted_demand / 30
        lead_time_demand = int(daily_demand * inventory_item.lead_time_days)
        
        # Total quantity needed
        total_quantity = base_need + safety_stock + lead_time_demand
        
        # Check warehouse capacity constraints
        max_capacity = inventory_item.max_capacity
        available_space = max_capacity - current_stock
        
        if total_quantity > available_space:
            final_quantity = available_space
            capped = True
        else:
            final_quantity = total_quantity
            capped = False
        
        # Apply minimum order quantity (vendor requirement)
        if final_quantity < MINIMUM_ORDER_QUANTITY:
            final_quantity = MINIMUM_ORDER_QUANTITY
        
        return {
            "predicted_demand": predicted_demand,
            "current_stock": current_stock,
            "base_need": base_need,
            "safety_stock": safety_stock,
            "lead_time_demand": lead_time_demand,
            "total_quantity": total_quantity,
            "final_quantity": final_quantity,
            "capped": capped,
            "max_capacity": max_capacity,
            "available_space": available_space
        }
    
    def _determine_urgency(self, stock_status, forecast, lead_time_days: int):
        """Determine urgency level based on stock coverage."""
        current_qty = stock_status.current_quantity
        reorder_point = stock_status.reorder_point
        predicted_demand = forecast.predicted_demand
        
        daily_demand = predicted_demand / 30
        if daily_demand > 0:
            days_remaining = current_qty / daily_demand
        else:
            days_remaining = 999
        
        if days_remaining < lead_time_days:
            return "CRITICAL"
        
        if current_qty < reorder_point:
            return "HIGH"
        
        if days_remaining < 14:
            return "MEDIUM"
        
        return "LOW"
    
    def _generate_reasoning(self, forecast, stock_status, order_calc, urgency, 
                              forecast_model=None, forecast_confidence=None):
        """Generate natural language explanation for the recommendation using LLM."""
        prompt = f"""You are a supply chain advisor. Provide a brief 4-5 line explanation for this order recommendation.

Current Stock: {stock_status.current_quantity} units (Reorder Point: {stock_status.reorder_point})
AI Forecast: {forecast.predicted_demand} units/month (Model: {forecast_model or forecast.model_used}, {(forecast_confidence or forecast.confidence)*100:.0f}% confidence)
Trend: {forecast.trend}
Recommended Order: {order_calc['final_quantity']} units
Urgency: {urgency}

Explain concisely why this quantity makes sense, mentioning the AI forecast confidence. Be professional and easy to understand."""
        
        try:
            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["reasoning"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=150 # Max tokens adjusted for concise explanation
            )
            
            reasoning = response.choices[0].message.content.strip()
            return reasoning
            
        except Exception as e:
            self.log_error("AI Reasoning", str(e))
            return self._build_simple_reasoning(stock_status, forecast, order_calc, urgency)
    
    def _build_simple_reasoning(self, stock_status, forecast, order_calc, urgency):
        """Fallback reasoning if LLM fails."""
        reasons = []
        
        if stock_status.needs_reorder:
            reasons.append(f"Current stock ({stock_status.current_quantity} units) is below reorder point ({stock_status.reorder_point} units)")
        
        reasons.append(f"AI forecast predicts {forecast.predicted_demand} units/month demand using {forecast.model_used} model")
        
        if forecast.trend == "increasing":
            reasons.append("Demand is trending upward")
        elif forecast.trend == "decreasing":
            reasons.append("Demand is trending downward")
        
        reasons.append(f"Safety buffer of {order_calc['safety_stock']} units included")
        reasons.append(f"Recommended order: {order_calc['final_quantity']} units")
        
        return ". ".join(reasons) + "."
    
    def calculate_batch_recommendations(self, item_codes: list, forecast_days: int = 30) -> list:
        """Calculate recommendations for multiple items."""
        recommendations = []
        
        for item_code in item_codes:
            result = self.execute(item_code, forecast_days=forecast_days)
            if result and not result.get('error'):
                recommendations.append(result)
        
        return recommendations
    
    def get_priority_orders(self, top_n: int = 5) -> list:
        """Get top priority orders by urgency and quantity."""
        self.log_start("Identifying priority orders")
        
        low_stock_items = self.stock_monitor.check_all_low_stock_items()
        
        urgent_recommendations = []
        
        for stock_status in low_stock_items:
            result = self.execute(stock_status.item_code)
            if result and not result.get('error') and result['recommendation'].urgency in ['URGENT', 'HIGH']:
                urgent_recommendations.append(result)
        
        urgent_recommendations.sort(
            key=lambda x: 0 if x['recommendation'].urgency == 'URGENT' else 1
        )
        
        self.log_complete("Priority Orders", f"Found {len(urgent_recommendations)} urgent items")
        
        return urgent_recommendations


if __name__ == "__main__":
    print("="*60)
    print("Testing Agent 3 - Replenishment Advisor (with New Agent 1)")
    print("="*60)
    
    advisor = ReplenishmentAdvisor()
    
    print("\nTest 1: Short Reasoning for ITM009")
    print("-"*60)
    result = advisor.execute("ITM009", forecast_days=30)
    
    if result:
        if result.get('error'):
            print(f"Error: {result['message']}")
        else:
            recommendation = result['recommendation']
            
            print(f"\nItem: {recommendation.item_name}")
            print(f"Recommended Quantity: {recommendation.recommended_quantity} units")
            print(f"Urgency: {recommendation.urgency}")
            print(f"\n Forecast Model: {result['forecast_model']}")
            print(f"Confidence: {result['forecast_confidence']*100:.0f}%")
            print(f"Trend: {result['forecast_trend']}")
            print(f"\n Reasoning:")
            print(recommendation.reason)
    
    print("\n" + "="*60)
    print("\nTest 2: Detailed Reasoning for ITM009")
    print("-"*60)
    result_detailed = advisor.execute("ITM009", forecast_days=30)
    
    if result_detailed:
        if result_detailed.get('error'):
            print(f"Error: {result_detailed['message']}")
        else:
            recommendation = result_detailed['recommendation']
            
            print(f"\nItem: {recommendation.item_name}")
            print(f"Recommended Quantity: {recommendation.recommended_quantity} units")
            print(f"Urgency: {recommendation.urgency}")
            
            print(f"\nAI Forecast Details:")
            print(f"   Model: {result_detailed['forecast_model']}")
            print(f"   Confidence: {result_detailed['forecast_confidence']*100:.0f}%")
            print(f"   Trend: {result_detailed['forecast_trend']}")
            
            if result_detailed.get('model_comparison'):
                print(f"\nModel Performance Comparison:")
                for model in result_detailed['model_comparison']:
                    print(f"   {model['name']:25s} - MAPE: {model['mape']:5.1f}%")
            
            print(f"\nData Quality:")
            dq = result_detailed['data_quality']
            print(f"   Months of Historical Data: {dq['months_of_data']}")
            if dq.get('cleaning_report'):
                cr = dq['cleaning_report']
                print(f"   Rows Processed: {cr.get('rows_before', 0)} → {cr.get('rows_after', 0)}")
                print(f"   Outliers Detected: {len(cr.get('outliers_detected', []))}")
            
            print(f"\nDetailed Reasoning:")
            print(recommendation.reason)
    
    print("\n" + "="*60)
    print("\nTest 3: Batch Processing (Multiple Items)")
    print("-"*60)
    
    items_to_test = ["ITM001", "ITM009"]
    batch_results = advisor.calculate_batch_recommendations(items_to_test)
    
    print(f"\nSuccessfully processed {len(batch_results)} items:\n")
    for res in batch_results:
        rec = res['recommendation']
        print(f"  {rec.item_code} - {rec.item_name}:")
        print(f"    Order: {rec.recommended_quantity} units")
        print(f"    Urgency: {rec.urgency}")
        print(f"    Model: {res['forecast_model']} ({res['forecast_confidence']*100:.0f}% confidence)")
        print()
    
    print("="*60)
    print("Agent 3 Test Complete!")
    print("="*60)
