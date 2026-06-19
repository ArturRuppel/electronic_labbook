"""Native folder picker for the backup destination.

Run as ``python -m eln.sdgl.folder_dialog`` so tkinter owns this process's main
thread. Prints the chosen absolute path to stdout, or nothing if cancelled or if
no display / Tk is available.
"""

import sys


def main():
    try:
        import tkinter
        from tkinter import filedialog
    except Exception:  # noqa: BLE001 — headless or no Tk: caller falls back to typed path
        return 1
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        path = filedialog.askdirectory(title="Choose backup destination")
    finally:
        root.destroy()
    if path:
        sys.stdout.write(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
