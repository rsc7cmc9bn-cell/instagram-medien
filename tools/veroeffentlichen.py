"""Veröffentlicht fällige Beiträge und Storys aus plan/zeitplan.json über die Instagram Graph API.

Läuft in GitHub Actions. Zugang über das Secret IG_ACCESS_TOKEN (Instagram-Login-Schlüssel, beginnt
mit "IG", oder Seiten-Schlüssel über Facebook-Login). Instagram-Login-Schlüssel gelten 60 Tage; das
Skript frischt sie regelmäßig auf und legt den neuen Schlüssel verschlüsselt in plan/token.enc ab.
Das ursprüngliche Secret dient dabei als Passwort, im Repo liegt nie ein lesbarer Schlüssel.

Bilder müssen JPEG sein und öffentlich erreichbar; sie werden per Commit-SHA-URL aus diesem Repo
geladen. Jeder Lauf wartet gut fünf Stunden auf fällige Einträge und stößt dann den nächsten an (Kette);
der stündliche Lauf startet die Kette neu, falls sie einmal abreißt.
"""
import json, os, subprocess, sys, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
SECRET = os.environ.get("IG_ACCESS_TOKEN", "").strip()
VERSION = os.environ.get("GRAPH_VERSION", "v23.0")
REPO = os.environ.get("GITHUB_REPOSITORY", "rsc7cmc9bn-cell/instagram-medien")
PLAN, DONE = "plan/zeitplan.json", "plan/veroeffentlicht.json"
TOKEN_ENC, TOKEN_STAND = "plan/token.enc", "plan/token_stand.json"
LATE = timedelta(hours=6)  # ältere, verpasste Einträge nicht mehr nachholen
REFRESH_EVERY = timedelta(days=7)
TOKEN = SECRET


def host():
    return "graph.instagram.com" if TOKEN.startswith("IG") else "graph.facebook.com"


def api(method, path, versioned=True, **params):
    params["access_token"] = TOKEN
    url = f"https://{host()}/{VERSION + '/' if versioned else ''}{path}"
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


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def sync():
    """Neuesten Stand holen, damit Änderungen am Zeitplan während des Laufs greifen."""
    try:
        git("pull", "--rebase", "-q")
    except subprocess.CalledProcessError as e:
        print("Hinweis: git pull fehlgeschlagen:", e.stderr[:200])
    return git("rev-parse", "HEAD")


def commit(files, msg):
    git("add", *files)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return
    git("commit", "-q", "-m", msg)
    for _ in range(3):
        try:
            git("pull", "--rebase", "-q")
            git("push", "-q")
            return
        except subprocess.CalledProcessError:
            time.sleep(5)
    print("Hinweis: Push fehlgeschlagen")


def openssl(args, data):
    env = dict(os.environ, TK=SECRET)
    r = subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-a", "-A", *args, "-pass", "env:TK"],
                       input=data, capture_output=True, text=True, env=env, check=True)
    return r.stdout.strip()


def load_token():
    global TOKEN
    if os.path.exists(TOKEN_ENC):
        TOKEN = openssl(["-d"], open(TOKEN_ENC).read().strip() + "\n")


