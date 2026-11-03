#!/usr/bin/env python3
"""Bygger index.html (løpekartet) fra Strava-svar.

Bruk:  python3 build/build.py strava-side1.json [strava-side2.json ...]
Hver fil er svaret fra Strava list_activities med include_polyline=true.
Sporene klippes innenfor PRIVACY_M meter fra steder der minst MIN_STARTS turer starter eller slutter.
"""
import csv, json, math, os, sys, datetime

PRIVACY_M = 500
CLUSTER_M = 300
MIN_STARTS = 3
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

def decode(s):
    i = lat = lng = 0; out = []
    while i < len(s):
        for k in range(2):
            sh = r = 0
            while True:
                b = ord(s[i]) - 63; i += 1
                r |= (b & 0x1f) << sh; sh += 5
                if b < 0x20 or i >= len(s): break
            d = ~(r >> 1) if r & 1 else r >> 1
            if k == 0: lat += d
            else: lng += d
        out.append((lat / 1e5, lng / 1e5))
    return out

def encode(pts):
    out = []; plat = plng = 0
    for lat, lng in pts:
        for v, p in ((round(lat * 1e5), plat), (round(lng * 1e5), plng)):
            d = v - p; d = ~(d << 1) if d < 0 else d << 1
            while d >= 0x20:
                out.append(chr((0x20 | (d & 0x1f)) + 63)); d >>= 5
            out.append(chr(d + 63))
        plat, plng = round(lat * 1e5), round(lng * 1e5)
    return ''.join(out)

def dist(a, b):
    R = 6371000; la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))

KIND = {'Run': 'Løp', 'TrailRun': 'Løp', 'VirtualRun': 'Mølle', 'Walk': 'Gåtur', 'Hike': 'Gåtur', 'NordicSki': 'Ski',
        'BackcountrySki': 'Ski', 'SkateNordicSki': 'Ski', 'ClassicNordicSki': 'Ski', 'StandUpPaddling': 'Padling',
        'Kayaking': 'Padling', 'Canoeing': 'Padling', 'Ride': 'Sykkel', 'MountainBikeRide': 'Sykkel', 'GravelRide': 'Sykkel'}

def main(files):
    acts, seen = [], set()
    for f in files:
        o = json.load(open(f, encoding='utf-8'))
        for a in o.get('activities', []):
            if a['id'] not in seen and a.get('reduced_polyline'):
                seen.add(a['id']); acts.append(a)
    fix = {r['id']: r for r in csv.DictReader(open(os.path.join(HERE, 'korreksjoner.csv'), encoding='utf-8'))}
    tracks = []
    for a in acts:
        k = fix.get(a['id'], {})
        if (k.get('skip') or '').strip(): continue
        pts = decode(a['reduced_polyline'])
        if len(pts) > 1: tracks.append((a, k, pts))
    # Personvernsoner: steder der mange turer starter eller slutter
    ends = [p for _, _, pts in tracks for p in (pts[0], pts[-1])]
    clusters = []
    for p in ends:
        for c in clusters:
            if dist(p, c['c']) < CLUSTER_M:
                c['n'] += 1; c['pts'].append(p)
                c['c'] = (sum(x[0] for x in c['pts']) / c['n'], sum(x[1] for x in c['pts']) / c['n']); break
        else:
            clusters.append({'c': p, 'n': 1, 'pts': [p]})
    zones = [c['c'] for c in clusters if c['n'] >= MIN_STARTS]
    hidden = lambda p: any(dist(p, z) < PRIVACY_M for z in zones)
    out = []
    for a, k, pts in tracks:
        segs, cur = [], []
        for p in pts:
            if hidden(p):
                if len(cur) > 1: segs.append(cur)
                cur = []
            else: cur.append(p)
        if len(cur) > 1: segs.append(cur)
        if not segs: continue
        s = a.get('summary', {})
        km = float(k['km']) if (k.get('km') or '').strip() else round((s.get('distance') or 0) / 1000, 2)
        sec = int(float(k['sec'])) if (k.get('sec') or '').strip() else s.get('moving_time') or 0
        t = (k.get('type') or '').strip() or KIND.get(a.get('sport_type'), 'Annet')
        if t == 'Løp' and a.get('is_trainer'): t = 'Mølle'
        out.append({'id': a['id'], 'n': a.get('name', ''), 'd': a['start_local'][:10], 't': t, 'km': km, 's': sec,
                    'hm': round(s.get('elevation_gain') or 0), 're': s.get('relative_effort'), 'f': k.get('notat', ''),
                    'p': [encode(seg) for seg in segs]})
    out.sort(key=lambda x: x['d'])
    tpl = open(os.path.join(HERE, 'template.html'), encoding='utf-8').read()
    js = open(os.path.join(HERE, 'leaflet.js'), encoding='utf-8').read()
    css = open(os.path.join(HERE, 'leaflet.css'), encoding='utf-8').read()
    data = json.dumps(out, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    today = datetime.date.today().isoformat()
    html = tpl.replace('/*@@LEAFLETCSS@@*/', css).replace('/*@@LEAFLET@@*/', js).replace('/*@@DATA@@*/', data).replace('/*@@DATE@@*/', today)
    open(os.path.join(ROOT, 'index.html'), 'w', encoding='utf-8').write(html)
    print(f'{len(out)} turer, {len(zones)} personvernsoner, {len(html)} byte')

if __name__ == '__main__':
    main(sys.argv[1:])
