import configparser
import time
import os
import socket
import sys
import struct
import json

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
SRV_MSS_PROPOSE = _cfg.getint("CONNEXION", "serveur_mss_propose", fallback=1024)
N_PROPOSE = _cfg.getint("CONNEXION", "n_propose", fallback=4)
HOST = _cfg.get("SERVEUR", "host", fallback="127.0.0.1")
PORT = _cfg.getint("SERVEUR", "port", fallback=4242)
DOSSIER_SAUV = _cfg.get("SERVEUR", "dossier_sauvegardes", fallback="sauvegardes")
DOSSIER_FICHIERS = _cfg.get("SERVEUR", "dossier_fichiers", fallback="tests")

# Taille maximale d'un datagramme UDP qu'on peut recevoir
UDP_BUF_MAX = 65535

def log(msg):
    """Affiche un message horodaté sur stdout."""
    print(f"[SERVEUR {time.strftime('%H:%M:%S')}] {msg}")

def envoyer(sock, paquet, addr):
    """Envoie un paquet de données à une adresse donnée."""
    sock.sendto(paquet, addr)

# Handshake de connexion
def handshake(sock, addr, syn_payload):
    """
    Complète le Three-Way Handshake côté serveur.
    """
        
    # Analyse de la proposition du client
    if len(syn_payload) >= 4:
        client_mss, client_n = struct.unpack("!HH", syn_payload[:4])
        log(f"Proposition du client : MSS={client_mss}, N={client_n}")
    else:
        log("Proposition du client invalide, utilisation des valeurs par défaut.")
        client_mss, client_n = SRV_MSS_PROPOSE, N_PROPOSE
        
    # Négociation des paramètres de connexion
    mss_negocie = min(client_mss, SRV_MSS_PROPOSE)
    n_negocie = min(client_n, N_PROPOSE)
        
    log(f"SYN reçu de {addr} – MSS client={client_mss}, N client={client_n}")
    log(f"Paramètres négociés : MSS={mss_negocie}, N={n_negocie}")
        
    # Envoi du SYN-ACK 
    payload_syn_ack = struct.pack("!HH", mss_negocie, n_negocie)
    envoyer(sock, build_packet(MSG_SYN_ACK,seq=0, ack=1, payload=payload_syn_ack), addr)
        
    # Attente du ACK du client
    sock.settimeout(TIMEOUT * MAX_REPRISES)
    for tentative in range(MAX_REPRISES):
        try:
            data, src = sock.recvfrom(UDP_BUF_MAX)
            if src != addr:
                log(f"Paquet reçu de {src} pendant handshake, ignoré (en attente de {addr}).")
                continue
            header, _ = parse_packet(data)
            if header["type"] == MSG_ACK:
                log(f"ACK de connexion reçu de {addr}, handshake terminé.")
                return {"mss": mss_negocie, "n": n_negocie}
        except socket.timeout:
            log(f"Timeout en attente du ACK de connexion (tentative {tentative + 1}/{MAX_REPRISES}), renvoi du SYN-ACK.")
            envoyer(sock, build_packet(MSG_SYN_ACK,seq=0, ack=1, payload=payload_syn_ack), addr)
        except ValueError as e:
            log(f"Paquet reçu pendant handshake invalide : {e}")
    
    log(f"Échec du handshake avec {addr} après {MAX_REPRISES} tentatives.")
    return None

# Traitement de la commande LS
def traiter_ls(sock, addr):
    """
    Traite une commande LS : envoie la liste des fichiers disponibles dans le dossier de sauvegardes.
    """
    os.makedirs(DOSSIER_FICHIERS, exist_ok=True)
    fichiers = sorted(os.listdir(DOSSIER_FICHIERS))
    payload = json.dumps(fichiers, ensure_ascii=False).encode("utf-8")
    envoyer(sock, build_packet(MSG_LS_RESP, payload=payload), addr)
    log(f"LS → {len(fichiers)} fichier(s) envoyé(s).")

