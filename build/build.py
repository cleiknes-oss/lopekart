#!/usr/bin/env python3
"""Bygger index.html (løpekartet) fra Strava-svar.

Bruk:
  LOPEKART_PASSORD=... python3 build/build.py [--korreksjoner fil.csv] strava-side1.json [strava-side2.json ...]

Hver Strava-fil er svaret fra list_activities med include_polyline=true.

Personvern:
- Hver tur kortes av med en tilfeldig lengde mellom TRIM_MIN og TRIM_MAX meter i begge ender, målt langs sporet.
  Lengden er fast per tur (avledet av passordet og turens id), så den ikke kan gjettes eller snittes ut.
- I tillegg skjules et område rundt steder der minst MIN_STARTS turer starter eller slutter. Området har tilfeldig
  radius (ZONE_MIN–ZONE_MAX m) og et tilfeldig forskjøvet sentrum, så kanten ikke peker på startstedet.
- Alle turdata krypteres med AES-256-GCM. Nøkkelen avledes fra passordet med PBKDF2-SHA256.
"""
import base64, csv, hashlib, hmac, json, math, os, sys, datetime
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TRIM_MIN, TRIM_MAX = 500, 1000
ZONE_MIN, ZONE_MAX = 700, 1000
ZONE_OFFSET_MIN, ZONE_OFFSET_MAX = 200, 350
CLUSTER_M = 300
MIN_STARTS = 3
PBKDF2_ROUNDS = 600000
SALT = b"lopekart-v2-salt"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def decode(s):
    i = lat = lng = 0
    out = []
    while i < len(s):
        for k in range(2):
            sh = r = 0
            while True:
                b = ord(s[i]) - 63
                i += 1
                r |= (b & 0x1F) << sh
                sh += 5
                if b < 0x20 or i >= len(s):
                    break
            d = ~(r >> 1) if r & 1 else r >> 1
            if k == 0:
                lat += d
            else:
                lng += d
        out.append((lat / 1e5, lng / 1e5))
    return out


def encode(pts):
    out = []
    plat = plng = 0
    for lat, lng in pts:
        for v, p in ((round(lat * 1e5), plat), (round(lng * 1e5), plng)):
            d = v - p
            d = ~(d << 1) if d < 0 else d << 1
            while d >= 0x20:
                out.append(chr((0x20 | (d & 0x1F)) + 63))
                d >>= 5
            out.append(chr(d + 63))
        plat, plng = round(lat * 1e5), round(lng * 1e5)
    return "".join(out)


