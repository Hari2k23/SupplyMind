"""Configuration settings for the Multi-Agent Procurement System."""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODELS = {
    "reasoning": "llama-3.3-70b-versatile",
    "quick": "llama-3.1-8b-instant",
    "vision": "meta-llama/llama-4-scout-17b-16e-instruct"  
}
TEMPERATURE = 0.3
MAX_TOKENS = 2048  

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)


REORDER_POINT = 500    
SAFETY_BUFFER = 500   
APPROVAL_LIMIT = 5000 
CURRENCY = "₹"
MAX_DEFECT_RATE = 0.3  
ACCEPT_THRESHOLD = 2.0   # < 2% mismatch → accept shipment
REJECT_THRESHOLD = 10.0  # > 10% mismatch → reject shipment

APP_NAME = os.getenv("APP_NAME", "SupplyMind")
COMPANY_NAME = "Manufacturing Solutions Pvt Ltd"
COMPANY_EMAIL = "procurement@company.com"
TEST_MODE = True
