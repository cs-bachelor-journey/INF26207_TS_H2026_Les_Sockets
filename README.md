# INF26207 – Travail de session : Serveur de sauvegarde UDP fiable

---

## Prérequis

- **Python 3.12**
- **Conda**
- Module `usocket.pyc`

---

## Installation de l'environnement Conda

Ce projet utilise un environnement Conda avec Python 3.12. Voici comment l'activer :

### Créer l'environnement depuis le fichier YML

```bash
# Créer l'environnement à partir du fichier environment.yml
conda env create -f environment.yml

# Activer l'environnement
conda activate py312
```

---

## Comment lancer le serveur

1. Assurez-vous d'être dans le répertoire du projet
2. Activez l'environnement Conda : `conda activate py312`
3. Lancez le serveur :

```bash
python serveur.py
```

Le serveur écoute sur le port **4242** et enregistre les fichiers reçus dans le dossier `./sauvegardes/`.

---

## Comment lancer le client

1. Dans un autre terminal, activez l'environnement Conda : `conda activate py312`
2. Lancez le client :

```bash
python client.py
```

---

## Comment exécuter un transfert de fichier

Une fois le client connecté au serveur, utilisez les commandes suivantes :

```text
>>> open 127.0.0.1
>>> ls
>>> put test1.bin
>>> bye
```

**Description des commandes :**

- `open 127.0.0.1` : Établit une connexion avec le serveur
- `ls` : Affiche la liste des fichiers disponibles sur le serveur
- `put <fichier>` : Envoie un fichier au serveur (depuis le dossier `tests/` ou chemin absolu)
- `bye` : Déconnecte du serveur

---

## Comment tester la reprise (resume)

La commande `resume` permet de reprendre un transfert interrompu :

1. Lancez un transfert avec `put` et interrompez-le avec `Ctrl+C` pendant l'envoi
2. Relancez le client et reconnectez-vous
3. Utilisez la commande `resume` :

```text
>>> open 127.0.0.1
>>> resume tests/test1.bin
```

Le client interroge le serveur pour connaître l'offset valide (nombre d'octets déjà reçus), puis reprend l'envoi à partir de ce point sans retransmettre les données déjà reçues.

---

## Comment vérifier l'intégrité finale du fichier

Le protocole implémente une vérification d'intégrité à deux niveaux :

1. **Checksum par segment** : Chaque segment inclut un CRC32 vérifié à la réception
2. **Checksum final** : Comparaison CRC32 complète via le message FIN_ACK

### Méthode automatique

Le client vérifie automatiquement le checksum à la fin du transfert. Si les CRC32 correspondent, le message "Transfert réussi et intègre !" s'affiche.

### Méthode manuelle – CRC32 via Python

```python
import zlib

def crc32_fichier(chemin):
    with open(chemin, "rb") as f:
        return zlib.crc32(f.read()) & 0xFFFFFFFF

original = crc32_fichier("tests/test1.bin")
recu = crc32_fichier("sauvegardes/test1.bin")

print("Identique :", original == recu)
print(f"  Original  : {original:#010x}")
print(f"  Reçu      : {recu:#010x}")
```

### Méthode via terminal (Linux/macOS)

```bash
md5sum tests/test1.bin sauvegardes/test1.bin
# ou
sha256sum tests/test1.bin sauvegardes/test1.bin
```

Les deux sommes doivent être identiques.

---

## Paramètres de configuration (config.ini)

Le fichier `config.ini` contient tous les paramètres réseau et de connexion :

| Paramètre             | Description                                   | Défaut |
| --------------------- | --------------------------------------------- | ------ |
| `fiabilite`           | Probabilité de succès d'un envoi UDP          | 0.95   |
| `taux_corruption`     | Taux de corruption des segments reçus         | 0.02   |
| `timeout`             | Délai (secondes) avant retransmission         | 3.0    |
| `max_reprises`        | Nombre max de tentatives consécutives         | 5      |
| `client_mss_propose`  | MSS proposé par le client (octets)            | 1024   |
| `serveur_mss_propose` | MSS proposé par le serveur (octets)           | 1024   |
| `n_propose`           | Fenêtre d'envoi (segments par bloc avant ACK) | 4      |

> **Conseil :** Pour les tests initiaux, utilisez `timeout = 1.0`. Une fois le débogage terminé, réduisez à `0.05` pour accélérer les transferts.

---

## Structure du projet

```
projet/
├── usocket.pyc          # Module socket non-fiable
├── usocket.pyi          # Aide IntelliSense
├── client.py            # Application console client
├── serveur.py           # Serveur (port 4242)
├── protocol.py          # Définitions partagées du protocole
├── config.ini           # Configuration réseau et connexion
├── environment.yml      # Environnement Conda (Python 3.12)
├── README.md            # Ce fichier
├── tests/               # Fichiers binaires de test (≥200 Kio)
│   ├── test1.bin        # 256 Ko
│   ├── test2.bin        # 300 Ko
│   ├── test3.bin        # 350 Ko
│   └── test_small.bin   # 10 Ko
└── sauvegardes/         # Fichiers reçus par le serveur
```

---

## Fonctionnement général du protocole

### Three-Way Handshake

1. Client -> SYN (MSS, N proposés)
2. Serveur -> SYN-ACK (paramètres négociés)
3. Client -> ACK (connexion établie)

### Transfert de fichier

1. Client -> PUT (taille + nom du fichier)
2. Serveur -> PUT_ACK
3. Client -> Envoi des données par blocs de N segments
4. Serveur -> DATA_ACK pour chaque bloc
5. En cas de corruption -> NACK -> retransmission du bloc
6. Client -> FIN
7. Serveur -> FIN_ACK (checksum CRC32 final)

### Reprise de transfert

- Utilise MSG_RESUME et MSG_RES_ACK
- Le serveur retourne l'offset (nombre d'octets valides reçus)
- Le client envoie les données à partir de cet offset
