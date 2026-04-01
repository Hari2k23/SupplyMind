import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crewai import Agent        # type: ignore
from utils.logger import logger, log_info, log_error, log_warning, log_debug
from utils.groq_helper import groq
import pandas as pd             # type: ignore

class BaseAgent:
    """Base class that all procurement agents inherit from with common functionality."""
    
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    def __init__(self, name: str, role: str, goal: str, backstory: str):
        """Initialize base agent with CrewAI configuration."""
        self.name = name
        self.role = role
        self.goal = goal
        self.backstory = backstory
        
        self.agent = Agent(
            role=role,
            goal=goal,
            backstory=backstory,
            verbose=True, 
            allow_delegation=False,  
            llm=groq.client
        )
        
        log_info(f"{name} initialized", agent=name)
    
    def get_data_path(self, filename: str) -> str:
        """Get absolute path to file in data/ folder."""
        return os.path.join(self.PROJECT_ROOT, 'data', filename)
    
    def load_csv(self, filename: str) -> pd.DataFrame:
        """Load CSV file into pandas DataFrame."""
        filepath = self.get_data_path(filename)
        
        try:
            df = pd.read_csv(filepath)
            log_info(f"Loaded {filename}: {len(df)} rows", agent=self.name)
            return df
        except FileNotFoundError:
            log_error(f"File not found: {filename}", agent=self.name)
            return pd.DataFrame()
        except Exception as e:
            log_error(f"Error loading {filename}: {e}", agent=self.name)
            return pd.DataFrame()
    
    def save_csv(self, df: pd.DataFrame, filename: str):
        """Save DataFrame to CSV file."""
        filepath = self.get_data_path(filename)
        
        try:
            df.to_csv(filepath, index=False)
            log_info(f"Saved {filename}: {len(df)} rows", agent=self.name)
        except Exception as e:
            log_error(f"Error saving {filename}: {e}", agent=self.name)
    
    def log_info(self, message: str):
        """Log info message with agent name."""
        log_info(message, agent=self.name)
    
    def log_warning(self, message: str):
        """Log warning message with agent name."""
        log_warning(message, agent=self.name)
    
    def log_debug(self, message: str):
        """Log debug message with agent name."""
        log_debug(message, agent=self.name)
    
    def log_start(self, task: str):
        """Log that agent is starting a task."""
        log_info(f"Starting: {task}", agent=self.name)
    
    def log_complete(self, task: str, result: str = "Success"):
        """Log that agent completed a task."""
        log_info(f"Completed: {task} - {result}", agent=self.name)
    
    def log_error(self, task: str, error: str = None):
        """Log an error with flexible signature for backward compatibility."""
        if error:
            log_error(f"Failed: {task} - {error}", agent=self.name)
        else:
            log_error(task, agent=self.name)
    
    def execute(self, *args, **kwargs):
        """Main execution method - override in child classes."""
        raise NotImplementedError("Child agent must implement execute() method")

# Test the base agent
if __name__ == "__main__":
    print("\nTesting Base Agent...")
    
    test_agent = BaseAgent(
        name="Test Agent",
        role="Tester",
        goal="Test the base agent class",
        backstory="I am a test agent for verification"
    )
    
    print(f"\nAgent created: {test_agent.name}")
    print(f"  Role: {test_agent.role}")
    print(f"  Goal: {test_agent.goal}")
    
    # Test all logging methods
    print("\nTesting logging methods...")
    test_agent.log_info("This is an info message")
    test_agent.log_warning("This is a warning message")
    test_agent.log_debug("This is a debug message")
    test_agent.log_start("Testing CSV loading")
    test_agent.log_error("Test error", "This is an error message")
    test_agent.log_complete("Testing", "All tests passed")
    
    # Test CSV loading
    print("\nTesting CSV loading...")
    df = test_agent.load_csv('current_inventory.csv')
    if not df.empty:
        print(f"Loaded {len(df)} items from inventory")
        print(f"First item: {df.iloc[0]['item_name']}")
    
    print("\nBase Agent test complete!")
    