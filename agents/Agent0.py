import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.base_agent import BaseAgent
from agents.Agent3_replenishmentAdvisor import ReplenishmentAdvisor
from agents.Agent4_supplierDiscovery import SupplierDiscovery
from agents.Agent5_rfqGenerator import RFQGenerator
from agents.Agent6_decisionMaker import DecisionAgent
from agents.Agent7_communicationOrchestrator import CommunicationOrchestrator
from utils.groq_helper import groq
from utils.logger import log_info, log_error
from config.settings import GROQ_MODELS, APP_NAME
from utils.date_formatter import format_display_date
import json
import re
from datetime import datetime
from difflib import SequenceMatcher

# ══════════════════════════════════════════════════════════════════════════════
#  NORMALIZATION & FUZZY MATCHING UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

# Common aliases that map alternate names to canonical inventory terms
ITEM_ALIASES = {
    "nut": "bolt", "nuts": "bolts",
    "motor oil": "lubricant oil", "engine oil": "lubricant oil",
    "pcb": "circuit board", "pcbs": "circuit boards",
    "safety glasses": "safety gloves", "ppe gloves": "safety gloves",
    "helmet": "hard hat", "helmets": "hard hats",
    "tape": "adhesive", "glue": "adhesive",
    "aluminium": "aluminum",  # British vs American spelling
    "gasket": "rubber gaskets", "gaskets": "rubber gaskets",
    "oring": "o-rings", "orings": "o-rings", "o ring": "o-rings",
    "drill": "drill bits", "drills": "drill bits",
    "wrench": "wrenches", "spanner": "wrenches", "spanners": "wrenches",
    "cardboard": "cardboard boxes", "boxes": "cardboard boxes",
    "solvent": "cleaning solvent", "cleaner": "cleaning solvent",
    "coating": "paint", "primer": "paint",
    "bubblewrap": "bubble wrap",
    "screw": "m8 screws", "screws": "m8 screws",
    "sensor": "sensors",
    "bearing": "bearings",
    "gear": "gears",
}

# Affirmative / negative phrases for state-aware override
_AFFIRMATIVE = {
    "yes", "yeah", "yea", "yep", "yup", "sure", "ok", "okay", "k",
    "kk", "go ahead", "do it", "proceed", "confirm", "absolutely",
    "of course", "definitely", "please", "lets go", "sounds good",
    "alright", "right", "cool", "fine", "approved", "approve",
    "yes please", "go for it", "lets do it", "affirmative",
    "ya", "yah", "aye", "si",
}
_NEGATIVE = {
    "no", "nah", "nope", "not now", "cancel", "stop", "dont",
    "skip", "later", "not yet", "negative", "reject", "denied",
    "no thanks", "not right now", "maybe later", "hold on",
    "wait", "nay",
}