def refresh_token():
    """Instagram-Login-Schlüssel verlängern (geht ab 24 Stunden Alter, verlängert auf 60 Tage)."""
    global TOKEN
    if not TOKEN.startswith("IG"):
        return
    stand = json.load(open(TOKEN_STAND)) if os.path.exists(TOKEN_STAND) else {}
    last = stand.get("aufgefrischt")
    now = datetime.now(BERLIN)
    if last and now - datetime.fromisoformat(last) < REFRESH_EVERY:
        return
    retry = stand.get("naechster_versuch")
    if retry and now < datetime.fromisoformat(retry):
        return
    try:
        r = api("GET", "refresh_access_token", versioned=False, grant_type="ig_refresh_token")
    except Exception as ex:
        stand["letzter_fehler"] = f"{now.isoformat(timespec='minutes')}: {str(ex)[:200]}"
        stand["naechster_versuch"] = (now + timedelta(days=1)).isoformat(timespec="minutes")
        json.dump(stand, open(TOKEN_STAND, "w"), ensure_ascii=False, indent=1)
        commit([TOKEN_STAND], "Schlüssel-Auffrischung fehlgeschlagen")
        print("Hinweis: Auffrischen fehlgeschlagen:", str(ex)[:200])
        return
    TOKEN = r["access_token"]
    with open(TOKEN_ENC, "w") as f:
        f.write(openssl([], TOKEN) + "\n")
    stand = {"aufgefrischt": now.isoformat(timespec="minutes"),
             "laeuft_ab": (now + timedelta(seconds=int(r.get("expires_in", 0)))).isoformat(timespec="minutes")}
    json.dump(stand, open(TOKEN_STAND, "w"), ensure_ascii=False, indent=1)
    commit([TOKEN_ENC, TOKEN_STAND], "Instagram-Schlüssel aufgefrischt")
    print("Schlüssel aufgefrischt, gültig bis", stand["laeuft_ab"])


def ig_user_id():
    if os.environ.get("IG_USER_ID"):
        return os.environ["IG_USER_ID"]
    if host() == "graph.instagram.com":
        return api("GET", "me", fields="user_id")["user_id"]
    return api("GET", "me", fields="instagram_business_account")["instagram_business_account"]["id"]


def wait_ready(container):
    for _ in range(30):
        s = api("GET", container, fields="status_code").get("status_code")
        if s == "FINISHED":
            return
        if s in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Container {container}: {s}")
        time.sleep(5)
    raise RuntimeError(f"Container {container} nicht fertig")


def publish(uid, e, sha):
    url = lambda p: f"https://raw.githubusercontent.com/{REPO}/{sha}/{p}"
    imgs = e["bilder"]
    if e["typ"] == "STORY":
        c = api("POST", f"{uid}/media", media_type="STORIES", image_url=url(imgs[0]))["id"]
    elif len(imgs) == 1:
        c = api("POST", f"{uid}/media", image_url=url(imgs[0]), caption=e["text"])["id"]
    else:
        kids = []
        for p in imgs:
            k = api("POST", f"{uid}/media", image_url=url(p), is_carousel_item="true")["id"]
            wait_ready(k)
            kids.append(k)
        c = api("POST", f"{uid}/media", media_type="CAROUSEL", children=",".join(kids), caption=e["text"])["id"]
    wait_ready(c)
    return api("POST", f"{uid}/media_publish", creation_id=c)["id"]


def run_due(uid, sha, now):
    """Fällige Einträge veröffentlichen; liefert den nächsten offenen Termin."""
    plan = json.load(open(PLAN))
    done = json.load(open(DONE)) if os.path.exists(DONE) else {}
    start = plan.get("start")
    if not start:
        return None, 0
    start = datetime.fromisoformat(start).replace(tzinfo=BERLIN)
    nxt, fehler = None, 0
    for e in sorted(plan["eintraege"], key=lambda x: x["zeit"]):
        t = datetime.fromisoformat(e["zeit"]).replace(tzinfo=BERLIN)
        if e["id"] in done or e.get("entwurf") or t < start:
            continue
        if t > now:
            nxt = nxt or t
            continue
        if now - t > LATE:
            done[e["id"]] = {"status": "verpasst", "am": now.isoformat(timespec="minutes")}
        else:
            try:
                mid = publish(uid, e, sha)
                done[e["id"]] = {"status": "veroeffentlicht", "media_id": mid, "am": now.isoformat(timespec="minutes")}
                print("Veröffentlicht:", e["id"], mid)
            except Exception as ex:
                fehler += 1
                print("FEHLER:", e["id"], ex)
                continue
        with open(DONE, "w") as f:
            json.dump(done, f, ensure_ascii=False, indent=1)
        commit([DONE], f"Veröffentlicht: {e['id']}")
    return nxt, fehler


