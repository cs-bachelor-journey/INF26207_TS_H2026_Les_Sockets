import configparser
import time
import socket
import struct
import sys
import json
import os

# importation du module de protocol
from protocol import (
    HEADER_SIZE,
    MSG_ACK, MSG_BYE, MSG_BYE_ACK, MSG_DATA, MSG_DATA_ACK,
    MSG_ERR, MSG_FIN, MSG_FIN_ACK, MSG_LS, MSG_LS_RESP,
    MSG_NACK, MSG_PUT, MSG_PUT_ACK, MSG_RESUME, MSG_RES_ACK,
    MSG_SYN, MSG_SYN_ACK,
    build_packet, checksum, msg_name, parse_packet,
)

# lecture de la configuration 
_cfg = configparser.ConfigParser()
_cfg.read("config.ini")

FIABILITE = _cfg.getfloat("RESEAU", "fiabilite", fallback=0.95)
TAUX_CORRUPTION = _cfg.getfloat("RESEAU", "taux_corruption", fallback=0.02)
TIMEOUT = _cfg.getfloat("RESEAU", "timeout", fallback=0.5)
MAX_REPRISES = _cfg.getint("RESEAU", "max_reprises", fallback=5)
CLIENT_MSS = _cfg.getint("CONNEXION", "client_mss_propose", fallback=1024)
N_PROPOSE = _cfg.getint("CONNEXION", "n_propose", fallback=4)
PORT_SERVEUR = _cfg.getint("SERVEUR", "port", fallback=4242)
DOSSIER_FICHIERS = os.path.join(os.path.dirname(__file__), _cfg.get("SERVEUR", "dossier_fichiers", fallback="tests"))

# Taille maximale d'un datagramme UDP qu'on peut recevoir
UDP_BUF_MAX = 65535


def log(msg: str) -> None:
    """Affiche un message horodaté."""
    print(f"[CLIENT  {time.strftime('%H:%M:%S')}] {msg}")

