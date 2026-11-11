"""Sucht und lädt moderne, gewerblich nutzbare Musik (nur CC0 / CC BY) für Reels. Ergebnis: musik/modern/.
Eingaben (Umgebung):
  INCOMPETECH=1      -> musik/modern/incompetech.json (Kevin MacLeod, CC BY 4.0; Liste aller Stücke mit bpm/Stimmung/Genre)
  CCMIXTER=tags|...  -> musik/modern/ccmixter.json (Instrumentals mit Lizenz CC BY oder CC0, inkl. bpm und Download-Links)
  COMMONS=suche|...  -> musik/modern/commons.json (Audio mit CC0 / CC BY 3.0/4.0)
  LADEN=url|url      -> lädt Dateien von incompetech.com, ccmixter.org, upload.wikimedia.org nach musik/modern/ + lizenzen.json
Keine NC/ND/SA-Lizenzen (gewerbliches Konto, Reel soll nicht unter SA fallen)."""
import json, os, re, time, urllib.error, urllib.parse, urllib.request
UA = {'User-Agent': 'instagram-medien-musik/1.1 (github.com/rsc7cmc9bn-cell/instagram-medien)'}
OUT = 'musik/modern'; os.makedirs(OUT, exist_ok=True)
def fetch(u, timeout=90):
    for i in range(5):
        try:
            time.sleep(1); return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == 4: raise
            time.sleep(10 * (i + 1))
def save(name, obj): json.dump(obj, open(f'{OUT}/{name}', 'w'), ensure_ascii=False, indent=1)
log = {}
if os.environ.get('INCOMPETECH'):
    for u in ['https://incompetech.com/music/royalty-free/pieces.json', 'https://incompetech.filmmusic.io/pieces.json']:
        try: d = json.loads(fetch(u)); save('incompetech.json', d); log['incompetech'] = f'{u}: {len(d)} Stücke'; break
        except Exception as e: log['incompetech_' + u] = str(e)
tags = [t for t in os.environ.get('CCMIXTER', '').split('|') if t.strip()]
if tags:
    res = {}
    for t in tags:
        for lic in ('by', 'zero'):
            u = 'https://ccmixter.org/api/query?' + urllib.parse.urlencode({'tags': t, 'lic': lic, 'f': 'json', 'limit': 40, 'sort': 'rank'})
            try:
                for x in json.loads(fetch(u)):
                    files = [dict(url=f.get('download_url'), name=f.get('file_name'), format=f.get('file_format_info', {}).get('default-ext'),
                                  dauer=f.get('file_format_info', {}).get('ps')) for f in x.get('files', [])]
                    res[x.get('upload_id')] = dict(titel=x.get('upload_name'), kuenstler=x.get('user_real_name') or x.get('user_name'),
                        lizenz=x.get('license_name'), lizenz_url=x.get('license_url'), bpm=(x.get('upload_extra') or {}).get('bpm'),
                        tags=x.get('upload_tags'), seite=x.get('file_page_url'), dateien=files, suche=t)
            except Exception as e: res[f'fehler_{t}_{lic}'] = str(e)
    save('ccmixter.json', res); log['ccmixter'] = len(res)
cs = [t for t in os.environ.get('COMMONS', '').split('|') if t.strip()]
if cs:
    API = 'https://commons.wikimedia.org/w/api.php'; res = {}
    for s in cs:
        try:
            d = json.loads(fetch(API + '?' + urllib.parse.urlencode({'action': 'query', 'list': 'search', 'srsearch': s + ' filetype:audio', 'srnamespace': 6, 'srlimit': 30, 'format': 'json'})))
            titles = [x['title'] for x in d['query']['search']]
            if not titles: res[s] = []; continue
            q = json.loads(fetch(API + '?' + urllib.parse.urlencode({'action': 'query', 'titles': '|'.join(titles), 'prop': 'imageinfo', 'format': 'json',
                     'iiprop': 'url|extmetadata|size|mime', 'iiextmetadatafilter': 'LicenseShortName|Artist|Credit|ImageDescription'})))
            out = []
            for p in q['query']['pages'].values():
                ii = (p.get('imageinfo') or [{}])[0]; m = ii.get('extmetadata', {})
                st = lambda k: re.sub('<[^>]+>', '', m.get(k, {}).get('value', ''))[:200]
                lz = st('LicenseShortName')
                if re.search(r'cc0|public domain|cc by (3\.0|4\.0)$|cc-by-(3\.0|4\.0)$', lz.strip(), re.I) and not re.search(r'sa|nc|nd', lz, re.I):
                    out.append(dict(titel=p['title'], url=ii.get('url'), lizenz=lz, urheber=st('Artist'), beschreibung=st('ImageDescription'), dauer=ii.get('duration')))
            res[s] = out
        except Exception as e: res[s] = [{'fehler': str(e)}]
    save('commons.json', res); log['commons'] = {k: len(v) for k, v in res.items()}
urls = [u.strip() for u in os.environ.get('LADEN', '').split('|') if u.strip()]
if urls:
    lp = f'{OUT}/lizenzen.json'; liz = json.load(open(lp)) if os.path.exists(lp) else {}
    for u in urls:
        host = urllib.parse.urlparse(u).netloc
        if not re.search(r'(^|\.)(incompetech\.com|incompetech\.filmmusic\.io|ccmixter\.org|wikimedia\.org)$', host): log[u] = 'Host nicht erlaubt'; continue
        try:
            name = re.sub(r'[^A-Za-z0-9._-]+', '_', urllib.parse.unquote(u.rsplit('/', 1)[-1]))
            open(f'{OUT}/{name}', 'wb').write(fetch(u, 180)); liz[name] = dict(url=u, geladen=time.strftime('%Y-%m-%d')); log[u] = 'ok ' + name
        except Exception as e: log[u] = str(e)
    save('lizenzen.json', liz)
save('protokoll.json', log); print(json.dumps(log, ensure_ascii=False, indent=1))
