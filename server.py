import socket
import struct
import json
import threading as th

host = "0.0.0.0"
port = 5000

esclusione = []

clients = []

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((host, port))
server.listen()




def main_thread(conn, addr):

	utente = conn.recv(1024).decode("utf-8")
	print(f"Client connesso con nome {utente}")
	invia_lista(conn, esclusione)
	print("lista di esclusione inviata")
	clients.append(utente)
	print("Client connessi: ", clients)
	print("Numero client connessi: ", len(clients))

	while True:
		data = conn.recv(1024)
		if data:
			messaggio = data.decode("utf-8")
			print(messaggio)
		if not data:
			print(f"Client {utente} disconnesso")
			clients.remove(utente)
			print("Numero client connessi: ", len(clients))
			return




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

	lista = json.loads(dati.decode("utf-8"))
	return lista





if __name__ == "__main__":



	regola = input("Inserisci nuova app da escludere (stop per fermare)")

	while regola != "stop":
		esclusione.append(regola)
		regola = input("Inserisci nuova app da escludere (stop per fermare)")

	print("Programmi esclusi: ", esclusione)

	print("Server in ascolto")

	while True:
		conn, addr = server.accept()
		thread = th.Thread(target=main_thread, args=(conn, addr))
		thread.start()