#!/usr/bin/env python3
"""Busca preços GYN/BSB -> SCL no Google Flights via SerpApi e grava site/data.json.

Data, horário mínimo e origens ficam em site/config.json (editável). As variáveis
FLIGHT_DATE e AFTER, quando preenchidas, têm prioridade sobre o arquivo.
Para as N primeiras ofertas de cada origem (config.booking_options), uma segunda
chamada traz onde comprar (companhia e agências) e o preço em cada uma.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data.json"
CONFIG = ROOT / "site" / "config.json"
DEST = "SCL"


def load_config():
    cfg = {"date": "2026-12-11", "after": "19:30", "origins": ["GYN", "BSB"], "booking_options": {}}
    if CONFIG.exists():
        cfg.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    if os.environ.get("FLIGHT_DATE", "").strip():
        cfg["date"] = os.environ["FLIGHT_DATE"].strip()
    if os.environ.get("AFTER", "").strip():
        cfg["after"] = os.environ["AFTER"].strip()
    return cfg


def call(params, key):
    params = dict(params, api_key=key)
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as r:
        resp = json.load(r)
    if resp.get("error"):
        raise RuntimeError(resp["error"])
    return resp


def base_params(origin, cfg):
    return {
        "engine": "google_flights", "departure_id": origin, "arrival_id": DEST,
        "outbound_date": cfg["date"], "type": "2", "currency": "BRL", "hl": "pt", "gl": "br",
        "adults": "1", "travel_class": "1",
    }


def parse(resp, cfg):
    """Extrai ofertas que saem na data a partir do horário, ordenadas por preço."""
    offers = []
    for item in (resp.get("best_flights") or []) + (resp.get("other_flights") or []):
        legs = item.get("flights") or []
        price = item.get("price")
        if not legs or price is None:
            continue
        dep = legs[0]["departure_airport"]["time"]  # "2026-12-11 19:45"
        arr = legs[-1]["arrival_airport"]["time"]
        if dep[:10] != cfg["date"] or dep[11:16] < cfg["after"]:
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
            "booking_token": item.get("booking_token"),
        })
    offers.sort(key=lambda o: o["price"])
    return offers


def parse_booking(resp):
    """Lista de {seller, price} (menor preço por vendedor), do mais barato ao mais caro."""
    best = {}
    for opt in resp.get("booking_options") or []:
        for part in ("together", "departing"):
            b = opt.get(part)
            if not b or b.get("price") is None:
                continue
            seller = b.get("book_with") or "?"
            if seller not in best or b["price"] < best[seller]:
                best[seller] = b["price"]
    return [{"seller": s, "price": p} for s, p in sorted(best.items(), key=lambda kv: kv[1])]


def main():
    cfg = load_config()
    data = json.loads(DATA.read_text(encoding="utf-8"))
    key = os.environ.get("SERPAPI_KEY")
    origins = cfg["origins"]
    data["query"] = {"date": cfg["date"], "after": cfg["after"]}
    if not key:
        msg = "Falta o segredo SERPAPI_KEY no repositório (Settings > Secrets and variables > Actions)."
        for o in origins:
            data["routes"][o] = {"status": "pending", "message": msg, "offers": []}
        data["message"] = msg
        DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(msg)
        return 0

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    point = {"when": now, "date": cfg["date"], "after": cfg["after"]}
    failures = 0
    for o in origins:
        try:
            resp = call(base_params(o, cfg), key)
            offers = parse(resp, cfg)
            n = int((cfg.get("booking_options") or {}).get(o, 0))
            for offer in offers:
                token = offer.pop("booking_token", None)
                if n > 0 and token:
                    n -= 1
                    try:
                        bres = call(dict(base_params(o, cfg), booking_token=token), key)
                        offer["sellers"] = parse_booking(bres)
                    except (urllib.error.URLError, RuntimeError, ValueError) as e:
                        print(o, "booking options falhou:", e, file=sys.stderr)
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

    if failures < len(origins):
        data["updated"] = now
        data["message"] = ""
        data.setdefault("history", []).append(point)
        data["history"] = data["history"][-500:]
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
