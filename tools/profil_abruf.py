"""Liest die veröffentlichten Beiträge des Profils (Graph API) und legt sie mit
Vorschaubildern unter profil/ ab. Dient der Feed-Vorschau und dem Doppelpost-Abgleich."""
import json, os, urllib.parse, urllib.request

TOKEN = os.environ["IG_ACCESS_TOKEN"].strip()
HOST = "graph.instagram.com" if TOKEN.startswith("IG") else "graph.facebook.com"
FIELDS = "id,caption,media_type,media_product_type,media_url,thumbnail_url,timestamp,permalink"


def get(path, **params):
    params["access_token"] = TOKEN
    url = f"https://{HOST}/v23.0/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read())


os.makedirs("profil/vorschau", exist_ok=True)
konto = get("me", fields="username,media_count")
medien, seite = [], get("me/media", fields=FIELDS, limit=50)
while True:
    medien += seite.get("data", [])
    nxt = seite.get("paging", {}).get("next")
    if not nxt or len(medien) >= 200:
        break
    with urllib.request.urlopen(nxt, timeout=60) as r:
        seite = json.loads(r.read())
for m in medien:
    bild = m.get("thumbnail_url") or m.get("media_url")
    if bild:
        try:
            urllib.request.urlretrieve(bild, f"profil/vorschau/{m['id']}.jpg")
            m["vorschau"] = f"profil/vorschau/{m['id']}.jpg"
        except Exception as e:
            m["vorschau_fehler"] = str(e)[:200]
    m.pop("media_url", None), m.pop("thumbnail_url", None)
json.dump({"konto": {"username": konto.get("username"), "media_count": konto.get("media_count")}, "medien": medien},
          open("profil/medien.json", "w"), indent=1, ensure_ascii=False)
print(konto.get("username"), konto.get("media_count"), len(medien))