def dist(a, b):
    R = 6371000
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def densify(pts, step=50):
    """Legg inn mellompunkter så klippingen treffer presist også på glisne spor."""
    out = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        n = max(1, int(dist(a, b) // step))
        for j in range(1, n + 1):
            out.append((a[0] + (b[0] - a[0]) * j / n, a[1] + (b[1] - a[1]) * j / n))
    return out


def trim(pts, start_m, end_m):
    """Fjern de første start_m og de siste end_m meterne langs sporet."""
    pts = densify(pts)
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + dist(a, b))
    total = cum[-1]
    if total <= start_m + end_m + 200:
        return []
    return [p for p, c in zip(pts, cum) if start_m <= c <= total - end_m]


def simplify(pts, tol=8):
    """Fjern mellompunkter som ligger på linje igjen (holder filen liten)."""
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = out[-1], pts[i], pts[i + 1]
        ab, bc, ac = dist(a, b), dist(b, c), dist(a, c)
        if ab + bc - ac > tol / 10 or ab > 400:
            out.append(b)
    out.append(pts[-1])
    return out


KIND = {"Run": "Løp", "TrailRun": "Løp", "VirtualRun": "Mølle", "Walk": "Gåtur", "Hike": "Gåtur", "NordicSki": "Ski",
        "BackcountrySki": "Ski", "SkateNordicSki": "Ski", "ClassicNordicSki": "Ski", "StandUpPaddling": "Padling",
        "Kayaking": "Padling", "Canoeing": "Padling", "Ride": "Sykkel", "MountainBikeRide": "Sykkel", "GravelRide": "Sykkel"}


def main(files, korr_path, password):
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), SALT, PBKDF2_ROUNDS)

    def trim_len(aid, end):
        h = hmac.new(key, f"trim:{aid}:{end}".encode(), "sha256").digest()
        return TRIM_MIN + int.from_bytes(h[:4], "big") / 2**32 * (TRIM_MAX - TRIM_MIN)

    acts, seen = [], set()
    for f in files:
        o = json.load(open(f, encoding="utf-8"))
        for a in o.get("activities", []):
            if a["id"] not in seen and a.get("reduced_polyline"):
                seen.add(a["id"])
                acts.append(a)
    fix = {r["id"]: r for r in csv.DictReader(open(korr_path, encoding="utf-8"))} if korr_path else {}
    tracks = []
    for a in acts:
        k = fix.get(a["id"], {})
        if (k.get("skip") or "").strip():
            continue
        pts = decode(a["reduced_polyline"])
        if len(pts) > 1:
            tracks.append((a, k, pts))
    # Steder der mange turer starter eller slutter
    clusters = []
    for p in [p for _, _, pts in tracks for p in (pts[0], pts[-1])]:
        for c in clusters:
            if dist(p, c["c"]) < CLUSTER_M:
                c["n"] += 1
                c["pts"].append(p)
                c["c"] = (sum(x[0] for x in c["pts"]) / c["n"], sum(x[1] for x in c["pts"]) / c["n"])
                break
        else:
            clusters.append({"c": p, "n": 1, "pts": [p]})
    # Hver sone forskyves tilfeldig (fast per sone, avledet av nøkkelen) og får tilfeldig radius,
    # så kanten av det skjulte området ikke peker rett på startstedet
    zones = []
    for c in clusters:
        if c["n"] < MIN_STARTS:
            continue
        h = hmac.new(key, f"zone:{c['c'][0]:.3f},{c['c'][1]:.3f}".encode(), "sha256").digest()
        ang = int.from_bytes(h[:4], "big") / 2**32 * 2 * math.pi
        off = ZONE_OFFSET_MIN + int.from_bytes(h[4:8], "big") / 2**32 * (ZONE_OFFSET_MAX - ZONE_OFFSET_MIN)
        rad = ZONE_MIN + int.from_bytes(h[8:12], "big") / 2**32 * (ZONE_MAX - ZONE_MIN)
        lat = c["c"][0] + off * math.cos(ang) / 111320
        lng = c["c"][1] + off * math.sin(ang) / (111320 * math.cos(math.radians(c["c"][0])))
        zones.append(((lat, lng), max(rad, off + 450)))
    hidden = lambda p: any(dist(p, z) < r for z, r in zones)
    out = []
    for a, k, pts in tracks:
        segs, cur = [], []
        for p in trim(pts, trim_len(a["id"], "start"), trim_len(a["id"], "slutt")):
            if hidden(p):
                if len(cur) > 1:
                    segs.append(cur)
                cur = []
            else:
                cur.append(p)
        if len(cur) > 1:
            segs.append(cur)
        if not segs:
            continue
        s = a.get("summary", {})
        km = float(k["km"]) if (k.get("km") or "").strip() else round((s.get("distance") or 0) / 1000, 2)
        sec = int(float(k["sec"])) if (k.get("sec") or "").strip() else s.get("moving_time") or 0
        t = (k.get("type") or "").strip() or KIND.get(a.get("sport_type"), "Annet")
        if t == "Løp" and a.get("is_trainer"):
            t = "Mølle"
        out.append({"id": a["id"], "n": a.get("name", ""), "d": a["start_local"][:10], "t": t, "km": km, "s": sec,
                    "hm": round(s.get("elevation_gain") or 0), "re": s.get("relative_effort"), "f": k.get("notat", ""),
                    "p": [encode(simplify(seg)) for seg in segs]})
    out.sort(key=lambda x: (x["d"], x["id"]))
    plain = json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    # Deterministisk IV avledet av nøkkel og innhold: samme data gir samme fil, ulike data gir aldri samme IV
    iv = hmac.new(key, b"iv:" + plain, "sha256").digest()[:12]
    ct = AESGCM(key).encrypt(iv, plain, None)
    b64 = lambda b: base64.b64encode(b).decode()
    blob = json.dumps({"v": 2, "rounds": PBKDF2_ROUNDS, "salt": b64(SALT), "iv": b64(iv), "ct": b64(ct)})
    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    js = open(os.path.join(HERE, "leaflet.js"), encoding="utf-8").read()
    css = open(os.path.join(HERE, "leaflet.css"), encoding="utf-8").read()
    html = tpl.replace("/*@@LEAFLETCSS@@*/", css).replace("/*@@LEAFLET@@*/", js).replace("/*@@DATA@@*/", blob)
    open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8").write(html)
    print(f"{len(out)} turer, {len(zones)} soner, {len(html)} byte, kryptert")


if __name__ == "__main__":
    args = sys.argv[1:]
    korr = None
    if args[:1] == ["--korreksjoner"]:
        korr, args = args[1], args[2:]
    pw = os.environ.get("LOPEKART_PASSORD", "")
    if len(pw) < 12:
        sys.exit("Mangler LOPEKART_PASSORD (minst 12 tegn). Ingenting er bygget.")
    if not args:
        sys.exit("Ingen Strava-filer oppgitt. Ingenting er bygget.")
    main(args, korr, pw)
