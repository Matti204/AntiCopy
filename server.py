import socket
import struct
import json
import threading as th
import time

HOST = "0.0.0.0"
PORT = 5000

esclusione = []
clients = []
clients_lock = th.Lock()

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen()


def invia_lista(sock, lista):
    dati = json.dumps(lista).encode("utf-8")
    lunghezza = struct.pack("!I", len(dati))
    sock.sendall(lunghezza)
    sock.sendall(dati)


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


def ricevi_linea(sock, buffer):
    """
    Legge dal socket finché non trova '\n'.
    Ritorna (linea, buffer_aggiornato).
    Se il client si disconnette, ritorna (None, buffer).
    """
    while "\n" not in buffer:
        data = sock.recv(1024)
        if not data:
            return None, buffer
        buffer += data.decode("utf-8", errors="ignore")

    linea, buffer = buffer.split("\n", 1)
    return linea.strip(), buffer


def heartbeat_checker(last_seen, stop_event, conn, utente):
    while not stop_event.is_set():
        time.sleep(2)

        if time.time() - last_seen[0] > 10:
            print(f"Client {utente} offline per timeout")
            stop_event.set()
            try:
                conn.close()
            except:
                pass
            break


def main_thread(conn, addr):
    utente = None
    buffer = ""
    stop_event = th.Event()
    last_seen = [time.time()]

    try:
        # Ricezione nome utente come prima riga
        utente, buffer = ricevi_linea(conn, buffer)
        if not utente:
            print(f"Connessione chiusa prima di ricevere il nome: {addr}")
            return

        print(f"Client connesso con nome {utente}")

        invia_lista(conn, esclusione)
        print("Lista di esclusione inviata")

        with clients_lock:
            clients.append(utente)
            print("Client connessi:", clients)
            print("Numero client connessi:", len(clients))

        hb_thread = th.Thread(
            target=heartbeat_checker,
            args=(last_seen, stop_event, conn, utente),
            daemon=True
        )
        hb_thread.start()

        while not stop_event.is_set():
            try:
                conn.settimeout(2)
                data = conn.recv(1024)

                if not data:
                    print(f"Client {utente} disconnesso")
                    break

                last_seen[0] = time.time()
                buffer += data.decode("utf-8", errors="ignore")

                while "\n" in buffer:
                    msg, buffer = buffer.split("\n", 1)
                    msg = msg.strip()

                    if not msg:
                        continue

                    if msg.strip().replace("\r", "") == "PING":
                        last_seen[0] = time.time()
                    else:
                        print(msg)

            except socket.timeout:
                continue

    except ConnectionResetError:
        print(f"Client {utente if utente else addr} chiuso brutalmente")

    except Exception as e:
        print(f"Errore con {utente if utente else addr}: {e}")

    finally:
        stop_event.set()

        with clients_lock:
            if utente in clients:
                clients.remove(utente)
            print("Numero client connessi:", len(clients))

        try:
            conn.close()
        except:
            pass

        print(f"Connessione chiusa: {addr}")


if __name__ == "__main__":
    regola = input("Inserisci nuova app da escludere (stop per fermare): ").strip()

    while regola.lower() != "stop":
        if regola:
            esclusione.append(regola)
        regola = input("Inserisci nuova app da escludere (stop per fermare): ").strip()

    print("Programmi esclusi:", esclusione)
    print("Server in ascolto")

    while True:
        conn, addr = server.accept()
        thread = th.Thread(target=main_thread, args=(conn, addr), daemon=True)
        thread.start()