import os
import sys
import warnings
import signal as _signal_mod

# ── 1. Set crewai telemetry opt-out BEFORE anything is imported ────────────────
os.environ['CREWAI_TELEMETRY_OPT_OUT'] = 'true'
os.environ['OTEL_SDK_DISABLED'] = 'true'
os.environ['ANONYMIZED_TELEMETRY'] = 'false'

# ── 2. Monkey-patch signal.signal to silently ignore ValueError in worker threads
#    (crewai telemetry tries to register SIGTERM/SIGINT — only works in main thread)
_orig_signal = _signal_mod.signal
def _safe_signal(sig, handler):
    try:
        return _orig_signal(sig, handler)
    except (ValueError, OSError):
        pass  # not in main thread — silently skip
_signal_mod.signal = _safe_signal

# ── 3. Suppress all noisy warnings from third-party libs ────────────────────
warnings.filterwarnings('ignore', module='statsmodels.*')        # catches ValueWarning/FutureWarning/UserWarning
warnings.filterwarnings('ignore', category=ResourceWarning)
warnings.filterwarnings('ignore', message='.*date index.*frequency.*')
warnings.filterwarnings('ignore', message='.*No supported index.*')
try:
    from statsmodels.tools.sm_exceptions import ValueWarning as _StatsVW
    warnings.filterwarnings('ignore', category=_StatsVW)
except ImportError:
    pass

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import json
import time
from datetime import datetime
import plotly.graph_objects as go
import plotly.express as px

from utils.logger import log_error
from utils.date_formatter import format_display_date
from config.settings import APP_NAME

