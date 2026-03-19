import time
import json
import os
from datetime import datetime
from collections import defaultdict
import getpass

import psutil
import win32gui
import win32process


def get_app_attiva():
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None, None

    titolo = win32gui.GetWindowText(hwnd)

    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        processo = psutil.Process(pid)
        return processo.name(), titolo
    except Exception:
        return None, titolo

if __name__ == "__main__":
    try:
        while True:
            app, titolo = get_app_attiva()
            if app:
                utente = getpass.getuser()
                if app != "pycharm64.exe":
                    print(f"{datetime.now().strftime('%H:%M:%S')} - {utente} - {app} - {titolo}")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nChiuso correttamente.")