# Traitement de la commande PUT
def recevoir_fichier(
    sock,
    addr,
    nom_fichier,
    taille_totale,
    mss,
    n,
    offset_depart = 0,
):
    """
    Reçoit un fichier par blocs de N segments, envoie des DATA_ACK après chaque bloc.

    Gestion des cas :
    - Corruption   → NACK envoyé, le client retransmet.
    - Doublons     → ignorés silencieusement (seq déjà vu).
    - Perte ACK    → le client retransmet le bloc, on renvoie le DATA_ACK.
    - Fin (FIN)    → on vérifie le checksum global et on envoie FIN_ACK.

    Le paramètre offset_depart permet de reprendre un transfert à partir d'un certain point (en cas de reprise).
    """
    os.makedirs(DOSSIER_SAUV, exist_ok=True)
    chemin = os.path.join(DOSSIER_SAUV, nom_fichier)

    # Mode d'ouverture : append binaire pour la reprise, write binaire sinon
    mode = "ab" if offset_depart > 0 else "wb"
    octets_recus = offset_depart   # Compteur des octets valides écrits

    # Ensemble des numéros de séquence déjà reçus (pour la détection de doublons)
    seqs_recus: set[int] = set()

    # Numéro de séquence du prochain bloc attendu
    # Chaque bloc couvre N segments, donc on avance de N à chaque bloc
    seq_attendu = offset_depart // mss   # segment depuis lequel on reprend

    sock.settimeout(None)  # Pas de timeout dans receive_fichier, on gère les timeouts manuellement

    with open(chemin, mode) as f:
        while True:
            # Réception d'un bloc de N segments 
            segments_du_bloc: dict[int, bytes] = {}  # seq → payload
            fin_fichier = False

            for _ in range(n):
                # On attend chaque segment du bloc courant
                tentatives_seg = 0
                while True:
                    try:
                        data, src = sock.recvfrom(UDP_BUF_MAX)
                    except socket.timeout:
                        # Timeout sur un segment : le client va retransmettre le bloc
                        # On sort de la boucle interne pour ré-acquitter ce qu'on a
                        break

                    if src != addr:
                        continue  # Paquet parasite

                    # Désérialisation
                    try:
                        hdr, payload = parse_packet(data)
                    except ValueError as exc:
                        # Checksum invalide ou paquet malformé → NACK
                        log(f"Segment corrompu : {exc} → NACK")
                        envoyer(sock, build_packet(MSG_NACK, ack=seq_attendu), addr)
                        tentatives_seg += 1
                        if tentatives_seg >= MAX_REPRISES:
                            log("Trop de corruptions consécutives → abandon.")
                            return False
                        continue

                    msg_type = hdr["type"]

                    # FIN de transfert
                    if msg_type == MSG_FIN:
                        fin_fichier = True
                        break

                    # Segment de données normal 
                    if msg_type == MSG_DATA:
                        seq = hdr["seq"]

                        if seq in seqs_recus:
                            # Doublon : on l'ignore et on renvoie le DATA_ACK précédent
                            log(f"Doublon détecté seq={seq} → ignoré")
                            envoyer(
                                sock,
                                build_packet(MSG_DATA_ACK, ack=seq_attendu),
                                addr,
                            )
                            continue

                        seqs_recus.add(seq)
                        segments_du_bloc[seq] = payload
                        break  # Segment valide reçu, on passe au suivant

                if fin_fichier:
                    break

            # Écriture ordonnée des segments du bloc
            for seq in sorted(segments_du_bloc.keys()):
                f.write(segments_du_bloc[seq])
                octets_recus += len(segments_du_bloc[seq])

            # Accusé de réception du bloc (seq_attendu mis à jour)
            seq_attendu += len(segments_du_bloc)

            if not fin_fichier:
                envoyer(sock, build_packet(MSG_DATA_ACK, ack=seq_attendu), addr)
                log(
                    f"Bloc acquitté : {octets_recus}/{taille_totale} octets "
                    f"({100*octets_recus/max(taille_totale,1):.1f}%)"
                )

            # Fin de fichier 
            if fin_fichier:
                log("FIN reçu – vérification de l'intégrité finale…")
                f.flush()
                break

    # Vérification de l'intégrité du fichier complet
    with open(chemin, "rb") as f:
        donnees_completes = f.read()

    checksum_final = checksum(donnees_completes)
    log(f"CRC32 final du fichier : {checksum_final:#010x} ({len(donnees_completes)} octets)")

    # Envoi du FIN_ACK avec le checksum calculé (le client peut le comparer)
    payload_fin = struct.pack("!IQ", checksum_final, len(donnees_completes))
    envoyer(sock, build_packet(MSG_FIN_ACK, payload=payload_fin), addr)

    if len(donnees_completes) != taille_totale:
        log(
            f"AVERTISSEMENT : taille reçue ({len(donnees_completes)}) "
            f"≠ taille attendue ({taille_totale})"
        )
        log(f"Transfert terminé avec avertissement (le client vérifiera le checksum).")
        return True

    log(f"Transfert de '{nom_fichier}' réussi et intègre.")
    return True
       
