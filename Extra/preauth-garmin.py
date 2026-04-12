"""Pré-authentifie garminconnect / garth depuis une machine quelconque et
dumpe les tokens OAuth pour les injecter ensuite dans garminconnect-tokens/
du projet garmin-grafana (évite le 429 SSO quand le flow du fetcher est banni).

Usage (sur une machine avec Python 3.10+) :

    pip install garminconnect==0.2.35
    python preauth-garmin.py

Le script demande email + mot de passe (+ MFA si nécessaire) et écrit les
tokens dans ./garminconnect-tokens/ à côté du script. Copie ensuite le
contenu de ce dossier dans garmin-grafana/garminconnect-tokens/ sur la
machine où tourne Docker.
"""
import getpass
import os
import sys

try:
    from garminconnect import Garmin
except ImportError:
    sys.exit("Installe d'abord : pip install garminconnect==0.2.35")

TOKEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "garminconnect-tokens")
os.makedirs(TOKEN_DIR, exist_ok=True)

email = input("Email Garmin : ").strip()
password = getpass.getpass("Mot de passe Garmin (masqué) : ")

print(f"\nConnexion à Garmin Connect...")
g = Garmin(email=email, password=password, return_on_mfa=True)
result1, result2 = g.login()

if result1 == "needs_mfa":
    mfa = input("Code MFA (email/SMS) : ").strip()
    g.resume_login(result2, mfa)
    print("MFA validé.")

g.garth.dump(TOKEN_DIR)
print(f"\nTokens écrits dans : {TOKEN_DIR}")
print("Contenu :")
for f in sorted(os.listdir(TOKEN_DIR)):
    print(f"  - {f}")
print("\nCopie ce dossier dans garmin-grafana/garminconnect-tokens/ sur ta machine Docker.")
