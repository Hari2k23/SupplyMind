import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base_agent import BaseAgent
from utils.groq_helper import groq
from config.settings import GROQ_MODELS
from utils.logger import log_info, log_error
import pandas as pd
import json

class DataHarmonizer(BaseAgent):
    """Stage 1: LLM-powered schema detection and mapping for messy data."""
    def __init__(self):
        super().__init__(
            name="Agent 1A - Data Harmonizer",
            role="Data Schema Analyzer",
            goal="Detect and map data schemas from various formats",
            backstory="Data engineer specialized in harmonizing inconsistent datasets"
        )
    
    def execute(self, file_path: str):
        """Analyze data and create standardized schema mapping."""
        self.log_start(f"Analyzing schema for {file_path}")
        
        preview_rows = 15 # Hardcode preview_rows as it's no longer a parameter
        
        # Load file
        try:
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
            elif file_path.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(file_path)
            else:
                return {"error": "Unsupported file format. Use CSV or Excel."}
        except Exception as e:
            self.log_error("File Load", str(e))
            return {"error": f"Failed to load file: {str(e)}"}
        
        if df.empty:
            return {"error": "File is empty"}
        
        # Get preview data for LLM
        preview_df = df.head(preview_rows)
        
        # Detect schema using LLM
        schema_result = self._detect_schema_with_llm(preview_df)
        
        if not schema_result:
            return {"error": "Schema detection failed"}
        
        # Validate detected schema
        validation = self._validate_schema(df, schema_result)
        
        self.log_complete("Schema Detection", 
                         f"Detected: date={schema_result.get('date_column')}, "
                         f"quantity={schema_result.get('quantity_column')}, "
                         f"item={schema_result.get('item_column')}")
        
        return {
            "schema": schema_result,
            "validation": validation,
            "total_rows": len(df),
            "columns_found": list(df.columns),
            "date_range": self._get_date_range(df, schema_result.get('date_column')) if validation['is_valid'] else None
        }
    
    def _detect_schema_with_llm(self, preview_df: pd.DataFrame) -> dict:
        """Use LLM to detect column mappings"""
        
        # Prepare data sample for LLM
        columns_info = []
        for col in preview_df.columns:
            sample_values = preview_df[col].dropna().head(5).tolist()
            columns_info.append({
                "column_name": col,
                "sample_values": [str(v) for v in sample_values],
                "data_type": str(preview_df[col].dtype)
            })
        
        prompt = f"""Analyze this dataset and identify which columns correspond to standard forecasting fields.

Dataset columns and samples:
{json.dumps(columns_info, indent=2)}

Identify and return ONLY a JSON object with these fields:
{{
  "date_column": "exact column name containing dates/timestamps",
  "item_column": "exact column name containing item/product names or codes",
  "quantity_column": "exact column name containing quantity/amount/sales numbers",
  "date_format": "detected date format like DD/MM/YYYY or YYYY-MM-DD or MM-DD-YYYY",
  "unit": "detected unit (pieces, kg, liters, meters, units, etc.)",
  "issues_found": ["list of any data quality issues noticed"],
  "confidence": "high/medium/low"
}}

Rules:
- Date column: look for columns with date-like values (2023-01-15, 15/01/2023, etc.)
- Item column: product names, item codes, SKU, material names
- Quantity column: numeric values representing amounts ordered/sold/used
- Unit detection: Look at item names for clues (Screws=pieces, Oil=liters, Wire=meters, Plates=pieces, etc.)
  If item names mention materials like screws, bolts, plates, motors, gloves → use "pieces"
  If liquids like oil, paint → use "liters"
  If wire, cable, chain → use "meters"
  If weight-based like grease, powder → use "kg"
  Default to "pieces" if unclear
- Issues: missing values, suspicious outliers, inconsistent formats
- Return ONLY valid JSON, no explanation

Analyze and respond:"""

        try:
            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["reasoning"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Clean JSON formatting
            if result_text.startswith('```json'):
                result_text = result_text.replace('```json', '').replace('```', '').strip()
            
            schema = json.loads(result_text)
            return schema
            
        except Exception as e:
            self.log_error("LLM Schema Detection", str(e))
            return None
    
    def _validate_schema(self, df: pd.DataFrame, schema: dict) -> dict:
        """Validate schema has required fields."""
        
        validation = {
            "is_valid": True,
            "errors": [],
            "warnings": []
        }
        
        # Check if columns exist
        date_col = schema.get('date_column')
        item_col = schema.get('item_column')
        qty_col = schema.get('quantity_column')
        
        if not date_col or date_col not in df.columns:
            validation['errors'].append(f"Date column '{date_col}' not found")
            validation['is_valid'] = False
        
        if not item_col or item_col not in df.columns:
            validation['errors'].append(f"Item column '{item_col}' not found")
            validation['is_valid'] = False
        
        if not qty_col or qty_col not in df.columns:
            validation['errors'].append(f"Quantity column '{qty_col}' not found")
            validation['is_valid'] = False
        
        if not validation['is_valid']:
            return validation
        
        # Check data quality
        if df[date_col].isnull().sum() > 0:
            null_count = df[date_col].isnull().sum()
            validation['warnings'].append(f"{null_count} missing values in date column")
        
        if df[qty_col].isnull().sum() > 0:
            null_count = df[qty_col].isnull().sum()
            validation['warnings'].append(f"{null_count} missing values in quantity column")
        
        # Check if quantity is numeric
        try:
            pd.to_numeric(df[qty_col], errors='coerce')
        except:
            validation['errors'].append("Quantity column contains non-numeric values")
            validation['is_valid'] = False
        
        return validation
    
    def _get_date_range(self, df: pd.DataFrame, date_column: str) -> dict:
        """Get date range from data."""
        date_col = date_column
        
        try:
            dates = pd.to_datetime(df[date_col], errors='coerce')
            return {
                "start_date": dates.min().strftime('%Y-%m-%d'),
                "end_date": dates.max().strftime('%Y-%m-%d'),
                "total_months": ((dates.max() - dates.min()).days // 30) + 1
            }
        except:
            return None


if __name__ == "__main__":
    print("Testing Agent 1A - Data Harmonizer\n")
    
    harmonizer = DataHarmonizer()
    
    # Test with historical orders
    result = harmonizer.execute('data/historical_orders.csv')
    
    if result.get('error'):
        print(f"Error: {result['error']}")
    else:
        print("Schema Detection Results:")
        print(json.dumps(result['schema'], indent=2))
        print("\nValidation:")
        print(f"Valid: {result['validation']['is_valid']}")
        if result['validation']['errors']:
            print(f"Errors: {result['validation']['errors']}")
        if result['validation']['warnings']:
            print(f"Warnings: {result['validation']['warnings']}")
        
        if result.get('date_range'):
            print(f"\nDate Range: {result['date_range']['start_date']} to {result['date_range']['end_date']}")
            print(f"Total Months: {result['date_range']['total_months']}")
    
    print("\nAgent 1A test complete!")
    