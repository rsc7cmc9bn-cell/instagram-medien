"""Veröffentlicht fällige Beiträge und Storys aus plan/zeitplan.json über die Instagram Graph API.

Läuft in GitHub Actions. Zugang über das Secret IG_ACCESS_TOKEN (Seiten-Schlüssel über
Facebook-Login, oder Instagram-Login-Schlüssel, der mit "IG" beginnt). Bilder müssen JPEG sein
und öffentlich erreichbar; sie werden per Commit-SHA-URL aus diesem Repo geladen.
"""
import json, os, sys, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
VERSION = os.environ.get("GRAPH_VERSION", "v23.0")
HOST = "graph.instagram.com" if TOKEN.startswith("IG") else "graph.facebook.com"
REPO = os.environ.get("GITHUB_REPOSITORY", "rsc7cmc9bn-cell/instagram-medien")
SHA = os.environ.get("GITHUB_SHA", "main")
PLAN, DONE = "plan/zeitplan.json", "plan/veroeffentlicht.json"
LATE = timedelta(hours=6)  # ältere, verpasste Einträge nicht mehr nachholen


def api(method, path, **params):
    params["access_token"] = TOKEN
    url = f"https://{HOST}/{VERSION}/{path}"
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        req = urllib.request.Request(url + "?" + data.decode())
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path}: {e.code} {e.read().decode()[:500]}") from None


def ig_user_id():
    if os.environ.get("IG_USER_ID"):
        return os.environ["IG_USER_ID"]
    if HOST == "graph.instagram.com":
        return api("GET", "me", fields="user_id")["user_id"]
    return api("GET", "me", fields="instagram_business_account")["instagram_business_account"]["id"]


def media_url(path):
    return f"https://raw.githubusercontent.com/{REPO}/{SHA}/{path}"


def wait_ready(container):
    for _ in range(30):
        s = api("GET", container, fields="status_code").get("status_code")
        if s == "FINISHED":
            return
        if s in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Container {container}: {s}")
        time.sleep(5)
    raise RuntimeError(f"Container {container} nicht fertig")


def publish(uid, e):
    imgs = e["bilder"]
    if e["typ"] == "STORY":
        c = api("POST", f"{uid}/media", media_type="STORIES", image_url=media_url(imgs[0]))["id"]
    elif len(imgs) == 1:
        c = api("POST", f"{uid}/media", image_url=media_url(imgs[0]), caption=e["text"])["id"]
    else:
        kids = []
        for p in imgs:
            k = api("POST", f"{uid}/media", image_url=media_url(p), is_carousel_item="true")["id"]
            wait_ready(k)
            kids.append(k)
        c = api("POST", f"{uid}/media", media_type="CAROUSEL", children=",".join(kids), caption=e["text"])["id"]
    wait_ready(c)
    return api("POST", f"{uid}/media_publish", creation_id=c)["id"]


def save(done):
    with open(DONE, "w") as f:
        json.dump(done, f, ensure_ascii=False, indent=1)


def main():
    if not TOKEN:
        print("Secret IG_ACCESS_TOKEN fehlt noch, nichts zu tun.")
        return
    uid = ig_user_id()
    if os.environ.get("MODUS") == "test":
        print("Konto:", api("GET", uid, fields="username"))
        print("Limit:", api("GET", f"{uid}/content_publishing_limit", fields="config,quota_usage"))
        return
    plan = json.load(open(PLAN))
    done = json.load(open(DONE)) if os.path.exists(DONE) else {}
    start = plan.get("start")
    if not start:
        print("Kein Startzeitpunkt gesetzt, nichts zu tun.")
        return
    start = datetime.fromisoformat(start).replace(tzinfo=BERLIN)
    now = datetime.now(BERLIN)
    fehler = 0
    for e in sorted(plan["eintraege"], key=lambda x: x["zeit"]):
        t = datetime.fromisoformat(e["zeit"]).replace(tzinfo=BERLIN)
        if e["id"] in done or e.get("entwurf") or t < start or t > now:
            continue
        if now - t > LATE:
            done[e["id"]] = {"status": "verpasst", "am": now.isoformat(timespec="minutes")}
            save(done)
            continue
        try:
            mid = publish(uid, e)
            done[e["id"]] = {"status": "veroeffentlicht", "media_id": mid, "am": now.isoformat(timespec="minutes")}
            print("Veröffentlicht:", e["id"], mid)
        except Exception as ex:
            fehler += 1
            print("FEHLER:", e["id"], ex)
        save(done)
    if fehler:
        sys.exit(f"{fehler} Eintrag/Einträge fehlgeschlagen")


if __name__ == "__main__":
    main()
