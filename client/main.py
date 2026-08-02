import argparse
from ui import NyxTUI, ReplUI
from commands import CommandContext, CommandRegistry, registry
from config import load_settings

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repl", action="store_true", help="use REPL UI")
    parser.add_argument("--tui", action="store_true", help="use Textual TUI")
    args = parser.parse_args()

    ctx = CommandContext()
    ctx.load_settings()

    if args.repl:
        ReplUI(ctx).run()
    else:
        NyxTUI(ctx=ctx).run()

if __name__ == "__main__":
    main()