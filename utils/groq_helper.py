import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from groq import Groq       # type: ignore
from config.settings import GROQ_API_KEY, GROQ_MODELS, TEMPERATURE, MAX_TOKENS
from utils.logger import logger
import json

class GroqHelper:
    """Helper class for Groq LLM API interactions."""
    
    def __init__(self):
        if not GROQ_API_KEY:
            logger.error("Groq API key missing!")
        
        self.client = Groq(api_key=GROQ_API_KEY)
        logger.info("Groq connection initialized")
    
    def ask(self, question: str, model_type: str = "quick") -> str:
        """Ask Groq a simple question and return the response."""
        model_name = GROQ_MODELS[model_type]
        
        try:
            response = self.client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "user", "content": question}
                ],
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS
            )
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Error asking Groq: {e}")
            return f"Error: Unable to process request — {e}"
    
    def ask_with_system(self, question: str, system_prompt: str, model_type: str = "reasoning") -> str:
        """Ask Groq with a system prompt for specialized instructions."""
        model_name = GROQ_MODELS[model_type]
        
        try:
            response = self.client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},  
                    {"role": "user", "content": question}       
                ],
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS
            )
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Error: {e}")
            return f"Error: Unable to process request — {e}"
    
    def ask_for_json(self, question: str, system_prompt: str) -> dict:
        """Ask Groq and get structured JSON response."""
        model_name = GROQ_MODELS["reasoning"]
        
        try:
            response = self.client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt + " Return only JSON."},
                    {"role": "user", "content": question}
                ],
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                response_format={"type": "json_object"} 
            )
            answer_text = response.choices[0].message.content
            return json.loads(answer_text)
            
        except Exception as e:
            logger.error(f"Error asking Groq: {e}")
            return {"error": str(e)}

groq = GroqHelper()

def test_connection():
    """Test Groq API connection."""
    logger.info("\nTesting Groq connection...")
    
    try:
        answer = groq.ask("Say 'Hello! I am working.' and nothing else.", model_type="quick")
        print(f"Response: {answer}")
        
        if "working" in answer.lower():
            logger.info("Groq test PASSED!")
            return True
        else:
            logger.warning("Groq responded but unexpected answer")
            return False
            
    except Exception as e:
        logger.error(f"Groq test FAILED: {e}")
        return False

if __name__ == "__main__":
    test_connection()
