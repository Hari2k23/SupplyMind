import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base_agent import BaseAgent
from models.data_models import DemandForecast
from utils.groq_helper import groq
from utils.logger import log_info, log_error
import pandas as pd
import numpy as np
import json
from datetime import datetime
from sklearn.metrics import mean_absolute_percentage_error
from sklearn.linear_model import LinearRegression
import warnings
warnings.filterwarnings('ignore')


# Import specific sub-agents
from agents.Agent1A_harmonizer import DataHarmonizer
from agents.Agent1B_cleaner import DataCleaner
from agents.Agent1C_forecaster import DemandForecaster

class DataHarmonizerAndForecaster(BaseAgent):
    """Standalone agent orchestrating 1A, 1B, and 1C sequentially."""
    def __init__(self):
        super().__init__(
            name="Agent 1 - Data Harmonizer & Demand Forecaster",
            role="End-to-End Data Processing and Forecasting",
            goal="Orchestrate harmonize plugins and forecasting pipelines",
            backstory="Master pipeline integrator"
        )
        self.harmonizer = DataHarmonizer()
        self.cleaner = DataCleaner()
        self.forecaster = DemandForecaster()

    def execute(self, item_code: str, file_path: str = None):
        """Execute the full 3-stage forecasting pipeline utilizing the harmonizer."""
        self.log_start(f"Running complete Agent 1 pipeline for {item_code}")
        
        if file_path is None:
            file_path = 'data/historical_orders.csv'
            
        # STEP 1: Harmonize (Agent 1A)
        # Dynamically matches messy column headers
        schema_result = self.harmonizer.execute(file_path)
        if "error" in schema_result:
            return schema_result
        schema = schema_result['schema']
        
        # Load raw data properly now that we verified file exists in step 1
        try:
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
        except Exception as e:
            return {"error": f"Failed to load file for cleaning: {e}"}
            
        # STEP 2: Clean (Agent 1B)
        # Handles NA values, formats random dates optimally with mixed parsing, and drops duplicates
        clean_result = self.cleaner.execute(df, schema)
        if "error" in clean_result:
            return clean_result
        clean_df = clean_result['cleaned_data']
        
        # STEP 3: Forecast (Agent 1C)
        # Filters to the item, runs feature engineering, and calculates stats via multi-model ensemble
        forecast_result = self.forecaster.execute(clean_df, schema, item_code=item_code)
        
        self.log_complete("Full Pipeline Execution", f"Finished end-to-end integration for {item_code}")
        
        return forecast_result

if __name__ == "__main__":
    print("="*60)
    print("Testing Agent 1 - INTEGRATED PIPELINE")
    print("="*60)
    
    agent1 = DataHarmonizerAndForecaster()
    
    print("\nTest 1: ITM001")
    result = agent1.execute("ITM001")
    
    if result.get('error'):
        print(f"ERROR: {result['error']}")
    else:
        fc = result['forecast']
        print(f"Predicted: {fc.predicted_demand} units")
        print(f"Model: {fc.model_used}")
        print(f"Confidence: {fc.confidence*100:.0f}%")
        print(f"Trend: {fc.trend}")
        
        print("\nModels tested:")
        for m in result['model_comparison']:
            print(f"  {m['name']}: {m['mape']:.1f}% MAPE")
    