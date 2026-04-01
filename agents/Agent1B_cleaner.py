import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base_agent import BaseAgent
from utils.logger import log_info, log_error
import pandas as pd


class DataCleaner(BaseAgent):
    """Stage 2: Rule-based data cleaning and outlier detection."""
    def __init__(self):
        super().__init__(
            name="Agent 1B - Data Cleaner",
            role="Data Quality Engineer",
            goal="Clean and standardize data for forecasting",
            backstory="Data quality specialist with expertise in preprocessing"
        )
    
    def execute(self, df: pd.DataFrame, schema: dict):
        """
        Clean data using detected schema.
            
        Returns:
            Dictionary with cleaned data and cleaning report
        """
        self.log_start("Starting data cleaning")
        
        cleaned_df = df.copy()
        cleaning_report = {
            "rows_before": len(df),
            "rows_after": 0,
            "duplicates_removed": 0,
            "nulls_handled": 0,
            "outliers_detected": [],
            "dates_fixed": 0
        }
        
        date_col = schema.get('date_column')
        item_col = schema.get('item_column')
        qty_col = schema.get('quantity_column')
        
        # Step 1: Remove exact duplicates
        before_dup = len(cleaned_df)
        cleaned_df = cleaned_df.drop_duplicates()
        cleaning_report['duplicates_removed'] = before_dup - len(cleaned_df)
        
        # Step 2: Standardize dates to YYYY-MM-DD
        date_format = schema.get('date_format', 'infer')
        cleaned_df, dates_fixed = self._standardize_dates(cleaned_df, date_col, date_format)
        cleaning_report['dates_fixed'] = dates_fixed
        
        # Step 3: Handle missing values
        cleaned_df, nulls_handled = self._handle_missing_values(cleaned_df, date_col, qty_col)
        cleaning_report['nulls_handled'] = nulls_handled
        
        # Step 4: Detect outliers (but don't remove yet - flag for review)
        outliers = self._detect_outliers(cleaned_df, qty_col)
        cleaning_report['outliers_detected'] = outliers
        
        # Step 5: Ensure quantity is numeric
        cleaned_df[qty_col] = pd.to_numeric(cleaned_df[qty_col], errors='coerce')
        cleaned_df = cleaned_df.dropna(subset=[qty_col])
        
        cleaning_report['rows_after'] = len(cleaned_df)
        
        self.log_complete("Data Cleaning", 
                         f"Cleaned {cleaning_report['rows_before']} rows -> {cleaning_report['rows_after']} rows")
        
        return {
            "cleaned_data": cleaned_df,
            "report": cleaning_report
        }
    
    def _standardize_dates(self, df: pd.DataFrame, date_col: str, date_format: str) -> tuple:
        """Convert date column to standard format."""
        
        dates_fixed = 0
        
        try:
            if date_format == 'infer':
                # Leverage modern pandas format="mixed" for high robustness across diverse date representations
                df[date_col] = pd.to_datetime(df[date_col], format="mixed", errors='coerce')
            else:
                # Try to parse with detected format, fallback to mixed on error
                try:
                    df[date_col] = pd.to_datetime(df[date_col], format=date_format, errors='raise')
                except:
                    df[date_col] = pd.to_datetime(df[date_col], format="mixed", errors='coerce')
            
            # Count how many dates were successfully parsed
            dates_fixed = df[date_col].notna().sum()
            
            # Convert to standard format
            df[date_col] = df[date_col].dt.strftime('%Y-%m-%d')
            
        except Exception as e:
            log_error(f"Date standardization failed: {e}", self.name)
        
        return df, dates_fixed
    
    def _handle_missing_values(self, df: pd.DataFrame, date_col: str, qty_col: str) -> tuple:
        """Handle missing quantity values."""
        
        nulls_handled = 0
        
        # Drop rows with missing dates (can't forecast without timeline)
        before = len(df)
        df = df.dropna(subset=[date_col])
        nulls_handled += (before - len(df))
        
        # For quantities: only interpolate if 1-2 missing in sequence
        qty_nulls = df[qty_col].isnull().sum()
        
        if qty_nulls > 0 and qty_nulls <= 2:
            df[qty_col] = df[qty_col].interpolate(method='linear')
            nulls_handled += qty_nulls
        else:
            # Too many nulls, drop them
            before = len(df)
            df = df.dropna(subset=[qty_col])
            nulls_handled += (before - len(df))
        
        return df, nulls_handled
    
    def _detect_outliers(self, df: pd.DataFrame, qty_col: str) -> list:
        """Detect outliers using IQR method."""
        
        outliers = []
        
        try:
            Q1 = df[qty_col].quantile(0.25)
            Q3 = df[qty_col].quantile(0.75)
            IQR = Q3 - Q1
            
            # Use 3.0 multiplier instead of 1.5 for more relaxed outlier detection
            # This prevents flagging legitimate large orders as outliers
            lower_bound = Q1 - 3.0 * IQR
            upper_bound = Q3 + 3.0 * IQR
            
            # Also check for extreme outliers (orders 10x the median)
            median_qty = df[qty_col].median()
            extreme_threshold = median_qty * 10
            
            outlier_mask = (df[qty_col] < lower_bound) | (df[qty_col] > upper_bound) | (df[qty_col] > extreme_threshold)
            
            if outlier_mask.any():
                outlier_rows = df[outlier_mask]
                for idx, row in outlier_rows.iterrows():
                    qty_value = float(row[qty_col])
                    
                    # Determine reason
                    if qty_value > extreme_threshold:
                        reason = f"Extreme value: {qty_value:.0f} (>10x median of {median_qty:.0f})"
                    elif qty_value > upper_bound:
                        reason = f"High value: {qty_value:.0f} (IQR upper bound: {upper_bound:.0f})"
                    else:
                        reason = f"Low value: {qty_value:.0f} (IQR lower bound: {lower_bound:.0f})"
                    
                    outliers.append({
                        "row_index": int(idx),
                        "value": qty_value,
                        "reason": reason
                    })
        
        except Exception as e:
            log_error(f"Outlier detection failed: {e}", self.name)
        
        return outliers


if __name__ == "__main__":
    print("Testing Agent 1B - Data Cleaner\n")
    
    # Load test data
    df = pd.read_csv('data/historical_orders.csv')
    
    # Simulate schema from harmonizer
    schema = {
        "date_column": "order_date",
        "item_column": "item_name",
        "quantity_column": "quantity_ordered",
        "date_format": "infer"
    }
    
    cleaner = DataCleaner()
    result = cleaner.execute(df, schema)
    
    print("Cleaning Report:")
    print(f"Rows before: {result['report']['rows_before']}")
    print(f"Rows after: {result['report']['rows_after']}")
    print(f"Duplicates removed: {result['report']['duplicates_removed']}")
    print(f"Nulls handled: {result['report']['nulls_handled']}")
    print(f"Dates fixed: {result['report']['dates_fixed']}")
    print(f"Outliers detected: {len(result['report']['outliers_detected'])}")
    
    if result['report']['outliers_detected']:
        print("\nOutliers found:")
        for outlier in result['report']['outliers_detected'][:5]:
            print(f"  Row {outlier['row_index']}: {outlier['value']} - {outlier['reason']}")
    
    print("\nCleaned data preview:")
    print(result['cleaned_data'].head())
    
    print("\nAgent 1B test complete!")
    