# Classe Client
class Client: 
    """
    Encapsule l'état d'une session client : socket, adresse du serveur,
    paramètres négociés (MSS, N).
    """
    
    def __init__(self):
        self.sock = None
        self.addr_serveur = None # (IP, port) du serveur
        self.mss = None # Taille max du payload d'un segment
        self.n = None 
    
    # Connexion
    def connecter(self, ip):
        """
        Crée le socket usocket et effectue le Three-Way Handshake.
        """
        
        if self.sock is not None:
            log("Déjà connecté, impossible de se connecter à nouveau.")
            return False

        try:
            from usocket import usocket as USocket
        except ImportError:
            log("ERREUR : impossible d'importer usocket. Assurez-vous que usocket.pyc est présent.")
            return False
        
        # Création du socket UDP
        self.sock = USocket(family=socket.AF_INET, type=socket.SOCK_DGRAM,fiabilite=FIABILITE, taux_corruption=TAUX_CORRUPTION)
        self.addr_serveur = (ip, PORT_SERVEUR)
        self.sock.settimeout(TIMEOUT)
        
        log(f"Socket créé, tentative de connexion à {self.addr_serveur}...")
        
        # Etape 1 : envoi du SYN 
        payload_syn = struct.pack("!HH", CLIENT_MSS, N_PROPOSE)
        for tentative in range(MAX_REPRISES):
            self.sock.sendto(build_packet(MSG_SYN, seq=0, payload=payload_syn), self.addr_serveur)
            
            try:
                data, _ = self.sock.recvfrom(UDP_BUF_MAX)
                header, payload = parse_packet(data)
                if header["type"] == MSG_SYN_ACK:
                    # Etape 2 : réception du SYN-ACK, analyse de la proposition du serveur
                    if len(payload) >= 4:
                        self.mss, self.n = struct.unpack("!HH", payload[:4])
                        log(f"SYN-ACK reçu du serveur – MSS proposé={self.mss}, N proposé={self.n}")
                        break
            except socket.timeout:
                log(f"Timeout SYN (tentative {tentative + 1}/{MAX_REPRISES})")
            except ValueError as exc:
                log(f"SYN-ACK invalide : {exc}")
        else:
            log("Échec du handshake : pas de SYN-ACK reçu après plusieurs tentatives.")
            self.sock = None
            self.addr_serveur = None
            return False

        # Etape 3 : envoi du ACK de connexion
        self.sock.sendto(build_packet(MSG_ACK, seq=0, ack=1), self.addr_serveur)
        log("ACK de connexion envoyé, handshake terminé.")
        return True
    
    # Déconnexion
    def deconnecter(self):
        """
        Envoie un BYE et ferme le socket.
        """
        if self.sock is None:
            log("Pas connecté, impossible de se déconnecter.")
            return
        
        # Envoi du BYE
        self.sock.sendto(build_packet(MSG_BYE, seq=0), self.addr_serveur)
        
        # Attente du BYE-ACK
        try:
            data, _ = self.sock.recvfrom(UDP_BUF_MAX)
            header, _ = parse_packet(data)
            if header["type"] == MSG_BYE_ACK:
                log("BYE-ACK reçu du serveur, déconnexion réussie.")
            else:
                log(f"Réponse inattendue au BYE : {msg_name(header['type'])}")
        except socket.timeout:
            log("Timeout en attente du BYE-ACK, fermeture du socket malgré tout.")
        
        self.sock.close()
        self.sock = None
        self.addr_serveur = None
        self.mss = None
        self.n = None
        log("Socket fermé, client déconnecté.")       

    # commande ls 
    def lister(self):
        """
        Envoie une commande LS et affiche la liste des fichiers disponibles pour le client.
        """
        if not self._verifier_connexion():
            return
        
        # Envoi du LS
        self.sock.sendto(build_packet(MSG_LS, seq=0), self.addr_serveur)
        self.sock.settimeout(TIMEOUT * MAX_REPRISES)
        
        # Attente de la réponse LS_RESP
        try:
            data, _ = self.sock.recvfrom(UDP_BUF_MAX)
            header, payload = parse_packet(data)
            if header["type"] == MSG_LS_RESP:
                # Affichage de la liste des fichiers
                fichiers = json.loads(payload.decode("utf-8"))
                if fichiers:
                    print("Fichiers disponibles :")
                    for f in fichiers:
                        print(f"  {f}")
                else:
                    print("Aucun fichier disponible.")
            else:
                log(f"Réponse inattendue au LS : {msg_name(header['type'])}")
        except socket.timeout:
            log("Timeout : pas de réponse du serveur pour LS.")
        except ValueError as exc:
            log(f"Réponse LS invalide : {exc}")   
    
    # commande put <fichier>
    def envoyer_fichier(self, chemin: str, offset_depart: int = 0) -> bool:
        """
        Envoie un fichier au serveur par blocs de N segments.

        Chaque segment contient au plus MSS octets de payload.
        Après chaque bloc de N segments, on attend un DATA_ACK.
        En cas de timeout ou NACK, on retransmet le bloc (jusqu'à MAX_REPRISES fois).
        À la fin, on envoie FIN et on attend FIN_ACK pour vérifier l'intégrité.

        Args:
            chemin        : chemin local du fichier à envoyer
            offset_depart : octets déjà transmis (reprise), 0 pour un nouveau transfert

        Returns:
            True si le transfert réussit, False sinon.
        """
        if not self._verifier_connexion():
            return False

        if os.path.isfile(chemin):
            chemin_fichier = chemin
        elif os.path.isfile(os.path.join(DOSSIER_FICHIERS, chemin)):
            chemin_fichier = os.path.join(DOSSIER_FICHIERS, chemin)
        else:
            log(f"Fichier introuvable : '{chemin}'")
            log(f"Recherche dans : {DOSSIER_FICHIERS}/")
            return False

        nom_fichier   = os.path.basename(chemin_fichier)
        taille_totale = os.path.getsize(chemin_fichier)

        log(f"Envoi de '{nom_fichier}' ({taille_totale} octets, offset={offset_depart})")

        # ── Annonce PUT (ou RESUME) ─────────────────────────────────────────
        if offset_depart == 0:
            # Nouveau transfert : payload = taille (8 o) + nom_fichier
            payload_put = struct.pack("!Q", taille_totale) + nom_fichier.encode("utf-8")
            msg_annonce = MSG_PUT
            msg_rep_ok  = MSG_PUT_ACK
        else:
            # Reprise : même structure, type différent
            payload_put = struct.pack("!Q", taille_totale) + nom_fichier.encode("utf-8")
            msg_annonce = MSG_RESUME
            msg_rep_ok  = MSG_RES_ACK

        # Envoi de l'annonce avec attente d'acquittement
        self.sock.settimeout(TIMEOUT)
        for tentative in range(MAX_REPRISES):
            self.sock.sendto(build_packet(msg_annonce, payload=payload_put), self.addr_serveur)
            try:
                data, _ = self.sock.recvfrom(UDP_BUF_MAX)
                hdr, payload_rep = parse_packet(data)
                if hdr["type"] == msg_rep_ok:
                    if msg_annonce == MSG_RESUME and len(payload_rep) >= 8:
                        # Récupération de l'offset confirmé par le serveur
                        offset_depart = struct.unpack("!Q", payload_rep[:8])[0]
                        log(f"Reprise confirmée à l'offset {offset_depart} octets")
                    break
                elif hdr["type"] == MSG_ERR:
                    log(f"Serveur a refusé : {payload_rep.decode('utf-8', errors='replace')}")
                    return False
            except socket.timeout:
                log(f"Timeout annonce (tentative {tentative + 1}/{MAX_REPRISES})")
        else:
            log("Le serveur n'a pas répondu à l'annonce → abandon.")
            return False

        # ── Envoi des segments ──────────────────────────────────────────────
        with open(chemin_fichier, "rb") as f:
            f.seek(offset_depart)
            seq = offset_depart // self.mss   # Numéro de séquence du premier segment restant
            octets_envoyes = offset_depart

            while octets_envoyes < taille_totale:
                # Construction du bloc courant (au plus N segments)
                bloc: list[tuple[int, bytes]] = []  # (seq, payload)
                for _ in range(self.n):
                    chunk = f.read(self.mss)
                    if not chunk:
                        break
                    bloc.append((seq, chunk))
                    seq += 1

                if not bloc:
                    break

                # Envoi du bloc avec retransmission en cas d'échec
                ack_recu = False
                octets_bloc = sum(len(chunk) for _, chunk in bloc)  # Taille réelle du bloc
                for tentative in range(MAX_REPRISES):
                    # Envoi de chaque segment du bloc
                    for s, chunk in bloc:
                        self.sock.sendto(
                            build_packet(MSG_DATA, seq=s, payload=chunk),
                            self.addr_serveur,
                        )

                    # Attente du DATA_ACK pour ce bloc
                    try:
                        data, _ = self.sock.recvfrom(UDP_BUF_MAX)
                        hdr, _ = parse_packet(data)

                        if hdr["type"] == MSG_DATA_ACK:
                            octets_envoyes += octets_bloc
                            pct = 100 * octets_envoyes / taille_totale
                            print(
                                f"\r  Progression : {octets_envoyes}/{taille_totale} "
                                f"({pct:.1f}%)  ",
                                end="",
                                flush=True,
                            )
                            ack_recu = True
                            break
                        elif hdr["type"] == MSG_NACK:
                            log(f"NACK reçu (tentative {tentative + 1}) → retransmission du bloc")

                    except socket.timeout:
                        log(f"Timeout DATA_ACK (tentative {tentative + 1}/{MAX_REPRISES})")
                    except ValueError as exc:
                        log(f"DATA_ACK invalide : {exc}")

                if not ack_recu:
                    print()
                    log(f"Bloc non acquitté après {MAX_REPRISES} tentatives → abandon.")
                    return False

        print()   # Nouvelle ligne après la progression

        # ── Envoi du FIN ────────────────────────────────────────────────────
        log("Envoi FIN…")

        # Calcul du checksum du fichier complet pour vérification côté client
        with open(chemin_fichier, "rb") as f:
            checksum_local = checksum(f.read())

        for tentative in range(MAX_REPRISES):
            self.sock.sendto(build_packet(MSG_FIN, seq=seq), self.addr_serveur)
            try:
                data, _ = self.sock.recvfrom(UDP_BUF_MAX)
                hdr, payload_fin = parse_packet(data)

                if hdr["type"] == MSG_FIN_ACK:
                    # Vérification du checksum renvoyé par le serveur
                    if len(payload_fin) >= 12:
                        chk_serveur, taille_serveur = struct.unpack("!IQ", payload_fin[:12])
                        if chk_serveur == checksum_local and taille_serveur == taille_totale:
                            log(
                                f"Transfert réussi et intègre ! "
                                f"CRC32={checksum_local:#010x}, {taille_totale} octets."
                            )
                        else:
                            log(
                                f"AVERTISSEMENT : discordance ! "
                                f"CRC32 client={checksum_local:#010x} "
                                f"vs serveur={chk_serveur:#010x}"
                            )
                    else:
                        log("FIN_ACK reçu (pas de checksum dans le payload).")
                    return True

            except socket.timeout:
                log(f"Timeout FIN (tentative {tentative + 1}/{MAX_REPRISES})")
            except ValueError as exc:
                log(f"FIN_ACK invalide : {exc}")

        log("FIN non acquitté → transfert possiblement incomplet.")
        return False
   
    # commande resume <fichier>    
    def reprendre_fichier(self, chemin: str) -> bool:
        """
        Reprend le transfert d'un fichier interrompu.
        Le serveur indique l'offset à partir duquel reprendre.
        """
        # Note : offset_depart=-1 est un marqueur pour déclencher la négociation de l'offset réel avec le serveur
        return self.envoyer_fichier(chemin, offset_depart=-1)

    
    # Méthode utilitaire pour vérifier la connexion avant d'envoyer une commande
    def _verifier_connexion(self):
        """Vérifie que le client est connecté avant d'envoyer une commande."""
        if self.sock is None or self.addr_serveur is None:
            log("Non connecté. Utilisez 'open <adresse_ip>' d'abord.")
            return False
        return True
    
