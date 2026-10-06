// Cloudflare Worker: faz a busca no Google Flights (SerpApi) para o site.
// A chave SERPAPI_KEY fica guardada como segredo aqui; o navegador nunca a vê.
// GET /search?from=GYN&to=SCL&date=2026-12-11&after=19:30&adults=1&sellers=2
const ALLOWED_ORIGINS = ["https://jonatasmiranda2405-crypto.github.io"]; // ajuste se mudar o domínio
const CACHE_SECONDS = 6 * 3600;   // mesma busca reaproveita o resultado por 6 horas
const PER_VISITOR_DAY = 8;        // buscas novas (fora do cache) por visitante por dia
const GLOBAL_DAY = 40;            // buscas novas por dia, somando todos (protege a cota)
const MAX_SELLERS = 2;            // ofertas por busca com "onde comprar" (1 chamada extra cada)

function cors(req) {
  const o = req.headers.get("Origin") || "";
  const ok = ALLOWED_ORIGINS.includes(o) || /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(o);
  return {
    "Access-Control-Allow-Origin": ok ? o : ALLOWED_ORIGINS[0],
    "Vary": "Origin",
  };
}
const json = (req, body, status = 200, extra = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...cors(req), ...extra },
  });

function validate(u) {
  const from = (u.searchParams.get("from") || "").toUpperCase();
  const to = (u.searchParams.get("to") || "").toUpperCase();
  const date = u.searchParams.get("date") || "";
  const after = u.searchParams.get("after") || "00:00";
  const adults = parseInt(u.searchParams.get("adults") || "1", 10);
  const sellers = Math.min(MAX_SELLERS, Math.max(0, parseInt(u.searchParams.get("sellers") || "0", 10) || 0));
  if (!/^[A-Z]{3}$/.test(from) || !/^[A-Z]{3}$/.test(to) || from === to) return { error: "Origem e destino devem ser códigos IATA de 3 letras e diferentes." };
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return { error: "Data inválida." };
  const d = Date.parse(date + "T12:00:00Z");
  const now = Date.now();
  if (isNaN(d) || d < now - 86400000 || d > now + 330 * 86400000) return { error: "Escolha uma data entre hoje e 330 dias à frente." };
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(after)) return { error: "Horário inválido." };
  if (!(adults >= 1 && adults <= 9)) return { error: "Número de adultos inválido (1 a 9)." };
  return { from, to, date, after, adults, sellers };
}

function parse(resp, q) {
  const offers = [];
  for (const item of [...(resp.best_flights || []), ...(resp.other_flights || [])]) {
    const legs = item.flights || [];
    if (!legs.length || item.price == null) continue;
    const dep = legs[0].departure_airport.time;
    const arr = legs[legs.length - 1].arrival_airport.time;
    if (dep.slice(0, 10) !== q.date || dep.slice(11, 16) < q.after) continue;
    const airlines = [];
    for (const l of legs) if (l.airline && !airlines.includes(l.airline)) airlines.push(l.airline);
    offers.push({
      airline: airlines.join(" + "),
      flights: legs.map((l) => l.flight_number || "").join(" ").trim(),
      dep, arr,
      stops: legs.length - 1,
      via: (item.layovers || []).map((l) => l.id || l.name || "").join(", "),
      duration_min: item.total_duration,
      price: item.price,
      booking_token: item.booking_token,
    });
  }
  return offers.sort((a, b) => a.price - b.price);
}

function parseBooking(resp) {
  const best = {};
  for (const opt of resp.booking_options || []) {
    for (const part of ["together", "departing"]) {
      const b = opt[part];
      if (!b || b.price == null) continue;
      const s = b.book_with || "?";
      if (!(s in best) || b.price < best[s]) best[s] = b.price;
    }
  }
  return Object.entries(best).sort((a, b) => a[1] - b[1]).map(([seller, price]) => ({ seller, price }));
}

async function serp(params, key) {
  const url = "https://serpapi.com/search.json?" + new URLSearchParams({ ...params, api_key: key });
  const r = await fetch(url);
  const j = await r.json();
  if (j.error) throw new Error(j.error);
  return j;
}

// Contador simples por dia usando o Cache API (sem custo, sem KV). Não é atômico, mas basta como freio.
async function bump(name, limit) {
  const cache = caches.default;
  const day = new Date().toISOString().slice(0, 10);
  const req = new Request("https://counter.invalid/" + day + "/" + name);
  const hit = await cache.match(req);
  const n = hit ? parseInt(await hit.text(), 10) : 0;
  if (n >= limit) return false;
  await cache.put(req, new Response(String(n + 1), { headers: { "Cache-Control": "max-age=90000" } }));
  return true;
}

export default {
  async fetch(req, env, ctx) {
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: { ...cors(req), "Access-Control-Allow-Methods": "GET", "Access-Control-Max-Age": "86400" } });
    const u = new URL(req.url);
    if (u.pathname !== "/search") return json(req, { error: "Use /search" }, 404);
    if (!env.SERPAPI_KEY) return json(req, { error: "Servidor sem SERPAPI_KEY." }, 500);

    const q = validate(u);
    if (q.error) return json(req, { error: q.error }, 400);

    const cache = caches.default;
    const key = new Request("https://cache.invalid/" + [q.from, q.to, q.date, q.after, q.adults, q.sellers].join("-"));
    const cached = await cache.match(key);
    if (cached) {
      const body = await cached.json();
      return json(req, { ...body, cached: true });
    }

    const ip = req.headers.get("CF-Connecting-IP") || "anon";
    if (!(await bump("ip-" + ip, PER_VISITOR_DAY))) return json(req, { error: "Limite diário de buscas atingido para você. Tente amanhã." }, 429);
    if (!(await bump("global", GLOBAL_DAY))) return json(req, { error: "O site atingiu o limite diário de buscas. Tente amanhã." }, 429);

    try {
      const base = {
        engine: "google_flights", departure_id: q.from, arrival_id: q.to, outbound_date: q.date,
        type: "2", currency: "BRL", hl: "pt", gl: "br", adults: String(q.adults), travel_class: "1",
      };
      const resp = await serp(base, env.SERPAPI_KEY);
      const offers = parse(resp, q);
      let n = q.sellers;
      for (const o of offers) {
        const token = o.booking_token; delete o.booking_token;
        if (n > 0 && token) {
          n--;
          try { o.sellers = parseBooking(await serp({ ...base, booking_token: token }, env.SERPAPI_KEY)); } catch (e) { /* segue sem vendedores */ }
        }
      }
      const out = {
        query: q, offers: offers.slice(0, 15), updated: new Date().toISOString(),
        google_flights_url: (resp.search_metadata || {}).google_flights_url || null,
      };
      ctx.waitUntil(cache.put(key, new Response(JSON.stringify(out), { headers: { "Cache-Control": "max-age=" + CACHE_SECONDS } })));
      return json(req, out);
    } catch (e) {
      return json(req, { error: "Falha na busca: " + e.message }, 502);
    }
  },
};
