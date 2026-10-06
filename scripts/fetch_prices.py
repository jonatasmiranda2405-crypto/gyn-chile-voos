#!/usr/bin/env python3
"""Busca preços GYN/BSB -> SCL no Google Flights via SerpApi e grava site/data.json.

Variáveis: SERPAPI_KEY (obrigatória), FLIGHT_DATE (padrão 2026-12-11), AFTER (padrão 19:30).
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "site" / "data.json"
DATE = os.environ.get("FLIGHT_DATE", "2026-12-11")
AFTER = os.environ.get("AFTER", "19:30")
DEST = "SCL"
ORIGINS = ["GYN", "BSB"]


def search(origin, key):
    params = {
        "engine": "google_flights", "departure_id": origin, "arrival_id": DEST,
        "outbound_date": DATE, "type": "2", "currency": "BRL", "hl": "pt", "gl": "br",
        "adults": "1", "travel_class": "1", "api_key": key,
    }
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def parse(resp):
    """Extrai ofertas que saem em DATE a partir de AFTER, ordenadas por preço."""
    offers = []
    for item in (resp.get("best_flights") or []) + (resp.get("other_flights") or []):
        legs = item.get("flights") or []
        price = item.get("price")
        if not legs or price is None:
            continue
        dep = legs[0]["departure_airport"]["time"]  # "2026-12-11 19:45"
        arr = legs[-1]["arrival_airport"]["time"]
        if dep[:10] != DATE or dep[11:16] < AFTER:
            continue
        airlines = []
        for leg in legs:
            a = leg.get("airline")
            if a and a not in airlines:
                airlines.append(a)
        offers.append({
            "airline": " + ".join(airlines),
            "flights": " ".join(leg.get("flight_number", "") for leg in legs).strip(),
            "dep": dep, "arr": arr,
            "stops": len(legs) - 1,
            "via": ", ".join(l.get("id") or l.get("name", "") for l in (item.get("layovers") or [])),
            "duration_min": item.get("total_duration"),
            "price": price,
        })
    offers.sort(key=lambda o: o["price"])
    return offers


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        msg = "Falta o segredo SERPAPI_KEY no repositório (Settings > Secrets and variables > Actions)."
        for o in ORIGINS:
            if data["routes"][o]["status"] != "ok":
                data["routes"][o] = {"status": "pending", "message": msg, "offers": []}
        data["message"] = msg
        DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(msg)
        return 0

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    point = {"when": now}
    failures = 0
    for o in ORIGINS:
        try:
            resp = search(o, key)
            if resp.get("error"):
                raise RuntimeError(resp["error"])
            offers = parse(resp)
            data["routes"][o] = {
                "status": "ok", "message": "", "offers": offers[:15],
                "google_flights_url": (resp.get("search_metadata") or {}).get("google_flights_url"),
            }
            point[o] = offers[0]["price"] if offers else None
            print(o, len(offers), "ofertas; menor:", point[o])
        except (urllib.error.URLError, RuntimeError, KeyError, ValueError) as e:
            failures += 1
            prev = data["routes"].get(o, {})
            msg = "Falha na última busca: %s" % e
            if prev.get("status") == "ok":
                prev["message"] = msg
                data["routes"][o] = prev
            else:
                data["routes"][o] = {"status": "error", "message": msg, "offers": []}
            point[o] = None
            print(o, msg, file=sys.stderr)

    if failures < len(ORIGINS):
        data["updated"] = now
        data["message"] = ""
        data.setdefault("history", []).append(point)
        data["history"] = data["history"][-500:]
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
