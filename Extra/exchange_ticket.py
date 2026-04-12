"""Exchange a Garmin SSO ticket for OAuth tokens (garth 0.5.x)."""
import os, sys
from garth.sso import get_oauth1_token, exchange
from garth import Client

ticket = input("Colle le ticket (ST-...) : ").strip()
if not ticket.startswith("ST-"):
    print("Le ticket doit commencer par ST-")
    sys.exit(1)

client = Client()
print("Step 1/2 : ticket -> OAuth1...")
oauth1 = get_oauth1_token(ticket, client)
print("Step 2/2 : OAuth1 -> OAuth2...")
oauth2 = exchange(oauth1, client)
client.oauth1_token = oauth1
client.oauth2_token = oauth2
client.dump("/tokens")
print("OK!", os.listdir("/tokens"))
