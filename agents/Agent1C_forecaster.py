import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base_agent import BaseAgent
from models.data_models import DemandForecast
from utils.logger import log_info, log_error
import pandas as pd
import numpy as np
from sklearn.metrics import mean_absolute_percentage_error
import warnings
warnings.filterwarnings('ignore')

class DemandForecaster(BaseAgent):
    """Stage 3: Multi-model forecasting with automatic model selection."""
    def __init__(self):
        super().__init__(
            name="Agent 1C - Demand Forecaster",
            role="Forecasting Specialist",
            goal="Predict future demand using best-fit model",
            backstory="Time series analyst with 10+ years in demand forecasting"
        )
    
    def execute(self, df: pd.DataFrame, schema: dict, item_code: str = None, forecast_days: int = 30):
        """Generate demand forecast using best model."""
        self.log_start(f"Forecasting demand for {item_code if item_code else 'all items'}")
        
        date_col = schema.get('date_column')
        item_col = schema.get('item_column')
        qty_col = schema.get('quantity_column')
        
        # Filter by item if specified
        if item_code:
            df_item = df[df[item_col].str.contains(item_code, case=False, na=False)]
            if df_item.empty:
                return {"error": f"No data found for item {item_code}"}
        else:
            df_item = df
        
        # Aggregate by month
        df_item[date_col] = pd.to_datetime(df_item[date_col])
        df_monthly = df_item.groupby(df_item[date_col].dt.to_period('M'))[qty_col].sum().reset_index()
        df_monthly.columns = ['month', 'quantity']
        df_monthly['month'] = df_monthly['month'].dt.to_timestamp()
        
        # Check minimum data requirement
        if len(df_monthly) < 6:
            return {"error": f"Insufficient data: need at least 6 months, found {len(df_monthly)}"}
        
        # Prepare time series
        ts_data = df_monthly.set_index('month')['quantity']
        
        # Feature engineering
        features = self._create_features(df_monthly)
        
        # Split train/test (80/20)
        split_idx = int(len(ts_data) * 0.8)
        train = ts_data[:split_idx]
        test = ts_data[split_idx:]
        
        # Run models via dedicated methods
        models = [
            self._forecast_moving_average(train, test),
            self._forecast_exponential_smoothing(train, test),
            self._forecast_linear_regression(features, split_idx),
        ]

        # Select best model based on MAPE
        best_model = min(models, key=lambda x: x['mape'])
        
        # Make final forecast for next month using best model
        if best_model['name'] == "Moving Average":
            forecast_qty = int(ts_data[-3:].mean())
        elif best_model['name'] == "Exponential Smoothing":
            try:
                from statsmodels.tsa.holtwinters import ExponentialSmoothing
                final_model = ExponentialSmoothing(ts_data, trend='add', seasonal=None).fit()
                forecast_qty = int(final_model.forecast(steps=1).iloc[0])
            except:
                forecast_qty = int(ts_data.mean())
        else:  # Linear Regression
            try:
                from sklearn.linear_model import LinearRegression
                X_all = np.arange(len(ts_data)).reshape(-1, 1)
                X_next = np.array([[len(ts_data)]])
                final_lr = LinearRegression().fit(X_all, ts_data.values)
                forecast_qty = int(final_lr.predict(X_next)[0])
            except:
                forecast_qty = int(ts_data.mean())
                
        forecast_qty = max(0, forecast_qty)
        
        # Detect trend and seasonality via dedicated methods
        trend = self._detect_trend(ts_data)
        seasonality = self._detect_seasonality(ts_data)
            
        # Confidence
        mape_val = best_model['mape']
        confidence = self._calculate_confidence(mape_val)
        
        # Create forecast object
        forecast = DemandForecast(
            item_code=item_code if item_code else "ALL",
            predicted_demand=forecast_qty,
            confidence=confidence,
            model_used=best_model['name'],
            historical_average=int(ts_data.mean()),
            trend=trend,
            seasonality_detected=seasonality
        )
        
        self.log_complete("Forecasting", 
                         f"Model: {best_model['name']}, MAPE: {best_model['mape']:.1f}%, "
                         f"Forecast: {forecast_qty} units")
        
        return {
            "forecast": forecast,
            "model_comparison": [{"name": m["name"], "mape": m["mape"]} for m in models],
            "best_model": {"name": best_model["name"], "mape": best_model["mape"]},
            "confidence_interval": [int(forecast_qty * 0.9), int(forecast_qty * 1.1)],
            "historical_data": ts_data.to_dict(),
            "context": {
                "months_of_data": len(ts_data),
                "avg_monthly_demand": int(ts_data.mean()),
                "trend": trend,
                "seasonality": seasonality
            }
        }
    
    def _create_features(self, df: pd.DataFrame):
        """Create time-based features for forecasting."""
        df = df.copy()
        df['month_num'] = df['month'].dt.month
        df['quarter'] = df['month'].dt.quarter
        df['year'] = df['month'].dt.year
        
        # Lag features
        df['lag1'] = df['quantity'].shift(1)
        df['lag2'] = df['quantity'].shift(2)
        df['lag3'] = df['quantity'].shift(3)
        
        # Rolling average
        df['rolling_3m'] = df['quantity'].rolling(window=3, min_periods=1).mean()
        df['rolling_6m'] = df['quantity'].rolling(window=6, min_periods=1).mean()
        
        return df
    
    def _forecast_moving_average(self, train: pd.Series, test: pd.Series) -> dict:
        """Simple moving average forecast."""
        window = min(3, len(train))
        predictions = [train[-window:].mean()] * len(test)
        mape = mean_absolute_percentage_error(test, predictions) * 100
        
        return {
            "name": "Moving Average",
            "mape": mape,
            "predictions": predictions
        }
    
    def _forecast_exponential_smoothing(self, train: pd.Series, test: pd.Series) -> dict:
        """Exponential smoothing forecast."""
        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing
            
            model = ExponentialSmoothing(train, trend='add', seasonal=None)
            fitted = model.fit()
            predictions = fitted.forecast(steps=len(test))
            mape = mean_absolute_percentage_error(test, predictions) * 100
            
            return {
                "name": "Exponential Smoothing",
                "mape": mape,
                "predictions": predictions.tolist()
            }
        except Exception as e:
            log_error(f"Exponential Smoothing failed: {e}", self.name)
            return {
                "name": "Exponential Smoothing",
                "mape": 999.0,
                "predictions": []
            }
    
    def _forecast_linear_regression(self, features: pd.DataFrame, split_idx: int) -> dict:
        """Linear regression forecast with time features."""
        try:
            from sklearn.linear_model import LinearRegression
            
            features_df = features.dropna()
            feature_cols = ['month_num', 'quarter', 'lag1', 'lag2', 'rolling_3m']
            X = features_df[feature_cols]
            y = features_df['quantity']
            
            X_train = X[:split_idx]
            X_test = X[split_idx:]
            y_train = y[:split_idx]
            y_test = y[split_idx:]
            
            if len(X_test) == 0:
                raise ValueError("No test data")
            
            model = LinearRegression()
            model.fit(X_train, y_train)
            predictions = model.predict(X_test)
            mape = mean_absolute_percentage_error(y_test, predictions) * 100
            
            return {
                "name": "Linear Regression",
                "mape": mape,
                "predictions": predictions.tolist()
            }
        except Exception as e:
            log_error(f"Linear Regression failed: {e}", self.name)
            return {
                "name": "Linear Regression",
                "mape": 999.0,
                "predictions": []
            }
    
    def _detect_trend(self, series: pd.Series) -> str:
        """Detect if data has upward or downward trend."""
        if len(series) < 3:
            return "stable"
        
        x = np.arange(len(series))
        y = series.values
        slope = np.polyfit(x, y, 1)[0]
        threshold = series.mean() * 0.05
        
        if slope > threshold:
            return "increasing"
        elif slope < -threshold:
            return "decreasing"
        else:
            return "stable"
    
    def _detect_seasonality(self, series: pd.Series) -> bool:
        """Detect weekly or monthly seasonality patterns."""
        if len(series) < 12:
            return False
        
        try:
            from statsmodels.tsa.stattools import acf
            autocorr = acf(series, nlags=min(12, len(series)-1))
            
            if len(autocorr) > 12 and abs(autocorr[12]) > 0.3:
                return True
        except:
            pass
        
        return False
    
    def _calculate_confidence(self, mape: float) -> float:
        """Convert MAPE to confidence score (0-1)"""
        if mape < 10:
            return 0.95
        elif mape < 15:
            return 0.85
        elif mape < 20:
            return 0.75
        elif mape < 30:
            return 0.65
        else:
            return 0.50


