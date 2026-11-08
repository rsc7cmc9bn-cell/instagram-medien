"""Sucht und lädt gemeinfreie Musik von Wikimedia Commons (für Reels).
SUCHE: Suchbegriffe, durch | getrennt -> musik/suche.json (Titel, Lizenz, Urheber, Dauer)
DATEIEN: Commons-Dateinamen, durch | getrennt -> musik/<name> + musik/lizenzen.json
Geladen wird nur, was Commons als Public Domain oder CC0 ausweist."""
import json, os, re, time, urllib.error, urllib.parse, urllib.request
API = 'https://commons.wikimedia.org/w/api.php'
UA = {'User-Agent': 'instagram-medien-musik/1.0 (github.com/rsc7cmc9bn-cell/instagram-medien)'}
def fetch(u, timeout=60):
    for i in range(6):
        try:
            time.sleep(2)
            return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == 5:
                raise
            w = int(e.headers.get('Retry-After') or 0) or 10 * (i + 1)
            print('429, warte', w, 's'); time.sleep(min(w, 120))
def get(params):
    u = API + '?' + urllib.parse.urlencode({**params, 'format': 'json', 'maxlag': 5})
    return json.loads(fetch(u))
def info(titles):
    d = get({'action': 'query', 'titles': '|'.join(titles), 'prop': 'imageinfo',
             'iiprop': 'url|extmetadata|size|mime', 'iiextmetadatafilter': 'LicenseShortName|Artist|Credit|ImageDescription|UsageTerms'})
    out = []
    for p in d['query']['pages'].values():
        ii = (p.get('imageinfo') or [{}])[0]
        m = ii.get('extmetadata', {})
        strip = lambda k: re.sub('<[^>]+>', '', m.get(k, {}).get('value', ''))[:300]
        out.append({'titel': p['title'], 'url': ii.get('url'), 'mime': ii.get('mime'), 'groesse': ii.get('size'),
                    'dauer': ii.get('duration'), 'lizenz': strip('LicenseShortName'), 'urheber': strip('Artist'),
                    'quelle': strip('Credit'), 'beschreibung': strip('ImageDescription')})
    return out
os.makedirs('musik', exist_ok=True)
suche = [s for s in os.environ.get('SUCHE', '').split('|') if s.strip()]
if suche:
    res = {}
    for s in suche:
        try:
            d = get({'action': 'query', 'list': 'search', 'srsearch': s + ' filetype:audio', 'srnamespace': 6, 'srlimit': 15})
            titles = [x['title'] for x in d['query']['search']]
            res[s] = info(titles) if titles else []
        except Exception as e:
            res[s] = [{'fehler': str(e)}]
    json.dump(res, open('musik/suche.json', 'w'), ensure_ascii=False, indent=1)
dateien = [s.strip() for s in os.environ.get('DATEIEN', '').split('|') if s.strip()]
if dateien:
    lp = 'musik/lizenzen.json'
    liz = json.load(open(lp)) if os.path.exists(lp) else {}
    for x in info([t if t.startswith('File:') else 'File:' + t for t in dateien]):
        ok = re.search(r'public domain|^pd|cc0', x['lizenz'], re.I)
        print(x['titel'], '|', x['lizenz'], '|', 'OK' if ok else 'ABGELEHNT')
        if not ok or not x['url']:
            continue
        name = re.sub(r'[^A-Za-z0-9._-]+', '_', x['titel'][5:])
        open('musik/' + name, 'wb').write(fetch(x['url'], 180))
        liz[name] = x
    json.dump(liz, open(lp, 'w'), ensure_ascii=False, indent=1)
