"""cli.py — Command-line interface for the Procurement Assistant."""
import os
import sys

# Suppress noisy third-party warnings before any imports
os.environ['CREWAI_TELEMETRY_OPT_OUT'] = 'true'
os.environ['OTEL_SDK_DISABLED'] = 'true'
os.environ['ANONYMIZED_TELEMETRY'] = 'false'

import warnings
warnings.filterwarnings('ignore', category=ResourceWarning)
warnings.filterwarnings('ignore', module='statsmodels.*')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import re
import textwrap


# ── Terminal colors ─────────────────────────────────────────────────────────
class C:
    RESET  = '\033[0m'
    BOLD   = '\033[1m'
    DIM    = '\033[2m'
    CYAN   = '\033[96m'
    GREEN  = '\033[92m'
    BLUE   = '\033[94m'
    YELLOW = '\033[93m'
    WHITE  = '\033[97m'

WIDTH = 82


# ── Formatting helpers ──────────────────────────────────────────────────────

def _strip_md(text: str) -> str:
    """Convert basic markdown to terminal-readable text with color."""
    lines = text.split('\n')
    out = []
    for line in lines:
        s = line.strip()
        if s.startswith('### '):
            out.append(C.BOLD + C.GREEN + s[4:] + C.RESET)
        elif s.startswith('## '):
            out.append(C.BOLD + C.CYAN + s[3:] + C.RESET)
        elif s.startswith('# '):
            out.append(C.BOLD + C.BLUE + s[2:] + C.RESET)
        elif s.startswith(('- ', '* ')):
            out.append(f'  {C.CYAN}•{C.RESET} {s[2:]}')
        elif s == '---':
            out.append(C.DIM + '─' * WIDTH + C.RESET)
        else:
            # Inline formatting
            s = re.sub(r'\*\*(.+?)\*\*', C.BOLD + r'\1' + C.RESET, s)
            s = re.sub(r'\*(.+?)\*',     C.WHITE + r'\1' + C.RESET, s)
            s = re.sub(r'`(.+?)`',       C.CYAN  + r'\1' + C.RESET, s)
            out.append(s)
    return '\n'.join(out)


def _parse_pills(response: str):
    """Split AI response into body text and up to 3 pill labels."""
    parts = re.split(r'\n\s*===+\s*\n', response, maxsplit=1)
    if len(parts) == 2:
        pills = [l.strip() for l in parts[1].strip().splitlines() if l.strip()]
        return parts[0].strip(), pills[:3]
    return response.strip(), []


def _wrap(line: str, indent: int = 2) -> str:
    pad = ' ' * indent
    return textwrap.fill(
        line, width=WIDTH - indent,
        initial_indent=pad,
        subsequent_indent=pad,
        break_long_words=False,
        break_on_hyphens=False
    )


def _print_divider():
    print(C.DIM + '─' * WIDTH + C.RESET)


def _print_user(text: str):
    print(f"\n{C.BLUE}{C.BOLD}You{C.RESET}")
    print(C.BLUE + '  ' + text + C.RESET)


def _print_assistant(text: str, pills: list):
    print(f"\n{C.GREEN}{C.BOLD}⚡  Assistant{C.RESET}")
    cleaned = _strip_md(text)
    for line in cleaned.split('\n'):
        stripped = line.strip()
        if not stripped:
            print()
            continue
        # Already-colored lines (headings/bullets): print as-is with indent
        if any(code in line for code in [C.BOLD, C.CYAN, C.GREEN, C.DIM]):
            print('  ' + line)
        else:
            print(_wrap(stripped))

    if pills:
        print(f"\n  {C.DIM}Quick actions — type the number or the full text:{C.RESET}")
        for i, p in enumerate(pills, 1):
            print(f"  {C.CYAN}[{i}]{C.RESET}  {C.WHITE}{p}{C.RESET}")


def _print_header():
    bolt = '⚡'
    bar  = '─' * (WIDTH - 4)
    print('\n' + C.GREEN + C.BOLD + f'{bolt}  {bar}  {bolt}' + C.RESET)
    title = 'Procurement Assistant  —  CLI'
    pad   = (WIDTH - len(title)) // 2
    print(' ' * pad + C.BOLD + C.WHITE + title + C.RESET)
    hint  = 'type your message · pick a pill number · "exit" to quit'
    pad2  = (WIDTH - len(hint)) // 2
    print(' ' * pad2 + C.DIM + hint + C.RESET)
    print(C.GREEN + C.BOLD + f'{bolt}  {bar}  {bolt}' + C.RESET + '\n')


# ── Main loop ───────────────────────────────────────────────────────────────

def main():
    _print_header()

    print(f"{C.DIM}  Initializing agents…{C.RESET}", end='', flush=True)
    try:
        from agents.Agent0 import MasterOrchestrator
        orchestrator = MasterOrchestrator()
        print(f"\r{C.GREEN}  ✓ All agents ready.{C.RESET}{'  ' * 12}\n")
    except Exception as e:
        print(f"\r{C.YELLOW}  ⚠  Init error: {e}{C.RESET}\n")
        sys.exit(1)

    last_pills: list = []

    while True:
        try:
            raw = input(f"\n{C.CYAN}>{C.RESET} ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n\n{C.DIM}  Goodbye.{C.RESET}\n")
            break

        if not raw:
            continue

        # Exit commands
        if raw.lower() in ('exit', 'quit', 'bye', 'q'):
            print(f"\n{C.DIM}  Goodbye.{C.RESET}\n")
            break

        # Pill number shortcut
        if raw.isdigit() and last_pills:
            idx = int(raw) - 1
            if 0 <= idx < len(last_pills):
                raw = last_pills[idx]
                _print_user(raw)
            else:
                print(f"  {C.YELLOW}Enter a number between 1 and {len(last_pills)}.{C.RESET}")
                continue
        else:
            _print_user(raw)

        # Thinking indicator
        print(f"  {C.DIM}thinking…{C.RESET}", end='\r', flush=True)

        try:
            response = orchestrator.process_request(raw)
        except Exception as e:
            response = f"I encountered an error: {e}. Please try again."

        print(' ' * 30, end='\r')  # clear thinking line

        body, pills = _parse_pills(response)
        last_pills  = pills

        _print_assistant(body, pills)
        print()
        _print_divider()


if __name__ == '__main__':
    main()
    