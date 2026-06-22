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
    # Hide dotfiles/dotdirs by default, but keep the toggle so they can be shown.
    # The variables only exist once Tk's file-dialog code is autoloaded, which the
    # (deliberately failing) probe call below forces.
    try:
        root.tk.call("tk_getOpenFile", "-badoption")
    except tkinter.TclError:
        pass
    try:
        root.tk.call("set", "::tk::dialog::file::showHiddenBtn", "1")
        root.tk.call("set", "::tk::dialog::file::showHiddenVar", "0")
    except tkinter.TclError:
        pass
    try:
        # mustexist=False lets the user type a new folder name; the caller mkdir's it.
        path = filedialog.askdirectory(
            title="Choose backup destination", mustexist=False
        )
    finally:
        root.destroy()
    if path:
        sys.stdout.write(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
