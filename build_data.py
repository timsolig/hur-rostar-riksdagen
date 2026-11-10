#!/usr/bin/env python3
"""Hämtar riksdagens voteringar och skriver kompakta JSON-filer per riksmöte till data/.

Källa: Sveriges riksdag, data.riksdagen.se (öppna data).

    python build_data.py              # uppdaterar innevarande och föregående riksmöte
    python build_data.py --all        # alla riksmöten från 2002/03
    python build_data.py --rm 2019/20 # ett eller flera specifika riksmöten
"""
import argparse
import datetime as dt
import io
import json
import sys
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

BASE = "https://data.riksdagen.se"
OUT = Path(__file__).resolve().parent / "data"
FIRST_YEAR = 2002  # JSON-dataset finns från 2002/03

PARTY_ORDER = ["V", "S", "MP", "C", "L", "KD", "M", "SD"]
PARTY_ALIAS = {"FP": "L", "KDS": "KD", "": "-"}
VOTE_INDEX = {"Ja": 0, "Nej": 1, "Avstår": 2, "Frånvarande": 3}


def rm_name(year):
    return f"{year}/{(year + 1) % 100:02d}"


def rm_file(year):
    return f"{year}-{(year + 1) % 100:02d}.json"


def year_of(rm):
    return int(rm.split("/")[0])


def current_year(today=None):
    today = today or dt.date.today()
    return today.year if today.month >= 9 else today.year - 1


def get(url, tries=3):
    for attempt in range(tries):
        try:
            req = Request(url, headers={"User-Agent": "riksdagens-samarbeten/1.0"})
            with urlopen(req, timeout=180) as r:
                return r.read()
        except HTTPError as e:
            if e.code == 404:
                raise
            if attempt == tries - 1:
                raise
        except OSError:
            if attempt == tries - 1:
                raise
        time.sleep(3 * (attempt + 1))


def as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def iter_rows(obj):
    """Hittar alla ledamotsrader (dict med votering_id och rost), oavsett nästling."""
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if "votering_id" in o and "rost" in o:
                yield o
            else:
                stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)


def norm_party(p):
    p = (p or "").strip().upper()
    return PARTY_ALIAS.get(p, p)


def to_int(x):
    try:
        return int(str(x).strip())
    except ValueError:
        return 0


def load_votes(year):
    url = f"{BASE}/dataset/votering/votering-{year}{(year + 1) % 100:02d}.json.zip"
    raw = get(url)
    votes, seen = {}, {}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue
            data = json.loads(z.read(name).decode("utf-8-sig"))
            for row in iter_rows(data):
                if row.get("votering") not in (None, "", "huvud"):
                    continue
                idx = VOTE_INDEX.get((row.get("rost") or "").strip())
                if idx is None:
                    continue
                vid = row["votering_id"]
                v = votes.get(vid)
                if v is None:
                    avser = (row.get("avser") or "").lower()
                    v = votes[vid] = {
                        "d": (row.get("datum") or row.get("systemdatum") or "")[:10],
                        "b": (row.get("beteckning") or "").strip(),
                        "p": to_int(row.get("punkt")),
                        "a": "m" if avser.startswith("motiv") else "s",
                        "dok": (row.get("dok_id") or "").strip(),
                        "c": {},
                    }
                    seen[vid] = set()
                who = row.get("intressent_id") or (row.get("namn"), row.get("banknummer"))
                if who in seen[vid]:
                    continue
                seen[vid].add(who)
                counts = v["c"].setdefault(norm_party(row.get("parti")), [0, 0, 0, 0])
                counts[idx] += 1
    return votes


def load_titles(year):
    """Betänkandenas titel och dok_id, nyckel beteckning (t.ex. JuU41)."""
    titles = {}
    url = (f"{BASE}/dokumentlista/?doktyp=bet&rm={quote(rm_name(year))}"
           f"&sz=500&sort=datum&sortorder=asc&utformat=json")
    for _ in range(30):
        d = json.loads(get(url).decode("utf-8-sig"))["dokumentlista"]
        for doc in as_list(d.get("dokument")):
            bet = (doc.get("beteckning") or "").strip()
            if bet:
                titles[bet] = ((doc.get("titel") or "").strip(), (doc.get("dok_id") or doc.get("id") or "").strip())
        url = d.get("@nasta_sida")
        if not url:
            break
        url = "https://" + url.split("://", 1)[-1]
        time.sleep(0.3)
    return titles


