import struct
import zlib



# Format d'en-tête
HEADER_FMT = "!BBIIHI"          
HEADER_SIZE = struct.calcsize(HEADER_FMT)   
PROTOCOL_VERSION = 1

# Types de messages

# Three-way handshake
MSG_SYN = 0x01
MSG_SYN_ACK = 0x02
MSG_ACK = 0x03

# Commandes
MSG_LS = 0x10
MSG_LS_RESP = 0x11
MSG_PUT = 0x12
MSG_PUT_ACK = 0x13
MSG_RESUME  = 0x14  
MSG_RES_ACK = 0x15
MSG_BYE = 0x20
MSG_BYE_ACK = 0x21

# Transfert de données
MSG_DATA = 0x30
MSG_DATA_ACK = 0x31
MSG_FIN = 0x32
MSG_FIN_ACK = 0x33

# Erreurs
MSG_ERR = 0xF0
MSG_NACK = 0xF1

# Noms lisibles pour les logs
MSG_NAMES = {
    MSG_SYN: "SYN",
    MSG_SYN_ACK: "SYN-ACK",
    MSG_ACK: "ACK",
    MSG_LS: "LS",
    MSG_LS_RESP: "LS_RESP",
    MSG_PUT: "PUT",
    MSG_PUT_ACK: "PUT_ACK",
    MSG_RESUME:  "RESUME",
    MSG_RES_ACK: "RES_ACK",
    MSG_BYE: "BYE",
    MSG_BYE_ACK: "BYE_ACK",
    MSG_DATA: "DATA",
    MSG_DATA_ACK: "DATA_ACK",
    MSG_FIN: "FIN",
    MSG_FIN_ACK: "FIN_ACK",
    MSG_ERR: "ERR",
    MSG_NACK: "NACK",
}

def checksum(data):
    """
    Calcule le checksum CRC32 d'un payload.
    """
    
    return zlib.crc32(data) & 0xffffffff

def build_packet(msg_type, seq=0, ack=0, payload=b""):
    """
    Construit un paquet complet = en-tête + payload.
    """
    
    chk = checksum(payload) if payload else 0
    
    # Pack de l'en-tête avec les champs appropriés
    header = struct.pack(HEADER_FMT, PROTOCOL_VERSION, msg_type, seq, ack, len(payload), chk)
    
    return header + payload
    

def parse_header(data):
    """
    Désérialise les 16 premiers octets d'un paquet en un dictionnaire.
    """
    
    if len(data) < HEADER_SIZE:
        raise ValueError(f"Paquet trop court : {len(data)} octets, minimum {HEADER_SIZE}")
    
    # Unpack de l'en-tête 
    version, msg_type, seq, ack, length, chk = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
    
    # Vérifie la version du protocole
    if version != PROTOCOL_VERSION:
        raise ValueError(f"Version de protocole invalide: {version}")
    
    return {
        "ver": version,
        "type": msg_type,
        "seq": seq,
        "ack": ack,
        "len": length,
        "chk": chk
    }
    
    
def parse_packet(data):
    """
    Désérialise un paquet complet en (en-tête, payload).
    Vérifie la cohérence du checksum.
    """
    
    header = parse_header(data)
    
    # Vérification de la version du protocole
    if header["ver"] != PROTOCOL_VERSION:
        raise ValueError(f"Version de protocole invalide: {header['ver']}")
    
    # Extraction du payload
    payload = data[HEADER_SIZE:HEADER_SIZE + header["len"]]
    
    # Vérification du checksum 
    if payload:
        computed_chk = checksum(payload)
        if computed_chk != header["chk"]:
            raise ValueError("Checksum invalide")
    
    return header, payload

def msg_name(msg_type):
    """
    Retourne le nom lisible d'un type de message pour les logs.
    """
    
    return MSG_NAMES.get(msg_type, f"UNKNOWN(0x{msg_type:02X})")