def other_runs():
    """Andere laufende oder wartende Läufe dieses Workflows (ältere zuerst)."""
    gh = os.environ.get("GITHUB_TOKEN")
    if not gh:
        return []
    own = int(os.environ.get("GITHUB_RUN_ID", "0"))
    runs = []
    for status in ("in_progress", "queued"):
        url = f"https://api.github.com/repos/{REPO}/actions/workflows/instagram-veroeffentlichen.yml/runs?status={status}&per_page=20"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {gh}", "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                runs += [x for x in json.loads(r.read())["workflow_runs"] if x["id"] != own]
        except Exception as ex:
            print("Hinweis: Läufe nicht abfragbar:", str(ex)[:200])
    return sorted(runs, key=lambda x: x["id"])


KETTE = timedelta(hours=5, minutes=30)  # Länge eines Kettenlaufs, unter dem Job-Limit von 350 Minuten


def gh_api(method, path, body=None):
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                                          "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def start_next():
    """Nächsten Kettenlauf anstoßen, falls nicht schon einer läuft oder wartet."""
    if not os.environ.get("GITHUB_TOKEN"):
        return
    if [r for r in other_runs() if r["event"] == "workflow_dispatch"]:
        print("Nächster Lauf steht schon an.")
        return
    try:
        gh_api("POST", "actions/workflows/instagram-veroeffentlichen.yml/dispatches", {"ref": "main", "inputs": {"modus": ""}})
        print("Nächster Kettenlauf angestoßen.")
    except Exception as ex:
        print("Hinweis: Nächster Lauf nicht angestoßen:", str(ex)[:200])


def window_end(now):
    bis = os.environ.get("BIS", "").strip()
    if bis:
        h, m = map(int, bis.split(":"))
        end = now.replace(hour=h, minute=m, second=0, microsecond=0)
        return min(end, now + timedelta(hours=5, minutes=40))
    return now + KETTE


def main():
    if not SECRET:
        print("Secret IG_ACCESS_TOKEN fehlt noch, nichts zu tun.")
        return
    if os.environ.get("MODUS") == "test":
        load_token()
        uid = ig_user_id()
        print("Konto:", api("GET", uid, fields="username"))
        print("Limit:", api("GET", f"{uid}/content_publishing_limit", fields="config,quota_usage"))
        return
    # Die Läufe bilden eine Kette: Jeder wartet gut fünf Stunden auf fällige Einträge und stößt vor dem Ende
    # den nächsten an. Der stündliche Lauf ist nur das Sicherheitsnetz: Ist kein Lauf aktiv, startet er die
    # Kette neu. So veröffentlicht nie mehr als ein Lauf gleichzeitig, und es braucht niemanden, der startet.
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        if other_runs():
            print("Kette läuft, Sicherheitslauf endet.")
        else:
            print("Keine Kette aktiv, starte sie neu.")
            start_next()
        return
    end = window_end(datetime.now(BERLIN))
    fehler = 0
    try:
        load_token()
        uid = ig_user_id()
        refresh_token()
        while True:
            sha = sync()
            now = datetime.now(BERLIN)
            nxt, f = run_due(uid, sha, now)
            fehler += f
            if not nxt or nxt > end:
                break
            time.sleep(max(0, (nxt - datetime.now(BERLIN)).total_seconds()) + 5)
    except Exception as ex:
        fehler += 1
        print("FEHLER im Lauf:", str(ex)[:500])
    finally:
        # Auch nach einem Fehler erst am Fensterende weitermachen, damit nichts im Sekundentakt neu startet.
        rest = (end - datetime.now(BERLIN)).total_seconds()
        if rest > 0:
            time.sleep(rest)
        start_next()
    if fehler:
        sys.exit(f"{fehler} Fehler im Lauf")


if __name__ == "__main__":
    main()