def party_order(found):
    known = [p for p in PARTY_ORDER if p in found]
    other = sorted(p for p in found if p not in PARTY_ORDER and p != "-")
    return known + other + (["-"] if "-" in found else [])


def load_vote_doc(vid):
    """Titel, datum och dok_id för en votering, hämtat från voteringens eget dokument.

    Behövs för omröstningar som inte hör till något betänkande (statsministeromröstningar,
    misstroendeförklaringar) och för voteringar där datasetet saknar datum."""
    try:
        d = json.loads(get(f"{BASE}/votering/{quote(vid)}/json").decode("utf-8-sig"))
        doc = d["votering"]["dokument"]
    except (HTTPError, OSError, ValueError, KeyError, TypeError):
        return "", "", ""
    title = (doc.get("titel") or "").strip()
    if title.startswith("Omröstning: "):
        title = title[len("Omröstning: "):]
    return title, (doc.get("datum") or doc.get("systemdatum") or "")[:10], (doc.get("dok_id") or "").strip()


def fill_missing(votes, titles, doc_fn=load_vote_doc):
    """Sätter titel och dok_id per beteckning och kompletterar det som saknas i voteringsdatat."""
    lower = {k.lower(): t for k, t in titles.items()}
    for vid, v in votes.items():
        title, dok = titles.get(v["b"]) or lower.get(v["b"].lower(), ("", ""))
        if title and v["d"]:
            titles[v["b"]] = (title, dok or v["dok"])
            continue
        doc_title, doc_date, doc_dok = doc_fn(vid)
        time.sleep(0.2)
        if not title:
            title, dok = doc_title, doc_dok
        titles[v["b"]] = (title, dok or v["dok"])
        v["d"] = v["d"] or doc_date


def build_year(year, titles_fn=load_titles, votes_fn=load_votes, doc_fn=load_vote_doc):
    votes = votes_fn(year)
    if not votes:
        return None
    titles = titles_fn(year)
    fill_missing(votes, titles, doc_fn)
    parties = party_order({p for v in votes.values() for p in v["c"]})
    bet = {}
    rows = []
    for v in sorted(votes.values(), key=lambda v: (v["d"], v["b"], v["p"], v["a"])):
        if v["b"] not in bet:
            bet[v["b"]] = list(titles.get(v["b"], ("", v["dok"])))
        flat = []
        for p in parties:
            flat.extend(v["c"].get(p, [0, 0, 0, 0]))
        rows.append([v["d"], v["b"], v["p"], v["a"], flat])
    return {"rm": rm_name(year), "parties": parties, "bet": bet, "votes": rows}


def write_index():
    years = []
    for f in sorted(OUT.glob("*-*.json"), reverse=True):
        d = json.loads(f.read_text(encoding="utf-8"))
        years.append({"rm": d["rm"], "file": f.name, "n": len(d["votes"])})
    index = {
        "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source": "Sveriges riksdag, data.riksdagen.se",
        "years": years,
    }
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="alla riksmöten från 2002/03")
    ap.add_argument("--rm", nargs="*", default=[], help="riksmöten, t.ex. 2019/20")
    args = ap.parse_args(argv)

    now = current_year()
    if args.rm:
        years = [year_of(rm) for rm in args.rm]
    elif args.all or not (OUT / "index.json").exists():
        years = list(range(FIRST_YEAR, now + 1))
    else:
        years = [now - 1, now]

    OUT.mkdir(exist_ok=True)
    failed = 0
    for year in years:
        print(f"{rm_name(year)} ...", end=" ", flush=True)
        try:
            data = build_year(year)
        except HTTPError as e:
            print(f"hoppar över ({e.code})")
            continue
        except Exception as e:  # noqa: BLE001
            print(f"fel: {e}")
            failed += 1
            continue
        if data is None:
            print("inga voteringar")
            continue
        path = OUT / rm_file(year)
        path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{len(data['votes'])} voteringar, {path.stat().st_size // 1024} kB")
    write_index()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