if __name__ == "__main__":
    print("Testing Agent 1C - Demand Forecaster\n")
    
    # Load and clean test data
    df = pd.read_csv('data/historical_orders.csv')
    
    schema = {
        "date_column": "order_date",
        "item_column": "item_code",
        "quantity_column": "quantity_ordered"
    }
    
    forecaster = DemandForecaster()
    
    # Test for ITM001
    result = forecaster.execute(df, schema, "ITM001")
    
    if result.get('error'):
        print(f"Error: {result['error']}")
    else:
        forecast = result['forecast']
        print(f"Item: {forecast.item_code}")
        print(f"Predicted Demand: {forecast.predicted_demand} units")
        print(f"Confidence: {forecast.confidence * 100:.0f}%")
        print(f"Model Used: {forecast.model_used}")
        print(f"Historical Average: {forecast.historical_average} units")
        print(f"Trend: {forecast.trend}")
        print(f"Seasonality: {forecast.seasonality_detected}")
        
        print("\nModel Comparison:")
        for model in result['model_comparison']:
            print(f"  {model['name']}: MAPE = {model['mape']:.1f}%")
        
        print(f"\nBest Model: {result['best_model']['name']} (MAPE: {result['best_model']['mape']:.1f}%)")
    
    print("\nAgent 1C test complete!")
    