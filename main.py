import time
import json
import os
from datetime import datetime
from collections import defaultdict
import getpass
import struct
import socket
import psutil
import win32gui
import win32process

HOST = "127.0.0.1"   # IP del server
PORT = 5000


def invia_lista(sock, lista):
    dati = json.dumps(lista).encode("utf-8")

    # invia prima la lunghezza (4 byte)
    lunghezza = struct.pack("!I", len(dati))

    sock.sendall(lunghezza)
    sock.sendall(dati)


def ricevi_lista(sock):
    # riceve la lunghezza
    raw_len = sock.recv(4)
    if not raw_len:
        return None


    lunghezza = struct.unpack("!I", raw_len)[0]

    dati = b""

    while len(dati) < lunghezza:
        chunk = sock.recv(lunghezza - len(dati))
        if not chunk:
            return None
        dati += chunk

    lista = json.loads(dati.decode("utf-8"))

    return lista


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

esclusi = []

if __name__ == "__main__":

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    client.connect((HOST, PORT))
    print("Connesso al server")
    client.sendall(getpass.getuser().encode("utf-8"))

    esclusi = ricevi_lista(client)
    print("Lista di esclusione: ", esclusi)
    app_old = ""
    titolo_old = ""
    try:
        while True:
            app, titolo = get_app_attiva()
            if app:
                utente = getpass.getuser()
                if (app != app_old or titolo != titolo_old) and app not in esclusi:
                    print(app)
                    messaggio = f"{datetime.now().strftime('%H:%M:%S')} - {utente} - {app} - {titolo}"
                    print(messaggio)
                    client.sendall(messaggio.encode("utf-8"))
                    app_old = app
                    titolo_old = titolo
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nChiuso correttamente.")