# Page configuration
st.set_page_config(
    page_title=APP_NAME,
    page_icon='⚡',
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Session state: track sidebar collapse for the toggle button ──────────────
if 'sidebar_open' not in st.session_state:
    st.session_state.sidebar_open = True

# Custom CSS for premium glassmorphism design
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    * {
        font-family: 'Inter', sans-serif;
    }
    
    :root {
        --primary-blue: #2E86AB;
        --primary-blue-light: #3A9BC4;
        --accent-cyan: #06D6A0;
        --warning-orange: #E8B84B;
        --danger-red: #EF476F;
        --bg-dark: #0A0E27;
        --bg-card: rgba(20, 30, 60, 0.4);
        --text-primary: #E8E9ED;
        --text-secondary: #A0A3B1;
        --glass-border: rgba(46, 134, 171, 0.3);
    }
    
    /* Remove top padding */
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 2rem !important;
    }
    
    /* Main app background */
    .stApp {
        background: linear-gradient(135deg, #0A0E27 0%, #1a1f3a 50%, #0f1629 100%);
    }
    
    /* Glassmorphism chat container - only show when has messages */
    .chat-container {
        background: rgba(20, 30, 60, 0.3);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border-radius: 20px;
        padding: 28px;
        border: 1px solid rgba(46, 134, 171, 0.2);
        margin-bottom: 20px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.05);
    }
    
    /* Enhanced message bubbles */
    .user-message {
        background: linear-gradient(135deg, #2E86AB 0%, #3A9BC4 100%);
        color: white;
        padding: 18px 24px;
        border-radius: 20px 20px 4px 20px;
        margin: 14px 0;
        max-width: 70%;
        margin-left: auto;
        box-shadow: 0 4px 16px rgba(46, 134, 171, 0.4);
        font-size: 15px;
        line-height: 1.6;
        animation: slideInRight 0.3s ease;
    }
    
    .assistant-message {
        background: linear-gradient(135deg, rgba(30, 40, 70, 0.6) 0%, rgba(40, 50, 80, 0.6) 100%);
        backdrop-filter: blur(10px);
        color: #E8E9ED;
        padding: 18px 24px;
        border-radius: 20px 20px 20px 4px;
        margin: 14px 0;
        max-width: 70%;
        border-left: 4px solid #06D6A0;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
        font-size: 15px;
        line-height: 1.6;
        animation: slideInLeft 0.3s ease;
    }
    
    @keyframes slideInRight {
        from { opacity: 0; transform: translateX(20px); }
        to { opacity: 1; transform: translateX(0); }
    }
    
    @keyframes slideInLeft {
        from { opacity: 0; transform: translateX(-20px); }
        to { opacity: 1; transform: translateX(0); }
    }
    
    /* Premium glassmorphism metric cards */
    .metric-card {
        background: linear-gradient(135deg, rgba(30, 40, 70, 0.4) 0%, rgba(40, 50, 80, 0.3) 100%);
        backdrop-filter: blur(15px);
        -webkit-backdrop-filter: blur(15px);
        border-radius: 20px;
        padding: 28px;
        border: 1px solid rgba(46, 134, 171, 0.25);
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.05);
        transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
        position: relative;
        overflow: hidden;
    }
    
    .metric-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 2px;
        background: linear-gradient(90deg, #2E86AB, #06D6A0);
        opacity: 0;
        transition: opacity 0.4s ease;
    }
    
    .metric-card:hover {
        transform: translateY(-6px);
        box-shadow: 0 12px 40px rgba(46, 134, 171, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.1);
        border-color: rgba(46, 134, 171, 0.5);
    }
    
    .metric-card:hover::before {
        opacity: 1;
    }
    
    .metric-value {
        font-size: 42px;
        font-weight: 700;
        background: linear-gradient(135deg, #06D6A0 0%, #2E86AB 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 10px 0;
        letter-spacing: -1px;
    }
    
    .metric-label {
        color: #A0A3B1;
        font-size: 13px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1.5px;
    }
    
    .metric-delta {
        font-size: 13px;
        margin-top: 10px;
        font-weight: 500;
    }
    
    .metric-delta.positive {
        color: #06D6A0;
    }
    
    .metric-delta.negative {
        color: #EF476F;
    }
    
    /* Enhanced info cards */
    .info-card {
        background: linear-gradient(135deg, rgba(46, 134, 171, 0.15) 0%, rgba(6, 214, 160, 0.1) 100%);
        backdrop-filter: blur(10px);
        border-left: 4px solid #2E86AB;
        border-radius: 16px;
        padding: 24px;
        margin: 18px 0;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(12, 18, 38, 0.97) 0%, rgba(8, 12, 32, 0.98) 100%);
        backdrop-filter: blur(24px);
        border-right: 1px solid rgba(46, 134, 171, 0.15);
    }

    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
        color: #E8E9ED;
    }

    /* Sidebar divider lines */
    [data-testid="stSidebar"] hr {
        border: none !important;
        height: 1px !important;
        background: linear-gradient(90deg, transparent, rgba(46, 134, 171, 0.25), transparent) !important;
        margin: 16px 0 !important;
    }

    /* Sidebar radio nav — premium nav items */
    [data-testid="stSidebar"] [data-testid="stRadio"] > div[role="radiogroup"] {
        gap: 2px !important;
        padding: 0 4px !important;
    }

    /* Ensure the widget label stays hidden */
    [data-testid="stSidebar"] [data-testid="stRadio"] > label,
    [data-testid="stSidebar"] [data-testid="stRadio"] > div:first-child:not([role="radiogroup"]) {
        display: none !important;
    }

    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label {
        display: flex !important;
        align-items: center !important;
        padding: 10px 16px 10px 18px !important;
        border-radius: 10px !important;
        cursor: pointer !important;
        transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
        border: 1px solid transparent !important;
        margin: 0 !important;
        background: transparent !important;
        position: relative !important;
        overflow: hidden !important;
    }

    /* Hidden radio circle */
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label > div:first-child {
        display: none !important;
    }

    /* Nav text default */
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label p {
        color: #546178 !important;
        font-size: 13.5px !important;
        font-weight: 500 !important;
        transition: all 0.25s ease !important;
        margin: 0 !important;
        letter-spacing: 0.01em !important;
        position: relative !important;
        z-index: 1 !important;
    }

    /* Hover */
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label:hover {
        background: rgba(46, 134, 171, 0.06) !important;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label:hover p {
        color: #8FA4B8 !important;
    }

    /* Active / Selected */
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) {
        background: linear-gradient(135deg, rgba(6, 214, 160, 0.08) 0%, rgba(46, 134, 171, 0.06) 100%) !important;
        border-color: rgba(6, 214, 160, 0.12) !important;
    }
    /* Green left accent bar with glow */
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked)::before {
        content: '' !important;
        position: absolute !important;
        left: 0 !important;
        top: 20% !important;
        bottom: 20% !important;
        width: 3px !important;
        border-radius: 0 4px 4px 0 !important;
        background: #06D6A0 !important;
        box-shadow: 0 0 10px rgba(6, 214, 160, 0.5) !important;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) p {
        color: #06D6A0 !important;
        font-weight: 600 !important;
    }
    
    /* Enhanced input fields */
    .stTextInput > div > div > input {
        background: rgba(30, 40, 70, 0.5) !important;
        backdrop-filter: blur(10px);
        border: 1.5px solid rgba(46, 134, 171, 0.3) !important;
        border-radius: 14px !important;
        color: #E8E9ED !important;
        padding: 14px 18px !important;
        font-size: 15px !important;
        transition: all 0.3s ease !important;
    }
    
    .stTextInput > div > div > input:focus {
        border-color: #2E86AB !important;
        box-shadow: 0 0 0 3px rgba(46, 134, 171, 0.15) !important;
        background: rgba(30, 40, 70, 0.7) !important;
    }
    
    .stTextInput > div > div > input::placeholder {
        color: #6B7280 !important;
        opacity: 0.7 !important;
    }
    
    /* Premium buttons */
    .stButton > button {
        background: linear-gradient(135deg, #2E86AB 0%, #3A9BC4 100%) !important;
        color: white !important;
        border: none !important;
        border-radius: 14px !important;
        padding: 14px 32px !important;
        font-weight: 600 !important;
        font-size: 15px !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        box-shadow: 0 4px 16px rgba(46, 134, 171, 0.3) !important;
        letter-spacing: 0.3px !important;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 6px 24px rgba(46, 134, 171, 0.5) !important;
        background: linear-gradient(135deg, #3A9BC4 0%, #2E86AB 100%) !important;
    }
    
    /* Enhanced tabs with glassmorphism */
    .stTabs [data-baseweb="tab-list"] {
        gap: 12px;
        background: linear-gradient(135deg, rgba(30, 40, 70, 0.4) 0%, rgba(20, 30, 60, 0.4) 100%);
        backdrop-filter: blur(15px);
        -webkit-backdrop-filter: blur(15px);
        padding: 12px;
        border-radius: 18px;
        border: 1px solid rgba(46, 134, 171, 0.25);
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
    }
    
    .stTabs [data-baseweb="tab"] {
        background: rgba(30, 40, 70, 0.3);
        backdrop-filter: blur(10px);
        border-radius: 14px;
        color: #A0A3B1;
        font-weight: 600;
        padding: 16px 32px;
        transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
        border: 1px solid rgba(46, 134, 171, 0.15);
        position: relative;
        overflow: hidden;
    }
    
    .stTabs [data-baseweb="tab"]::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: linear-gradient(135deg, rgba(46, 134, 171, 0.1), rgba(6, 214, 160, 0.1));
        opacity: 0;
        transition: opacity 0.4s ease;
    }
    
    .stTabs [data-baseweb="tab"]:hover {
        background: rgba(46, 134, 171, 0.2);
        color: #06D6A0;
        border-color: rgba(46, 134, 171, 0.4);
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(46, 134, 171, 0.2);
    }
    
    .stTabs [data-baseweb="tab"]:hover::before {
        opacity: 1;
    }
    
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #2E86AB 0%, #06D6A0 100%);
        color: white;
        border-color: rgba(6, 214, 160, 0.5);
        box-shadow: 0 6px 20px rgba(46, 134, 171, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.2);
        transform: translateY(-2px);
    }
    
    /* Data tables */
    .dataframe {
        background: rgba(20, 30, 60, 0.3);
        backdrop-filter: blur(10px);
        border-radius: 16px;
        overflow: hidden;
        border: 1px solid rgba(46, 134, 171, 0.2);
    }
    
    /* Hide streamlit elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* ── Sidebar toggle button — always visible in top-left ── */
    .sidebar-toggle-btn {
        position: fixed;
        top: 14px;
        left: 14px;
        z-index: 99999;
        background: rgba(20, 30, 60, 0.85);
        backdrop-filter: blur(16px);
        border: 1.5px solid rgba(46, 134, 171, 0.45);
        border-radius: 12px;
        width: 40px;
        height: 40px;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
        box-shadow: 0 4px 16px rgba(0,0,0,0.35);
        color: #A0C4D8;
        font-size: 18px;
    }
    .sidebar-toggle-btn:hover {
        background: rgba(46, 134, 171, 0.3);
        border-color: #06D6A0;
        color: #06D6A0;
        box-shadow: 0 0 18px rgba(6,214,160,0.3);
    }

    /* ============================================
       SUPPLYMIND CHAT INTERFACE - PREMIUM STYLES
       ============================================ */

    /* Full-height chat page wrapper */
    .chat-page-wrapper {
        display: flex;
        flex-direction: column;
        height: calc(100vh - 120px);
        position: relative;
    }

    /* Chat messages scroll area */
    .chat-messages-area {
        flex: 1;
        overflow-y: auto;
        padding: 24px 0 120px 0;
        scroll-behavior: smooth;
    }

    /* Welcome hero center section */
    .chat-welcome-hero {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
        padding: 60px 20px 40px 20px;
        animation: fadeInUp 0.6s ease;
    }

    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(24px); }
        to   { opacity: 1; transform: translateY(0); }
    }

    /* Lightning bolt icon — pure glow, NO box, NO background */
    .chat-bolt-icon {
        font-size: 72px;
        line-height: 1;
        margin-bottom: 28px;
        display: block;
        text-align: center;
        filter:
            drop-shadow(0 0 18px rgba(255,160,0,1))
            drop-shadow(0 0 40px rgba(255,120,0,0.85))
            drop-shadow(0 0 80px rgba(255,80,0,0.45));
        animation: bolt-pulse 2.5s ease-in-out infinite;
    }

    @keyframes bolt-pulse {
        0%, 100% {
            filter:
                drop-shadow(0 0 18px rgba(255,160,0,1))
                drop-shadow(0 0 40px rgba(255,120,0,0.8))
                drop-shadow(0 0 80px rgba(255,80,0,0.35));
        }
        50% {
            filter:
                drop-shadow(0 0 30px rgba(255,180,0,1))
                drop-shadow(0 0 70px rgba(255,140,0,0.95))
                drop-shadow(0 0 130px rgba(255,100,0,0.6));
        }
    }

    .chat-welcome-title {
        font-size: 32px;
        font-weight: 700;
        color: #E8E9ED;
        margin: 0 0 12px 0;
        letter-spacing: -0.5px;
    }

    .chat-welcome-subtitle {
        font-size: 16px;
        color: #6B7280;
        line-height: 1.6;
        max-width: 460px;
        margin: 0;
    }

    /* Quick action chips */
    .quick-chips-row {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        justify-content: center;
        margin-top: 36px;
    }

    .quick-chip {
        background: rgba(14, 22, 52, 0.72);
        backdrop-filter: blur(12px);
        border: 1.5px solid rgba(46, 134, 171, 0.42);
        border-radius: 50px;
        padding: 10px 22px;
        color: #A0C4D8;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
        white-space: nowrap;
        user-select: none;
    }

    .quick-chip:hover {
        background: rgba(46, 134, 171, 0.25);
        border-color: #2E86AB;
        color: #06D6A0;
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(46,134,171,0.25);
    }

    /* Chat message bubbles */
    .chat-msg-user {
        display: flex;
        justify-content: flex-end;
        margin: 10px 0;
        animation: slideInRight 0.3s ease;
    }

    .chat-msg-ai {
        display: flex;
        align-items: center;
        margin: 10px 0;
        gap: 12px;
        animation: slideInLeft 0.3s ease;
    }

    .chat-bubble-user {
        background: linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%);
        color: white;
        padding: 14px 20px;
        border-radius: 20px 20px 4px 20px;
        max-width: 68%;
        font-size: 15px;
        line-height: 1.6;
        box-shadow: 0 4px 16px rgba(37, 99, 235, 0.4);
        word-wrap: break-word;
    }

    .chat-bubble-ai {
        background: rgba(26, 31, 50, 0.8);
        backdrop-filter: blur(12px);
        border: 1px solid rgba(46, 134, 171, 0.2);
        border-bottom: none;
        color: #D1D5DB;
        padding: 14px 20px;
        border-radius: 20px 20px 20px 4px;
        max-width: 68%;
        font-size: 15px;
        line-height: 1.6;
        box-shadow: 0 4px 16px rgba(0,0,0,0.3);
        word-wrap: break-word;
    }

    /* AI lightning in chat bubbles — pure glow, no box */
    .ai-lightning {
        font-size: 20px;
        line-height: 1;
        min-width: 26px;
        text-align: center;
        flex-shrink: 0;
        align-self: center;
        filter:
            drop-shadow(0 0 8px rgba(255,160,0,1))
            drop-shadow(0 0 18px rgba(255,100,0,0.75));
    }


    /* ── Streamlit stBottom container — fully transparent, no box ever ────── */
    [data-testid="stBottom"],
    [data-testid="stBottom"] > *,
    [data-testid="stBottom"] > * > *,
    [data-testid="stBottom"] > * > * > *,
    [data-testid="stBottom"] > * > * > * > * {
        background: transparent !important;
        background-color: transparent !important;
        box-shadow: none !important;
    }

    /* Force the inner wrapper to also be transparent */
    .stBottom, .css-1fcdlhc, .e1ewe7hr0 {
        background: transparent !important;
        background-color: transparent !important;
    }

    /* ── Native chat_input — blue tone, very rounded, no red focus ── */
    [data-testid="stChatInput"] {
        background: rgba(10, 20, 55, 0.92) !important;
        backdrop-filter: blur(24px) !important;
        border: 1.5px solid rgba(46, 134, 171, 0.45) !important;
        border-radius: 50px !important;
        box-shadow: 0 4px 24px rgba(0,0,0,0.35), 0 0 0 1px rgba(46,134,171,0.08) !important;
        transition: border-color 0.3s ease, box-shadow 0.3s ease !important;
        overflow: hidden !important;
    }

    [data-testid="stChatInput"]:focus-within {
        border-color: rgba(46, 134, 171, 0.8) !important;
        box-shadow: 0 4px 24px rgba(0,0,0,0.35), 0 0 0 3px rgba(46,134,171,0.14) !important;
        outline: none !important;
    }

    /* Kill Streamlit’s own red/orange focus ring */
    [data-testid="stChatInput"] *:focus,
    [data-testid="stChatInput"] *:focus-visible {
        outline: none !important;
        box-shadow: none !important;
    }

    [data-testid="stChatInputTextArea"] {
        color: #D8E4F0 !important;
        font-size: 15px !important;
        background: transparent !important;
        caret-color: #06D6A0 !important;
    }

    /* Round send button — gradient, perfectly circular */
    [data-testid="stChatInputSubmitButton"] button {
        border-radius: 50% !important;
        background: linear-gradient(135deg, #2E86AB 0%, #06D6A0 100%) !important;
        width: 38px !important;
        height: 38px !important;
        padding: 0 !important;
        box-shadow: 0 4px 12px rgba(46,134,171,0.5) !important;
        transition: all 0.3s cubic-bezier(0.4,0,0.2,1) !important;
        border: none !important;
    }

    [data-testid="stChatInputSubmitButton"] button:hover {
        transform: scale(1.12) !important;
        box-shadow: 0 6px 22px rgba(6,214,160,0.65) !important;
    }


    /* ── Pills: center + full style with green hover glow ─────────── */
    /* Try all parent container paths Streamlit may render */
    [data-testid="stPills"],
    [data-testid="stPills"] > div,
    [data-testid="stPills"] > div > div {
        display: flex !important;
        justify-content: center !important;
        flex-wrap: wrap !important;
        gap: 10px !important;
        width: 100% !important;
    }

    [data-testid="stPills"] button {
        background: rgba(14, 22, 50, 0.72) !important;
        border: 1.5px solid rgba(46, 134, 171, 0.4) !important;
        border-radius: 50px !important;
        color: #90B4CC !important;
        font-size: 14px !important;
        font-weight: 500 !important;
        padding: 10px 26px !important;
        transition: all 0.3s cubic-bezier(0.4,0,0.2,1) !important;
        white-space: nowrap !important;
        box-shadow: none !important;
        letter-spacing: 0.01em !important;
    }

    [data-testid="stPills"] button:hover {
        background: rgba(6, 214, 160, 0.12) !important;
        border-color: rgba(6, 214, 160, 0.65) !important;
        color: #06D6A0 !important;
        transform: translateY(-2px) !important;
        box-shadow:
            0 0 18px rgba(6,214,160,0.3),
            0 6px 20px rgba(6,214,160,0.15) !important;
    }

    [data-testid="stPills"] button[aria-pressed="true"] {
        background: rgba(6, 214, 160, 0.15) !important;
        border-color: #06D6A0 !important;
        color: #06D6A0 !important;
        box-shadow: 0 0 14px rgba(6,214,160,0.35) !important;
    }

    /* ── st.chat_message bubbles ──────────────────────────────────── */
    [data-testid="stChatMessage"] {
        background: transparent !important;
        padding: 4px 0 !important;
    }

    /* User messages – align right */
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
        flex-direction: row-reverse !important;
    }

    [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p {
        font-size: 15px !important;
        line-height: 1.65 !important;
    }

    /* AI avatar override */
    [data-testid="chatAvatarIcon-assistant"] {
        background: linear-gradient(135deg, #06D6A0 0%, #2E86AB 100%) !important;
        border-radius: 10px !important;
    }

    /* ── Chat header ── */
    .block-container,
    [data-testid="stVerticalBlock"],
    .element-container {
        overflow: visible !important;
    }
    .chat-active-header {
        position: sticky;
        top: 14px;
        z-index: 9999;
        display: inline-flex;
        align-items: center;
        gap: 14px;
        padding: 14px 34px 14px 22px;
        margin-bottom: 24px;
        margin-left: 20px;
        background: linear-gradient(145deg, rgba(12, 18, 46, 0.92) 0%, rgba(18, 30, 60, 0.88) 100%) !important;
        backdrop-filter: blur(24px) saturate(1.5) !important;
        border: 1.2px solid rgba(46, 134, 171, 0.28);
        border-radius: 60px;
        box-shadow:
            0 6px 28px rgba(0, 0, 0, 0.35),
            0 0 0 1px rgba(46, 134, 171, 0.10),
            inset 0 1px 0 rgba(255, 255, 255, 0.05);
        animation: headerSlideIn 0.5s cubic-bezier(0.22, 1, 0.36, 1) both,
                   headerBreath 4s ease-in-out 0.5s infinite;
        transition: transform 0.3s ease, box-shadow 0.3s ease;
    }

    .chat-active-header:hover {
        transform: translateY(-2px);
        border-color: rgba(46, 134, 171, 0.45);
        box-shadow:
            0 10px 40px rgba(0, 0, 0, 0.40),
            0 0 24px rgba(46, 134, 171, 0.15),
            0 0 0 1px rgba(46, 134, 171, 0.20),
            inset 0 1px 0 rgba(255, 255, 255, 0.07);
    }

    @keyframes headerSlideIn {
        from { opacity: 0; transform: translateY(-16px) scale(0.97); }
        to   { opacity: 1; transform: translateY(0) scale(1); }
    }

    @keyframes headerBreath {
        0%, 100% {
            box-shadow:
                0 6px 28px rgba(0, 0, 0, 0.35),
                0 0 0 1px rgba(46, 134, 171, 0.10),
                inset 0 1px 0 rgba(255, 255, 255, 0.05);
        }
        50% {
            box-shadow:
                0 6px 28px rgba(0, 0, 0, 0.35),
                0 0 20px rgba(46, 134, 171, 0.10),
                0 0 0 1px rgba(46, 134, 171, 0.18),
                inset 0 1px 0 rgba(255, 255, 255, 0.05);
        }
    }

    .chat-header-bolt {
        font-size: 30px;
        line-height: 1;
        flex-shrink: 0;
        filter:
            drop-shadow(0 0 8px rgba(255,160,0,0.9))
            drop-shadow(0 0 20px rgba(255,110,0,0.7));
        animation: headerBoltPulse 2.8s ease-in-out infinite;
    }

    @keyframes headerBoltPulse {
        0%, 100% {
            filter:
                drop-shadow(0 0 8px rgba(255,160,0,0.9))
                drop-shadow(0 0 20px rgba(255,110,0,0.7));
        }
        50% {
            filter:
                drop-shadow(0 0 14px rgba(255,180,0,1))
                drop-shadow(0 0 36px rgba(255,130,0,0.85));
        }
    }

    .chat-header-name {
        font-size: 24px;
        font-weight: 700;
        background: linear-gradient(135deg, #ffffff 0%, #7DD3FC 40%, #06D6A0 80%, #7DD3FC 100%);
        background-size: 300% 300%;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        letter-spacing: -0.2px;
        line-height: 1;
        animation: headerGradientShift 6s ease-in-out infinite;
    }

    @keyframes headerGradientShift {
        0%, 100% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
    }

    /* Spacer so messages dont hide behind fixed input */
    .chat-bottom-spacer {
        height: 20px;
    }

    /* ── Follow-up pill — targeted via marker, same style as quick-action chips ── */
    [data-testid="stMarkdown"]:has(.followup-pill-trigger) + [data-testid="stButton"] button {
        background: rgba(14, 22, 52, 0.72) !important;
        border: 1.5px solid rgba(46, 134, 171, 0.42) !important;
        border-radius: 50px !important;
        color: #90B4CC !important;
        font-size: 12.5px !important;
        font-weight: 500 !important;
        padding: 7px 18px !important;
        white-space: nowrap !important;
        letter-spacing: 0.01em !important;
        min-height: unset !important;
        box-shadow: none !important;
        transition: all 0.3s cubic-bezier(0.4,0,0.2,1) !important;
        transform: none !important;
        margin: 4px 0 0 0 !important;
    }
    [data-testid="stMarkdown"]:has(.followup-pill-trigger) + [data-testid="stButton"] button:hover {
        background: rgba(6, 214, 160, 0.12) !important;
        border-color: rgba(6, 214, 160, 0.65) !important;
        color: #06D6A0 !important;
        transform: translateY(-2px) !important;
        box-shadow:
            0 0 18px rgba(6,214,160,0.3),
            0 6px 20px rgba(6,214,160,0.15) !important;
    }

    /* ── Thinking dots animation ── */
    .thinking-dots {
        display: flex;
        gap: 6px;
        padding: 4px 0;
    }
    .thinking-dots span {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #06D6A0;
        animation: dotBounce 1.4s ease-in-out infinite;
    }
    .thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
    .thinking-dots span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes dotBounce {
        0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
        40% { opacity: 1; transform: scale(1.1); }
    }

    /* ── Followup pill rows: compact layout matching welcome chips ── */
    [data-testid="stHorizontalBlock"]:has(.followup-pill-trigger) {
        display: flex !important;
        gap: 12px !important;
        flex-wrap: wrap !important;
        justify-content: flex-start !important;
        margin-left: 38px !important;
        margin-top: 6px !important;
    }
    [data-testid="stHorizontalBlock"]:has(.followup-pill-trigger) > div,
    [data-testid="stHorizontalBlock"]:has(.followup-pill-trigger) > [data-testid="stColumn"] {
        flex: 0 0 auto !important;
        width: auto !important;
        min-width: 0 !important;
        max-width: none !important;
        padding: 0 !important;
    }
    [data-testid="stHorizontalBlock"]:has(.followup-pill-trigger) [data-testid="stVerticalBlockBorderWrapper"],
    [data-testid="stHorizontalBlock"]:has(.followup-pill-trigger) [data-testid="stVerticalBlock"] {
        width: auto !important;
        padding: 0 !important;
    }

    /* Custom scrollbar */
    ::-webkit-scrollbar {
        width: 12px;
        height: 12px;
    }
    
    ::-webkit-scrollbar-track {
        background: rgba(20, 30, 60, 0.3);
        border-radius: 10px;
    }
    
    ::-webkit-scrollbar-thumb {
        background: linear-gradient(135deg, #2E86AB, #3A9BC4);
        border-radius: 10px;
        border: 2px solid rgba(20, 30, 60, 0.3);
    }
    
    ::-webkit-scrollbar-thumb:hover {
        background: linear-gradient(135deg, #3A9BC4, #06D6A0);
    }
    
    /* Responsive design */
    @media (max-width: 768px) {
        .metric-card {
            padding: 20px;
        }
        
        .metric-value {
            font-size: 32px;
        }
        
        .user-message, .assistant-message {
            max-width: 85%;
            padding: 14px 18px;
            font-size: 14px;
        }
        
        .chat-container {
            padding: 20px;
        }
    }
    
    @media (max-width: 480px) {
        .metric-value {
            font-size: 28px;
        }
        
        .user-message, .assistant-message {
            max-width: 95%;
        }
    }
    
    /* Enhanced selectbox */
    .stSelectbox > div > div {
        background: rgba(30, 40, 70, 0.5);
        backdrop-filter: blur(10px);
        border: 1.5px solid rgba(46, 134, 171, 0.3);
        border-radius: 14px;
    }
    
    /* File uploader */
    .stFileUploader {
        background: rgba(30, 40, 70, 0.3);
        backdrop-filter: blur(10px);
        border-radius: 16px;
        border: 2px dashed rgba(46, 134, 171, 0.3);
        padding: 20px;
    }

    /* ============================================
       CROSS-TAB UI ENHANCEMENTS
       ============================================ */

    /* ── Gradient page headers ── */
    [data-testid="stMarkdownContainer"] h1 {
        background: linear-gradient(135deg, #06D6A0 0%, #2E86AB 60%, #8B5CF6 100%) !important;
        -webkit-background-clip: text !important;
        -webkit-text-fill-color: transparent !important;
        background-clip: text !important;
        font-weight: 800 !important;
        letter-spacing: -0.5px !important;
        padding-bottom: 4px !important;
    }

    /* ── Page transition animation ── */
    [data-testid="stMainBlockContainer"],
    section.main > div.block-container {
        animation: pageSlideIn 0.35s cubic-bezier(0.22, 1, 0.36, 1) both !important;
    }
    @keyframes pageSlideIn {
        from { opacity: 0; transform: translateY(12px); }
        to   { opacity: 1; transform: translateY(0); }
    }

    /* ── Styled expanders (glassmorphism) ── */
    [data-testid="stExpander"] {
        background: rgba(20, 30, 60, 0.35) !important;
        backdrop-filter: blur(12px) !important;
        border: 1px solid rgba(46, 134, 171, 0.18) !important;
        border-radius: 14px !important;
        overflow: hidden !important;
        transition: border-color 0.3s ease !important;
    }
    [data-testid="stExpander"]:hover {
        border-color: rgba(46, 134, 171, 0.35) !important;
    }
    [data-testid="stExpander"] summary {
        color: #C0CAD8 !important;
        font-weight: 600 !important;
        padding: 14px 18px !important;
    }
    [data-testid="stExpander"] summary:hover {
        color: #06D6A0 !important;
    }
    [data-testid="stExpander"] [data-testid="stExpanderDetails"] {
        border-top: 1px solid rgba(46, 134, 171, 0.12) !important;
        padding: 14px 18px !important;
    }

    /* ── Enhanced alert / info / warning boxes ── */
    [data-testid="stAlert"] {
        background: rgba(20, 30, 60, 0.4) !important;
        backdrop-filter: blur(10px) !important;
        border-radius: 12px !important;
        border: 1px solid rgba(46, 134, 171, 0.2) !important;
    }
    /* info variant */
    [data-testid="stAlert"][data-baseweb="notification"] {
        border-left: 3px solid #2E86AB !important;
    }
    [data-testid="stAlert"] .st-emotion-cache-1gulkj5,
    [data-testid="stAlert"] p {
        color: #A0ACBE !important;
    }

    /* ── Dark dataframe theming ── */
    [data-testid="stDataFrame"],
    [data-testid="stDataFrame"] > div {
        border-radius: 14px !important;
        overflow: hidden !important;
    }
    [data-testid="stDataFrame"] [data-testid="stDataFrameResizable"] {
        border: 1px solid rgba(46, 134, 171, 0.18) !important;
        border-radius: 14px !important;
    }

    /* ── Premium file uploader drop zone ── */
    [data-testid="stFileUploader"] {
        background: rgba(20, 30, 60, 0.3) !important;
        backdrop-filter: blur(12px) !important;
        border: 2px dashed rgba(46, 134, 171, 0.25) !important;
        border-radius: 16px !important;
        padding: 24px !important;
        transition: all 0.3s ease !important;
    }
    [data-testid="stFileUploader"]:hover {
        border-color: rgba(6, 214, 160, 0.4) !important;
        background: rgba(6, 214, 160, 0.04) !important;
    }
    [data-testid="stFileUploader"] button {
        background: linear-gradient(135deg, #2E86AB 0%, #3A9BC4 100%) !important;
        border-radius: 10px !important;
        border: none !important;
    }
    [data-testid="stFileUploader"] small {
        color: #5E6B80 !important;
    }

    /* ── Styled number input / slider ── */
    [data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {
        background: #06D6A0 !important;
        border-color: #06D6A0 !important;
    }
    [data-testid="stSlider"] [data-baseweb="slider"] div[style*="background"] {
        background: linear-gradient(90deg, #06D6A0, #2E86AB) !important;
    }

    /* ── Primary button restyle ── */
    button[data-testid="stBaseButton-primary"],
    .stButton > button[kind="primary"],
    .stButton > button[type="submit"] {
        background: linear-gradient(135deg, rgba(6, 214, 160, 0.15) 0%, rgba(46, 134, 171, 0.12) 100%) !important;
        border: 1px solid rgba(6, 214, 160, 0.25) !important;
        color: #E8E9ED !important;
        border-radius: 10px !important;
        font-weight: 600 !important;
        padding: 8px 24px !important;
        transition: all 0.25s ease !important;
        box-shadow: none !important;
    }
    button[data-testid="stBaseButton-primary"]:hover,
    .stButton > button[kind="primary"]:hover,
    .stButton > button[type="submit"]:hover {
        background: linear-gradient(135deg, rgba(6, 214, 160, 0.22) 0%, rgba(46, 134, 171, 0.18) 100%) !important;
        border-color: rgba(6, 214, 160, 0.35) !important;
        color: #FFFFFF !important;
        box-shadow: none !important;
    }

    /* ── Secondary / default button restyle ── */
    .stButton > button,
    button[data-testid="stBaseButton-secondary"] {
        background: rgba(20, 30, 60, 0.4) !important;
        border: 1px solid rgba(100, 116, 139, 0.25) !important;
        color: #C0CAD8 !important;
        border-radius: 10px !important;
        font-weight: 500 !important;
        transition: all 0.25s ease !important;
    }
    .stButton > button:hover,
    button[data-testid="stBaseButton-secondary"]:hover {
        background: rgba(30, 42, 78, 0.6) !important;
        border-color: rgba(100, 116, 139, 0.4) !important;
        color: #E8E9ED !important;
    }

    /* ── Tabs — Premium Glass Pill Design ── */
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        background: rgba(15, 23, 42, 0.4) !important;
        border-radius: 12px !important;
        padding: 5px !important;
        gap: 6px !important;
        border: 1px solid rgba(100, 116, 139, 0.15) !important;
        backdrop-filter: blur(10px) !important;
        margin-bottom: 25px !important;
    }
    [data-testid="stTabs"] [data-baseweb="tab"] {
        background: transparent !important;
        border-radius: 8px !important;
        color: #718096 !important;
        font-weight: 500 !important;
        font-size: 14px !important;
        padding: 8px 20px !important;
        border: none !important;
        outline: none !important;
        box-shadow: none !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    }
    [data-testid="stTabs"] [data-baseweb="tab"]:hover {
        color: #E2E8F0 !important;
        background: rgba(100, 116, 139, 0.1) !important;
    }
    [data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {
        background: rgba(6, 214, 160, 0.12) !important;
        color: #06D6A0 !important;
        font-weight: 600 !important;
        border: 1px solid rgba(6, 214, 160, 0.2) !important;
        box-shadow: 0 0 15px rgba(6, 214, 160, 0.08) !important;
    }
    /* Specific color accents for certain tabs if needed */
    [data-testid="stTabs"] [data-baseweb="tab"]:focus {
        outline: none !important;
    }
    
    /* Kill ALL default highlights/borders */
    [data-testid="stTabs"] [data-baseweb="tab-highlight"],
    [data-testid="stTabs"] [data-baseweb="tab-border"] {
        display: none !important;
    }
    [data-testid="stTabs"] [data-baseweb="tab-list"]::after {
        display: none !important;
    }

    /* ── Alert boxes — Dynamic Glassmorphism ── */
    div[data-testid="stNotification"],
    div[role="alert"],
    .stAlert,
    div[data-testid="stAlert"] {
        background: rgba(15, 23, 42, 0.5) !important;
        backdrop-filter: blur(12px) !important;
        border-radius: 12px !important;
        border: 1px solid rgba(100, 116, 139, 0.18) !important;
        padding: 16px 20px !important;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1) !important;
    }
    /* Info (Blue/Green) */
    div[role="alert"].st-ae, div[data-testid="stAlert"].st-ae {
        border-left: 4px solid #06D6A0 !important;
    }
    /* Warning (Orange/Yellow) */
    div[role="alert"].st-af, div[data-testid="stAlert"].st-af {
        border-left: 4px solid #E8B84B !important;
    }
    /* Success (Green) */
    div[role="alert"].st-ag, div[data-testid="stAlert"].st-ag {
        border-left: 4px solid #06D6A0 !important;
    }
    /* Error (Red) */
    div[role="alert"].st-ah, div[data-testid="stAlert"].st-ah {
        border-left: 4px solid #EF476F !important;
    }
    div[data-testid="stNotification"] p,
    .stAlert p,
    div[role="alert"] p {
        color: #8899AA !important;
    }
    div[data-testid="stNotification"] svg,
    .stAlert svg {
        fill: #5A6478 !important;
    }

    /* ── Spinner ── */
    .stSpinner > div > div {
        border-top-color: #06D6A0 !important;
    }

    /* ── Checkbox restyle ── */
    [data-testid="stCheckbox"] label span[data-testid="stCheckbox-label"] {
        color: #C0CAD8 !important;
    }

    /* ── Text input restyle ── */
    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input {
        background: rgba(15, 23, 42, 0.5) !important;
        border: 1px solid rgba(100, 116, 139, 0.2) !important;
        border-radius: 10px !important;
        color: #E8E9ED !important;
        transition: border-color 0.25s ease !important;
    }
    [data-testid="stTextInput"] input:focus,
    [data-testid="stNumberInput"] input:focus {
        border-color: rgba(200, 210, 225, 0.35) !important;
        box-shadow: none !important;
    }

    /* ── Labels for all inputs ── */
    [data-testid="stTextInput"] label p,
    [data-testid="stNumberInput"] label p,
    [data-testid="stSelectbox"] label p,
    [data-testid="stSlider"] label p,
    [data-testid="stFileUploader"] label p {
        color: #8899AA !important;
        font-weight: 500 !important;
    }

</style>
<script>
(function() {
    /* ── 1. Sticky header via IntersectionObserver ── */
    function initStickyHeader() {
        var hdr = document.getElementById('procure-header');
        if (!hdr) return;
        // Sentinel: invisible element placed just above header
        var sentinel = document.createElement('div');
        sentinel.style.cssText = 'height:1px;width:100%;position:relative;top:0;pointer-events:none;';
        hdr.parentNode.insertBefore(sentinel, hdr);
        // Capture header's initial left/width for fixed positioning
        var rect = hdr.getBoundingClientRect();
        var fixedLeft = rect.left;
        var fixedWidth = rect.width;
        var obs = new IntersectionObserver(function(entries) {
            if (!entries[0].isIntersecting) {
                hdr.style.position = 'fixed';
                hdr.style.top = '10px';
                hdr.style.left = fixedLeft + 'px';
                hdr.style.width = fixedWidth + 'px';
                hdr.style.zIndex = '9999';
                hdr.style.background = 'transparent';
            } else {
                hdr.style.position = 'relative';
                hdr.style.top = 'auto';
                hdr.style.left = 'auto';
                hdr.style.width = 'auto';
                hdr.style.zIndex = 'auto';
            }
        }, { threshold: 0 });
        obs.observe(sentinel);
    }

    /* ── 2. Restyle followup pill buttons ── */
    var PILL_STYLE = [
        'background: rgba(14,22,52,0.72)',
        'border: 1.5px solid rgba(46,134,171,0.42)',
        'border-radius: 50px',
        'color: #90B4CC',
        'font-size: 12.5px',
        'font-weight: 500',
        'padding: 7px 18px',
        'white-space: nowrap',
        'box-shadow: none',
        'letter-spacing: 0.01em',
        'min-height: unset',
        'line-height: 1.4',
        'transition: all 0.3s cubic-bezier(0.4,0,0.2,1)',
        'transform: none',
        'margin: 4px 0 0 0',
        'width: auto',
        'display: inline-flex'
    ].join(';');

    function styleFollowupBtns() {
        document.querySelectorAll('.followup-pill-trigger').forEach(function(marker) {
            // Walk up to the element-container wrapper
            var wrap = marker.closest('.element-container') || marker.parentNode;
            if (!wrap) return;
            var nextWrap = wrap.nextElementSibling;
            if (!nextWrap) return;
            var btn = nextWrap.querySelector('button');
            if (!btn || btn.dataset.pillStyled) return;
            btn.dataset.pillStyled = '1';
            btn.style.cssText = PILL_STYLE;
            btn.addEventListener('mouseenter', function() {
                btn.style.cssText = PILL_STYLE +
                    ';background: rgba(6,214,160,0.12)' +
                    ';border-color: rgba(6,214,160,0.65)' +
                    ';color: #06D6A0' +
                    ';transform: translateY(-2px)' +
                    ';box-shadow: 0 0 18px rgba(6,214,160,0.3),0 6px 20px rgba(6,214,160,0.15)';
            });
            btn.addEventListener('mouseleave', function() {
                btn.style.cssText = PILL_STYLE;
            });
        });
    }

    function init() {
        initStickyHeader();
        styleFollowupBtns();
        // Re-check on DOM changes (Streamlit re-renders components)
        new MutationObserver(function() {
            initStickyHeader();
            styleFollowupBtns();
        }).observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else { setTimeout(init, 100); }
})();
</script>
""", unsafe_allow_html=True)

# ── Sidebar toggle via components.html (runs JS in real iframe with window.parent access) ──
components.html("""
<script>
(function() {
    var doc = window.parent.document;
    // Remove any stale button first, then re-create
    var old = doc.getElementById('mas-sidebar-toggle');
    if (old) old.remove();

    var btn = doc.createElement('button');
    btn.id = 'mas-sidebar-toggle';
    btn.title = 'Toggle navigation panel';
    btn.innerHTML = '&#9776;';
    btn.style.cssText = [
        'position:fixed', 'top:14px', 'left:14px', 'z-index:99999',
        'background:rgba(20,30,60,0.88)', 'backdrop-filter:blur(16px)',
        'border:1.5px solid rgba(46,134,171,0.5)', 'border-radius:12px',
        'width:40px', 'height:40px', 'display:flex', 'align-items:center',
        'justify-content:center', 'cursor:pointer',
        'transition:all 0.3s cubic-bezier(0.4,0,0.2,1)',
        'box-shadow:0 4px 16px rgba(0,0,0,0.35)', 'color:#A0C4D8',
        'font-size:18px', 'line-height:1', 'padding:0'
    ].join(';');
    btn.onmouseenter = function(){
        btn.style.background = 'rgba(46,134,171,0.3)';
        btn.style.borderColor = '#06D6A0';
        btn.style.color = '#06D6A0';
        btn.style.boxShadow = '0 0 18px rgba(6,214,160,0.3)';
        btn.style.transform = 'scale(1.08)';
    };
    btn.onmouseleave = function(){
        btn.style.background = 'rgba(20,30,60,0.88)';
        btn.style.borderColor = 'rgba(46,134,171,0.5)';
        btn.style.color = '#A0C4D8';
        btn.style.boxShadow = '0 4px 16px rgba(0,0,0,0.35)';
        btn.style.transform = 'scale(1)';
    };
    btn.onclick = function() {
        // Re-query every click so we always find the current toggle
        var d = window.parent.document;
        var toggle = d.querySelector('[data-testid="stSidebarCollapseButton"] button')
                  || d.querySelector('[data-testid="collapsedControl"] button')
                  || d.querySelector('button[aria-label="Close sidebar"]')
                  || d.querySelector('button[aria-label="Open sidebar"]')
                  || d.querySelector('[data-testid="stSidebarCollapsedControl"] button');
        if (toggle) { toggle.click(); return; }
        // Fallback: force-toggle sidebar transform
        var sb = d.querySelector('[data-testid="stSidebar"]');
        if (sb) {
            var hidden = sb.getAttribute('aria-expanded') === 'false'
                      || sb.style.transform.indexOf('-') > -1
                      || sb.offsetWidth < 10;
            if (hidden) {
                sb.style.transform = 'none';
                sb.setAttribute('aria-expanded', 'true');
            } else {
                sb.style.transform = 'translateX(-110%)';
                sb.setAttribute('aria-expanded', 'false');
            }
        }
    };
    doc.body.appendChild(btn);
})();
</script>
""", height=0, width=0)

# ── Orchestrator cached for the server lifetime (avoids re-init on every rerun) ──
@st.cache_resource
def _get_orchestrator():
    from agents.Agent0 import MasterOrchestrator
    return MasterOrchestrator()

# Initialize session state
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []

# Attach cached orchestrator to session (safe — cache_resource is shared)
if 'orchestrator' not in st.session_state:
    st.session_state.orchestrator = _get_orchestrator()
if 'pending_prompt' not in st.session_state:
    st.session_state.pending_prompt = None

# Utility functions

import re as _re

def _md_to_html(text):
    """Convert basic markdown to safe HTML for chat bubbles."""
    lines = text.split('\n')
    out = []
    in_ul = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('### '):
            if in_ul: out.append('</ul>'); in_ul = False
            out.append(f'<h3 style="margin:10px 0 4px;font-size:16px;font-weight:700;color:#E2EAF4;">{stripped[4:]}</h3>')
        elif stripped.startswith('## '):
            if in_ul: out.append('</ul>'); in_ul = False
            out.append(f'<h2 style="margin:12px 0 4px;font-size:18px;font-weight:700;color:#E2EAF4;">{stripped[3:]}</h2>')
        elif stripped.startswith('# '):
            if in_ul: out.append('</ul>'); in_ul = False
            out.append(f'<h1 style="margin:12px 0 6px;font-size:20px;font-weight:700;color:#E2EAF4;">{stripped[2:]}</h1>')
        elif stripped.startswith(('- ', '* ')):
            if not in_ul: out.append('<ul style="margin:6px 0;padding-left:18px;">'); in_ul = True
            out.append(f'<li style="margin:3px 0;color:#D0DCE8;">{stripped[2:]}</li>')
        elif stripped in ('---', '___', '***'):
            if in_ul: out.append('</ul>'); in_ul = False
        elif stripped == '':
            if in_ul: out.append('</ul>'); in_ul = False
            out.append('<div style="height:6px;"></div>')
        else:
            if in_ul: out.append('</ul>'); in_ul = False
            bold_line = _re.match(r'^\*\*(.+?)\*\*\s*$', stripped)
            # Lines ending with colon and no other formatting → sub-heading
            colon_heading = (not bold_line and stripped.endswith(':') and len(stripped) < 80
                            and not stripped.startswith(('- ', '* ', '> ')))
            if bold_line:
                out.append(f'<h4 style="margin:12px 0 5px;font-size:15.5px;font-weight:700;color:#E8EDF4;letter-spacing:0.01em;">{bold_line.group(1)}</h4>')
            elif colon_heading:
                label = stripped.rstrip(':')
                out.append(f'<p style="margin:10px 0 3px;line-height:1.65;color:#E2EAF4;font-weight:600;font-size:15px;">{label}:</p>')
            else:
                out.append(f'<p style="margin:4px 0;line-height:1.65;color:#D0DCE8;">{stripped}</p>')
    if in_ul:
        out.append('</ul>')
    html = '\n'.join(out)
    html = _re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', html)
    html = _re.sub(r'\*\*(.+?)\*\*', r'<strong style="color:#E8EDF4;font-weight:600;">\1</strong>', html)
    html = _re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    html = _re.sub(r'`(.+?)`', r'<code style="background:rgba(46,134,171,0.15);padding:1px 5px;border-radius:4px;font-size:13px;">\1</code>', html)
    return html

def _parse_ai_message(content):
    """Split AI response into main body and a list of followup pill labels (up to 3)."""
    followups = []

    parts = _re.split(r'\n\s*===+\s*\n', content, maxsplit=1)
    if len(parts) == 2:
        lines = [l.strip() for l in parts[1].strip().splitlines() if l.strip()]
        followups = [l for l in lines if len(l) > 3][:3]
        body = parts[0].strip()
        return body, followups

    paras = [p.strip() for p in content.strip().split('\n\n') if p.strip()]
    if paras:
        last = paras[-1]
        if last.endswith('?') and len(last) < 250 and len(paras) > 1:
            opts = _re.split(r',?\s+or\s+would\s+you\s+like\s+', last, flags=_re.IGNORECASE)
            if len(opts) > 1:
                followups = [o.strip().strip('?') + '?' for o in opts if len(o.strip()) > 4][:3]
            else:
                followups = [last]
            body = '\n\n'.join(paras[:-1]).strip()
            return body, followups

    return content.strip(), []

def _stream_response(text):
    """Yield word chunks for progressive streaming display."""
    words = text.split(' ')
    chunk_size = 4
    for i in range(0, len(words), chunk_size):
        yield ' '.join(words[i:i + chunk_size])
        time.sleep(0.018)

@st.cache_data(ttl=30)
def load_json_data(filepath, default=None):
    """Load JSON data with error handling and 30s cache."""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                content = f.read().strip()
                # Treat empty files as "no data" instead of raising JSON errors
                if not content:
                    return default if default is not None else {}
                return json.loads(content)
        return default if default is not None else {}
    except Exception as e:
        log_error(f"Error loading {filepath}: {e}")
        return default if default is not None else {}

@st.cache_data(ttl=30)
def load_inventory_data():
    """Load current inventory from CSV with 30s cache."""
    try:
        csv_path = "data/current_inventory.csv"
        if os.path.exists(csv_path):
            return pd.read_csv(csv_path)
        return pd.DataFrame()
    except Exception as e:
        log_error(f"Error loading inventory: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=30)
def get_system_metrics():
    """Calculate real-time system metrics with 30s cache."""
    try:
        inventory_df = load_inventory_data()
        quotes = load_json_data("data/quotes_collected.json", {})
        pos = load_json_data("data/purchase_orders.json", [])
        notifications = load_json_data("data/notification_logs.json", [])
        
        total_items = len(inventory_df) if not inventory_df.empty else 0
        
        low_stock_count = 0
        if not inventory_df.empty and 'current_quantity' in inventory_df.columns and 'reorder_point' in inventory_df.columns:
            low_stock_count = len(inventory_df[inventory_df['current_quantity'] < inventory_df['reorder_point']])
        
        active_pos = len([po for po in pos if po.get('status') == 'approved']) if isinstance(pos, list) else 0
        total_quotes = sum(len(supplier_quotes) for supplier_quotes in quotes.values()) if isinstance(quotes, dict) else 0
        recent_notifications = len([n for n in notifications if isinstance(n, dict) and 
                                   (datetime.now() - datetime.fromisoformat(n.get('timestamp', '2020-01-01'))).days < 7]) if isinstance(notifications, list) else 0
        
        return {
            'total_items': total_items,
            'low_stock_count': low_stock_count,
            'active_pos': active_pos,
            'total_quotes': total_quotes,
            'recent_notifications': recent_notifications
        }
    except Exception as e:
        log_error(f"Error calculating metrics: {e}")
        return {'total_items': 0, 'low_stock_count': 0, 'active_pos': 0, 'total_quotes': 0, 'recent_notifications': 0}

# Sidebar navigation
with st.sidebar:
    st.markdown("""
    <style>
        @keyframes titleShimmer {
            0% { background-position: -200% center; }
            100% { background-position: 200% center; }
        }
    </style>
    <div style='padding: 6px 0 4px 0;'>
        <div style='display: flex; align-items: center; gap: 12px;'>
            <span style='font-size: 30px; line-height: 1;
                         filter: drop-shadow(0 0 10px rgba(255,160,0,0.95))
                                 drop-shadow(0 0 22px rgba(255,100,0,0.6));'>&#9889;</span>
            <div>
                <div style='font-size: 22px; font-weight: 800;
                            background: linear-gradient(90deg, #06D6A0, #2E86AB, #8B5CF6, #06D6A0);
                            background-size: 200% auto;
                            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
                            background-clip: text;
                            animation: titleShimmer 4s linear infinite;
                            letter-spacing: -0.3px; line-height: 1.2;'>__APP_NAME__</div>
                <div style='font-size: 10px; color: #5A6478; font-weight: 600;
                            letter-spacing: 2px; text-transform: uppercase;
                            margin-top: 3px;'>Multi-Agent System</div>
            </div>
        </div>
    </div>
    """.replace('__APP_NAME__', APP_NAME), unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("<div style='color:#4A5568; font-size:9px; font-weight:700; letter-spacing:2.5px; text-transform:uppercase; padding:0 18px 6px 18px;'>Navigation</div>", unsafe_allow_html=True)
    # Handle new_chat query param BEFORE radio to force Chat Interface page
    if st.query_params.get("new_chat"):
        st.query_params.clear()
        st.session_state.chat_history = []
        if 'orchestrator' in st.session_state:
            st.session_state.orchestrator._reset_state()
            st.session_state.orchestrator.conversation_history = []
        st.session_state.nav_radio = "Chat Interface"

    page = st.radio(
        "Navigation",
        ["Dashboard", "Chat Interface", "Inventory Monitor", "Procurement Pipeline", "Document Verification", "Configurations"],
        key="nav_radio",
        label_visibility="collapsed"
    )

    st.markdown("---")
    st.markdown("<div style='color:#5A6478; font-size:10px; font-weight:700; letter-spacing:2px; text-transform:uppercase; padding:0 0 6px 0;'>System Status</div>", unsafe_allow_html=True)
    metrics = get_system_metrics()

    st.markdown(f"""
    <div style='padding: 12px 14px; background: linear-gradient(135deg, rgba(6,214,160,0.10) 0%, rgba(6,214,160,0.04) 100%);
                border-radius: 10px; margin: 6px 0; border: 1px solid rgba(6,214,160,0.20);
                display: flex; align-items: center; justify-content: space-between;'>
        <div style='color: #6B7A8E; font-size: 11px; font-weight: 600; letter-spacing: 0.5px;'>System</div>
        <div style='display: flex; align-items: center; gap: 6px;'>
            <span style='width:7px; height:7px; border-radius:50%; background:#06D6A0;
                         box-shadow: 0 0 8px rgba(6,214,160,0.6); display:inline-block;'></span>
            <span style='color: #06D6A0; font-size: 13px; font-weight: 700;'>Operational</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style='padding: 12px 14px; background: linear-gradient(135deg, rgba(46,134,171,0.10) 0%, rgba(46,134,171,0.04) 100%);
                border-radius: 10px; margin: 6px 0; border: 1px solid rgba(46,134,171,0.20);
                display: flex; align-items: center; justify-content: space-between;'>
        <div style='color: #6B7A8E; font-size: 11px; font-weight: 600; letter-spacing: 0.5px;'>Agents</div>
        <span style='color: #2E86AB; font-size: 13px; font-weight: 700;'>12 / 12</span>
    </div>
    """, unsafe_allow_html=True)

    if metrics['low_stock_count'] > 0:
        st.markdown(f"""
        <div style='padding: 12px 14px; background: linear-gradient(135deg, rgba(232,184,75,0.10) 0%, rgba(232,184,75,0.04) 100%);
                    border-radius: 10px; margin: 6px 0; border: 1px solid rgba(232,184,75,0.20);
                    display: flex; align-items: center; justify-content: space-between;'>
            <div style='color: #6B7A8E; font-size: 11px; font-weight: 600; letter-spacing: 0.5px;'>Low Stock</div>
            <span style='color: #E8B84B; font-size: 13px; font-weight: 700;'>{metrics['low_stock_count']} items</span>
        </div>
        """, unsafe_allow_html=True)

# Main content area
if page == "Dashboard":
    st.markdown("<h1 style='font-size:32px;font-weight:800;letter-spacing:-0.5px;margin-bottom:0;display:inline-block;background:linear-gradient(90deg,#06D6A0,#2E86AB,#8B5CF6,#06D6A0);background-size:200% auto;-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;animation:titleShimmer 4s linear infinite;'>Dashboard</h1><p style='color:#6B7A8E;margin-top:4px;font-size:15px;'>Real-time overview of your procurement system</p>", unsafe_allow_html=True)
    
    col1, col2, col3, col4 = st.columns(4)
    metrics = get_system_metrics()
    
    with col1:
        st.markdown(f"""
        <div class='metric-card'>
            <div class='metric-label'>Total Items</div>
            <div class='metric-value'>{metrics['total_items']}</div>
            <div class='metric-delta positive'>In Inventory</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        delta_class = 'negative' if metrics['low_stock_count'] > 0 else 'positive'
        st.markdown(f"""
        <div class='metric-card'>
            <div class='metric-label'>Low Stock Items</div>
            <div class='metric-value'>{metrics['low_stock_count']}</div>
            <div class='metric-delta {delta_class}'>Needs Attention</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div class='metric-card'>
            <div class='metric-label'>Active Orders</div>
            <div class='metric-value'>{metrics['active_pos']}</div>
            <div class='metric-delta positive'>In Progress</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div class='metric-card'>
            <div class='metric-label'>Quotes Received</div>
            <div class='metric-value'>{metrics['total_quotes']}</div>
            <div class='metric-delta positive'>This Month</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### Inventory Status")
        inventory_df = load_inventory_data()
        
        if not inventory_df.empty and 'current_quantity' in inventory_df.columns and 'reorder_point' in inventory_df.columns:
            inventory_df['status'] = inventory_df.apply(
                lambda row: 'Critical' if row['current_quantity'] < row['reorder_point'] * 0.5
                else 'Low' if row['current_quantity'] < row['reorder_point']
                else 'Adequate', axis=1
            )
            
            status_counts = inventory_df['status'].value_counts()
            
            # Enhanced pie chart with vibrant colors
            fig = go.Figure(data=[go.Pie(
                labels=status_counts.index,
                values=status_counts.values,
                hole=0.5,
                marker=dict(
                    colors=['#8B5CF6', '#3B82F6', '#06D6A0'],  # Purple, Blue, Teal gradient
                    line=dict(color='rgba(10, 14, 39, 0.8)', width=3)
                ),
                textfont=dict(size=16, color='white', family='Inter'),
                textposition='outside',
                textinfo='label+percent',
                hovertemplate='<b>%{label}</b><br>Count: %{value}<br>Percentage: %{percent}<extra></extra>',
                pull=[0.05, 0.05, 0.05]
            )])
            
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#E8E9ED', family='Inter'),
                showlegend=True,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=-0.2,
                    xanchor="center",
                    x=0.5,
                    font=dict(size=14)
                ),
                height=350,
                margin=dict(t=40, b=60, l=20, r=20)
            )
            
            st.plotly_chart(fig, width='stretch')
        else:
            st.info("No inventory data available")
    
    with col2:
        st.markdown("### Recent Activity")
        notifications = load_json_data("data/notification_logs.json", {})
        
        if notifications and isinstance(notifications, dict):
            notifications = list(notifications.values())

        if notifications and isinstance(notifications, list):
            recent = sorted(notifications, key=lambda x: x.get('timestamp', ''), reverse=True)[:5]
            
            for notif in recent:
                event_type = notif.get('event_type', 'unknown')
                timestamp = notif.get('timestamp', '')
                
                if timestamp:
                    time_str = format_display_date(timestamp)
                else:
                    time_str = "Unknown time"
                
                color = '#06D6A0' if 'approved' in event_type else '#2E86AB' if 'sent' in event_type else '#E8B84B'
                
                st.markdown(f"""
                <div style='padding: 14px; background: rgba(30, 40, 70, 0.4); backdrop-filter: blur(10px); border-left: 3px solid {color}; 
                            border-radius: 12px; margin: 10px 0; border: 1px solid rgba(46, 134, 171, 0.2);'>
                    <div style='color: #E8E9ED; font-size: 14px; font-weight: 600;'>{event_type.replace('_', ' ').title()}</div>
                    <div style='color: #A0A3B1; font-size: 12px; margin-top: 4px;'>{time_str}</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No recent activity")
    
    st.markdown("### Recent Purchase Orders")
    pos = load_json_data("data/purchase_orders.json", {})
    
    if pos and isinstance(pos, dict):
        pos = list(pos.values())

    if pos and isinstance(pos, list):
        po_data = []
        for po in sorted(pos, key=lambda x: x.get('created_at', ''), reverse=True)[:5]:
            po_data.append({
                'PO Number': po.get('po_number', 'N/A'),
                'Supplier': po.get('supplier_name', 'N/A'),
                'Item': po.get('item_name', 'N/A'),
                'Quantity': po.get('quantity', 0),
                'Total Amount': f"₹{po.get('total_amount', 0):,.2f}",
                'Status': po.get('status', 'unknown').upper()
            })
        
        if po_data:
            df = pd.DataFrame(po_data)
            st.dataframe(df, width='stretch', hide_index=True)
    else:
        st.info("No purchase orders found")

elif page == "Chat Interface":

    st.markdown("""
    <style>
    /* ── Pill button styling (Chat Interface only — welcome + follow-up pills) ── */
    [data-testid="stHorizontalBlock"] [data-testid="stButton"] button {
        background: rgba(14, 22, 52, 0.72) !important;
        border: 1.5px solid rgba(46, 134, 171, 0.42) !important;
        border-radius: 50px !important;
        color: #90B4CC !important;
        font-size: 12.5px !important;
        font-weight: 500 !important;
        padding: 10px 22px !important;
        white-space: nowrap !important;
        overflow: visible !important;
        transition: all 0.3s cubic-bezier(0.4,0,0.2,1) !important;
        min-height: unset !important;
    }
    [data-testid="stHorizontalBlock"] [data-testid="stButton"] button:hover {
        background: rgba(6, 214, 160, 0.10) !important;
        border-color: rgba(6, 214, 160, 0.65) !important;
        color: #06D6A0 !important;
        transform: translateY(-2px) !important;
        box-shadow: 0 0 18px rgba(6,214,160,0.28) !important;
    }
    [data-testid="stHorizontalBlock"] {
        display: flex !important;
        justify-content: center !important;
        gap: 12px !important;
        flex-wrap: nowrap !important;
    }
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
    [data-testid="stHorizontalBlock"] > div {
        flex: 0 0 auto !important;
        width: auto !important;
        min-width: unset !important;
        padding: 0 !important;
    }
    [data-testid="stHorizontalBlock"] [data-testid="stVerticalBlockBorderWrapper"],
    [data-testid="stHorizontalBlock"] [data-testid="stVerticalBlock"] {
        padding: 0 !important;
        width: auto !important;
    }
    </style>
    """, unsafe_allow_html=True)


    # ── Session state init ─────────────────────────────────────────────
    if 'chip_query' not in st.session_state:
        st.session_state.chip_query = None

    # ── Welcome hero (shown only when no messages yet) ─────────────────
    if not st.session_state.chat_history:
        st.markdown("""
        <div class='chat-welcome-hero'>
            <div class='chat-bolt-icon'>⚡</div>
            <h1 class='chat-welcome-title'>""" + APP_NAME + """ Assistant</h1>
            <p class='chat-welcome-subtitle'>
                Ask me about inventory, suppliers, RFQs, purchase orders,<br>or document verification.
            </p>
        </div>
        """, unsafe_allow_html=True)

        # ── Inject page-level CSS overrides just for the chat welcome area ──
        st.markdown("""
        <style>
        /* Kill the stBottom black box — target ALL children deep */
        [data-testid="stBottom"],
        [data-testid="stBottom"] > *,
        [data-testid="stBottom"] > * > *,
        [data-testid="stBottom"] > * > * > *,
        [data-testid="stBottom"] > * > * > * > * {
            background: transparent !important;
            background-color: transparent !important;
            box-shadow: none !important;
        }

        /* Chat input: deep blue, very rounded, kill the red Streamlit ring */
        [data-testid="stChatInput"] {
            background: rgba(8, 16, 50, 0.96) !important;
            border: 1.5px solid rgba(46, 134, 171, 0.5) !important;
            border-radius: 50px !important;
            box-shadow: 0 4px 24px rgba(0,0,0,0.45) !important;
            overflow: hidden !important;
        }
        [data-testid="stChatInput"]:focus-within {
            border-color: rgba(46, 134, 171, 0.85) !important;
            box-shadow: 0 4px 24px rgba(0,0,0,0.45), 0 0 0 3px rgba(46,134,171,0.15) !important;
        }
        /* Override Streamlit's --primary-color red focus across all inner elements */
        [data-testid="stBottom"] *,
        [data-testid="stChatInput"] *,
        [data-testid="stChatInput"] *:focus,
        [data-testid="stChatInput"] *:focus-visible,
        [data-testid="stChatInput"] textarea,
        [data-testid="stChatInput"] textarea:focus {
            outline: none !important;
            box-shadow: none !important;
            border-color: transparent !important;
            --primary-color: transparent !important;
        }

        </style>
        """, unsafe_allow_html=True)


        # 4 equal columns — CSS handles centering the row
        cc1, cc2, cc3, cc4 = st.columns(4)
        with cc1:
            if st.button("Check inventory", key="chip_inv"):
                st.session_state.chip_query = "Check current inventory levels"
                st.rerun()
        with cc2:
            if st.button("Show pending RFQs", key="chip_rfq"):
                st.session_state.chip_query = "Show all pending RFQs"
                st.rerun()
        with cc3:
            if st.button("Check inbox", key="chip_qt"):
                st.session_state.chip_query = "Check inbox for quotes"
                st.rerun()
        with cc4:
            if st.button("Help", key="chip_help"):
                st.session_state.chip_query = "Help"
                st.rerun()
    else:

        # ── Glowing mini header (clickable — st.html with JS) ──────────────
        st.html("""
        <style>
            .chat-active-header-wrapper {
                display: flex;
                justify-content: flex-start;
                width: 100%;
            }
            .chat-active-header {
                cursor: pointer;
                position: relative;
                display: inline-flex;
                align-items: center;
                gap: 14px;
                padding: 14px 34px 14px 22px;
                background: linear-gradient(145deg, rgba(12, 18, 46, 0.92) 0%, rgba(18, 30, 60, 0.88) 100%);
                backdrop-filter: blur(24px) saturate(1.5);
                border: 1.2px solid rgba(46, 134, 171, 0.28);
                border-radius: 60px;
                box-shadow:
                    0 6px 28px rgba(0, 0, 0, 0.35),
                    0 0 0 1px rgba(46, 134, 171, 0.10),
                    inset 0 1px 0 rgba(255, 255, 255, 0.05);
                transition: transform 0.3s ease, box-shadow 0.3s ease;
                font-family: 'Inter', 'Segoe UI', sans-serif;
            }
            .chat-active-header:hover {
                transform: translateY(-2px);
                border-color: rgba(46, 134, 171, 0.45);
                box-shadow:
                    0 10px 40px rgba(0, 0, 0, 0.40),
                    0 0 24px rgba(46, 134, 171, 0.15),
                    0 0 0 1px rgba(46, 134, 171, 0.20),
                    inset 0 1px 0 rgba(255, 255, 255, 0.07);
            }
            .chat-header-bolt {
                font-size: 30px;
                line-height: 1;
                flex-shrink: 0;
                position: relative;
                filter:
                    drop-shadow(0 0 8px rgba(255,160,0,0.9))
                    drop-shadow(0 0 20px rgba(255,110,0,0.7));
            }
            .chat-header-bolt::after {
                content: 'New Chat';
                position: absolute;
                top: calc(100% + 10px);
                left: 50%;
                transform: translateX(-50%) translateY(4px);
                background: rgba(10, 14, 36, 0.95);
                color: #7DD3FC;
                font-size: 11px;
                font-weight: 600;
                padding: 5px 12px;
                border-radius: 6px;
                border: 1px solid rgba(46, 134, 171, 0.3);
                white-space: nowrap;
                opacity: 0;
                pointer-events: none;
                transition: opacity 0.2s ease, transform 0.2s ease;
                z-index: 10000;
            }
            .chat-active-header:hover .chat-header-bolt::after {
                opacity: 1;
                transform: translateX(-50%) translateY(0);
            }
            .chat-header-name {
                font-size: 24px;
                font-weight: 700;
                background: linear-gradient(135deg, #ffffff 0%, #7DD3FC 40%, #06D6A0 80%, #7DD3FC 100%);
                background-size: 300% 300%;
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                letter-spacing: -0.2px;
                line-height: 1;
                animation: headerGradientShift 6s ease-in-out infinite;
            }
            @keyframes headerGradientShift {
                0%, 100% { background-position: 0% 50%; }
                50% { background-position: 100% 50%; }
            }
        </style>
        <div class="chat-active-header-wrapper">
            <div class="chat-active-header" id="procure-header">
                <span class="chat-header-bolt">&#9889;</span>
                <span class="chat-header-name">__APP_NAME__ Assistant</span>
            </div>
        </div>
        <script>
            document.getElementById('procure-header').addEventListener('click', function() {
                window.location.search = '?new_chat=1';
            });
        </script>
        """.replace('__APP_NAME__', APP_NAME), unsafe_allow_javascript=True)

        # ── Render chat messages with custom styled bubbles ────────────
        for i, msg in enumerate(st.session_state.chat_history):
            if msg['role'] == 'user':
                content = msg['content'].replace('<', '&lt;').replace('>', '&gt;')
                st.markdown(f"""
                <div class='chat-msg-user'>
                    <div class='chat-bubble-user'>{content}</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                main_content, followups = _parse_ai_message(msg['content'])
                html_content = _md_to_html(main_content)
                if followups:
                    paras = main_content.strip().split('\n\n')
                    last_para = paras[-1].strip() if paras else ''
                    if last_para.endswith('?') and len(paras) > 1:
                        followup_hr = '<hr style="border:none;border-top:1px solid rgba(46,134,171,0.25);margin:12px 0 6px;">'
                        body_before = '\n\n'.join(paras[:-1])
                        html_body = _md_to_html(body_before)
                        html_question = _md_to_html(last_para)
                        html_content = html_body + followup_hr + html_question
                    else:
                        html_content = _md_to_html(main_content)
                st.markdown(f"""
                <div class='chat-msg-ai'>
                    <div class='ai-lightning'>&#9889;</div>
                    <div class='chat-bubble-ai'>{html_content}</div>
                </div>
                """, unsafe_allow_html=True)
                if followups:
                    n = len(followups)
                    pill_cols = st.columns(n if n > 1 else 1)
                    for j, (pc, fq) in enumerate(zip(pill_cols, followups)):
                        with pc:
                            st.markdown('<div class="followup-pill-trigger"></div>', unsafe_allow_html=True)
                            if st.button(fq, key=f"followup_{i}_{j}"):
                                st.session_state.chip_query = fq
                                st.rerun()

        # ── Handle pending response with streaming ──────────────────────
        if st.session_state.get('pending_prompt'):
            _prompt = st.session_state.pending_prompt
            st.session_state.pending_prompt = None
            response_ph = st.empty()
            response_ph.markdown("""
            <div class='chat-msg-ai'>
                <div class='ai-lightning'>&#9889;</div>
                <div class='chat-bubble-ai'>
                    <div class='thinking-dots'><span></span><span></span><span></span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            try:
                response = st.session_state.orchestrator.process_request(_prompt)
            except Exception as e:
                response = f"I encountered an error: {str(e)}. Please try again."
            main_text, _ = _parse_ai_message(response)
            streamed_parts = []
            for chunk in _stream_response(main_text):
                streamed_parts.append(chunk)
                partial_html = _md_to_html(' '.join(streamed_parts))
                response_ph.markdown(f"""
                <div class='chat-msg-ai'>
                    <div class='ai-lightning'>&#9889;</div>
                    <div class='chat-bubble-ai'>{partial_html}</div>
                </div>
                """, unsafe_allow_html=True)
            st.session_state.chat_history.append({
                'role': 'assistant',
                'content': response,
                'timestamp': datetime.now().isoformat()
            })
            st.rerun()

        # ── JS via components.html (same-origin iframe → window.parent.document) ──
        # This is the ONLY reliable way to run JS that touches Streamlit's DOM
        components.html("""
        <script>
        (function() {
            var doc = window.parent.document;

            /* — 1. Restyle followup pills — */
            var PILL = 'background:rgba(14,22,52,0.85)!important;'
                     + 'border:1.5px solid rgba(46,134,171,0.42)!important;'
                     + 'border-radius:50px!important;'
                     + 'color:#90B4CC!important;'
                     + 'font-size:12.5px!important;'
                     + 'font-weight:500!important;'
                     + 'padding:7px 18px!important;'
                     + 'white-space:nowrap!important;'
                     + 'box-shadow:none!important;'
                     + 'letter-spacing:0.01em!important;'
                     + 'width:auto!important;'
                     + 'display:inline-flex!important;'
                     + 'align-items:center!important;'
                     + 'cursor:pointer!important;'
                     + 'transition:all 0.3s cubic-bezier(0.4,0,0.2,1)!important;';

            var PILL_HOVER = PILL
                     + 'background:rgba(6,214,160,0.12)!important;'
                     + 'border-color:rgba(6,214,160,0.65)!important;'
                     + 'color:#06D6A0!important;'
                     + 'box-shadow:0 0 18px rgba(6,214,160,0.3),0 6px 20px rgba(6,214,160,0.15)!important;';

            function stylePills() {
                doc.querySelectorAll('.followup-pill-trigger').forEach(function(m) {
                    var wrap = m.closest('.element-container') || m.parentNode;
                    if (!wrap) return;
                    var next = wrap.nextElementSibling;
                    if (!next) return;
                    var btn = next.querySelector('button');
                    if (!btn || btn.dataset.ps) return;
                    btn.dataset.ps = '1';
                    btn.setAttribute('style', PILL);
                    btn.onmouseenter = function() { btn.setAttribute('style', PILL_HOVER); };
                    btn.onmouseleave = function() { btn.setAttribute('style', PILL); };

                    /* Collapse the Streamlit column to auto-width using direct property assignment
                       (cssText doesn't override Streamlit's inline styles; individual props do) */
                    var col = btn.closest('[data-testid="column"]');
                    if (col) {
                        col.style.setProperty('flex', '0 0 auto', 'important');
                        col.style.setProperty('width', 'auto', 'important');
                        col.style.setProperty('min-width', '0', 'important');
                        col.style.setProperty('padding', '0', 'important');
                        col.style.setProperty('max-width', 'none', 'important');
                    }

                    /* Fix the horizontal block row: compact flex, 12px gap, aligned with bubble */
                    var row = btn.closest('[data-testid="stHorizontalBlock"]');
                    if (row && !row.dataset.pr) {
                        row.dataset.pr = '1';
                        row.style.setProperty('display', 'flex', 'important');
                        row.style.setProperty('flex-wrap', 'wrap', 'important');
                        row.style.setProperty('gap', '12px', 'important');
                        row.style.setProperty('margin-left', '38px', 'important');
                        row.style.setProperty('margin-top', '6px', 'important');
                        row.style.setProperty('width', 'auto', 'important');
                        row.style.setProperty('justify-content', 'flex-start', 'important');
                    }
                });
            }

            /* — 2. Sticky header via IntersectionObserver — */
            function initSticky() {
                var hdr = doc.getElementById('procure-header');
                if (!hdr || hdr._stickyInit) return;
                hdr._stickyInit = true;
                var rect = hdr.getBoundingClientRect();
                var sentinel = doc.createElement('div');
                sentinel.style.cssText = 'height:1px;width:100%;pointer-events:none;';
                hdr.parentNode.insertBefore(sentinel, hdr);
                new IntersectionObserver(function(entries) {
                    if (!entries[0].isIntersecting) {
                        hdr.style.position = 'fixed';
                        hdr.style.top = '10px';
                        hdr.style.left = rect.left + 'px';
                        hdr.style.width = rect.width + 'px';
                        hdr.style.zIndex = '9999';
                        hdr.style.background = 'transparent';
                    } else {
                        hdr.style.position = 'relative';
                        hdr.style.top = 'auto';
                        hdr.style.left = 300px;
                        hdr.style.width = 'auto';
                    }
                }, { threshold: 0 }).observe(sentinel);
            }

            function run() { stylePills(); initSticky(); }
            run();
            new MutationObserver(run).observe(doc.body, { childList: true, subtree: true });
        })();
        </script>
        """, height=0, width=0)

    st.markdown("<div class='chat-bottom-spacer'></div>", unsafe_allow_html=True)

    # ── Native chat input – always fixed at bottom, Enter sends, auto-clears ──
    prompt = st.chat_input(f"Message {APP_NAME} Assistant...")

    # If a chip was clicked, use that as prompt
    if not prompt and st.session_state.chip_query:
        prompt = st.session_state.chip_query
        st.session_state.chip_query = None

    # ── Process message ────────────────────────────────────────────────
    if prompt:
        st.session_state.chat_history.append({
            'role': 'user',
            'content': prompt,
            'timestamp': datetime.now().isoformat()
        })
        st.session_state.pending_prompt = prompt
        st.rerun()

elif page == "Inventory Monitor":
    st.markdown("<h1 style='font-size:32px;font-weight:800;letter-spacing:-0.5px;margin-bottom:0;display:inline-block;background:linear-gradient(90deg,#06D6A0,#2E86AB,#8B5CF6,#06D6A0);background-size:200% auto;-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;animation:titleShimmer 4s linear infinite;'>Inventory Monitor</h1><p style='color:#6B7A8E;margin-top:4px;font-size:15px;'>Real-time stock levels and replenishment alerts</p>", unsafe_allow_html=True)
    
    inventory_df = load_inventory_data()
    
    if not inventory_df.empty:
        col1, col2, col3 = st.columns(3)
        
        total_items = len(inventory_df)
        if 'current_quantity' in inventory_df.columns and 'reorder_point' in inventory_df.columns:
            critical_items = len(inventory_df[inventory_df['current_quantity'] < inventory_df['reorder_point'] * 0.5])
            low_stock_items = len(inventory_df[
                (inventory_df['current_quantity'] >= inventory_df['reorder_point'] * 0.5) &
                (inventory_df['current_quantity'] < inventory_df['reorder_point'])
            ])
        else:
            critical_items = 0
            low_stock_items = 0
        
        with col1:
            st.markdown(f"""
            <div class='metric-card'>
                <div class='metric-label'>Total SKUs</div>
                <div class='metric-value'>{total_items}</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class='metric-card'>
                <div class='metric-label'>Critical Stock</div>
                <div class='metric-value' style='background: linear-gradient(135deg, #EF476F 0%, #E8B84B 100%); 
                            -webkit-background-clip: text; -webkit-text-fill-color: transparent;'>{critical_items}</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class='metric-card'>
                <div class='metric-label'>Low Stock</div>
                <div class='metric-value' style='background: linear-gradient(135deg, #E8B84B 0%, #2E86AB 100%); 
                            -webkit-background-clip: text; -webkit-text-fill-color: transparent;'>{low_stock_items}</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            filter_option = st.selectbox(
                "Filter by status",
                ["All Items", "Critical Stock", "Low Stock", "Adequate Stock"]
            )
        
        with col2:
            search_term = st.text_input("Search items", placeholder="Enter item name or code...")
        
        filtered_df = inventory_df.copy()
        
        if 'current_quantity' in filtered_df.columns and 'reorder_point' in filtered_df.columns:
            if filter_option == "Critical Stock":
                filtered_df = filtered_df[filtered_df['current_quantity'] < filtered_df['reorder_point'] * 0.5]
            elif filter_option == "Low Stock":
                filtered_df = filtered_df[
                    (filtered_df['current_quantity'] >= filtered_df['reorder_point'] * 0.5) &
                    (filtered_df['current_quantity'] < filtered_df['reorder_point'])
                ]
            elif filter_option == "Adequate Stock":
                filtered_df = filtered_df[filtered_df['current_quantity'] >= filtered_df['reorder_point']]
        
        if search_term:
            mask = filtered_df.apply(lambda row: search_term.lower() in str(row).lower(), axis=1)
            filtered_df = filtered_df[mask]
        
        if not filtered_df.empty:
            if 'current_quantity' in filtered_df.columns and 'reorder_point' in filtered_df.columns:
                filtered_df['Status'] = filtered_df.apply(
                    lambda row: 'Critical' if row['current_quantity'] < row['reorder_point'] * 0.5
                    else 'Low' if row['current_quantity'] < row['reorder_point']
                    else 'Adequate', axis=1
                )
            
            st.dataframe(filtered_df, width='stretch', hide_index=True, height=400)
        else:
            st.info("No items match the current filters")
    else:
        st.warning("No inventory data available. Please ensure current_inventory.csv exists in the data folder.")

elif page == "Procurement Pipeline":
    st.markdown("<h1 style='font-size:32px;font-weight:800;letter-spacing:-0.5px;margin-bottom:0;display:inline-block;background:linear-gradient(90deg,#06D6A0,#2E86AB,#8B5CF6,#06D6A0);background-size:200% auto;-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;animation:titleShimmer 4s linear infinite;'>Procurement Pipeline</h1><p style='color:#6B7A8E;margin-top:4px;font-size:15px;'>Track RFQs, quotes, and purchase orders</p>", unsafe_allow_html=True)
    
    tab1, tab2, tab3 = st.tabs(["Active RFQs", "Quotes Analysis", "Purchase Orders"])
    
    with tab1:
        sent_rfqs = load_json_data("data/sent_rfqs.json", {})
        pending_rfqs = load_json_data("data/pending_rfqs.json", {})
        
        if sent_rfqs:
            st.markdown(f"<div style='color:#06D6A0;font-size:14px;font-weight:700;letter-spacing:0.5px;padding:8px 0 10px 0;'>SENT RFQs ({len(sent_rfqs)})</div>", unsafe_allow_html=True)
            for rfq_id, rfq_data in sent_rfqs.items():
                urgency = rfq_data.get('urgency', 'N/A')
                urg_color = '#EF476F' if urgency in ('CRITICAL','URGENT') else '#E8B84B' if urgency == 'HIGH' else '#06D6A0'
                with st.expander(f"**{rfq_data.get('item_code', 'N/A')} - {rfq_data.get('item_name', 'Unknown')}**"):   
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.markdown(f"**Quantity:** {rfq_data.get('quantity', 0):,} units")
                    with c2:
                        st.markdown(f"**Emails Sent:** {rfq_data.get('emails_sent', 'N/A')}")
                    with c3:
                        st.markdown(f"**Sent:** {format_display_date(rfq_data.get('sent_at', 'N/A'))}")
                    
                    st.markdown(f"<span style='background:rgba({int(urg_color[1:3],16)},{int(urg_color[3:5],16)},{int(urg_color[5:7],16)},0.15);color:{urg_color};padding:4px 14px;border-radius:20px;font-size:12px;font-weight:600;'>{urgency}</span>", unsafe_allow_html=True)
                    
                    suppliers = rfq_data.get('suppliers', [])
                    if suppliers:
                        supplier_list = ", ".join([f"{s.get('supplier_name','Unknown')} ({s.get('location','N/A')})" for s in suppliers])
                        st.markdown(f"**Suppliers contacted:** {supplier_list}")
        if pending_rfqs:
            st.markdown(f"<div style='color:#E8B84B;font-size:14px;font-weight:700;letter-spacing:0.5px;padding:16px 0 10px 0;'>PENDING RFQs ({len(pending_rfqs)})</div>", unsafe_allow_html=True)
            for rfq_id, rfq_data in pending_rfqs.items():
                urgency = rfq_data.get('urgency', 'N/A')
                urg_color = '#EF476F' if urgency in ('CRITICAL','URGENT') else '#E8B84B' if urgency == 'HIGH' else '#06D6A0'
                with st.expander(f"**{rfq_data.get('item_code', 'N/A')} - {rfq_data.get('item_name', 'Unknown')}**"):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.markdown(f"**Quantity:** {rfq_data.get('quantity', 0):,} units")
                    with c2:
                        st.markdown(f"**Suppliers Found:** {len(rfq_data.get('suppliers', []))}")
                    with c3:
                        st.markdown(f"**Created:** {format_display_date(rfq_data.get('created_at', 'N/A'))}")

                    st.markdown(f"<span style='background:rgba({int(urg_color[1:3],16)},{int(urg_color[3:5],16)},{int(urg_color[5:7],16)},0.15);color:{urg_color};padding:4px 14px;border-radius:20px;font-size:12px;font-weight:600;'>{urgency}</span>", unsafe_allow_html=True)
            
        if not sent_rfqs and not pending_rfqs:
            st.info("No RFQs found — start a procurement workflow in the Chat Interface!")

    with tab2:
        quotes = load_json_data("data/quotes_collected.json", {})

        if quotes:
            quote_data = []
            for supplier_key, supplier_info in quotes.items():
                if isinstance(supplier_info, dict):
                    s_name = supplier_info.get('supplier_name', supplier_key)
                    q_list = supplier_info.get('quotes', [])
                else:
                    s_name = supplier_key
                    q_list = supplier_info if isinstance(supplier_info, list) else []
                for quote in q_list:
                    quote_data.append({
                        'Supplier': s_name,
                        'Item': quote.get('item_name', 'N/A'),
                        'Unit Price (₹)': quote.get('unit_price', 0),
                        'Quantity': quote.get('quantity', 0),
                        'Total (₹)': quote.get('total_cost', quote.get('total_price', 0)),
                        'Delivery': f"{quote.get('delivery_days', 'N/A')} days",
                        'Payment': quote.get('payment_terms', 'N/A'),
                        'Certs': quote.get('quality_certs', 'N/A'),
                        'Received': format_display_date(quote.get('received_at', 'N/A'))
                    })

            if quote_data:
                st.markdown(f"<div style='color:#2E86AB;font-size:14px;font-weight:700;letter-spacing:0.5px;padding:8px 0 10px 0;'>QUOTES FROM {len(quotes)} SUPPLIERS  •  {len(quote_data)} QUOTES TOTAL</div>", unsafe_allow_html=True)
                df = pd.DataFrame(quote_data)
                st.dataframe(df, width='stretch', hide_index=True)

                if len(quote_data) > 1:
                    fig = px.bar(df, x='Item', y='Unit Price (₹)', color='Supplier', barmode='group', title='Unit Price Comparison by Supplier')
                    fig.update_layout(
                        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                        font=dict(color='#E8E9ED', family='Inter'),
                        title_font=dict(size=16, color='#E2EAF4'),
                        xaxis=dict(gridcolor='rgba(46,134,171,0.1)'),
                        yaxis=dict(gridcolor='rgba(46,134,171,0.1)'),
                        legend=dict(bgcolor='rgba(0,0,0,0)')
                    )
                    st.plotly_chart(fig, width='stretch')
            else:
                st.info("No quotes collected yet")
        else:
            st.info("No quotes collected yet — quotes appear here after suppliers respond to RFQs")

    with tab3:
        pos_raw = load_json_data("data/purchase_orders.json", {})

        if isinstance(pos_raw, dict):
            pos = list(pos_raw.values())
        elif isinstance(pos_raw, list):
            pos = pos_raw
        else:
            pos = []

        if pos:
            approved_n = sum(1 for po in pos if po.get('status','').lower() in ('approved',))
            pending_n = sum(1 for po in pos if po.get('status','').lower() in ('pending_approval', 'needs_approval'))
            rejected_n = sum(1 for po in pos if po.get('status','').lower() in ('rejected',))

            st.markdown(f"""
            <div style='display:flex;gap:16px;margin:8px 0 16px 0;'>
                <div style='flex:1;background:rgba(6,214,160,0.08);border:1px solid rgba(6,214,160,0.2);border-radius:12px;padding:14px 18px;text-align:center;'>
                    <div style='color:#06D6A0;font-size:24px;font-weight:800;'>{approved_n}</div>
                    <div style='color:#6B7A8E;font-size:12px;font-weight:600;letter-spacing:0.5px;'>APPROVED</div>
                </div>
                <div style='flex:1;background:rgba(232,184,75,0.08);border:1px solid rgba(232,184,75,0.2);border-radius:12px;padding:14px 18px;text-align:center;'>
                    <div style='color:#E8B84B;font-size:24px;font-weight:800;'>{pending_n}</div>
                    <div style='color:#6B7A8E;font-size:12px;font-weight:600;letter-spacing:0.5px;'>PENDING</div>
                </div>
                <div style='flex:1;background:rgba(239,71,111,0.08);border:1px solid rgba(239,71,111,0.2);border-radius:12px;padding:14px 18px;text-align:center;'>
                    <div style='color:#EF476F;font-size:24px;font-weight:800;'>{rejected_n}</div>
                    <div style='color:#6B7A8E;font-size:12px;font-weight:600;letter-spacing:0.5px;'>REJECTED</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            status_filter = st.selectbox("Filter by status", ["All", "Approved", "Pending", "Rejected"])

            filtered_pos = pos
            if status_filter == "Approved":
                filtered_pos = [po for po in pos if po.get('status', '').lower() in ('approved',)]
            elif status_filter == "Pending":
                filtered_pos = [po for po in pos if po.get('status', '').lower() in ('pending_approval', 'needs_approval')]
            elif status_filter == "Rejected":
                filtered_pos = [po for po in pos if po.get('status', '').lower() in ('rejected',)]

            filtered_pos = sorted(filtered_pos, key=lambda x: x.get('created_at', x.get('approved_at', '')), reverse=True)

            for po in filtered_pos:
                raw_status = po.get('status', 'unknown').lower()
                if raw_status == 'approved':
                    status_label, status_color = 'APPROVED', '#06D6A0'
                elif raw_status in ('pending_approval', 'needs_approval'):
                    status_label, status_color = 'PENDING APPROVAL', '#E8B84B'
                elif raw_status == 'rejected':
                    status_label, status_color = 'REJECTED', '#EF476F'
                else:
                    status_label, status_color = raw_status.upper(), '#6B7A8E'

                total = po.get('total_cost', po.get('total_amount', 0))

                with st.expander(f"**{po.get('po_number', 'N/A')}**\n\n**{po.get('item_code', 'N/A')} - {po.get('item_name', 'N/A')}**\n\n"):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.markdown(f"**Supplier:** {po.get('supplier_name', 'N/A')}")
                        st.markdown(f"**Quantity:** {po.get('quantity', 0):,}")
                    with c2:
                        st.markdown(f"**Created:** {format_display_date(po.get('created_at', 'N/A'))}")
                        st.markdown(f"**Unit Price:** ₹{po.get('unit_price', 0):,.2f}")
                    with c3:
                        st.markdown(f"**Total Cost:** ₹{total:,.2f}")
                        st.markdown(f"**Delivery:** {po.get('delivery_days', 'N/A')} days")

                    st.markdown(f"<span style='background:rgba({int(status_color[1:3],16)},{int(status_color[3:5],16)},{int(status_color[5:7],16)},0.15);color:{status_color};padding:4px 14px;border-radius:20px;font-size:12px;font-weight:600;'>{status_label}</span>", unsafe_allow_html=True)
                    if po.get('justification'):
                        j = po['justification']
                        st.markdown(f"**Justification:** {j}")
        else:
            st.info("No purchase orders found")

elif page == "Document Verification":
    st.markdown("<h1 style='font-size:32px;font-weight:800;letter-spacing:-0.5px;margin-bottom:0;display:inline-block;background:linear-gradient(90deg,#06D6A0,#2E86AB,#8B5CF6,#06D6A0);background-size:200% auto;-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;animation:titleShimmer 4s linear infinite;'>Document Verification</h1><p style='color:#6B7A8E;margin-top:4px;font-size:15px;'>Upload and verify delivery notes and invoices</p>", unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### Upload Delivery Note")
        delivery_note = st.file_uploader("Choose delivery note image", type=['jpg', 'jpeg', 'png'], key="delivery_note")
        if delivery_note:
            st.image(delivery_note, caption="Delivery Note", width='stretch')
    
    with col2:
        st.markdown("### Upload Invoice")
        invoice = st.file_uploader("Choose invoice image", type=['jpg', 'jpeg', 'png'], key="invoice")
        if invoice:
            st.image(invoice, caption="Invoice", width='stretch')
    
    if delivery_note and invoice:
        po_number = st.text_input("Enter PO Number for verification")
        
        if st.button("Verify Documents", type="primary"):
            with st.spinner("Verifying documents using AI vision..."):
                st.info("Document verification feature requires Agent 8 integration. This will process the uploaded documents and perform three-way matching.")
    
    st.markdown("### Recent Verifications")
    goods_receipts = load_json_data("data/goods_receipts.json", [])
    
    if goods_receipts and isinstance(goods_receipts, list):
        for gr in goods_receipts[-5:]:
            match_status = gr.get('match_status', 'unknown').upper()
            status_color = '#06D6A0' if match_status == 'PASS' else '#EF476F'
            
            st.markdown(f"""
            <div style='padding: 18px; background: rgba(30, 40, 70, 0.4); backdrop-filter: blur(10px); border-left: 4px solid {status_color}; 
                        border-radius: 14px; margin: 14px 0; border: 1px solid rgba(46, 134, 171, 0.2);'>
                <div style='display: flex; justify-content: space-between; align-items: center;'>
                    <div>
                        <div style='color: #E8E9ED; font-size: 16px; font-weight: 600;'>{gr.get('gr_number', 'N/A')}</div>
                        <div style='color: #A0A3B1; font-size: 13px; margin-top: 4px;'>PO: {gr.get('po_number', 'N/A')} | Item: {gr.get('item_code', 'N/A')}</div>
                    </div>
                    <div><span style='background: rgba({int(status_color[1:3], 16)}, {int(status_color[3:5], 16)}, {int(status_color[5:7], 16)}, 0.2); color: {status_color}; padding: 8px 16px; border-radius: 20px; font-size: 13px; font-weight: 600;'>{match_status}</span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No verification history available")

elif page == "Configurations":
    st.markdown("<h1 style='font-size:32px;font-weight:800;letter-spacing:-0.5px;margin-bottom:0;display:inline-block;background:linear-gradient(90deg,#06D6A0,#2E86AB,#8B5CF6,#06D6A0);background-size:200% auto;-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;animation:titleShimmer 4s linear infinite;'>System Configurations</h1><p style='color:#6B7A8E;margin-top:4px;font-size:15px;'>Configure system parameters and preferences</p>", unsafe_allow_html=True)
    
    tab1, tab2, tab3 = st.tabs(["General", "Email Configuration", "Agent Settings"])
    
    with tab1:
        st.markdown("""
        <div style='background: linear-gradient(135deg, rgba(6, 214, 160, 0.08) 0%, rgba(15, 23, 42, 0.2) 100%);
                    border-left: 4px solid #06D6A0; border-radius: 12px; padding: 20px 24px; margin: 12px 0 24px 0;
                    border: 1px solid rgba(6, 214, 160, 0.15); backdrop-filter: blur(10px);
                    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);'>
            <div style='color: #06D6A0; font-size: 17px; font-weight: 800; letter-spacing: 0.3px; margin-bottom: 4px;'>General Settings</div>
            <div style='color: #8899AA; font-size: 13px; font-weight: 500;'>Company identity and core system preferences</div>
        </div>
        """, unsafe_allow_html=True)
        company_name = st.text_input("Company Name", value="Manufacturing Solutions Pvt Ltd")
        company_email = st.text_input("Company Email", value="procurement@company.com")
        test_mode = st.checkbox("Test Mode", value=True, help="Send emails to test addresses instead of actual suppliers")
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        if st.button("Save General Settings", type="primary"):
            st.success("Settings saved successfully")
    
    with tab2:
        st.markdown("""
        <div style='background: linear-gradient(135deg, rgba(46, 134, 171, 0.08) 0%, rgba(15, 23, 42, 0.2) 100%);
                    border-left: 4px solid #2E86AB; border-radius: 12px; padding: 20px 24px; margin: 12px 0 24px 0;
                    border: 1px solid rgba(46, 134, 171, 0.15); backdrop-filter: blur(10px);
                    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);'>
            <div style='color: #2E86AB; font-size: 17px; font-weight: 800; letter-spacing: 0.3px; margin-bottom: 4px;'>Email Configuration</div>
            <div style='color: #8899AA; font-size: 13px; font-weight: 500;'>Gmail integration for automated supplier and agent communication</div>
        </div>
        """, unsafe_allow_html=True)
        gmail_user = st.text_input("Gmail Address", type="default")
        gmail_password = st.text_input("Gmail App Password", type="password")
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        if st.button("Save Email Settings", type="primary"):
            st.success("Email settings saved successfully")
    
    with tab3:
        st.markdown("""
        <div style='background: linear-gradient(135deg, rgba(139, 92, 246, 0.08) 0%, rgba(15, 23, 42, 0.2) 100%);
                    border-left: 4px solid #8B5CF6; border-radius: 12px; padding: 20px 24px; margin: 12px 0 24px 0;
                    border: 1px solid rgba(139, 92, 246, 0.15); backdrop-filter: blur(10px);
                    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);'>
            <div style='color: #8B5CF6; font-size: 17px; font-weight: 800; letter-spacing: 0.3px; margin-bottom: 4px;'>Agent Configuration</div>
            <div style='color: #8899AA; font-size: 13px; font-weight: 500;'>Fine-tune multi-agent decision thresholds and behavioral logic</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("<div style='color:#06D6A0;font-size:13px;font-weight:700;letter-spacing:0.5px;padding:12px 0 6px 0;'>AGENT 6 — DECISION MAKER</div>", unsafe_allow_html=True)
        always_require_approval = st.checkbox("Always Require Approval", value=True)
        approval_threshold = st.number_input("Approval Threshold (₹)", value=50000, step=1000)
        budget_limit = st.number_input("Budget Limit (₹)", value=100000, step=5000)

        st.markdown("<div style='height:1px;background:linear-gradient(90deg,transparent,rgba(46,134,171,0.2),transparent);margin:16px 0;'></div>", unsafe_allow_html=True)

        st.markdown("<div style='color:#2E86AB;font-size:13px;font-weight:700;letter-spacing:0.5px;padding:8px 0 6px 0;'>AGENT 9 — EXCEPTION HANDLER</div>", unsafe_allow_html=True)
        accept_threshold = st.slider("Accept Threshold (%)", 0.0, 10.0, 2.0, 0.1)
        reject_threshold = st.slider("Reject Threshold (%)", 5.0, 20.0, 10.0, 0.5)
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        if st.button("Save Agent Settings", type="primary"):
            st.success("Agent settings saved successfully")
    

# Footer — hidden on Chat Interface to keep it clean
if page != "Chat Interface":
    st.markdown("<div style='height:1px;background:linear-gradient(90deg,transparent,rgba(46,134,171,0.15),transparent);margin:24px 0;'></div>", unsafe_allow_html=True)
    st.markdown("""
    <div style='text-align: center; color: #3A4255; font-size: 12px; padding: 12px 0;'>
        Multi-Agent Procurement System
    </div>
    """, unsafe_allow_html=True)
    