# Boucle console principale
def main():
    client = Client()
    print("================")
    print("=    Client    =")
    print("================")
    print("Commandes disponibles :")
    print("  open <IP> - se connecter au serveur à l'adresse IP spécifiée")
    print("  ls - lister les fichiers disponibles sur le serveur")
    print("  put <fichier> - envoyer un fichier au serveur")
    print("  resume <fichier> - reprendre l'envoi d'un fichier interrompu")
    print("  bye - se déconnecter du serveur")
    print("================")
    print()
    
    while True:
        # Lecture de la commande utilisateur
        try:
            ligne = input("Entrez une commande: ").strip()
        except EOFError:
            print("\nFin de l'entrée détectée, fermeture du client.")
            break
        except KeyboardInterrupt:
            print("\nInterruption clavier détectée, fermeture du client.")
            break
            
        if not ligne:
            continue
        
        parties = ligne.split()
        commande = parties[0].lower()
        
        # Traitement des commandes
       
        # - commande open <IP>
        if commande == "open":
            if len(parties) != 2:
                log("Usage : open <IP>")
                continue
            else: 
                ip = parties[1]
                if client.connecter(ip):
                    log(f"Connecté au serveur {ip}:{PORT_SERVEUR} avec MSS={client.mss} et N={client.n}.")
                else:
                    log("Échec de la connexion.")
                    
        # - commande ls
        elif commande == "ls":
            client.lister()
            
        # - commande put <fichier>
        elif commande == "put":
            if len(parties) < 2:
                print("Usage : put <chemin_fichier>")
            else:
                chemin = " ".join(parties[1:])
                client.envoyer_fichier(chemin)
                
        # - commande resume <fichier>
        elif commande == "resume":
            if len(parties) < 2:
                print("Usage : resume <chemin_fichier>")
            else:
                chemin = " ".join(parties[1:])
                # Demande au serveur l'offset, puis reprend depuis là
                client.envoyer_fichier(chemin, offset_depart=-1)
                
        # - commande bye
        elif commande == "bye":
            client.deconnecter()
            
        else:
            log(f"Commande inconnue : {commande}")
            log("Commandes disponibles : open <IP>, ls, put <fichier>, resume <fichier>, bye")

if __name__ == "__main__":
    main()