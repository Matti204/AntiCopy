import time
import json
from datetime import datetime
import getpass
import struct
import socket
import threading as th

import psutil
import win32gui
import win32process
#PRODUZIONE
HOST = "31.14.140.197"
#HOST = "127.0.0.1"
PORT = 5000

MAX_TENTATIVI = 3
ATTESA_TENTATIVI = 5
ATTESA_PRIMA_RICONNESSIONE = 10
INTERVALLO_PING = 3


def ricevi_lista(sock):
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

    return json.loads(dati.decode("utf-8"))


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


def invia_linea(sock, testo, send_lock):
    with send_lock:
        sock.sendall((testo + "\n").encode("utf-8"))


def connetti_con_tentativi(host, port, max_tentativi=3, attesa=5):
    for tentativo in range(1, max_tentativi + 1):
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.connect((host, port))
            return client
        except Exception as e:
            print(f"Tentativo {tentativo}/{max_tentativi} fallito: {e}")
            try:
                client.close()
            except Exception:
                pass

            if tentativo < max_tentativi:
                print(f"Riprovo tra {attesa} secondi...")
                time.sleep(attesa)

    return None


def heartbeat(sock, stop_event, dead_event, send_lock):
    while not stop_event.is_set():
        try:
            invia_linea(sock, "PING", send_lock)
            time.sleep(INTERVALLO_PING)
        except Exception:
            dead_event.set()
            stop_event.set()
            break


def sessione_client(sock):
    utente = getpass.getuser()
    send_lock = th.Lock()
    stop_event = th.Event()
    dead_event = th.Event()

    invia_linea(sock, utente, send_lock)

    esclusi = ricevi_lista(sock)
    if esclusi is None:
        raise ConnectionError("Lista di esclusione non ricevuta dal server")

    print("Connesso al server")
    print("Lista di esclusione:", esclusi)

    hb_thread = th.Thread(
        target=heartbeat,
        args=(sock, stop_event, dead_event, send_lock),
        daemon=True
    )
    hb_thread.start()

    app_old = ""
    titolo_old = ""

    try:
        while not stop_event.is_set():
            app, titolo = get_app_attiva()

            if app and (app != app_old or titolo != titolo_old) and app not in esclusi:
                messaggio = f"{datetime.now().strftime('%H:%M:%S')} - {utente} - {app} - {titolo}"
                print(messaggio)
                invia_linea(sock, messaggio, send_lock)

                app_old = app
                titolo_old = titolo

            time.sleep(0.2)

    except KeyboardInterrupt:
        print("\nChiuso correttamente dall'utente.")
        stop_event.set()
        raise

    except Exception as e:
        print(f"Errore durante la sessione: {e}")
        dead_event.set()
        stop_event.set()

    finally:
        stop_event.set()
        try:
            sock.close()
        except Exception:
            pass

    return dead_event.is_set()


if __name__ == "__main__":
    try:
        # Connessione iniziale: 3 tentativi, 1 ogni 5 secondi
        client = connetti_con_tentativi(HOST, PORT, MAX_TENTATIVI, ATTESA_TENTATIVI)

        if client is None:
            print("Impossibile connettersi al server. Chiusura del client.")
            raise SystemExit

        while True:
            try:
                crashato = sessione_client(client)

                if not crashato:
                    break

                print(f"Connessione persa. Attendo {ATTESA_PRIMA_RICONNESSIONE} secondi prima di riprovare...")
                time.sleep(ATTESA_PRIMA_RICONNESSIONE)

                client = connetti_con_tentativi(HOST, PORT, MAX_TENTATIVI, ATTESA_TENTATIVI)

                if client is None:
                    print("Riconnessione fallita dopo 3 tentativi. Chiusura del client.")
                    break

            except KeyboardInterrupt:
                break

            except Exception as e:
                print(f"Errore critico: {e}")
                print(f"Attendo {ATTESA_PRIMA_RICONNESSIONE} secondi prima di riprovare...")
                time.sleep(ATTESA_PRIMA_RICONNESSIONE)

                client = connetti_con_tentativi(HOST, PORT, MAX_TENTATIVI, ATTESA_TENTATIVI)

                if client is None:
                    print("Riconnessione fallita dopo 3 tentativi. Chiusura del client.")
                    break

    finally:
        try:
            client.close()
        except Exception:
            pass