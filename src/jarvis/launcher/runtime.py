"""Child entry point, always run inside the selected Jarvis installation."""

import argparse
import sys

from jarvis.ui.desktop_control import StdinDesktopControl


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Jarvis launcher runtime child.")
    parser.add_argument("--mode", choices=("assistant", "mcp"), required=True)
    parser.add_argument("--touchstrip", choices=("on", "off"), required=True)
    args = parser.parse_args(argv)
    if sys.stdin is None:
        raise RuntimeError("The launcher runtime requires its inherited command pipe.")

    # Import the application only in the child; an idle tray never loads it.
    from jarvis.app import main as run_jarvis

    command = ["--status-console"]
    if args.mode == "mcp":
        command.append("--mcp-mode")
    run_jarvis(
        command,
        desktop_control=StdinDesktopControl(
            sys.stdin, touchstrip_visible=args.touchstrip == "on"
        ),
        show_message_box=lambda message: print(message, file=sys.stderr),
    )


if __name__ == "__main__":
    main()