def _normalize(text: str) -> str:
    """Normalize text for matching: lowercase, strip punctuation, collapse whitespace."""
    text = text.lower().strip()
    # Normalize hyphens and underscores to spaces
    text = re.sub(r'[-_]+', ' ', text)
    # Remove all punctuation except alphanumeric and spaces
    text = re.sub(r'[^a-z0-9\s]', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _fuzzy_score(a: str, b: str) -> float:
    """Return similarity ratio between two strings (0.0 – 1.0)."""
    return SequenceMatcher(None, a, b).ratio()


def _fuzzy_word_score(query_words: list, target_words: list) -> float:
    """Score how well query words match target words, allowing per-word fuzzy."""
    if not query_words or not target_words:
        return 0.0
    total = 0.0
    matched = 0
    for qw in query_words:
        best = max((_fuzzy_score(qw, tw) for tw in target_words), default=0.0)
        if best >= 0.65:  # per-word threshold
            total += best
            matched += 1
    if matched == 0:
        return 0.0
    # Reward matching more words of the target
    coverage = matched / max(len(target_words), len(query_words))
    return (total / matched) * 0.6 + coverage * 0.4


def _is_affirmative(text: str) -> bool:
    """Check if text is an affirmative response."""
    norm = _normalize(text)
    return norm in _AFFIRMATIVE or any(norm.startswith(a) for a in _AFFIRMATIVE if len(a) > 2)


def _is_negative(text: str) -> bool:
    """Check if text is a negative response."""
    norm = _normalize(text)
    return norm in _NEGATIVE or any(norm.startswith(n) for n in _NEGATIVE if len(n) > 2)



class MasterOrchestrator(BaseAgent):
    """Intent-based flow coordinator that routes requests to appropriate agents."""
    def __init__(self):
        super().__init__(
            name="Agent 0 - Master Orchestrator",
            role="Procurement Flow Coordinator",
            goal="Route user requests to appropriate agents and manage conversation flow",
            backstory="Expert in understanding user intent and orchestrating multi-agent workflows"
        )
        log_info("Master Orchestrator initialized", self.name)

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        self.advisor = ReplenishmentAdvisor()
        self.supplier_finder = SupplierDiscovery()
        self.rfq_generator = RFQGenerator()
        self.decision_agent = DecisionAgent()
        self.communication_agent = CommunicationOrchestrator()
        self.state = "idle"
        self.last_item_code = None
        self.last_item_name = None
        self.last_quantity = None
        self.last_suppliers = None
        self.rfq_sent = False
        self.collected_quotes = []
        self.pending_po_data = None
        self.conversation_history = []  # Track last N exchanges for context
       
        self.pending_rfqs_file = os.path.join(project_root, 'data', 'pending_rfqs.json')
        self.sent_rfqs_file = os.path.join(project_root, 'data', 'sent_rfqs.json')
        self.context_file = os.path.join(project_root, 'data', 'agent0_context.json')
        self.last_urgency = None

        self._restore_context()

    def process_request(self, user_input: str) -> str:
        """Process user request by classifying intent and routing to appropriate handler."""
        log_info(f"Processing: {user_input}", self.name)

        # Track conversation history for context
        self.conversation_history.append({"role": "user", "content": user_input})
        if len(self.conversation_history) > 12:  # keep last 6 exchanges (12 messages)
            self.conversation_history = self.conversation_history[-12:]

        override_intent = self._state_aware_override(user_input)
        if override_intent:
            log_info(f"State override -> {override_intent['type']}", self.name)
            intent = override_intent
        else:
            intent = self._classify_user_intent(user_input)
        
        log_info(f"Detected intent: {intent['type']}", self.name)
       
        if intent['type'] == 'full_inventory_check':
            self._reset_state()
            response = self._handle_full_inventory_check()
       
        elif intent['type'] == 'new_demand_check':
            self._reset_state()
            response = self._handle_demand_check(user_input)
       
        elif intent['type'] == 'find_suppliers_for_item':
            item_name = intent.get('item_name')
            response = self._handle_supplier_request(user_input, item_name)
       
        elif intent['type'] == 'show_pending_rfqs':
            response = self._show_pending_rfqs()
        
        elif intent['type'] == 'show_sent_rfqs':
            response = self._show_sent_rfqs()
        
        elif intent['type'] == 'show_all_rfqs':
            response = self._show_all_rfqs()
       
        elif intent['type'] == 'resume_rfq':
            item_identifier = intent.get('item_identifier')
            if not item_identifier:
                self.state = "awaiting_rfq_selection"
                response = "I have pending RFQs saved. Could you tell me which one you'd like to continue? You can mention the item name, item code, or when you created it."
            else:
                response = self._resume_rfq(item_identifier)
       
        elif intent['type'] == 'help':
            response = self._show_help()
       
        elif intent['type'] == 'supplier_approval':
            if self.state == "awaiting_supplier_approval":
                if intent.get('response') == 'yes':
                    response = self._find_suppliers()
                else:
                    self._reset_state()
                    response = "Alright, no problem. Just let me know when you need something."
            else:
                response = "I'm not sure what you're referring to. Would you like to check an item's inventory status?"
       
        elif intent['type'] == 'rfq_intent':
            if self.state == "awaiting_rfq_approval":
                response = self._handle_rfq_intent(user_input, intent)
            else:
                response = "I'm not currently waiting for RFQ instructions. Would you like to check an item's status?"
       
        elif intent['type'] == 'quote_submission':
            response = self._handle_quote_submission(user_input)
       
        elif intent['type'] == 'analyze_quotes':
            response = self._handle_analyze_quotes()
       
        elif intent['type'] == 'po_approval':
            if self.state == "awaiting_po_approval":
                response = self._handle_po_approval(intent)
            else:
                response = "I'm not currently waiting for PO approval. Would you like to check an item's status?"
       
        elif intent['type'] == 'notification_query':
            response = self._handle_notification_query(user_input)
       
        elif intent['type'] == 'inbox_check':
            response = self._handle_inbox_check(user_input)
       
        elif intent['type'] in ('acknowledgment', 'unclear'):
            response = self._handle_acknowledgment(user_input)
       
        else:
            response = self._handle_acknowledgment(user_input)

        # Attach smart pills if the response does not already have them
        response = self._attach_pills(response)

        # Track assistant response in history
        self.conversation_history.append({"role": "assistant", "content": response.split('===')[0].strip()[:200]})
        if len(self.conversation_history) > 12:
            self.conversation_history = self.conversation_history[-12:]

        return response

    # ══════════════════════════════════════════════════════════════════════
    #  STATE-AWARE DETERMINISTIC OVERRIDE
    # ══════════════════════════════════════════════════════════════════════

    def _state_aware_override(self, user_input: str) -> dict | None:
        """Override intent classification based on conversation state."""
        norm = _normalize(user_input)
        is_short = len(norm.split()) <= 5

        # Keyword shortcut: "help" always goes to help handler
        if norm.strip() in ("help", "help me", "what can you do"):
            return {"type": "help"}

        if self.state == "awaiting_supplier_approval" and is_short:
            if _is_affirmative(norm):
                return {"type": "supplier_approval", "response": "yes"}
            if _is_negative(norm):
                return {"type": "supplier_approval", "response": "no"}

        if self.state == "awaiting_rfq_approval":
            if is_short:
                if _is_affirmative(norm):
                    return {"type": "rfq_intent"}
                if _is_negative(norm):
                    return {"type": "rfq_intent"}
            # Catch "Run live web search" pill clicks
            if any(w in norm for w in ["search", "web", "live"]) or "run live web search" in norm:
                return {"type": "rfq_intent"}

        if self.state == "awaiting_po_approval" and is_short:
            if _is_affirmative(norm):
                return {"type": "po_approval", "response": "yes"}
            if _is_negative(norm):
                return {"type": "po_approval", "response": "no"}

        # When pending RFQs were just shown and user mentions an item name or
        # says "resume this", "continue that", "this one" etc. → route to resume_rfq
        if self.state == "awaiting_rfq_selection":
            # If user declines, reset state
            if _is_negative(norm):
                self.state = "idle"
                return {"type": "acknowledgment"}

            # Words that signal a NEW intent (not a resume) → reset state, let LLM classify
            new_intent_words = ["check", "status", "order", "need", "do we", "should we",
                                "inventory", "find", "show", "help", "pending", "analyze",
                                "how much", "how many", "whats", "what is", "what's",
                                "inbox", "quote", "notify"]
            casual_words = ["hi", "hey", "hello", "how", "what", "why", "who",
                           "thanks", "thank", "ok", "okay", "sure",
                           "bye", "good", "great", "fine", "cool", "nice",
                           "sup", "yo", "doin", "doing", "morning", "evening"]

            if any(w in norm for w in new_intent_words) or any(w in norm for w in casual_words):
                self.state = "idle"
                return None  # Fall through to LLM classifier

            # Only catch explicit resume-like messages:
            # Pronouns / demonstratives that refer to what was just shown
            if any(w in norm for w in ["this", "that", "resume", "continue", "first", "last", "one"]):
                return {"type": "resume_rfq", "item_identifier": user_input}
            # Bare short item name with no other intent signals (e.g. just "circuit boards")
            if is_short:
                return {"type": "resume_rfq", "item_identifier": user_input}

            # Anything else → reset state, let LLM handle
            self.state = "idle"

        return None

    def _classify_user_intent(self, user_input: str) -> dict:
        """Use LLM to classify user intent from natural language."""

        low = user_input.lower().strip()

        if any(p in low for p in ["check the inventory", "check inventory", "full inventory",
                                   "stock report", "scan inventory", "inventory overview",
                                   "what needs ordering", "inventory scan", "check all items"]):
            return {"type": "full_inventory_check"}

        if any(p in low for p in ["sent rfq", "show sent", "rfqs i sent", "rfqs sent"]):
            return {"type": "show_sent_rfqs"}
        if any(p in low for p in ["pending rfq", "pending order", "saved rfq"]):
            return {"type": "show_pending_rfqs"}
        if any(p in low for p in ["show rfq", "all rfq", "list rfq", "rfq history"]):
            return {"type": "show_all_rfqs"}

        # Build a compact inventory list so the LLM is aware of actual items
        inv_list = self._get_inventory_names_for_prompt()

        # Build conversation context (last 4 messages)
        recent_context = ""
        if self.conversation_history:
            recent = self.conversation_history[-4:]  # last 2 exchanges
            recent_context = "\n".join(
                f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                for m in recent
            )

        prompt = f"""You are an intent classifier for a procurement assistant chatbot.

SYSTEM STATE: {self.state}
ITEM IN CONTEXT: {self.last_item_name or 'None'}
INVENTORY ITEMS: {inv_list}

RECENT CONVERSATION:
{recent_context}

CURRENT USER MESSAGE: "{user_input}"

Classify the user's intent into EXACTLY ONE of the types below.
Return ONLY a valid JSON object — no explanation, no markdown.

INTENT TYPES:
1. "new_demand_check" — check inventory / stock / order status for a SPECIFIC item (user mentions an item name)
   → {{"type": "new_demand_check"}}
1b. "full_inventory_check" — check the ENTIRE inventory / full stock report / what needs to be ordered (NO specific item mentioned)
    → {{"type": "full_inventory_check"}}
2. "find_suppliers_for_item" — explicitly find or get suppliers for a SPECIFIC item
   → {{"type": "find_suppliers_for_item", "item_name": "<item>"}}
3. "show_all_rfqs" — view ALL RFQs (both sent and pending combined)
   → {{"type": "show_all_rfqs"}}
4. "show_pending_rfqs" — view saved / pending RFQs only
   → {{"type": "show_pending_rfqs"}}
5. "show_sent_rfqs" — view sent RFQs only
   → {{"type": "show_sent_rfqs"}}

6. "resume_rfq" — continue a saved RFQ
   → {{"type": "resume_rfq", "item_identifier": "<item or code or date>"}}
7. "supplier_approval" — yes/no to "shall I find suppliers?"
   → {{"type": "supplier_approval", "response": "yes" or "no"}}
8. "rfq_intent" — response to RFQ send/wait/cancel
   → {{"type": "rfq_intent"}}
9. "quote_submission" — submitting or informing about received quotes (NOT analyzing)
   → {{"type": "quote_submission"}}
10. "analyze_quotes" — analyze / compare / review collected quotes
   → {{"type": "analyze_quotes"}}
11. "po_approval" — approve or reject a purchase order
   → {{"type": "po_approval", "response": "yes" or "no"}}
12. "notification_query" — asking about sent notifications
    → {{"type": "notification_query"}}
13. "inbox_check" — check inbox for supplier emails / replies
    → {{"type": "inbox_check"}}
14. "acknowledgment" — simple acknowledgment (ok, thanks, got it) when NOT awaiting a decision
    → {{"type": "acknowledgment"}}
15. "help" — asking for help or guidance
    → {{"type": "help"}}
16. "unclear" — truly cannot determine intent
    → {{"type": "unclear"}}

══════════════════ PRIORITY RULES (MUST OBEY) ══════════════════
• STATE OVERRIDES:
  – If state is "awaiting_supplier_approval" and user says yes/no/ok/sure → "supplier_approval", NOT "acknowledgment"
  – If state is "awaiting_rfq_approval" and user says yes/send/ok/sure → "rfq_intent", NOT "acknowledgment"
  – If state is "awaiting_po_approval" and user says yes/approve/ok/sure → "po_approval", NOT "acknowledgment"
  – ONLY classify as "acknowledgment" when state is "idle" or no decision pending

• KEYWORD OVERRIDES:
  – "analyze", "analyse", "compare", "done", "let's see", "ready", "show me" (about quotes) → "analyze_quotes"
  – "I got quote", "received quote", pasting price data → "quote_submission"
  – "check inbox", "any emails", "did suppliers reply" → "inbox_check"
  – Checking / status for a SPECIFIC item (name mentioned) → "new_demand_check"
  – "check the inventory", "full inventory", "stock report", "what needs ordering", "scan inventory", "inventory overview" (NO specific item) → "full_inventory_check"
  – "find suppliers", "get suppliers", "where to buy" → "find_suppliers_for_item"
  – "pending rfqs", "pending orders", "saved rfqs" → "show_pending_rfqs"
  – "sent rfqs", "show sent", "rfqs I sent" → "show_sent_rfqs"
  – "show rfqs", "all rfqs", "rfq history", "list rfqs" → "show_all_rfqs"
  – "resume", "continue" + item → "resume_rfq"

• DISAMBIGUATION: "check inventory" vs "check M8 screws":
  – If user mentions a specific item name → "new_demand_check"
  – If user says "check inventory" / "check all items" generically → "full_inventory_check"

• CONVERSATION CONTEXT:
  – If user says "this", "it", "that one" → refer to conversation history to determine the item/intent
  – If state is "awaiting_rfq_selection" and user says an item name → "resume_rfq"
  – If user refers to a recently discussed item with a pronoun → use ITEM IN CONTEXT

• TYPO TOLERANCE: User may misspell item names. Match to closest inventory item.

Return ONLY the JSON object."""
        try:
            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["reasoning"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.05,
                max_tokens=200
            )
           
            result_text = response.choices[0].message.content.strip()
           
            # Strip markdown fences if present
            if result_text.startswith('```'):
                result_text = re.sub(r'^```(?:json)?\s*', '', result_text)
                result_text = re.sub(r'\s*```$', '', result_text)
           
            intent = json.loads(result_text)
            return intent
           
        except Exception as e:
            log_error(f"Intent classification failed: {e}", self.name)
            return {"type": "unclear"}

    def _get_inventory_names_for_prompt(self) -> str:
        """Return a compact comma-separated list of inventory item names for LLM context."""
        try:
            inv = self.load_csv('current_inventory.csv')
            if inv.empty:
                return "(inventory unavailable)"
            names = inv['item_name'].tolist()
            return ", ".join(names)
        except Exception:
            return "(inventory unavailable)"

    def _handle_demand_check(self, user_input: str) -> str:
        """Handle new demand check request."""
       
        item_code = self._extract_item(user_input)
        if not item_code:
            return "I couldn't identify the item. Try like: 'Status of M8 Screws' or 'Check Electric Motors'."
        log_info(f"Checking order for {item_code}", self.name)
        result = self.advisor.execute(item_code, forecast_days=30)
        if not result:
            return "Item not found in inventory database."
       
        # Check if result contains error
        if result.get('error'):
            return f"Error: {result.get('message', 'Unknown error occurred')}"
        rec = result['recommendation']
        self.last_item_code = item_code
        self.last_item_name = rec.item_name
        self.last_quantity = rec.recommended_quantity
        self.last_urgency = rec.urgency
        self.state = "awaiting_supplier_approval"
        self._persist_context()
        
        question = self._generate_supplier_approval_question()
        return f"""### Inventory Analysis: {rec.item_name}
**Primary Recommendation**: Procure **{rec.recommended_quantity} units**
**Urgency Level**: {rec.urgency}

**Justification**:
{rec.reason}


---
{question}

===
Yes, find me suppliers
No, not right now
Check a different item"""

    def _handle_full_inventory_check(self) -> str:
        """Scan ALL inventory items and report which ones need procurement."""
        from agents.Agent2_stockMonitor import StockMonitor

        log_info("Running full inventory scan", self.name)

        try:
            monitor = StockMonitor()
            low_stock_items = monitor.check_all_low_stock_items()

            # Also count total items for the summary
            inv_df = self.load_csv('current_inventory.csv')
            total_items = len(inv_df) if not inv_df.empty else 0

            if not low_stock_items:
                return f"""### Full Inventory Scan Complete

All **{total_items}** items are at adequate stock levels. No procurement action needed right now!

===
Check a specific item
Show pending RFQs
Help"""

            # Group by urgency
            urgent = [s for s in low_stock_items if s.priority == "URGENT"]
            high = [s for s in low_stock_items if s.priority == "HIGH"]
            medium = [s for s in low_stock_items if s.priority == "MEDIUM"]
            adequate_count = total_items - len(low_stock_items)

            output = f"""### Full Inventory Scan Complete

**{len(low_stock_items)}** of **{total_items}** items need attention — **{adequate_count}** items are at healthy levels.

"""
            if urgent:
                output += "**URGENT - Immediate Procurement Required:**\n"
                for s in urgent:
                    output += f"- **{s.item_name}** ({s.item_code}): {s.current_quantity} units (reorder at {s.reorder_point}) - {s.status}\n"
                output += "\n"

            if high:
                output += "**HIGH PRIORITY - Order Soon:**\n"
                for s in high:
                    output += f"- **{s.item_name}** ({s.item_code}): {s.current_quantity} units (reorder at {s.reorder_point})\n"
                output += "\n"

            if medium:
                output += "**MEDIUM - Plan Ahead:**\n"
                for s in medium:
                    output += f"- **{s.item_name}** ({s.item_code}): {s.current_quantity} units (reorder at {s.reorder_point})\n"
                output += "\n"

            # Suggest the most urgent item for action
            top_item = (urgent or high or medium)[0]
            output += f"---\nI'd recommend starting with **{top_item.item_name}**. Would you like me to check it in detail?"

            output += f"\n\n===\nCheck {top_item.item_name} in detail\nShow pending RFQs\nHelp"

            return output

        except Exception as e:
            log_error(f"Full inventory check failed: {e}", self.name)
            return "I encountered an error while scanning the inventory. Please try again."

    def _handle_supplier_request(self, user_input: str, suggested_item_name: str = None) -> str:
        """Handle explicit supplier search request for a specific item."""
       
        if suggested_item_name:
            item_code = self._extract_item(suggested_item_name)
        else:
            item_code = self._extract_item(user_input)
       
        if not item_code:
            return "I couldn't identify which item you want suppliers for. Could you specify the item name?"
       
        log_info(f"Running demand analysis for {item_code} before supplier search", self.name)
        result = self.advisor.execute(item_code, forecast_days=30)
       
        if not result:
            return "Item not found in inventory database."
       
        # Check if result contains error
        if result.get('error'):
            return f"Error: {result.get('message', 'Unknown error occurred')}"
       
        rec = result['recommendation']
       
        self.last_item_code = item_code
        self.last_item_name = rec.item_name
        self.last_quantity = rec.recommended_quantity
        self._persist_context()
        log_info(f"Proceeding directly to supplier search for {self.last_item_name}", self.name)
        return self._find_suppliers()

    def _generate_supplier_approval_question(self) -> str:
        """Generate varied, natural supplier approval questions."""
        import random
       
        questions = [
            "Would you like me to suggest suppliers for this item?",
            "Should I look for suppliers for this?",
            "Want me to find some supplier options?",
            "Shall I search for suppliers who can fulfill this order?",
            "Would you like to see supplier recommendations?",
            "Should I find suppliers for this item?",
            "Do you want me to search for available suppliers?",
        ]
       
        return random.choice(questions)
   
    def _find_suppliers(self, force_web: bool = False) -> str:
        log_info(f"Finding suppliers for {self.last_item_code}", self.name)
        supplier_result = self.supplier_finder.execute(
            self.last_item_code,
            self.last_item_name,
            top_n=5,
            force_web=force_web
        )
        if not supplier_result or not supplier_result.get('suppliers'):
            return "No suppliers found for this item."
        self.last_suppliers = supplier_result
        suppliers_text = self.supplier_finder.format_supplier_info(supplier_result['suppliers'])
        self.state = "awaiting_rfq_approval"
        self._persist_context()
        
        if supplier_result.get('from_db'):
            try:                
                analysis_prompt = f"""You are a helpful procurement assistant. You found these historical suppliers for {self.last_item_name}:
{json.dumps(supplier_result['suppliers'], default=str)}

Write a very brief, natural, conversational response (1-2 concise sentences max) summarizing how their delivery was last time. 
Do NOT mention "JSON", "database", "data", or "retrieved". Just talk directly to the user like a human.
End by asking if they want to 'Send RFQs to these suppliers' or 'Run live web search'. Keep it professional but highly concise."""
                
                analysis_response = groq.client.chat.completions.create(
                    model=GROQ_MODELS["quick"],
                    messages=[{"role": "user", "content": analysis_prompt}],
                    temperature=0.4,
                    max_tokens=250
                )
                approval_question = analysis_response.choices[0].message.content.strip()
            except Exception as e:
                log_error(f"Failed to generate historical analysis: {e}", self.name)
                approval_question = f"I found previously approved suppliers for {self.last_item_name} in our database. Should I draft RFQs for them, or would you prefer I run a live web search to discover new suppliers?"
                
            pill_buttons = """===
Send RFQs to these suppliers
Run live web search
Save this RFQ for later"""
        else:
            approval_question = self._generate_rfq_approval_question()
            pill_buttons = """===
Send RFQs to all suppliers
Send to low risk suppliers only
Save this RFQ for later"""
        
        return f"""### Supplier Identification: {self.last_item_name}
{suppliers_text}

---
{approval_question}

{pill_buttons}"""

    def _generate_rfq_approval_question(self) -> str:
        """Generate natural language approval question using LLM."""
        prompt = f"""Generate a natural, friendly question asking if the user wants to send RFQs to suppliers.
Context:
- Item: {self.last_item_name}
- Recommended quantity: {self.last_quantity} units
- Default delivery: 14 days
Requirements:
- Mention the recommended quantity naturally
- Mention default delivery timeline
- Invite user to specify different quantity/delivery if needed
- Sound conversational, not robotic
- Be 1-2 sentences maximum
- Return ONLY the question text with NO quotes, NO markdown formatting, NO special characters
Generate ONLY the question text, nothing else. No quotes. No markdown."""
        try:
            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["quick"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=100
            )
           
            question = response.choices[0].message.content.strip()
            question = question.strip('"').strip("'").strip('`')
           
            return question
           
        except Exception as e:
            log_error(f"Question generation failed: {e}", self.name)
            return f"Based on our analysis, we'd need {self.last_quantity} units with 14-day delivery. Would you like to send RFQs to these suppliers?"

    def _handle_rfq_intent(self, user_input: str, classified_intent: dict) -> str:
        """Classify user's natural language intent for RFQ using LLM."""
       
        log_info("Classifying user RFQ intent...", self.name)
       
        supplier_list_text = ""
        for i, sup in enumerate(self.last_suppliers['suppliers'], 1):
            # Handle both risk_level and quality_level for backward compatibility
            quality_or_risk = sup.get('quality_level', sup.get('risk_level', 'Unknown'))
            supplier_list_text += f"{i}. {sup['supplier_name']} - {sup['location']} - {quality_or_risk} - {sup['contact_email']}\n"
       
        prompt = f"""Analyze the user's response and classify their intent for sending RFQs.
User said: "{user_input}"
Context:
- Item: {self.last_item_name}
- Recommended quantity: {self.last_quantity} units
- Default delivery days: 14
Available suppliers:
{supplier_list_text}
Classify the user's intent and return ONLY a JSON object:
{{
  "action": "send" or "wait" or "cancel" or "web_search",
  "quantity": {self.last_quantity} or user's modified quantity,
  "delivery_days": 14 or user's specified days (convert "urgent" to 7, "fast" to 5, etc.),
  "filter_type": "all" or "risk_based" or "count_based" or "name_based" or "location_based",
  "filter_value": appropriate value based on filter_type
}}
Rules:
- action "send" means proceed with RFQs
- action "wait" means save for later
- action "cancel" means stop the process
- action "web_search" means run a fresh live web search to discover alternative/new suppliers (e.g., "search online", "run web search")
- filter_type "all" → filter_value: "all"
- filter_type "risk_based" → filter_value: ["Low Risk"] or ["Low Risk", "Medium Risk"] (also accept "High Quality", "Medium Quality")
- filter_type "count_based" → filter_value: number (e.g., 3 for "first 3")
- filter_type "name_based" → filter_value: list of supplier names (fuzzy match)
- filter_type "location_based" → filter_value: list of locations
Examples:
"yes" → {{"action": "send", "quantity": {self.last_quantity}, "delivery_days": 14, "filter_type": "all", "filter_value": "all"}}
"send to low risk only" → {{"action": "send", "quantity": {self.last_quantity}, "delivery_days": 14, "filter_type": "risk_based", "filter_value": ["Low Risk"]}}
"first 3 suppliers, 7 days delivery" → {{"action": "send", "quantity": {self.last_quantity}, "delivery_days": 7, "filter_type": "count_based", "filter_value": 3}}
"wait for now" → {{"action": "wait", "quantity": {self.last_quantity}, "delivery_days": 14, "filter_type": null, "filter_value": null}}
"run live web search" → {{"action": "web_search", "quantity": {self.last_quantity}, "delivery_days": 14, "filter_type": null, "filter_value": null}}
Return ONLY the JSON, no explanation."""
        try:
            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["reasoning"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=300
            )
           
            result_text = response.choices[0].message.content.strip()
           
            if result_text.startswith('```json'):
                result_text = result_text.replace('```json', '').replace('```', '').strip()
           
            intent = json.loads(result_text)
            log_info(f"RFQ Intent classified: {intent}", self.name)
           
            if intent['action'] == 'send':
                return self._send_rfqs_with_filters(intent)
            elif intent['action'] == 'wait':
                return self._save_pending_rfq(intent)
            elif intent['action'] == 'web_search':
                return self._find_suppliers(force_web=True)
            elif intent['action'] == 'cancel':
                self._reset_state()
                return "Alright, no worries. Let me know when you're ready to proceed."
           
        except Exception as e:
            log_error(f"RFQ intent classification failed: {e}", self.name)
            return "I couldn't understand your request. Could you please rephrase? (e.g., 'yes, send to all' or 'only low risk suppliers')"

    def _send_rfqs_with_filters(self, intent: dict) -> str:
        """Send RFQs to filtered suppliers based on intent."""
       
        all_suppliers = self.last_suppliers['suppliers']
        selected_suppliers = []
       
        filter_type = intent.get('filter_type')
        filter_value = intent.get('filter_value')
       
        if filter_type == "all":
            selected_suppliers = all_suppliers
       
        elif filter_type == "risk_based":
            # Support both risk_level and quality_level filtering
            selected_suppliers = [
                s for s in all_suppliers
                if s.get('risk_level') in filter_value or s.get('quality_level') in filter_value
            ]
       
        elif filter_type == "count_based":
            selected_suppliers = all_suppliers[:filter_value]
       
        elif filter_type == "name_based":
            selected_suppliers = [s for s in all_suppliers if s['supplier_name'] in filter_value]
       
        elif filter_type == "location_based":
            selected_suppliers = [s for s in all_suppliers if s['location'] in filter_value]
       
        else:
            selected_suppliers = all_suppliers
       
        if not selected_suppliers:
            return "No suppliers match your criteria. Please try different filters."
       
        log_info(f"Filtered to {len(selected_suppliers)} suppliers", self.name)
       
        quantity = intent.get('quantity', self.last_quantity)
        delivery_days = intent.get('delivery_days', 14)
       
        rfq_result = self.rfq_generator.execute(
            self.last_item_code,
            self.last_item_name,
            quantity,
            selected_suppliers,
            delivery_days=delivery_days
        )
        if not rfq_result:
            self._reset_state()
            return "RFQ sending failed. Check email configuration."
        self.rfq_sent = True
        self.state = "awaiting_quotes"
        self._persist_context()
        self.communication_agent.send_notification('rfq_sent', {
            'item_name': self.last_item_name,
            'quantity': quantity,
            'suppliers_contacted': rfq_result['suppliers_contacted'],
            'emails_sent': rfq_result['emails_sent'],
            'success_list': rfq_result['success_list'],
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        # Save to sent_rfqs.json
        self._save_sent_rfq(rfq_result, selected_suppliers, quantity, delivery_days)
        sent = "\n".join([f"- {e}" for e in rfq_result['success_list']])
        return f"""RFQs sent successfully
Details:
- Item: {self.last_item_name}
- Quantity: {quantity} units
- Delivery Timeline: {delivery_days} days
- Urgency: {self.last_urgency or 'N/A'}
- Suppliers Contacted: {rfq_result['suppliers_contacted']}
- Emails Sent: {rfq_result['emails_sent']}/{rfq_result['suppliers_contacted']}
Delivered to:
{sent}
Stakeholders have been notified. Once you receive quotes, you can check the inbox or say "analyze quotes" when ready."""

    def _save_pending_rfq(self, intent: dict) -> str:
        """Save RFQ to pending_rfqs.json for later."""
       
        rfq_id = f"{self.last_item_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
       
        pending_rfq = {
            "rfq_id": rfq_id,
            "item_code": self.last_item_code,
            "item_name": self.last_item_name,
            "quantity": intent.get('quantity', self.last_quantity),
            "delivery_days": intent.get('delivery_days', 14),
            "urgency": self.last_urgency or 'N/A',
            "suppliers": self.last_suppliers['suppliers'],
            "status": "pending",
            "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
       
        try:
            if os.path.exists(self.pending_rfqs_file):
                with open(self.pending_rfqs_file, 'r') as f:
                    pending_rfqs = json.load(f)
            else:
                pending_rfqs = {}
        except Exception as e:
            log_error(f"Failed to load pending RFQs: {e}", self.name)
            pending_rfqs = {}
       
        pending_rfqs[rfq_id] = pending_rfq
       
        try:
            os.makedirs('data', exist_ok=True)
            with open(self.pending_rfqs_file, 'w') as f:
                json.dump(pending_rfqs, f, indent=2)
            log_info(f"Saved pending RFQ: {rfq_id}", self.name)
        except Exception as e:
            log_error(f"Failed to save pending RFQ: {e}", self.name)
            return "Failed to save RFQ. Please try again."
       
        item_display_name = self.last_item_name if self.last_item_name else "this item"
       
        self._reset_state()
       
        return f"""RFQ saved to pending list.
You can resume this later by mentioning {item_display_name} again, or ask me to show you all pending orders whenever you're ready."""

    def _show_pending_rfqs(self) -> str:
        """Display all pending RFQs."""
       
        try:
            if not os.path.exists(self.pending_rfqs_file):
                return "No pending RFQs found. All clear!"
           
            with open(self.pending_rfqs_file, 'r') as f:
                pending_rfqs = json.load(f)
           
            if not pending_rfqs:
                return "No pending RFQs found. All clear!"
           
            output = "**Pending RFQs:**\n\n"
            for rfq_id, rfq in pending_rfqs.items():
                output += f"**{rfq['item_name']}**\n"
                output += f"- Quantity: {rfq['quantity']} units\n"
                output += f"- Delivery: {rfq['delivery_days']} days\n"
                output += f"- Urgency: {rfq.get('urgency', 'N/A')}\n"
                output += f"- Suppliers Found: {len(rfq['suppliers'])}\n"
                output += f"- Created: {format_display_date(rfq['created_at'])}\n\n"
           
            output += "To resume any of these, just mention the item name and I'll help you continue."

            # Set state so the next message with an item name routes to resume_rfq
            self.state = "awaiting_rfq_selection"
           
            return output
           
        except Exception as e:
            log_error(f"Failed to show pending RFQs: {e}", self.name)
            return "Error loading pending RFQs."

    def _save_sent_rfq(self, rfq_result: dict, suppliers: list, quantity: int, delivery_days: int):
        """Save sent RFQ to sent_rfqs.json."""
        rfq_id = f"{self.last_item_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        sent_rfq = {
            "rfq_id": rfq_id,
            "item_code": self.last_item_code,
            "item_name": self.last_item_name,
            "quantity": quantity,
            "delivery_days": delivery_days,
            "urgency": self.last_urgency or 'N/A',
            "suppliers_contacted": rfq_result['suppliers_contacted'],
            "emails_sent": rfq_result['emails_sent'],
            "success_list": rfq_result['success_list'],
            "suppliers": [
                {
                    "supplier_name": s.get('supplier_name', s.get('company_name', 'Unknown')),
                    "location": s.get('location', 'Unknown'),
                    "quality_level": s.get('quality_level', 'N/A'),
                    "risk_level": s.get('risk_level', 'N/A'),
                    "rating": s.get('rating', 'N/A')
                }
                for s in suppliers
            ],
            "status": "sent",
            "sent_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        try:
            sent_rfqs = {}
            if os.path.exists(self.sent_rfqs_file):
                with open(self.sent_rfqs_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        sent_rfqs = json.loads(content)
        except Exception as e:
            log_error(f"Failed to load sent RFQs: {e}", self.name)
            sent_rfqs = {}
        
        sent_rfqs[rfq_id] = sent_rfq
        
        try:
            os.makedirs('data', exist_ok=True)
            with open(self.sent_rfqs_file, 'w') as f:
                json.dump(sent_rfqs, f, indent=2)
            log_info(f"Saved sent RFQ: {rfq_id}", self.name)
        except Exception as e:
            log_error(f"Failed to save sent RFQ: {e}", self.name)

    def _show_sent_rfqs(self) -> str:
        """Display all sent RFQs."""
        try:
            if not os.path.exists(self.sent_rfqs_file):
                return "No sent RFQs found yet."
            
            with open(self.sent_rfqs_file, 'r') as f:
                sent_rfqs = json.load(f)
            
            if not sent_rfqs:
                return "No sent RFQs found yet."
            
            output = "**Sent RFQs:**\n\n"
            for rfq_id, rfq in sent_rfqs.items():
                output += f"**{rfq['item_name']}**\n"
                output += f"- Quantity: {rfq['quantity']} units\n"
                output += f"- Delivery: {rfq['delivery_days']} days\n"
                output += f"- Urgency: {rfq.get('urgency', 'N/A')}\n"
                output += f"- Suppliers Contacted: {rfq['suppliers_contacted']}\n"
                output += f"- Emails Sent: {rfq['emails_sent']}\n"
                output += f"- Sent At: {format_display_date(rfq['sent_at'])}\n"
                # List supplier names
                supplier_names = [s['supplier_name'] for s in rfq.get('suppliers', [])]
                if supplier_names:
                    output += f"- Suppliers: {', '.join(supplier_names)}\n"
                output += "\n"
            
            return output
        
        except Exception as e:
            log_error(f"Failed to show sent RFQs: {e}", self.name)
            return "Error loading sent RFQs."

    def _show_all_rfqs(self) -> str:
        """Display all RFQs — sent first, then pending."""
        sent_output = self._show_sent_rfqs()
        pending_output = self._show_pending_rfqs()
        
        # Combine: sent first, then pending
        combined = ""
        
        if "No sent RFQs" not in sent_output:
            combined += sent_output + "\n---\n\n"
        
        if "No pending RFQs" not in pending_output:
            combined += pending_output
        elif combined:
            combined += "No pending RFQs at the moment."
        
        if not combined:
            return "No RFQs found — neither sent nor pending."
        
        return combined

    def _resume_rfq(self, item_identifier: str) -> str:
        """Resume a saved RFQ with fuzzy matching support."""
       
        try:
            if not os.path.exists(self.pending_rfqs_file):
                return "No pending RFQs found to resume."
           
            with open(self.pending_rfqs_file, 'r') as f:
                pending_rfqs = json.load(f)
           
            if not pending_rfqs:
                return "No pending RFQs found. All clear!"
           
            matched_rfq = None
            matched_id = None
           
            id_norm = _normalize(item_identifier)
            id_words = id_norm.replace('rfq', '').replace('order', '').replace('the', '').split()
            id_words = [w for w in id_words if len(w) > 1]

            # Detect pronoun-only input: "this", "that", "it", "first one", "last one"
            pronoun_words = {"this", "that", "it", "one", "resume", "continue", "first", "last"}
            meaningful_words = [w for w in id_words if w not in pronoun_words]
            is_pronoun_only = len(meaningful_words) == 0

            # If pronoun-only and only 1 pending RFQ, auto-select it
            if is_pronoun_only and len(pending_rfqs) == 1:
                rfq_id, rfq = next(iter(pending_rfqs.items()))
                matched_rfq = rfq
                matched_id = rfq_id
            elif is_pronoun_only and len(pending_rfqs) > 1:
                # Pick the most recent one
                most_recent_id = max(pending_rfqs.keys(), key=lambda k: pending_rfqs[k].get('created_at', ''))
                matched_rfq = pending_rfqs[most_recent_id]
                matched_id = most_recent_id

            best_score = 0.0
           
            for rfq_id, rfq in pending_rfqs.items():
                item_name_norm = _normalize(rfq['item_name'])
                item_code_lower = rfq['item_code'].lower()
                created_date = rfq['created_at'].split()[0]
               
                # Exact word match
                if id_words and any(word in item_name_norm for word in id_words):
                    matched_rfq = rfq
                    matched_id = rfq_id
                    break
               
                # Item code match
                if item_code_lower[:4] in id_norm or id_norm in item_code_lower:
                    matched_rfq = rfq
                    matched_id = rfq_id
                    break
               
                # Date match
                if id_norm in created_date.lower():
                    matched_rfq = rfq
                    matched_id = rfq_id
                    break

                # Fuzzy match on item name
                score = _fuzzy_score(id_norm, item_name_norm)
                word_score = _fuzzy_word_score(id_words, item_name_norm.split()) if id_words else 0
                combined = max(score, word_score)
                if combined > best_score and combined >= 0.55:
                    best_score = combined
                    matched_rfq = rfq
                    matched_id = rfq_id
           
            if not matched_rfq:
                return f"I couldn't find a pending RFQ matching '{item_identifier}'. Would you like to see all pending orders?"
           
            self.last_item_code = matched_rfq['item_code']
            self.last_item_name = matched_rfq['item_name']
            self.last_quantity = matched_rfq['quantity']
            self.last_suppliers = {'suppliers': matched_rfq['suppliers']}
            self.state = "awaiting_rfq_approval"
           
            suppliers_text = self.supplier_finder.format_supplier_info(matched_rfq['suppliers'])
           
            return f"""Resumed pending RFQ for {matched_rfq['item_name']}
Supplier Options:
{suppliers_text}
Ready to send RFQs for {matched_rfq['quantity']} units with {matched_rfq['delivery_days']}-day delivery.
Would you like to proceed, modify the specifications, or save it for later?"""
           
        except Exception as e:
            log_error(f"Failed to resume RFQ: {e}", self.name)
            return "Error resuming RFQ."

    def _handle_quote_submission(self, user_input: str) -> str:
        """Handle both manual quote pasting and automated quote reception."""
        lower = user_input.lower()

        if any(keyword in lower for keyword in ["received quote", "got quote", "i got a", "quotation for", "quote from supplier"]):
            log_info("User mentioned received quotes, checking inbox...", self.name)

            inbox_result = self.decision_agent.check_and_parse_quotes(self.last_item_code if self.last_item_code else None)

            if inbox_result['quotes_found'] > 0:
                parsed_count = len(inbox_result['parsed_quotes'])

                # Auto-notify stakeholders via Agent 7
                for quote in inbox_result['parsed_quotes']:
                    self.communication_agent.send_notification('quote_received', {
                        'item_name': quote.get('item_name', self.last_item_name),
                        'supplier_name': quote['supplier_name'],
                        'unit_price': quote['unit_price'],
                        'delivery_days': quote['delivery_days'],
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    })

                # Generate email summary
                summary_text = "\n\n".join([
                    f"From: {email['from']}\nSummary: {email['summary']}"
                    for email in inbox_result['emails_summary']
                ])

                # Set state to quotes_collected when quotes are found
                self.state = "quotes_collected"

                return f"""Found {inbox_result['quotes_found']} new quote email(s) from suppliers:

{summary_text}
Successfully parsed {parsed_count} quote(s). Stakeholders have been notified.
Say "analyze quotes" when ready to compare all quotes."""
            else:
                self.state = "awaiting_quotes"
                return """No new quotes found in inbox. Please paste the quote details here, and I'll process them.
Say "analyze quotes" when you've finished."""

        # Parse manual quote and normalize to standard format
        parsed_manual_quote = self._parse_manual_quote(user_input)
        if parsed_manual_quote:
            self.collected_quotes.append(parsed_manual_quote)
            self.state = "quotes_collected"
            self._persist_context()
            return f"Quote {len(self.collected_quotes)} received. Paste next or say 'analyze quotes'."
        else:
            return "I couldn't parse that quote. Please include supplier name, unit price, and delivery days."

    def _parse_manual_quote(self, quote_text: str) -> dict:
        """Parse manually pasted quote into standardized dict format."""
        try:
            prompt = f"""Parse this quote text into structured JSON format.
Quote text: "{quote_text}"
Extract and return ONLY a JSON object with these fields: {{ "supplier_name": "extracted supplier name", "unit_price": numeric value only (no currency symbol), "delivery_days": numeric days, "payment_terms": "extracted payment terms or 'Not specified'", "quality_certs": "extracted certifications or 'None'", "item_name": "item name if mentioned, otherwise null", "quantity": numeric quantity if mentioned, otherwise null }}
If information is missing, use null for optional fields, 'Not specified' for payment_terms, 'None' for quality_certs. Return ONLY the JSON object."""

            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["reasoning"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=200
            )

            result_text = response.choices[0].message.content.strip()
            if result_text.startswith('```json'):
                result_text = result_text.replace('```json', '').replace('```', '').strip()

            parsed = json.loads(result_text)

            # Validate required fields
            if parsed.get('supplier_name') and parsed.get('unit_price') and parsed.get('delivery_days'):
                # Add missing fields with defaults to match Agent 6 format
                parsed['risk_score'] = 0  # Default risk score
                parsed['contact_email'] = 'manual_entry'  # Mark as manually entered

                # Ensure quality_certs and payment_terms have values
                if not parsed.get('quality_certs'):
                    parsed['quality_certs'] = 'None'
                if not parsed.get('payment_terms'):
                    parsed['payment_terms'] = 'Not specified'

                return parsed
            else:
                return None

        except Exception as e:
            log_error(f"Failed to parse manual quote: {e}", self.name)
            return None

    def _handle_analyze_quotes(self) -> str:
        """Analyze all collected quotes from inbox or manual entry."""

        # Try to recover context from sent_rfqs if missing
        if not self.last_item_code or not self.last_item_name:
            try:
                if os.path.exists(self.sent_rfqs_file):
                    with open(self.sent_rfqs_file, 'r') as f:
                        sent_rfqs = json.load(f)
                    if sent_rfqs:
                        most_recent_id = max(sent_rfqs.keys(), key=lambda k: sent_rfqs[k].get('sent_at', ''))
                        most_recent = sent_rfqs[most_recent_id]
                        self.last_item_code = most_recent.get('item_code')
                        self.last_item_name = most_recent.get('item_name')
                        self.last_quantity = most_recent.get('quantity')
                        log_info(f"Recovered context from sent RFQs: {self.last_item_code} - {self.last_item_name}", self.name)
            except Exception as e:
                log_error(f"Failed to recover context from sent RFQs: {e}", self.name)

        # Also try to recover from quotes_collected.json
        if not self.last_item_code or not self.last_item_name:
            try:
                quotes_file = self.get_data_path('quotes_collected.json')
                if os.path.exists(quotes_file):
                    with open(quotes_file, 'r') as f:
                        quotes_data = json.load(f)
                    if quotes_data:
                        first_supplier = next(iter(quotes_data.values()))
                        if first_supplier.get('quotes'):
                            first_quote = first_supplier['quotes'][0]
                            self.last_item_code = first_quote.get('item_code', 'UNKNOWN')
                            self.last_item_name = first_quote.get('item_name', 'Unknown Item')
                            self.last_quantity = first_quote.get('quantity', 0)
                            log_info(f"Recovered context from quotes: {self.last_item_code} - {self.last_item_name}", self.name)
            except Exception as e:
                log_error(f"Failed to recover context from quotes: {e}", self.name)

        if not self.last_item_code or not self.last_item_name:
            return "I don't have context for which item we're analyzing quotes for. Could you check the item status first?"

        log_info("Analyzing all collected quotes...", self.name)

        # Load quotes from quotes_collected.json
        quotes_file = self.get_data_path('quotes_collected.json')

        all_quotes = []

        # Try to load from file first
        if os.path.exists(quotes_file):
            with open(quotes_file, 'r') as f:
                quotes_data = json.load(f)

            # Extract all quotes
            for supplier_email, supplier_data in quotes_data.items():
                parent_name = supplier_data.get('supplier_name', 'Unknown')
                for quote in supplier_data['quotes']:
                    quote['contact_email'] = supplier_email
                    # Always use parent supplier_name (derived from email key)
                    quote['supplier_name'] = parent_name
                    # Add backward compatibility for quality_score/risk_score
                    if 'risk_score' not in quote and 'quality_score' in quote:
                        quote['risk_score'] = quote['quality_score']
                    elif 'risk_score' not in quote:
                        quote['risk_score'] = 0
                    all_quotes.append(quote)

        # Add manually collected quotes
        if self.collected_quotes:
            all_quotes.extend(self.collected_quotes)

        # Deduplicate quotes
        all_quotes = self._deduplicate_quotes(all_quotes)

        if not all_quotes:
            return "No quotes available to analyze. Check inbox first or paste quotes manually."

        return self._analyze_quotes_internal(all_quotes)

    def _deduplicate_quotes(self, quotes: list) -> list:
        """Remove duplicate quotes based on supplier name, unit price, and delivery days."""
        seen = set()
        unique_quotes = []

        for quote in quotes:
            supplier = quote.get('supplier_name', '').lower().strip()
            price = quote.get('unit_price', 0)
            delivery = quote.get('delivery_days', 0)

            # Create unique key with supplier, price, AND delivery
            key = f"{supplier}_{price}_{delivery}"

            if key not in seen:
                seen.add(key)
                unique_quotes.append(quote)
            else:
                log_info(f"Removed duplicate quote: {supplier} @ Rs.{price} ({delivery} days)", self.name)

        return unique_quotes

    def _analyze_quotes_internal(self, quote_data_list) -> str:
        """Internal method to analyze quotes."""
        log_info("Running quote analysis...", self.name)

        category = self._get_item_category(self.last_item_code)

        result = self.decision_agent.execute(
            quote_data_list,
            self.last_item_code,
            self.last_item_name,
            self.last_quantity
        )

        self.collected_quotes = []

        if not result or result.get('error'):
            self._reset_state()
            return f"Quote analysis failed: {result.get('error', 'Unknown error')}"

        rec = result

        summary = ""
        for i, q in enumerate(rec['comparison_table'], start=1):
            summary += f"""
{i}. {q['supplier_name']}
   Unit: Rs.{q['unit_price']}
   Total: Rs.{q['total_cost']:,.0f}
   Delivery: {q['delivery_days']} days
   Terms: {q['payment_terms']}"""

        base_message = f"""Quote Comparison Complete

Item: {rec['po_data']['item_name']}
Quantity: {rec['po_data']['quantity']} units

Budget Check:
- Budget Limit: Rs.{50000:,.0f}
- Total Cost: Rs.{rec['po_data']['total_cost']:,.0f}
- Status: {rec['budget_status']}

Supplier Quotes:{summary}

RECOMMENDATION:
Supplier: {rec['selected_supplier']}
Total Cost: Rs.{rec['po_data']['total_cost']:,.0f}

Reasoning:
{rec['po_data']['justification']} """

        if rec.get('needs_user_approval'):
            self.pending_po_data = rec['po_data']
            self.state = "awaiting_po_approval"

            approval_question = self._generate_po_approval_question(
                rec['po_data']['item_name'],
                rec['selected_supplier'],
                rec['po_data']['total_cost'],
                rec['po_data']['delivery_days']
            )

            return f"{base_message}\n{approval_question}"
        else:
            self.decision_agent.approve_purchase_order(rec['po_data'], approved=True)

            self.communication_agent.send_notification('po_approved', {
                'po_number': rec['po_data']['po_number'],
                'item_name': rec['po_data']['item_name'],
                'supplier_name': rec['selected_supplier'],
                'quantity': rec['po_data']['quantity'],
                'total_cost': rec['po_data']['total_cost'],
                'expected_delivery_date': rec['po_data']['expected_delivery_date']
            })

            self._reset_state()
            return f"{base_message}\nPurchase order auto-approved and saved. Stakeholders have been notified."

    def _handle_notification_query(self, user_input: str) -> str:
        """Handle user queries about sent notifications"""
        log_info("Retrieving notification history", self.name)

        history = self.communication_agent.get_notification_history(limit=10)

        if not history:
            return "No notifications have been sent yet."

        output = "**Recent Notifications:**\n\n"
        for idx, notif in enumerate(history, 1):
            output += f"{idx}. Event: {notif['event_type']}\n"
            output += f"   Sent at: {format_display_date(notif['sent_at'])}\n"
            output += f"   Status: {notif['status']}\n"
            output += f"   Recipients: {', '.join(notif['recipients'])}\n\n"

        return output

    def _handle_inbox_check(self, user_input: str) -> str:
        """Handle user requests to check inbox or get email summary"""
        log_info("Checking inbox for supplier emails", self.name)

        lower = user_input.lower()

        if any(keyword in lower for keyword in ["summarize", "summary"]):
            summary = self.communication_agent.summarize_supplier_emails(days=7)
            return summary
        else:
            quote_result = self.decision_agent.check_and_parse_quotes(None)
            update_result = self.communication_agent.check_inbox_for_updates(None)

            is_cached = quote_result.get('status') == 'from_cache'
            total_emails = quote_result['quotes_found'] + update_result['new_emails_count']

            if total_emails == 0:
                return "No new supplier emails found in inbox."

            parsed_count = len(quote_result['parsed_quotes'])

            if is_cached:
                output = f"Found {parsed_count} previously received quote(s) from suppliers.\n\n"
            else:
                output = f"Found {total_emails} new email(s) from suppliers.\n\n"
                output += f"- Quote emails: {quote_result['quotes_found']}\n"
                output += f"- Update emails: {update_result['new_emails_count']}\n"

            if quote_result['quotes_found'] > 0:
                output += f"\n**Parsed {parsed_count} quote(s):**\n"

                for quote in quote_result['parsed_quotes']:
                    supplier = quote.get('supplier_name', 'Unknown')
                    price = quote.get('unit_price', 'N/A')
                    delivery = quote.get('delivery_days', 'N/A')
                    item = quote.get('item_name', self.last_item_name or 'Item')
                    output += f"\n**{supplier}**\n"
                    output += f"  Item: {item}\n"
                    output += f"  Unit Price: Rs.{price}\n"
                    output += f"  Delivery: {delivery} days\n"

                    if not is_cached:
                        self.communication_agent.send_notification('quote_received', {
                            'item_name': item,
                            'supplier_name': supplier,
                            'unit_price': price,
                            'delivery_days': delivery,
                            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        })

                if not is_cached:
                    output += f"\nStakeholders have been notified about all {parsed_count} supplier quote(s)."
                self.state = "quotes_collected"
                self._persist_context()

            if update_result['new_emails_count'] > 0:
                output += "\n\n**Update emails:**\n"
                for email_data in update_result['emails']:
                    output += f"- From: {email_data['from']} — {email_data.get('summary', email_data['subject'])}\n"

            return output

    def _generate_po_approval_question(self, item_name, supplier_name, total_cost, delivery_days):
        """Generate varied PO approval question using LLM"""
        try:
            prompt = f"""Generate a natural, conversational question asking for purchase order approval.

Item: {item_name}
Supplier: {supplier_name}
Total Cost: Rs.{total_cost:,.2f}
Delivery: {delivery_days} days

Requirements:
- Keep it under 30 words
- Sound natural and varied
- Include key details (supplier, cost)
- Ask for yes/no approval
- No markdown, no quotes
- Direct question only

Generate ONLY the question text."""

            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["quick"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=100
            )

            question = response.choices[0].message.content.strip()
            question = question.replace('*', '').replace('`', '').replace('"', '').replace("'", "")
            return question

        except Exception as e:
            log_error(f"Error generating approval question: {e}", self.name)
            return f"Approve purchase order for {item_name} from {supplier_name} at Rs.{total_cost:,.2f}? (yes/no)"

    def _handle_po_approval(self, intent: dict) -> str:
        """Handle PO approval/rejection"""
        if not self.pending_po_data:
            return "No pending purchase order to approve."

        if intent.get('response') == 'yes':
            self.decision_agent.approve_purchase_order(self.pending_po_data, approved=True)

            self.communication_agent.send_notification('po_approved', {
                'po_number': self.pending_po_data['po_number'],
                'item_name': self.pending_po_data['item_name'],
                'supplier_name': self.pending_po_data['supplier_name'],
                'quantity': self.pending_po_data['quantity'],
                'total_cost': self.pending_po_data['total_cost'],
                'expected_delivery_date': self.pending_po_data['expected_delivery_date']
            })

            po_number = self.pending_po_data['po_number']
            self.pending_po_data = None
            self._reset_state()
            return f"Purchase Order {po_number} approved and saved successfully! Stakeholders have been notified."
        else:
            self.decision_agent.approve_purchase_order(self.pending_po_data, approved=False)
            po_number = self.pending_po_data['po_number']
            self.pending_po_data = None
            self._reset_state()
            return f"Purchase Order {po_number} rejected and logged."

    def _handle_acknowledgment(self, user_input: str = "") -> str:
        """Handle casual conversation and fallback with contextual LLM response."""
        try:
            history_text = ""
            if self.conversation_history:
                recent = self.conversation_history[-6:]
                history_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in recent)

            capabilities = (
                "checking inventory status, finding suppliers, sending RFQs, "
                "checking inbox for quotes, analyzing quotes, generating purchase orders, "
                "viewing pending/sent RFQs, and viewing notification history"
            )

            system_msg = (
                f"You are {APP_NAME}, a smart procurement assistant for a manufacturing company. "
                f"Your capabilities include: {capabilities}. "
                "When the user sends a casual, unclear, or conversational message, respond warmly and helpfully. "
                "If they seem to want help but are vague, suggest 1-2 specific actions they can take. "
                "Keep responses to 1-3 sentences. Do not use emojis. "
                "Never repeat the exact same response as before. Be natural and varied."
            )

            user_msg = ""
            if history_text:
                user_msg += f"Recent conversation:\n{history_text}\n\n"
            user_msg += f"Current state: {self.state}\n"
            if self.last_item_name:
                user_msg += f"Last discussed item: {self.last_item_name}\n"
            user_msg += f"User says: {user_input}"

            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["quick"],
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.85,
                max_tokens=150
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            log_error(f"Chat conversation error: {e}", self.name)
            return "I'm here to help with procurement tasks. You can check inventory, find suppliers, or manage RFQs."

    # ==================================================================
    #  SMART PILLS SYSTEM
    # ==================================================================

    def _get_smart_pills(self) -> list:
        """Generate 3 smart follow-up pills based on current state and context.
        Returns [relevant_1, relevant_2, flow_switch].
        """
        item = self.last_item_name

        if self.state == "awaiting_supplier_approval" and item:
            return [
                f"Yes, find suppliers for {item}",
                "No, not right now",
                "Check the inventory",
            ]

        if self.state == "awaiting_rfq_approval" and item:
            return [
                "Send RFQs to all suppliers",
                "Save this RFQ for later",
                "Check a different item",
            ]

        if self.state == "awaiting_rfq_selection":
            # Try to get item names from pending RFQs for the first pill
            first_rfq_name = None
            try:
                if os.path.exists(self.pending_rfqs_file):
                    with open(self.pending_rfqs_file, 'r') as f:
                        rfqs = json.load(f)
                    if rfqs:
                        first_rfq = next(iter(rfqs.values()))
                        first_rfq_name = first_rfq.get('item_name')
            except Exception:
                pass
            if first_rfq_name:
                return [
                    f"Resume {first_rfq_name}",
                    "Show pending RFQs",
                    "Check the inventory",
                ]
            return [
                "Resume this RFQ",
                "Show pending RFQs",
                "Check the inventory",
            ]

        if self.state == "awaiting_quotes":
            return [
                "Check inbox for quotes",
                "Analyze quotes",
                "Show pending RFQs",
            ]

        if self.state == "quotes_collected":
            return [
                "Analyze quotes",
                "Check inbox for more quotes",
                "Show pending RFQs",
            ]

        if self.state == "awaiting_po_approval":
            return [
                "Yes, approve",
                "No, reject",
                "Check the inventory",
            ]

        # idle / default - provide general actions
        if item:
            return [
                f"Find suppliers for {item}",
                "Check the inventory",
                "Show pending RFQs",
            ]

        return [
            "Check the inventory",
            "Show pending RFQs",
            "Help",
        ]

    def _attach_pills(self, response: str) -> str:
        """Attach smart pills to any response that doesn't already have them."""
        if '===' in response:
            return response  # pills already present
        pills = self._get_smart_pills()
        pills_text = "\n".join(pills)
        return f"{response}\n\n===\n{pills_text}"

    def _show_help(self) -> str:
        """Display help message"""
        return """I'm your Procurement Assistant! Here's what I can do:

Full Inventory Scan:
 Say "check the inventory" and I'll scan all items and tell you what needs procurement

Check Specific Item Status:
 Ask about any item naturally - I'll analyze if we need to order it

Find Suppliers:
 Ask me to find suppliers for any item and I'll search for the best options

Send RFQs:
 I can send professional RFQ emails to suppliers based on your preferences

Manage Pending Orders:
 Save RFQs for later and resume them whenever you're ready

Compare Quotes & Generate POs:
 Share supplier quotes with me and I'll analyze and recommend the best option

Check Inbox:
 I automatically monitor supplier emails and can check for new quotes anytime

View Notifications:
 Ask me what notifications I've sent to keep track of communications

Just talk naturally - I understand conversational language and will figure out what you need!"""



    def _persist_context(self):
        """Save current item context to disk so it survives page refreshes."""
        try:
            context_data = {
                'last_item_code': self.last_item_code,
                'last_item_name': self.last_item_name,
                'last_quantity': self.last_quantity,
                'last_urgency': self.last_urgency,
                'state': self.state,
                'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            os.makedirs(os.path.dirname(self.context_file), exist_ok=True)
            with open(self.context_file, 'w') as f:
                json.dump(context_data, f, indent=2)
        except Exception:
            pass

    def _restore_context(self):
        """Restore item context from disk on init."""
        try:
            if os.path.exists(self.context_file):
                with open(self.context_file, 'r') as f:
                    ctx = json.load(f)
                if ctx.get('last_item_code'):
                    self.last_item_code = ctx['last_item_code']
                    self.last_item_name = ctx.get('last_item_name')
                    self.last_quantity = ctx.get('last_quantity')
                    self.last_urgency = ctx.get('last_urgency')
                    saved_state = ctx.get('state', 'idle')
                    if saved_state != 'idle':
                        self.state = saved_state
                    log_info(f"Restored context: {self.last_item_code} - {self.last_item_name} (state: {self.state})", self.name)
        except Exception:
            pass

    def _reset_state(self):
        """Reset conversation state for new flow."""
        self.state = "idle"
        self.last_item_code = None
        self.last_item_name = None
        self.last_quantity = None
        self.last_urgency = None
        self.last_suppliers = None
        self.rfq_sent = False
        self.collected_quotes = []
        self.pending_po_data = None
        self._persist_context()
        log_info("State reset", self.name)

    def _extract_item(self, text: str):
        """Extract item code using multi-strategy matching: exact → normalized → fuzzy → LLM."""
        try:
            inventory_df = self.load_csv('current_inventory.csv')
            if inventory_df.empty:
                return None

            text_norm = _normalize(text)
            text_words = text_norm.split()

            code_match = re.search(r'itm\s*0*(\d+)', text_norm)
            if code_match:
                candidate = f"ITM{int(code_match.group(1)):03d}"
                if candidate in inventory_df['item_code'].values:
                    return candidate

            for alias, canonical in ITEM_ALIASES.items():
                if alias in text_norm:
                    for _, row in inventory_df.iterrows():
                        if _normalize(row['item_name']) == _normalize(canonical):
                            return row['item_code']
                        if _normalize(canonical) in _normalize(row['item_name']):
                            return row['item_code']

            for _, row in inventory_df.iterrows():
                item_norm = _normalize(row['item_name'])
                if item_norm in text_norm or text_norm in item_norm:
                    return row['item_code']

            for _, row in inventory_df.iterrows():
                item_norm = _normalize(row['item_name'])
                item_words = item_norm.split()
                if any(w in text_norm for w in item_words if len(w) > 3):
                    return row['item_code']

            best_code = None
            best_score = 0.0

            for _, row in inventory_df.iterrows():
                item_norm = _normalize(row['item_name'])
                item_words = item_norm.split()

                full_score = _fuzzy_score(text_norm, item_norm)

                word_score = _fuzzy_word_score(text_words, item_words)

                per_word_best = 0.0
                for tw in text_words:
                    if len(tw) > 2:
                        for iw in item_words:
                            s = _fuzzy_score(tw, iw)
                            if s > per_word_best:
                                per_word_best = s

                score = max(full_score, word_score, per_word_best * 0.85)

                if score > best_score:
                    best_score = score
                    best_code = row['item_code']

            if best_score >= 0.60 and best_code:
                log_info(f"Fuzzy matched '{text}' → {best_code} (score={best_score:.2f})", self.name)
                return best_code

            return self._llm_extract_item(text, inventory_df)

        except Exception as e:
            log_error(f"Failed to extract item: {e}", self.name)
            return None

    def _llm_extract_item(self, text: str, inventory_df) -> str | None:
        """Use LLM as final fallback to match user text to an inventory item."""
        try:
            items_list = "\n".join(
                f"- {row['item_code']}: {row['item_name']}"
                for _, row in inventory_df.iterrows()
            )
            prompt = f"""Given the user's message and the inventory list below, identify which inventory item the user is referring to.
If the user misspelled the item name, use your best judgement to find the closest match.
If no item matches at all, return "NONE".

User message: "{text}"

Inventory:
{items_list}

Return ONLY the item_code (e.g. ITM001) or "NONE". No explanation."""
            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["quick"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=20
            )
            result = response.choices[0].message.content.strip().upper()
            if result.startswith("ITM") and result in inventory_df['item_code'].values:
                log_info(f"LLM fallback matched '{text}' → {result}", self.name)
                return result
            return None
        except Exception as e:
            log_error(f"LLM item extraction failed: {e}", self.name)
            return None

    def _get_item_category(self, item_code: str) -> str:
        """Get item category from inventory CSV"""
        try:
            inventory_df = self.load_csv('current_inventory.csv')
           
            row = inventory_df[inventory_df['item_code'] == item_code]
            if not row.empty:
                item_name = row.iloc[0]['item_name'].lower()
               
                if any(word in item_name for word in ['screw', 'bolt', 'nut', 'fastener']):
                    return 'Fasteners & Hardware'
                elif any(word in item_name for word in ['plate', 'sheet', 'metal', 'steel', 'aluminum']):
                    return 'Raw Materials'
                elif any(word in item_name for word in ['oil', 'grease', 'lubricant', 'fluid']):
                    return 'Industrial Fluids'
                elif any(word in item_name for word in ['bearing', 'valve', 'motor']):
                    return 'Machinery Parts'
                else:
                    return 'General Supplies'
           
            return 'General Supplies'
        except Exception as e:
            log_error(f"Failed to get category: {e}", self.name)
            return 'General Supplies'


if __name__ == "__main__":
    print("Testing Agent 0 - Master Orchestrator")

    orchestrator = MasterOrchestrator()

    print("\n--- Conversation Simulation ---\n")

    print("User: check M8 screws")
    response1 = orchestrator.process_request("check M8 screws")
    print(f"\nAssistant: {response1}\n")

    print("User: i got quotes")
    response2 = orchestrator.process_request("i got quotes")
    print(f"\nAssistant: {response2}\n")

    print("User: analyze quotes")
    response3 = orchestrator.process_request("analyze quotes")
    print(f"\nAssistant: {response3}\n")

    print("\nAgent 0 test complete")