# Traitement de la commande resume
def traiter_resume(sock, addr, payload, mss):
    """
    Répond à une demande de reprise de transfert.

    Le payload contient le nom du fichier (UTF-8).
    Le serveur renvoie l'offset (nombre d'octets déjà reçus) via RES_ACK.

    Returns:
        (nom_fichier, offset_valide)
    """
    nom_fichier = payload.decode("utf-8").strip()
    chemin = os.path.join(DOSSIER_SAUV, nom_fichier)

    # Calcul du dernier bloc complet (multiple de mss)
    if os.path.exists(chemin):
        taille_actuelle = os.path.getsize(chemin)
        # On arrondit à un multiple de mss pour s'assurer que le dernier bloc est complet
        offset = (taille_actuelle // mss) * mss
    else:
        offset = 0

    log(f"RESUME '{nom_fichier}' → offset={offset} octets")
    # Le payload du RES_ACK contient l'offset sur 8 octets (uint64, big-endian)
    payload_res = struct.pack("!Q", offset)
    envoyer(sock, build_packet(MSG_RES_ACK, ack=offset, payload=payload_res), addr)
    return nom_fichier, offset

# Boucle principale du serveur

def main():
    log("Démarrage du serveur...")
    
    # Création du dossier de sauvegardes s'il n'existe pas
    os.makedirs(DOSSIER_SAUV, exist_ok=True)
    
    # Importation du socket non-fiable
    try:
        from usocket import usocket as USocket
    except ImportError:
        log("ERREUR : impossible d'importer usocket. Assurez-vous que usocket.pyc est présent.")
        sys.exit(1)
    
    # Création du socket UDP
    sock = USocket(family=socket.AF_INET, type=socket.SOCK_DGRAM, fiabilite=FIABILITE, taux_corruption=TAUX_CORRUPTION)
    
    sock.bind((HOST, PORT))
    log(f"Serveur démarré sur {HOST}:{PORT}")
    log(f"Fiabilité={FIABILITE}, Taux corruption={TAUX_CORRUPTION}")
    log(f"Dossier de sauvegardes : {os.path.abspath(DOSSIER_SAUV)}")
    log("En attente de connexions…")
    
    # Paramètres de session courants
    mss = SRV_MSS_PROPOSE
    n = N_PROPOSE
    client_addr = None

    
    while True:
        try:
            sock.settimeout(None)  # Attente indéfinie pour la première connexion
            data, addr = sock.recvfrom(UDP_BUF_MAX)
        except KeyboardInterrupt:
            log("Arrêt du serveur. (Ctrl+C détecté)")
            break
        
        # Deserialisation du paquet reçu
        try:
            header, payload = parse_packet(data)
        except Exception as e:
            log(f"Paquet reçu de {addr} invalide : {e}")
            continue
    
        msg_type = header["type"]
        log(f"{msg_name(msg_type)} de {addr} (seq={header['seq']}, len={header['len']})")
        
        # hand shake de connexion
        if msg_type == MSG_SYN:
            params = handshake(sock, addr, payload)
           
            if params:
                client_addr = addr
                mss = params["mss"]
                n = params["n"]
                log(f"Connexion établie avec {addr} – MSS={mss}, N={n}")
            else:
               log(f"Échec du handshake avec {addr}, aucune connexion établie.")
            continue
        
        # if client_addr is None or addr != client_addr:
        #     log(f"Paquet de {addr} ignoré : aucune connexion établie.")
        #     continue
        
        # Traitement des commandes
        # - commande ls
        if msg_type == MSG_LS:
            traiter_ls(sock, addr)
        
        # - commande put 
        elif msg_type == MSG_PUT:
            # Payload du PUT : struct "!Q" (taille_totale) + nom_fichier (UTF-8)
            if len(payload) < 8:
                log("PUT invalide : payload trop court.")
                envoyer(sock, build_packet(MSG_ERR, payload=b"PUT payload trop court"), addr)
                continue

            taille_totale = struct.unpack("!Q", payload[:8])[0]
            nom_fichier   = payload[8:].decode("utf-8").strip()
            log(f"PUT '{nom_fichier}' ({taille_totale} octets)")

            # Signaler au client qu'on est prêt
            envoyer(sock, build_packet(MSG_PUT_ACK), addr)

            succes = recevoir_fichier(sock, addr, nom_fichier, taille_totale, mss, n)
            if not succes:
                log(f"Transfert de '{nom_fichier}' échoué.")
                envoyer(sock, build_packet(MSG_ERR, payload=b"Transfert echoue"), addr)
                
        # - commande bye
        elif msg_type == MSG_BYE:
            log(f"BYE reçu de {addr} – déconnexion.")
            envoyer(sock, build_packet(MSG_BYE_ACK), addr)
            client_addr = None
            log("En attente d'une nouvelle connexion…")
        
        # commande resume
        elif msg_type == MSG_RESUME:
            # Payload du RESUME : nom_fichier (UTF-8) + struct "!Q" taille_totale
            if len(payload) < 9:
                log("RESUME invalide : payload trop court.")
                envoyer(sock, build_packet(MSG_ERR, payload=b"RESUME payload trop court"), addr)
                continue

            taille_totale  = struct.unpack("!Q", payload[:8])[0]
            nom_fichier    = payload[8:].decode("utf-8").strip()

            nom_fichier, offset = traiter_resume(sock, addr, payload[8:], mss)
            log(f"Reprise de '{nom_fichier}' à partir de l'offset {offset}")

            # Le client enverra un PUT_ACK-like pour confirmer, puis les données
            # On réutilise recevoir_fichier avec l'offset de reprise
            succes = recevoir_fichier(
                sock, addr, nom_fichier, taille_totale, mss, n, offset_depart=offset
            )
            if not succes:
                log(f"Reprise de '{nom_fichier}' échouée.")
        
        # - commande fin 
        elif msg_type == MSG_FIN:
            log(f"FIN reçu de {addr} – déjà traité par recevoir_fichier.")
            
        else:
            log(f"Type de message inconnu : {msg_name(msg_type)}")
            
    
if __name__ == "__main__":
    main()