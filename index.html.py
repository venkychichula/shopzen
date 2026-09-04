# =====================================================================
# SHOPZEN AI - TRUSTED PRICE FINAL
# ✔ Real-Price Knowledge Engine (accurate Indian street prices)
# ✔ LIVE store fetch overrides → exact current price
# ✔ Friendly Q&A, one exact buy link, all features
# =====================================================================
from fastapi import FastAPI, Response, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os, json, random, hashlib, hmac, uuid, time, re, socket
import urllib.parse, urllib.request, concurrent.futures
from datetime import datetime, timedelta
from collections import OrderedDict
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="ShopZen AI", version="31.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
try:
    from openai import OpenAI
    client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
except ImportError:
    OpenAI = None; client = None
MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]

STORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_store.json")
USERS, FEEDBACK, SEARCH_HISTORY, CONVERSATIONS, ROOMS, WISHLISTS = {}, [], {}, {}, {}, {}
LAST_ACTIVE, RATE_BUCKETS, ASKED, CLARIFY_STATE = {}, {}, {}, {}
SESSION_TTL = 60 * 60 * 24 * 7
CHAT_COUNT = 0
CACHE = OrderedDict(); CACHE_MAX = 100
LIVE_CACHE = {}

def load_store():
    global USERS, FEEDBACK, SEARCH_HISTORY, CONVERSATIONS, ROOMS, WISHLISTS
    try:
        if os.path.exists(STORE_FILE):
            with open(STORE_FILE, encoding="utf-8") as f: d = json.load(f)
            USERS = d.get("users", {}); FEEDBACK = d.get("feedback", [])
            SEARCH_HISTORY = d.get("search_history", {}); CONVERSATIONS = d.get("conversations", {})
            ROOMS = d.get("rooms", {}); WISHLISTS = d.get("wishlists", {})
    except Exception: pass

def save_store():
    try:
        with open(STORE_FILE, "w", encoding="utf-8") as f:
            json.dump({"users": USERS, "feedback": FEEDBACK, "search_history": SEARCH_HISTORY,
                       "conversations": CONVERSATIONS, "rooms": ROOMS, "wishlists": WISHLISTS}, f)
    except Exception: pass
load_store()

APP_SECRET = "shopzen-ai-secret-2026"
def make_token(uid):
    exp = int(time.time()) + SESSION_TTL
    payload = uid + "." + str(exp)
    sig = hmac.new(APP_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + sig

def verify_token(tok):
    try:
        uid, exp, sig = tok.rsplit(".", 2)
        if int(exp) <= time.time(): return None
        expect = hmac.new(APP_SECRET.encode(), (uid + "." + exp).encode(), hashlib.sha256).hexdigest()
        return uid if hmac.compare_digest(sig, expect) else None
    except Exception:
        return None

# --------------- REAL-PRICE KNOWLEDGE ENGINE (true street prices) ---------------
PRICE_KB = [
    # phones
    ("redmi note 13 pro", 19999), ("redmi note 13", 13999), ("redmi note 14 pro", 21999),
    ("redmi 13c", 7499), ("redmi 12 5g", 9999), ("redmi 12", 8999),
    ("samsung galaxy m15", 10999), ("samsung galaxy m35", 17999), ("samsung galaxy a15", 12499),
    ("samsung galaxy a55", 27999), ("samsung galaxy s23 fe", 36999), ("samsung galaxy s24", 57999),
    ("iphone 15 pro", 119900), ("iphone 15", 65999), ("iphone 14", 57999), ("iphone 13", 49999),
    ("oneplus nord ce4 lite", 19999), ("oneplus nord ce4", 24999), ("oneplus 12r", 39999), ("oneplus 12", 64999),
    ("realme narzo 70x", 13999), ("realme narzo 70", 15999), ("realme 12 pro", 21999), ("realme c67", 12999),
    ("vivo t3 5g", 16999), ("vivo t3", 16999), ("vivo y28", 11999), ("vivo y18", 9499),
    ("iqoo z9 5g", 17999), ("iqoo z9", 17999), ("iqoo neo 9", 29999),
    ("poco x6 pro", 26999), ("poco x6", 21999), ("poco m6 pro", 10999), ("poco c65", 7499),
    # laptops
    ("macbook air m1", 67990), ("macbook air m2", 84990), ("macbook pro m3", 159900),
    ("hp 15s", 48990), ("hp laptop 15", 42990), ("hp pavilion 15", 62990), ("hp victus", 72990),
    ("lenovo ideapad slim 3", 38990), ("lenovo ideapad 3", 36990), ("lenovo ideapad slim 5", 55990),
    ("lenovo legion 5", 92990), ("lenovo loq", 72990),
    ("asus vivobook 15", 41990), ("asus vivobook 16", 52990), ("asus tuf f15", 72990), ("asus tuf gaming", 74990),
    ("acer nitro v", 62990), ("acer nitro 5", 69990), ("acer aspire 5", 45990), ("acer aspire 3", 32990),
    ("dell inspiron 15", 47990), ("dell g15", 79990), ("msi gf63", 64990),
    # earbuds
    ("boat airdopes 141", 1099), ("boat airdopes 311", 1299), ("boat airdopes 161", 999),
    ("boat airdopes 138", 899), ("boat airdopes 800", 1499),
    ("noise buds connect", 999), ("noise tws neo", 899), ("noise air buds", 1299),
    ("jbl wave beam", 1799), ("jbl wave buds", 1499), ("jbl tune 500", 2999),
    ("oneplus buds z2", 2999), ("oneplus buds 3", 4999),
    ("oppo enco air3", 1999), ("realme buds air 5", 1799), ("sony wi-c100", 1490),
    # headphones
    ("jbl tune 510bt", 2499), ("jbl tune 770nc", 4999), ("sony wh-ch520", 2990),
    ("sony wh-1000xm5", 26990), ("boat rockerz 450", 1499), ("boat rockerz 550", 1999),
    ("sennheiser hd 206", 1790), ("bo at rockerz", 1499),
    # watches
    ("noise colorfit pro 5", 2499), ("noise colorfit pro 4", 1999), ("noise colorfit pulse 3", 1799),
    ("fire-boltt ninja", 1299), ("fire-boltt phoenix", 1099), ("fire boltt", 1299),
    ("boat wave sigma", 1499), ("boat storm", 1299), ("titan smart", 4999),
    ("samsung galaxy watch6", 21999), ("apple watch se", 29900),
    # shoes
    ("nike revolution 7", 2699), ("nike downshifter 13", 3299), ("nike air force 1", 8695),
    ("adidas runfalcon 3", 2799), ("adidas duramo sl", 2999), ("adidas galaxy step", 2499),
    ("puma smash v2", 2499), ("puma rickie", 1999), ("campus oxyfit", 1299), ("campus", 1199),
    ("asian wonder", 799), ("sparx", 999),
    # tv / tablet / camera
    ("mi tv 43", 24999), ("redmi smart tv 43", 24999), ("samsung 43 inch tv", 28990), ("lg 43 inch tv", 27990),
    ("ipad 10th gen", 34999), ("ipad 9th gen", 29900), ("samsung galaxy tab a9", 13999),
    ("lenovo tab m10", 11999), ("oneplus pad", 29999),
    ("canon eos 1500d", 35990), ("nikon d3500", 38990), ("sony zv-1f", 44990), ("gopro hero 12", 32990),
]
KB_SORTED = sorted(PRICE_KB, key=lambda kv: len(kv[0]), reverse=True)
def kb_price(name):
    n = (name or "").lower()
    for keys, price in KB_SORTED:
        if keys in n: return price
    return None

# ------------------- LIVE EXACT-PRODUCT ENGINE -----------------------
STORE_LIST = ["Amazon", "Flipkart", "Croma", "Tata CLiQ", "Reliance Digital", "Vijay Sales", "Snapdeal"]
STORE_DOMAINS = {"Amazon": "amazon.in", "Flipkart": "flipkart.com", "Croma": "croma.com",
    "Tata CLiQ": "tatacliq.com", "Reliance Digital": "reliancedigital.in",
    "Vijay Sales": "vijaysales.com", "Snapdeal": "snapdeal.com"}

def _http_get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept-Language": "en-IN,en;q=0.9", "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=6) as r:
        return r.read().decode("utf-8", "ignore")

def direct_url(store, name):
    d = STORE_DOMAINS.get(store, "google.com")
    return "https://duckduckgo.com/?q=" + urllib.parse.quote('!ducky site:' + d + ' "' + name + '"')

def _resolve_exact(domain, name):
    try:
        q = urllib.parse.quote('site:' + domain + ' "' + name + '"')
        html = _http_get("https://html.duckduckgo.com/html/?q=" + q)
        m = re.search(r'uddg=([^&"]+)', html)
        if m: return urllib.parse.unquote(m.group(1))
    except Exception: pass
    return None

def _price_from_page(url):
    try:
        html = _http_get(url)
        m = re.search(r'₹\s*([\d,]{3,})', html)
        if m: return int(m.group(1).replace(",", ""))
        m = re.search(r'"price"\s*:\s*"([\d.]+)"', html)
        if m: return int(float(m.group(1)))
    except Exception: pass
    return None

def _scrape_flipkart(name):
    try:
        html = _http_get("https://www.flipkart.com/search?q=" + urllib.parse.quote(name))
        m = re.search(r'href="([^"]*?/p/itm[^"]*?)"', html)
        if not m: return None
        url = "https://www.flipkart.com" + m.group(1).split("?")[0]
        pm = re.search(r"₹([\d,]+)", html[m.end():])
        if not pm: return None
        return {"store": "Flipkart", "price": int(pm.group(1).replace(",", "")), "url": url, "live": True}
    except Exception:
        return None

def _scrape_amazon(name):
    try:
        html = _http_get("https://www.amazon.in/s?k=" + urllib.parse.quote(name))
        m = re.search(r'href="(/[^"]*?/dp/[A-Z0-9]{10})', html)
        if not m: return None
        url = "https://www.amazon.in" + m.group(1)
        pm = re.search(r"₹([\d,]+)", html[m.end():])
        if not pm: return None
        return {"store": "Amazon", "price": int(pm.group(1).replace(",", "")), "url": url, "live": True}
    except Exception:
        return None

def _live_store(store, name):
    if store == "Flipkart":
        r = _scrape_flipkart(name)
        if r: return r
    if store == "Amazon":
        r = _scrape_amazon(name)
        if r: return r
    url = _resolve_exact(STORE_DOMAINS[store], name) or direct_url(store, name)
    price = _price_from_page(url) if ("duckduckgo" not in url) else None
    return {"store": store, "price": price, "url": url, "live": price is not None}

def fetch_live_prices(name):
    key = name.lower().strip(); now = time.time()
    c = LIVE_CACHE.get(key)
    if c and now - c["ts"] < 300: return c["results"]
    results = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
            futs = [ex.submit(_live_store, s, name) for s in STORE_LIST]
            for f in concurrent.futures.as_completed(futs, timeout=14):
                try:
                    r = f.result()
                    if r: results.append(r)
                except Exception: pass
    except Exception: pass
    order = {s: i for i, s in enumerate(STORE_LIST)}
    results.sort(key=lambda x: order.get(x["store"], 99))
    LIVE_CACHE[key] = {"ts": now, "results": results}
    return results

# ------------------------------ AI CORE ------------------------------
SYSTEM_PROMPT = """You are ShopZen AI, a warm, friendly Indian shopping buddy 🛍️. Talk like a helpful friend, 1-2 light emojis, short caring summaries.
Respond with ONLY valid JSON. No markdown. No ```json.
ABSOLUTE RULES:
- NEVER repeat your previous answer.
- If the user switches category, treat as brand-new query.
- "products" MUST contain EXACTLY 4 items; FIRST must be the single best EXACT match for the user's brand/colour/budget/who.
- Respect user preferences STRICTLY.
- price = plain integer INR. Use EXACT current Indian street prices (e.g. Redmi Note 13 ≈ 13999, iPhone 15 ≈ 65999, boAt Airdopes 141 ≈ 1099). NEVER inflate prices.
INTENTS:
1) "chat": {"intent":"chat","summary":"friendly answer"}
2) "clarify": {"intent":"clarify","summary":"friendly question line","questions":[{"q":"...","options":["..."]}]}
3) "search": {"intent":"search","summary":"2-sentence friendly highlight","products":[{"name":"real Indian model","brand":"b","price":12345,"price_range":[11999,13499],"rating":4.5,"price_trend":"stable","festival_tip":"tip","image_prompt":"6-word visual white bg","specs":{},"pros":["p1","p2"],"cons":["c1"],"ai_reason":"why it fits THIS user"}]}
4) "decide": {"intent":"decide","summary":"verdict","winner":{...same as product...},"runner_up":""}
5) "timing": {"intent":"timing","summary":"advice","timing":{"product":"m","price_now":12345,"predicted_price":11800,"verdict":"WAIT","best_window":"Diwali","expected_drop_pct":10,"reason":"why"}}
6) "compare": {"intent":"compare","summary":"s","products":["A","B"],"comparison":[{"feature":"Price","values":["100","200"]}]}
7) "review": {"intent":"review","summary":"s","trust_score":80,"fake_pct":10,"reviews":[{"text":"review","verified":true,"rating":4}]}
8) "negotiate": {"intent":"negotiate","summary":"s","original_price":5000,"final_price":4500,"script":["AI: Hi","Seller: Yes"]}
"""

CATEGORY_DICT = {
    "laptop": ["laptop", "notebook", "macbook"], "phone": ["phone", "mobile", "smartphone", "iphone", "samsung"],
    "shoes": ["shoe", "shoes", "sneaker", "nike", "adidas"], "earbuds": ["earbud", "earbuds", "tws", "buds", "airpods"],
    "headphones": ["headphone", "headset"], "watch": ["watch", "smartwatch"], "tablet": ["tablet", "ipad"],
    "tv": ["tv", "television"], "camera": ["camera", "dslr"],
}
USE_WORDS = ["gaming","coding","college","office","running","gym","fitness","travel","study","daily","music","camera","editing"]
PRICE_BOUNDS = {
    "laptop": (25000, 120000), "phone": (6000, 80000), "shoes": (900, 12000),
    "earbuds": (800, 12000), "headphones": (1200, 20000), "watch": (1200, 25000),
    "tablet": (9000, 60000), "tv": (10000, 80000), "camera": (15000, 90000)
}
def clamp_price(cat, price):
    mn, mx = PRICE_BOUNDS.get(cat, (500, 500000))
    return int(max(mn, min(price, mx)))

BRAND_OPTIONS = {
    "phone": ["Redmi", "Samsung", "Realme", "OnePlus", "Vivo"],
    "laptop": ["HP", "Dell", "Lenovo", "Asus", "Acer", "Apple"],
    "earbuds": ["boAt", "Noise", "JBL", "Sony", "OnePlus"],
    "headphones": ["JBL", "Sony", "boAt", "Sennheiser"],
    "shoes": ["Nike", "Adidas", "Puma", "Campus"],
    "watch": ["Noise", "Fire-Boltt", "boAt", "Titan"],
    "tablet": ["Samsung", "Apple", "Lenovo"], "tv": ["Samsung", "LG", "Xiaomi", "Sony"],
    "camera": ["Canon", "Nikon", "Sony"],
}

def clarify_questions(cat):
    qs = [{"key": "budget", "q": "What's your budget? 💰",
           "options": ["Under 5000", "Under 20000", "Under 60000", "Under 100000", "No limit"]},
          {"key": "brand", "q": "Which brand do you prefer? ✨",
           "options": BRAND_OPTIONS.get(cat, ["Any brand"]) + ["Any brand"]}]
    if cat in ("shoes", "watch"):
        qs.append({"key": "who", "q": "Who is it for? 🙂", "options": ["Male", "Female", "Kids", "Unisex"]})
    else:
        qs.append({"key": "color", "q": "Which colour do you love? 🎨", "options": ["Black", "Blue", "White", "Any colour"]})
    for q in qs: q["options"] = q["options"] + ["⏭️ Skip, show now"]
    return qs

FRIENDLY_NEXT = {"budget": "Perfect! 💸", "brand": "Great taste! ✨", "color": "Love that! 🎨", "who": "Got it! 🙂"}

def store_price_comparison(name, base):
    base = max(1, int(to_num(base, 0)))
    rnd = random.Random(int(hashlib.md5(str(name).encode()).hexdigest(), 16) ^ 0x5f3)
    return [{"store": s, "price": int(base * rnd.uniform(0.95, 1.05)), "url": direct_url(s, name), "live": False} for s in STORE_LIST]

def to_num(v, default=0):
    try:
        if v is None: return default
        s = str(v).replace(",", "").replace("₹", "").lower().replace("rs", "").strip()
        m = re.search(r"-?\d+(\.\d+)?", s)
        return float(m.group(0)) if m else default
    except Exception:
        return default

def extract_category(text):
    text = text.lower()
    for cat, words in CATEGORY_DICT.items():
        if any(w in text for w in words): return cat
    return None

def extract_budget(text):
    text = text.lower()
    for pattern in [r"(?:under|below|budget|around)\s*(?:₹|rs\.?|inr)?\s*([0-9,]{3,})", r"(?:₹|rs\.?|inr)\s*([0-9,]{3,})"]:
        m = re.search(pattern, text)
        if m: return int(m.group(1).replace(",", ""))
    return None

def is_fragment(msg):
    m = msg.lower().strip()
    if extract_category(m): return False
    return len(m) <= 40

def get_image_url(prompt, name):
    seed = int(hashlib.md5(str(name).encode()).hexdigest(), 16) % 10000
    return "https://image.pollinations.ai/prompt/" + urllib.parse.quote(str(prompt)) + "?width=400&height=300&nologo=true&seed=" + str(seed)

def build_price_data(price, trend, name):
    price = max(1, int(to_num(price, 0)))
    rnd = random.Random(int(hashlib.md5(str(name).encode()).hexdigest(), 16))
    today = datetime.now()
    if trend == "falling": start = price * rnd.uniform(1.10, 1.22)
    elif trend == "rising": start = price * rnd.uniform(0.90, 0.97)
    else: start = price * rnd.uniform(1.00, 1.08)
    history = []
    for i in range(12):
        t = i / 11
        val = (start + (price - start) * t) * (1 + rnd.uniform(-0.02, 0.02))
        if 5 <= i <= 8 and rnd.random() < 0.5: val *= 0.95
        history.append(round(val))
    history[-1] = price
    if trend == "falling": forecast = [round(price * (1 - 0.008 * (i + 1))) for i in range(4)]
    elif trend == "rising": forecast = [round(price * (1 + 0.006 * (i + 1))) for i in range(4)]
    else: forecast = [round(price * (1 + rnd.uniform(-0.004, 0.004) * (i + 1))) for i in range(4)]
    labels = [(today - timedelta(days=7 * (11 - i))).strftime("%d %b") for i in range(12)]
    labels += [(today + timedelta(days=7 * (i + 1))).strftime("%d %b") for i in range(4)]
    predicted = forecast[-1]
    drop_pct = round((price - predicted) / price * 100, 1) if price else 0
    if drop_pct >= 2: verdict, advice = "WAIT", "Price trending down. Wait 2-4 weeks to save about Rs " + str(price - predicted) + "."
    elif drop_pct <= -2: verdict, advice = "BUY NOW", "Price rising. Buy soon before it crosses Rs " + str(predicted) + "."
    else: verdict, advice = "BUY NOW", "Price is stable. Buy when convenient."
    return {"history": history, "forecast": forecast, "labels": labels, "predicted_price": predicted,
            "verdict": verdict, "advice": advice, "lowest": min(history), "highest": max(history)}

def condense(data):
    intent = data.get("intent"); summ = str(data.get("summary") or "")[:140]
    if intent == "search" and data.get("products"):
        return "AI recommended: " + ", ".join([str(p.get("name")) + " (Rs " + str(p.get("price")) + ")" for p in data["products"][:4]]) + ". " + summ
    if intent == "decide" and data.get("winner"):
        return "FINAL pick: " + str(data["winner"].get("name")) + " (Rs " + str(data["winner"].get("price")) + "). " + summ
    if intent == "timing" and data.get("timing"):
        return "AI timing: " + str(data["timing"].get("verdict")) + " for " + str(data["timing"].get("product")) + ". " + summ
    return "AI said: " + summ

def get_stats():
    total = len(FEEDBACK); up = sum(1 for f in FEEDBACK if f["rating"] == "up")
    return {"total": total, "up": up, "down": total - up, "score": round(up / total * 100) if total else 100}

def call_llm(messages):
    for attempt in range(3):
        for model in MODELS:
            try:
                resp = client.chat.completions.create(model=model, messages=messages, temperature=0.6, response_format={"type": "json_object"})
                return resp.choices[0].message.content.strip(), model
            except Exception: continue
        if attempt < 2: time.sleep(2 * (attempt + 1))
    return "{}", MODELS[0]

def llm_text(prompt):
    try:
        resp = client.chat.completions.create(model=MODELS[0], messages=[{"role": "system", "content": "You are ShopZen AI, a friendly shopping buddy. Reply plain text, max 3 sentences, warm tone."}, {"role": "user", "content": prompt}], temperature=0.7)
        return resp.choices[0].message.content.strip()
    except Exception: return None

def rate_limit(key, limit=20, window=60):
    now = time.time(); bucket = RATE_BUCKETS.setdefault(key, [])
    RATE_BUCKETS[key] = [t for t in bucket if now - t < window]
    if len(RATE_BUCKETS[key]) >= limit: raise HTTPException(status_code=429, detail="Too many requests.")
    RATE_BUCKETS[key].append(now)

def hash_pw(pw):
    salt = os.urandom(16); digest = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, 100_000)
    return "pbkdf2$100000$" + salt.hex() + "$" + digest.hex()

def verify_pw(pw, stored):
    if stored.startswith("pbkdf2$"):
        try:
            _, iterations, salt_hex, digest_hex = stored.split("$", 3)
            digest = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
            return hmac.compare_digest(digest.hex(), digest_hex), False
        except Exception: return False, False
    return hmac.compare_digest(hashlib.sha256(pw.encode("utf-8")).hexdigest(), stored), True

def current_user(authorization=""):
    if not authorization.startswith("Bearer "): return None
    return verify_token(authorization[7:].strip())

def require_user(authorization, requested_uid=None):
    uid = current_user(authorization)
    if not uid: raise HTTPException(status_code=401, detail="Authentication required")
    if requested_uid and requested_uid != uid: raise HTTPException(status_code=403, detail="Forbidden")
    return uid

ALLOWED_INTENTS = {"chat", "clarify", "explain", "search", "compare", "review", "negotiate", "decide", "timing"}

def normalize_llm_data(data, cat=None):
    if not isinstance(data, dict): data = {}
    intent = data.get("intent")
    if intent not in ALLOWED_INTENTS:
        data["intent"] = "chat"; data["summary"] = str(data.get("summary") or "Here's my take.")[:800]
    else:
        data["summary"] = str(data.get("summary") or "")[:800]
    if data.get("intent") == "search":
        products = data.get("products") or []
        if not isinstance(products, list): products = []
        products = products[:4]
        for p in products:
            if not isinstance(p, dict): continue
            p["name"] = str(p.get("name") or "Unknown")[:160]; p["brand"] = str(p.get("brand") or "")[:80]
            kp = kb_price(p["name"])
            if kp: p["price"] = kp
            else: p["price"] = clamp_price(cat, max(1, int(to_num(p.get("price"), 0)))) if cat else max(1, int(to_num(p.get("price"), 0)))
            p["rating"] = max(0, min(5, to_num(p.get("rating"), 0)))
            if p.get("price_trend") not in {"falling", "stable", "rising"}: p["price_trend"] = "stable"
        data["products"] = products
    if data.get("intent") == "compare":
        if not isinstance(data.get("products"), list): data["products"] = []
        if not isinstance(data.get("comparison"), list): data["comparison"] = []
    if data.get("intent") == "review":
        if not isinstance(data.get("reviews"), list): data["reviews"] = []
    return data

class ChatReq(BaseModel): message: str; user_id: str = "demo"
class ResetReq(BaseModel): user_id: str = "demo"
class FeedbackReq(BaseModel): rating: str; reason: str = ""; summary: str = ""; user_id: str = "demo"
class AuthReq(BaseModel): name: str; password: str = ""
class RoomCreateReq(BaseModel): user: str = "friend"
class RoomJoinReq(BaseModel): code: str; user: str = "friend"
class RoomSendReq(BaseModel): code: str; user: str = "friend"; text: str = ""
class WishAddReq(BaseModel): user_id: str; product: dict
class WishRemoveReq(BaseModel): user_id: str; name: str

HISTORY = {}; LAST_QUERY = {}

@app.post("/register")
def register(req: AuthReq, request: Request):
    rate_limit("reg:" + request.client.host, 8, 600)
    name = (req.name or "").strip(); key = name.lower()
    if not name: return {"ok": False, "error": "Name required"}
    if len(req.password) < 4: return {"ok": False, "error": "Password 4+ chars"}
    if key in USERS: return {"ok": False, "error": "User exists"}
    USERS[key] = {"name": name, "pass": hash_pw(req.password), "created": datetime.now().isoformat()}
    save_store()
    return {"ok": True, "token": make_token(key), "uid": key, "user": name}

@app.post("/login")
def login(req: AuthReq, request: Request):
    rate_limit("login:" + request.client.host, 10, 300)
    key = (req.name or "").strip().lower(); u = USERS.get(key)
    if not u:
        if len(req.password) < 4: return {"ok": False, "error": "Password 4+ chars"}
        USERS[key] = {"name": (req.name or "").strip(), "pass": hash_pw(req.password), "created": datetime.now().isoformat()}
        save_store()
        return {"ok": True, "token": make_token(key), "uid": key, "user": (req.name or "").strip()}
    valid, legacy = verify_pw(req.password, u.get("pass", ""))
    if not valid: return {"ok": False, "error": "Invalid password"}
    if legacy: u["pass"] = hash_pw(req.password); save_store()
    return {"ok": True, "token": make_token(key), "uid": key, "user": u["name"]}

@app.post("/guest")
def guest(request: Request):
    rate_limit("guest:" + request.client.host, 10, 300)
    gid = "guest_" + uuid.uuid4().hex[:6]
    return {"ok": True, "token": make_token(gid), "uid": gid, "user": "Guest " + gid[-4:].upper()}

@app.post("/reset")
def reset(req: ResetReq, authorization: str = Header(default="")):
    uid = require_user(authorization, req.user_id)
    HISTORY.pop(uid, None); LAST_QUERY.pop(uid, None); CONVERSATIONS.pop(uid, None); ASKED.pop(uid, None); CLARIFY_STATE.pop(uid, None)
    save_store(); return {"ok": True}

@app.get("/history")
def history(user_id: str = "demo", authorization: str = Header(default="")):
    return SEARCH_HISTORY.get(require_user(authorization, user_id), [])

@app.get("/conversation")
def conversation(user_id: str = "demo", authorization: str = Header(default="")):
    return CONVERSATIONS.get(require_user(authorization, user_id), [])

@app.get("/liveprices")
def liveprices(name: str = "", authorization: str = Header(default="")):
    require_user(authorization)
    return {"results": fetch_live_prices(name or "")}

@app.get("/analytics")
def analytics():
    now = time.time()
    return {"online": sum(1 for t in LAST_ACTIVE.values() if now - t < 120), "users": len(LAST_ACTIVE), "chats": CHAT_COUNT, "stats": get_stats()}

@app.get("/stats")
def stats(): return get_stats()

@app.post("/feedback")
def feedback(req: FeedbackReq, authorization: str = Header(default="")):
    uid = require_user(authorization, req.user_id)
    rating = req.rating if req.rating in {"up", "down"} else "down"
    FEEDBACK.append({"rating": rating, "reason": req.reason[:120], "summary": req.summary[:200], "user": uid})
    save_store(); return {"ok": True, "stats": get_stats()}

@app.get("/wishlist")
def wishlist(authorization: str = Header(default="")):
    return WISHLISTS.get(require_user(authorization), [])

@app.post("/wishlist/add")
def wish_add(req: WishAddReq, authorization: str = Header(default="")):
    uid = require_user(authorization, req.user_id); wl = WISHLISTS.setdefault(uid, [])
    if not any(w.get("name") == req.product.get("name") for w in wl): wl.append(req.product); save_store()
    return {"ok": True}

@app.post("/wishlist/remove")
def wish_remove(req: WishRemoveReq, authorization: str = Header(default="")):
    uid = require_user(authorization, req.user_id)
    WISHLISTS[uid] = [w for w in WISHLISTS.get(uid, []) if w.get("name") != req.name]
    save_store(); return {"ok": True}

@app.post("/room/create")
def room_create(req: RoomCreateReq, authorization: str = Header(default="")):
    uid = require_user(authorization)
    code = "".join(random.choices("ABCDEFGHJKMNPQRSTUVWXYZ23456789", k=5))
    ROOMS[code] = {"members": [uid], "messages": [{"user": "ShopZen", "text": "Room " + code + " created! Tip: type @zen to ask AI.", "ts": time.time()}]}
    save_store(); return {"ok": True, "code": code}

@app.post("/room/join")
def room_join(req: RoomJoinReq, authorization: str = Header(default="")):
    uid = require_user(authorization); code = req.code.strip().upper(); r = ROOMS.get(code)
    if not r: return {"ok": False, "error": "Not found"}
    if uid not in r["members"]:
        r["members"].append(uid); r["messages"].append({"user": "ShopZen", "text": uid + " joined", "ts": time.time()}); save_store()
    return {"ok": True, "code": code}

@app.post("/room/send")
def room_send(req: RoomSendReq, authorization: str = Header(default="")):
    uid = require_user(authorization); rate_limit("room:" + uid, 30, 60)
    code = req.code.strip().upper(); r = ROOMS.get(code); msg = (req.text or "").strip()[:500]
    if not r or uid not in r["members"] or not msg: return {"ok": False, "error": "Invalid"}
    r["messages"].append({"user": uid, "text": msg, "ts": time.time()})
    if len(r["messages"]) > 200: del r["messages"][0:-200]
    if msg.lower().startswith("@zen"):
        ans = llm_text("Group asks: " + msg[4:].strip())
        if ans:
            r["messages"].append({"user": "ShopZen AI", "text": ans, "ts": time.time()})
            if len(r["messages"]) > 200: del r["messages"][0:-200]
    save_store(); return {"ok": True}

@app.get("/room/messages")
def room_messages(code: str = "", since: float = 0, authorization: str = Header(default="")):
    uid = require_user(authorization); r = ROOMS.get(code.strip().upper())
    if not r or uid not in r["members"]: return {"messages": [], "now": time.time()}
    return {"messages": [m for m in r["messages"] if m["ts"] > since], "now": time.time()}

@app.post("/chat")
async def chat(req: ChatReq, request: Request, authorization: str = Header(default="")):
    global CHAT_COUNT
    uid = require_user(authorization, req.user_id); rate_limit("chat:" + uid); LAST_ACTIVE[uid] = time.time()
    msg_text = (req.message or "").strip()[:1200]
    if not msg_text: return {"intent": "chat", "summary": "Tell me what you'd like to shop for! 😊"}
    CHAT_COUNT += 1
    if not client: return {"intent": "chat", "summary": "Groq API key missing."}

    current_cat = extract_category(msg_text)
    personalized = False; prefs = {}
    effective = None

    st = CLARIFY_STATE.get(uid)
    if st:
        cur = st["qs"][st["step"]]
        ans = msg_text
        skipped = "Skip" in ans
        if not skipped: st["answers"][cur["key"]] = ans
        st["step"] += 1
        if not skipped and st["step"] < len(st["qs"]):
            return {"intent": "clarify", "summary": FRIENDLY_NEXT.get(cur["key"], "Perfect! 😊") + " Now tell me:", "questions": [st["qs"][st["step"]]]}
        a = st["answers"]; cat = st["cat"]
        parts = ["best", cat]
        if a.get("brand") and "Any" not in a["brand"]: parts.append(a["brand"] + " brand")
        if a.get("color") and "Any" not in a["color"]: parts.append(a["color"] + " colour")
        if a.get("who"): parts.append("for " + a["who"].lower())
        if a.get("budget") and "No limit" not in a["budget"]: parts.append(a["budget"].lower())
        effective = " ".join(parts) + " model"
        prefs = a; CLARIFY_STATE.pop(uid, None); ASKED[uid] = True; personalized = True
        history = HISTORY.setdefault(uid, [])
    else:
        history = HISTORY.setdefault(uid, [])
        last_query = LAST_QUERY.get(uid, ""); last_cat = extract_category(last_query)
        if current_cat and last_cat and current_cat != last_cat:
            history = HISTORY[uid] = []; ASKED[uid] = False
        if current_cat and not ASKED.get(uid):
            qs = clarify_questions(current_cat)
            CLARIFY_STATE[uid] = {"cat": current_cat, "qs": qs, "step": 0, "answers": {}}
            return {"intent": "clarify", "summary": "Awesome! I'll find the PERFECT " + current_cat + " for you 😊 Let's start:", "questions": [qs[0]]}
        effective = last_query + ", " + msg_text if (last_query and is_fragment(msg_text)) else msg_text

    LAST_QUERY[uid] = effective
    ck = (uid, effective)
    if ck in CACHE: return CACHE[ck]

    user_content = effective
    if personalized:
        user_content += "\n(User answered in chat: " + json.dumps(prefs) + "). Respect brand/colour/who/budget STRICTLY. First product MUST be the single best exact match for THIS user."
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]; messages.extend(history[-10:]); messages.append({"role": "user", "content": user_content})
    try:
        raw, model = call_llm(messages)
        data = normalize_llm_data(json.loads(raw), current_cat or extract_category(effective))
        if personalized: data["personalized"] = True
        if data.get("intent") == "search" and data.get("products"):
            for p in data["products"]:
                p["image_url"] = get_image_url(p.get("image_prompt", p.get("name")), p.get("name"))
                p["price_data"] = build_price_data(p.get("price", 0), p.get("price_trend", "stable"), p.get("name"))
                p["store_prices"] = store_price_comparison(p.get("name"), p.get("price"))
            hlist = SEARCH_HISTORY.setdefault(uid, [])
            if effective not in hlist: hlist.insert(0, effective)
            if len(hlist) > 8: del hlist[8:]
        if data.get("intent") == "decide" and data.get("winner"):
            try:
                w = data["winner"]
                kp = kb_price(w.get("name"))
                w["price"] = kp if kp else (clamp_price(current_cat, max(1, int(to_num(w.get("price"), 0)))) if current_cat else max(1, int(to_num(w.get("price"), 0))))
                w["image_url"] = get_image_url(w.get("image_prompt", w.get("name")), w.get("name"))
                w["price_data"] = build_price_data(w.get("price", 0), w.get("price_trend", "stable"), w.get("name"))
                w["store_prices"] = store_price_comparison(w.get("name"), w.get("price"))
                data["winner"] = w
            except Exception: pass
        if data.get("intent") == "timing" and data.get("timing"):
            try:
                t = data["timing"]
                kp = kb_price(t.get("product"))
                if kp: t["price_now"] = kp
                trend = "falling" if t.get("verdict") == "WAIT" else "stable"
                t["price_data"] = build_price_data(t.get("price_now", 0), trend, t.get("product")); data["timing"] = t
            except Exception: pass
        history.append({"role": "user", "content": effective}); history.append({"role": "assistant", "content": condense(data)})
        if len(history) > 24: del history[:-24]
        conv = CONVERSATIONS.setdefault(uid, [])
        conv.append({"role": "user", "text": req.message}); conv.append({"role": "agent", "data": data})
        if len(conv) > 40: del conv[:-40]
        CACHE[ck] = data; CACHE.move_to_end(ck)
        while len(CACHE) > CACHE_MAX: CACHE.popitem(last=False)
        save_store(); return data
    except Exception:
        return {"intent": "chat", "summary": "Brain paused. Please try again. 🙏"}

HTML_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ShopZen AI — Your Intent. Our Intelligence.</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
:root{--bg:#f8f8fc;--glass:rgba(255,255,255,.85);--card:#fff;--card-2:#f1f1f8;--border:rgba(23,23,43,.08);--border-2:rgba(23,23,43,.16);--text:#17172b;--dim:#67677d;--a1:#6d5cf5;--a2:#9b4df7;--a3:#ec4899;--green:#059669;--red:#dc2626;--amber:#d97706;--grad:linear-gradient(135deg,var(--a1),var(--a2) 55%,var(--a3));--accent-soft:#5b4bd6;--skel1:#ececf4;--skel2:#f8f8fd;--modal-bg:#fff;--shadow:0 10px 30px rgba(23,23,43,.08);--shadow-lg:0 24px 70px rgba(23,23,43,.14)}
:root[data-theme=dark]{--bg:#08080a;--glass:rgba(16,16,20,.72);--card:#14141a;--card-2:#1a1a22;--border:rgba(255,255,255,.08);--border-2:rgba(255,255,255,.14);--text:#f5f5f7;--dim:#8f8f9a;--accent-soft:#c7c3ff;--green:#34d399;--red:#f87171;--amber:#fbbf24;--skel1:#15151b;--skel2:#1e1e26;--modal-bg:#121218;--shadow:0 12px 34px rgba(0,0,0,.45);--shadow-lg:0 30px 90px rgba(0,0,0,.6)}
:root[data-theme=lavender]{--bg:#f4f1fc;--glass:rgba(255,255,255,.88);--card:#fff;--card-2:#efeafb;--border:rgba(88,64,180,.1);--border-2:rgba(88,64,180,.2);--text:#2b2150;--dim:#6f6699;--a1:#8b5cf6;--a2:#a78bfa;--a3:#f472b6;--accent-soft:#7c3aed;--green:#059669;--red:#dc2626;--amber:#d97706;--skel1:#ece6fa;--skel2:#f8f5ff;--modal-bg:#fff;--shadow:0 10px 30px rgba(124,58,237,.1);--shadow-lg:0 24px 70px rgba(124,58,237,.16)}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:Inter,system-ui,sans-serif;height:100vh;overflow:hidden}
.hidden{display:none!important}
.shell{display:flex;height:100vh}
.sidebar{width:270px;background:var(--glass);backdrop-filter:blur(20px);border-right:1px solid var(--border);display:flex;flex-direction:column;padding:18px 14px;gap:12px}
.logo{font-weight:800;font-size:16px;background:var(--grad);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.new-chat-btn{width:100%;background:var(--grad);color:#fff;border:none;border-radius:14px;padding:12px;font-weight:700;cursor:pointer}
.side-item{background:transparent;border:none;color:var(--dim);text-align:left;border-radius:10px;padding:9px 10px;font-size:12px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;width:100%}
.side-item:hover{background:var(--border);color:var(--text)}
.side-empty{font-size:11px;color:var(--dim);padding:6px;opacity:.7}
.side-bottom{border-top:1px solid var(--border);padding-top:12px;display:flex;flex-direction:column;gap:8px}
.about-btn{width:100%;background:rgba(124,108,246,.05);border:1px solid var(--border);color:var(--text);border-radius:12px;padding:10px;font-size:12px;font-weight:600;cursor:pointer}
.about-btn:hover{border-color:var(--a1)}
.user-row{display:flex;align-items:center;gap:10px;padding:4px 6px}
.user-avatar{width:36px;height:36px;border-radius:12px;background:var(--grad);display:flex;align-items:center;justify-content:center;font-weight:800;color:#fff;font-size:14px}
.user-meta{flex:1;min-width:0}
.user-name{font-size:13px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.user-plan{font-size:10px;color:var(--dim)}
.main{flex:1;display:flex;flex-direction:column;min-width:0}
.topbar{height:58px;padding:0 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px;background:var(--glass);backdrop-filter:blur(20px)}
.top-title{font-weight:800;font-size:15px;flex:1}
.head-right{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.badge{font-size:11px;padding:6px 12px;border-radius:99px;background:rgba(124,108,246,.1);color:var(--accent-soft);font-weight:600;border:1px solid var(--border-2)}
.badge.live{background:rgba(52,211,153,.08);color:var(--green);border-color:rgba(52,211,153,.22)}
.icon-btn{background:rgba(255,255,255,.04);border:1px solid var(--border);color:var(--text);border-radius:11px;padding:7px 11px;font-size:12px;font-weight:600;cursor:pointer}
.icon-btn:hover{border-color:var(--a1)}
.theme-switch{display:flex;background:var(--glass);border:1px solid var(--border);border-radius:99px;padding:3px;gap:2px}
.theme-switch button{border:none;background:transparent;color:var(--dim);border-radius:99px;padding:4px 10px;font-size:12px;cursor:pointer}
.theme-switch button.active{background:var(--card);color:var(--text);box-shadow:var(--shadow)}
#hero{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;padding:28px;overflow-y:auto}
.hero-title{font-size:clamp(26px,4vw,40px);font-weight:900;text-align:center;line-height:1.15}
.grad{background:var(--grad);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero-cap{letter-spacing:4px;font-size:10px;text-transform:uppercase;font-weight:700}
.hero-sub{color:var(--dim);font-size:14px;text-align:center;max-width:540px;line-height:1.6}
.sugg-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;max-width:860px;width:100%;margin-top:18px}
.sugg{background:var(--card);border:1px solid var(--border);border-radius:18px;padding:14px;text-align:left;cursor:pointer;display:flex;gap:12px;align-items:flex-start;transition:all .2s;box-shadow:var(--shadow)}
.sugg:hover{border-color:var(--a1);transform:translateY(-3px)}
.sugg-ic{width:40px;height:40px;border-radius:13px;background:linear-gradient(135deg,rgba(124,108,246,.22),rgba(236,72,153,.14));border:1px solid rgba(124,108,246,.3);display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0}
.sugg-tx b{font-size:13.5px;display:block}
.sugg-tx small{color:var(--dim);font-size:11px}
#chat-area{flex:1;overflow-y:auto;padding:24px;display:flex;flex-direction:column;gap:20px}
.msg{display:flex;gap:12px;max-width:85%;animation:fadeIn .3s}
.msg.user{align-self:flex-end;flex-direction:row-reverse}
.avatar{width:34px;height:34px;border-radius:11px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px;flex-shrink:0}
.avatar.user{background:var(--grad);color:#fff}
.avatar.ai{background:var(--card);border:1px solid var(--border)}
.bubble{padding:14px 18px;border-radius:18px;font-size:14px;line-height:1.65}
.msg.user .bubble{background:var(--grad);color:#fff;border-bottom-right-radius:6px}
.msg.agent .bubble{background:var(--glass);backdrop-filter:blur(14px);border:1px solid var(--border);border-bottom-left-radius:6px;width:100%}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.chip{background:var(--card);border:1px solid var(--border);color:var(--text);border-radius:99px;padding:6px 13px;font-size:11px;font-weight:600;cursor:pointer}
.chip:hover{border-color:var(--a1)}
.cq{font-size:12px;font-weight:700;margin:12px 0 4px;color:var(--accent-soft)}
.disclaimer{font-size:10.5px;color:var(--dim);margin-top:10px}
.products-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px;margin-top:14px}
.product-card{background:var(--card);border:1px solid var(--border);border-radius:16px;overflow:hidden;transition:all .2s;box-shadow:var(--shadow)}
.product-card:hover{transform:translateY(-3px);border-color:var(--a1)}
.img-wrap{width:100%;height:140px;background:var(--skel1);overflow:hidden;cursor:pointer}
.img-wrap img{width:100%;height:100%;object-fit:cover}
.product-info{padding:12px;display:flex;flex-direction:column;gap:4px}
.brand{font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:1px;font-weight:700}
.name{font-weight:700;font-size:14px;line-height:1.35;cursor:pointer}
.name:hover{color:var(--accent-soft)}
.price{font-size:16px;font-weight:800;color:var(--a1)}
.bestline{font-size:10px;color:var(--green);font-weight:800}
.reason{font-size:11px;color:var(--dim);font-style:italic;margin-top:4px;line-height:1.4}
.winner-card{margin-top:14px;border:1px solid var(--amber);background:linear-gradient(135deg,rgba(251,191,36,.1),rgba(52,211,153,.05));border-radius:18px;padding:14px}
.winner-title{font-size:12px;font-weight:800;color:var(--amber);letter-spacing:1.5px;margin-bottom:10px}
.timing-card{margin-top:14px;border:1px solid var(--a1);background:linear-gradient(135deg,rgba(124,108,246,.08),rgba(236,72,153,.05));border-radius:18px;padding:14px}
.timing-title{font-size:12px;font-weight:800;color:var(--accent-soft);letter-spacing:1.5px;margin-bottom:8px}
table{width:100%;border-collapse:collapse;margin-top:14px;font-size:13px;background:var(--card);border-radius:12px;overflow:hidden;border:1px solid var(--border)}
th,td{padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)}
th{background:var(--card-2);font-weight:700;color:var(--dim)}
.panel{margin-top:14px;padding:14px;background:rgba(124,108,246,.05);border:1px solid rgba(124,108,246,.2);border-radius:14px}
.panel h4{font-size:12px;color:var(--accent-soft);margin-bottom:8px;text-transform:uppercase;letter-spacing:1px}
.input-area{padding:16px 20px;border-top:1px solid var(--border);background:var(--glass);backdrop-filter:blur(20px);display:flex;gap:10px}
.input-wrap{max-width:860px;margin:0 auto;display:flex;gap:10px;flex:1}
#input{flex:1;background:var(--card);border:1px solid var(--border);border-radius:14px;padding:14px 18px;color:var(--text);font-size:14px;outline:none}
#input:focus{border-color:var(--a1)}
button.send{background:var(--grad);color:#fff;border:none;border-radius:14px;padding:0 24px;font-weight:700;cursor:pointer}
button.send:disabled{opacity:.5;cursor:not-allowed}
.fine{max-width:860px;margin:8px auto 0;text-align:center;font-size:10px;color:var(--dim)}
.typing{display:flex;gap:4px;padding:8px 0}
.typing span{width:6px;height:6px;background:var(--dim);border-radius:50%;animation:bounce 1.4s infinite ease-in-out both}
.typing span:nth-child(1){animation-delay:-.32s}.typing span:nth-child(2){animation-delay:-.16s}
@keyframes bounce{0%,80%,100%{transform:scale(0)}40%{transform:scale(1)}}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.overlay{position:fixed;inset:0;background:rgba(10,10,20,.5);backdrop-filter:blur(8px);display:flex;align-items:center;justify-content:center;z-index:100;padding:20px}
:root[data-theme=dark] .overlay{background:rgba(4,4,8,.72)}
.modal{background:var(--modal-bg);border:1px solid var(--border-2);border-radius:22px;max-width:760px;width:100%;max-height:88vh;overflow-y:auto;padding:26px;position:relative;box-shadow:var(--shadow-lg)}
.modal.small{max-width:480px}
.modal-close{position:absolute;top:14px;right:14px;background:var(--card-2);border:1px solid var(--border);color:var(--dim);width:32px;height:32px;border-radius:10px;cursor:pointer;font-size:14px}
.modal-head{display:flex;gap:18px;align-items:flex-start}
.modal-img{width:150px;height:120px;object-fit:cover;border-radius:14px;background:var(--skel1)}
.modal-price{font-size:24px;font-weight:800;margin:4px 0}
.modal-reason{color:var(--dim);font-size:13px;font-style:italic;margin:12px 0}
.shop-links{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
.shop-btn{background:var(--card-2);border:1px solid var(--border);color:var(--text);border-radius:11px;padding:10px 16px;font-size:12px;font-weight:700;text-decoration:none;cursor:pointer}
.shop-btn:hover{border-color:var(--green);color:var(--green)}
.buy-btn{background:var(--grad);border:none;color:#fff;border-radius:11px;padding:11px 18px;font-size:12px;font-weight:800;text-decoration:none;cursor:pointer;display:inline-block}
.chart-box{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:16px;margin:14px 0}
.chart-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.chart-head h3{font-size:13px;font-weight:700}
.verdict{font-size:11px;font-weight:800;padding:4px 12px;border-radius:99px}
.verdict-WAIT{background:rgba(251,191,36,.15);color:var(--amber)}
.verdict-BUYNOW{background:rgba(52,211,153,.15);color:var(--green)}
.chart{width:100%;height:auto}
.line-hist{fill:none;stroke:var(--a1);stroke-width:2.5;stroke-linecap:round}
.line-fc{fill:none;stroke:var(--amber);stroke-width:2;stroke-dasharray:6 5}
.dot-now{fill:var(--card);stroke:var(--a1);stroke-width:3}
.tick{fill:var(--dim);font-size:10px}
.advice{font-size:12.5px;margin-top:10px;line-height:1.5}
.range{font-size:11px;color:var(--dim);margin-top:6px}
.specs{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.spec{font-size:11px;background:var(--card-2);padding:5px 10px;border-radius:9px;border:1px solid var(--border)}
.pros-cons{font-size:12px;display:flex;flex-direction:column;gap:4px}
.pros{color:var(--green)}
.cons{color:var(--red)}
.toast{position:fixed;bottom:96px;left:50%;transform:translateX(-50%) translateY(10px);background:var(--modal-bg);border:1px solid var(--border-2);color:var(--text);padding:11px 22px;border-radius:99px;font-size:13px;font-weight:600;opacity:0;transition:all .3s;z-index:200;pointer-events:none;box-shadow:var(--shadow-lg)}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
.auth-logo-wrap{display:flex;flex-direction:column;align-items:center;gap:6px;margin-bottom:10px}
.auth-name{font-weight:900;font-size:22px;letter-spacing:-.5px}
.auth-tabs{display:flex;gap:8px;margin:16px 0}
.auth-tabs button{flex:1;background:var(--card-2);border:1px solid var(--border);color:var(--dim);border-radius:12px;padding:10px;font-weight:700;font-size:12px;cursor:pointer}
.auth-tabs button.active{border-color:var(--a1);color:var(--accent-soft)}
.auth-input{width:100%;background:var(--card-2);border:1px solid var(--border);border-radius:13px;padding:13px 15px;color:var(--text);font-size:14px;outline:none;margin-bottom:10px}
.auth-input:focus{border-color:var(--a1)}
.auth-err{color:var(--red);font-size:12px;margin-bottom:8px;min-height:16px}
.auth-btn{width:100%;margin-bottom:10px;padding:13px}
.guest-btn{width:100%;background:transparent;border:1px dashed var(--border-2);color:var(--dim);border-radius:13px;padding:12px;font-size:13px;font-weight:600;cursor:pointer}
.guest-btn:hover{color:var(--text);border-color:var(--dim)}
.fab{position:fixed;right:20px;bottom:96px;z-index:65;width:56px;height:56px;border-radius:18px;background:var(--grad);border:none;color:#fff;font-size:22px;cursor:pointer;box-shadow:0 12px 34px rgba(124,108,246,.5)}
.fab:hover{transform:translateY(-2px)}
.gdrawer{position:fixed;top:0;right:0;bottom:0;width:360px;max-width:94vw;background:var(--modal-bg);border-left:1px solid var(--border-2);z-index:70;display:flex;flex-direction:column;transform:translateX(105%);transition:transform .25s}
.gdrawer.open{transform:none}
.g-head{padding:14px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px}
.g-code{font-weight:800;letter-spacing:2px;color:var(--accent-soft)}
.g-msgs{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}
.g-msg{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:9px 12px;font-size:12.5px;line-height:1.55}
.g-msg.g-ai{border-color:var(--a1);background:rgba(124,108,246,.08)}
.g-user{font-weight:700;color:var(--accent-soft);font-size:11px;margin-bottom:2px}
.g-input{display:flex;gap:8px;padding:12px;border-top:1px solid var(--border)}
.g-input input{flex:1;background:var(--card-2);border:1px solid var(--border);border-radius:12px;padding:11px 13px;color:var(--text);outline:none}
.wish-row{display:flex;align-items:center;gap:8px;background:var(--card);border:1px solid var(--border);border-radius:12px;padding:10px;margin-bottom:8px}
.wish-row img{width:44px;height:44px;border-radius:10px;object-fit:cover}
.wish-info{flex:1;min-width:0}
.wish-info b{font-size:12.5px;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wish-info span{font-size:11px;color:var(--dim)}
.about-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media(max-width:640px){.about-grid{grid-template-columns:1fr}}
.about-card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:13px;font-size:12px}
.about-card b{font-size:13px;display:block;margin-bottom:4px}
.about-card span{color:var(--dim);line-height:1.5}
.menu-btn{display:none;background:transparent;border:1px solid var(--border);color:var(--text);border-radius:10px;padding:6px 10px;font-size:16px;cursor:pointer}
.side-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:55;display:none}
.side-backdrop.open{display:block}
@media(max-width:860px){.menu-btn{display:inline-flex}.sidebar{position:fixed;left:0;top:0;bottom:0;transform:translateX(-100%);transition:transform .25s;z-index:60;box-shadow:var(--shadow-lg)}.sidebar.open{transform:none}}
::-webkit-scrollbar{width:8px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:var(--border-2);border-radius:4px}
</style></head><body>

<svg width="0" height="0" style="position:absolute"><defs><linearGradient id="lz" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#6d5cf5"/><stop offset=".5" stop-color="#9b4df7"/><stop offset="1" stop-color="#ec4899"/></linearGradient></defs>
<symbol id="logo" viewBox="0 0 64 64"><rect x="2" y="2" width="60" height="60" rx="18" fill="url(#lz)"/><path d="M22.5 27h19l2.6 17.2a3.2 3.2 0 0 1-3.2 3.8H23.1a3.2 3.2 0 0 1-3.2-3.8L22.5 27z" fill="none" stroke="#fff" stroke-width="3" stroke-linejoin="round"/><path d="M26 27v-2.5a6 6 0 0 1 12 0V27" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round"/><circle cx="45.5" cy="18.5" r="3" fill="#fff" opacity=".95"/></symbol></svg>

<div id="auth-overlay" class="overlay"><div class="modal small">
<div class="auth-logo-wrap"><svg width="58" height="58"><use href="#logo"/></svg><div class="auth-name">ShopZen AI</div><div class="hero-cap grad">Your Intent. Our Intelligence.</div></div>
<div class="auth-tabs"><button id="tab-login" class="active" onclick="setAuthMode('login')">Login</button><button id="tab-signup" onclick="setAuthMode('signup')">Sign Up</button></div>
<input id="auth-name" class="auth-input" placeholder="Your name"><input id="auth-pass" class="auth-input" type="password" placeholder="Password">
<div id="auth-err" class="auth-err"></div>
<button class="new-chat-btn auth-btn" onclick="doAuth()">Continue →</button>
<button class="guest-btn" onclick="doGuest()">👋 Continue as Guest</button>
</div></div>

<div class="shell">
<aside class="sidebar">
<div class="logo">ShopZen AI</div>
<button class="new-chat-btn" onclick="newChat()">＋ New Chat</button>
<div style="font-size:10px;color:var(--dim);font-weight:700;letter-spacing:1.5px;padding:6px 6px 0">RECENT SEARCHES</div>
<div id="side-history" style="flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:4px"></div>
<div class="side-bottom">
<button class="about-btn" onclick="openWish()">🔖 Wishlist</button>
<button class="about-btn" onclick="exportChat()">📥 Export chat</button>
<button class="about-btn" onclick="openAbout()">ℹ️ About ShopZen</button>
<div class="user-row">
<div class="user-avatar" id="user-avatar">U</div>
<div class="user-meta"><div class="user-name" id="user-name-side">User</div><div class="user-plan" id="user-plan">Free plan</div></div>
<button class="icon-btn" onclick="logout()" title="Logout">⎋</button>
</div></div></aside>
<div class="side-backdrop" id="side-backdrop" onclick="toggleSidebar()"></div>
<main class="main">
<header class="topbar">
<button class="menu-btn" onclick="toggleSidebar()">☰</button>
<div class="top-title">ShopZen AI</div>
<div class="head-right">
<div class="badge live" id="live-badge">🟢 –</div>
<div class="badge" id="stats-badge">👍 100%</div>
<div class="theme-switch" id="theme-switch">
<button data-t="light" onclick="setTheme('light')" title="Light">☀️</button>
<button data-t="dark" onclick="setTheme('dark')" title="Dark">🌙</button>
<button data-t="lavender" onclick="setTheme('lavender')" title="Lavender">🪻</button>
</div>
<button class="icon-btn" id="tts-btn" onclick="toggleTTS()" title="AI voice">🔇</button>
<button class="icon-btn" onclick="openShare(null)" title="Share">🔗</button>
<button class="icon-btn" onclick="openAbout()" title="About">ℹ️</button>
</div></header>

<div id="hero">
<div style="display:flex;align-items:center;gap:8px;font-size:11px;font-weight:700;color:var(--dim);border:1px solid var(--border);border-radius:99px;padding:7px 14px;background:var(--card)"><span style="width:7px;height:7px;border-radius:50%;background:var(--grad)"></span> SHOPZEN AI • TRUSTED REAL PRICES</div>
<h1 class="hero-title">Hello, <span class="grad" id="hero-name">friend</span> —<br>what are we shopping today? 😊</h1>
<div class="hero-cap grad">Your Intent. Our Intelligence.</div>
<p class="hero-sub">I ask your budget, brand, colour & who it's for — then show the REAL market price and one exact buy link you can trust.</p>
<div class="sugg-grid">
<button class="sugg" onclick="sendMessage('redmi note 13 under 20000')"><span class="sugg-ic">📱</span><span class="sugg-tx"><b>Redmi Note 13 ₹20k</b><small>Real price ₹13,999 + live check</small></span></button>
<button class="sugg" onclick="sendMessage('i want earbuds')"><span class="sugg-ic">🎧</span><span class="sugg-tx"><b>I want earbuds</b><small>Friendly Q&A → exact match</small></span></button>
<button class="sugg" onclick="sendMessage('macbook air m1')"><span class="sugg-ic">💻</span><span class="sugg-tx"><b>MacBook Air M1</b><small>Accurate ₹67,990 baseline</small></span></button>
<button class="sugg" onclick="sendMessage('when is the best time to buy redmi note 13?')"><span class="sugg-ic">⏳</span><span class="sugg-tx"><b>Best time to buy?</b><small>Sale-window foresight</small></span></button>
</div></div>

<div id="chat-area" class="hidden"></div>

<div class="input-area"><div class="input-wrap">
<input id="input" placeholder="Tell me what you want… I'll ask the right questions 😊" onkeydown="if(event.key==='Enter')send()">
<button class="icon-btn" onclick="startVoice()">🎤</button>
<button class="send" id="send-btn" onclick="send()">Send</button>
</div></div>
<div class="fine">Prices verified against real Indian market data + live store fetch. • Your Intent. Our Intelligence.</div>
</main></div>

<button class="fab" onclick="openGroup()" title="Group Chat">👥</button>

<div id="gdrawer" class="gdrawer">
<div class="g-head"><b style="flex:1">👥 Group Chat</b><span class="g-code" id="g-code"></span><button class="icon-btn" onclick="copyRoom()">📋</button><button class="icon-btn" onclick="closeGroup()">✕</button></div>
<div id="g-setup" style="padding:14px;display:flex;flex-direction:column;gap:10px">
<button class="new-chat-btn" onclick="createRoom()">＋ Create a room</button>
<div style="text-align:center;color:var(--dim);font-size:11px">— or join with a code —</div>
<input id="g-join-code" class="auth-input" style="margin:0" placeholder="ROOM CODE">
<button class="icon-btn" style="padding:11px" onclick="joinRoom()">Join room</button>
</div>
<div id="g-chat" class="hidden" style="display:flex;flex-direction:column;flex:1;min-height:0">
<div id="g-msgs" class="g-msgs"></div>
<div style="padding:0 12px 8px"><button class="chip" onclick="document.getElementById('g-text').value='@zen which is the best pick for us under 20k?'">@zen ask the AI for us…</button></div>
<div class="g-input"><input id="g-text" placeholder="Message… (use @zen to ask AI)" onkeydown="if(event.key==='Enter')sendGroup()"><button class="send" style="padding:0 16px" onclick="sendGroup()">➤</button></div>
</div></div>

<div id="overlay" class="overlay hidden" onclick="closeModal()"><div class="modal" onclick="event.stopPropagation()">
<button class="modal-close" onclick="closeModal()">✕</button>
<div class="modal-head"><img id="m-img" class="modal-img"><div>
<div id="m-brand" class="brand"></div><h2 id="m-name" style="font-size:18px"></h2>
<div id="m-price" class="modal-price"></div><div id="m-rating" style="color:var(--amber);font-size:12px"></div>
</div></div>
<p id="m-reason" class="modal-reason"></p>
<div id="m-links" class="shop-links"></div>
<div id="m-stores"></div>
<div class="chart-box">
<div class="chart-head"><h3>📈 Price History & AI Prediction</h3><span id="m-verdict" class="verdict"></span></div>
<div id="m-chart"></div>
<p id="m-advice" class="advice"></p>
<p id="m-range" class="range"></p>
</div>
<div id="m-specs" class="specs"></div>
<div id="m-proscons" class="pros-cons"></div>
</div></div>

<div id="wish-overlay" class="overlay hidden" onclick="closeWish()"><div class="modal small" onclick="event.stopPropagation()">
<button class="modal-close" onclick="closeWish()">✕</button>
<div style="font-size:16px;font-weight:800;margin-bottom:12px">🔖 Your Wishlist</div>
<div id="w-list"></div>
</div></div>

<div id="share-overlay" class="overlay hidden" onclick="closeShare()"><div class="modal small" onclick="event.stopPropagation()">
<button class="modal-close" onclick="closeShare()">✕</button>
<div style="font-size:16px;font-weight:800;margin-bottom:4px">Share ShopZen AI</div>
<div class="hero-cap grad" style="margin-bottom:12px">Your Intent. Our Intelligence.</div>
<div id="share-links" class="shop-links"></div>
</div></div>

<div id="about-overlay" class="overlay hidden" onclick="closeAbout()"><div class="modal" onclick="event.stopPropagation()">
<button class="modal-close" onclick="closeAbout()">✕</button>
<div style="display:flex;align-items:center;gap:10px;font-weight:900;font-size:18px"><svg width="28" height="28"><use href="#logo"/></svg> ShopZen AI</div>
<div class="hero-cap grad" style="margin:6px 0 10px">Your Intent. Our Intelligence.</div>
<p style="color:var(--dim);font-size:13px;margin-bottom:16px;line-height:1.6">A friendly AI shopkeeper with a Real-Price Knowledge Engine: accurate Indian street prices, live store verification, and one exact buy link.</p>
<div class="about-grid">
<div class="about-card"><b>💯 Trusted Prices</b><span>100+ popular products priced at true market rates; live fetch confirms.</span></div>
<div class="about-card"><b>🗣️ Conversational Discovery</b><span>Budget → brand → colour/who → exact match.</span></div>
<div class="about-card"><b>🎯 One Exact Buy Button</b><span>Only the store you tap opens, on the exact product page.</span></div>
<div class="about-card"><b>🛍️ 7-Store Comparison</b><span>LIVE rows + tight ±5% estimates.</span></div>
<div class="about-card"><b>🏆 Final Decisions</b><span>One decisive winner with trophy card.</span></div>
<div class="about-card"><b>⏳ Best-Time-To-Buy</b><span>Price graph + BUY/WAIT verdict.</span></div>
<div class="about-card"><b>🔐 Persistent Login</b><span>Signed 7-day tokens — never re-login.</span></div>
<div class="about-card"><b>👥 Group Chat + 🌓 Themes</b><span>Rooms, @zen, TTS, wishlist, 3 themes.</span></div>
</div>
<div style="margin-top:14px;font-size:11px;color:var(--dim);background:rgba(217,119,6,.06);border:1px solid rgba(217,119,6,.2);border-radius:12px;padding:11px;line-height:1.6">⚠️ LIVE = fetched from the store right now; AI CHECK = verified estimate. Powered by Groq Llama.</div>
</div></div>

<div id="toast" class="toast"></div>

<script>
function setTheme(t){document.documentElement.setAttribute('data-theme',t);localStorage.setItem('theme',t);document.querySelectorAll('#theme-switch button').forEach(function(b){b.classList.toggle('active',b.dataset.t===t)})}
setTheme(localStorage.getItem('theme')||'light');

var TTS=localStorage.getItem('tts')==='1';
function toggleTTS(){TTS=!TTS;localStorage.setItem('tts',TTS?'1':'0');document.getElementById('tts-btn').textContent=TTS?'🔊':'';if(!TTS&&'speechSynthesis' in window)speechSynthesis.cancel();toast(TTS?'AI voice ON':'AI voice OFF')}
document.getElementById('tts-btn').textContent=TTS?'🔊':'';
function speak(text){if(!TTS||!('speechSynthesis' in window)||!text)return;speechSynthesis.cancel();var u=new SpeechSynthesisUtterance(text);u.lang='en-IN';u.rate=1.05;speechSynthesis.speak(u)}

document.addEventListener('keydown',function(e){if(e.key==='/'&&document.activeElement!==document.getElementById('input')&&!e.ctrlKey&&!e.metaKey){e.preventDefault();document.getElementById('input').focus()}});
document.addEventListener('click',function(e){var t=e.target;var chip=t.closest?t.closest('.chip'):null;if(chip&&chip.dataset.o){sendMessage(chip.dataset.o)}});

var chatArea=document.getElementById('chat-area'),input=document.getElementById('input'),sendBtn=document.getElementById('send-btn');
var PSTORE=[],RSTORE=[],CHAT_LOG=[],LIVEQ=[];
var UID=localStorage.getItem('uid')||'',TOKEN=localStorage.getItem('token')||'',UNAME=localStorage.getItem('uname')||'';
var AUTH_MODE='login',ROOM={code:'',joined:false,lastTs:0,timer:null},MODAL_IDX=-1;

function inr(v){var n=Number(v);return new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:0}).format(isFinite(n)?n:0)}
function numSafe(v){var n=Number(v);return isFinite(n)?n:0}
function arr(x){return Array.isArray(x)?x:[]}
function esc(v){return String(v==null?'':v).replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function stars(r){var n=Math.max(0,Math.min(5,Math.round(numSafe(r))));return '★'.repeat(n)+'☆'.repeat(5-n)}
function toast(msg){var t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');setTimeout(function(){t.classList.remove('show')},2200)}
function directUrl(domain,name){return 'https://duckduckgo.com/?q='+encodeURIComponent('!ducky site:'+domain+' "'+name+'"')}

function apiFetch(url,options){
  options=options||{};options.headers=options.headers||{};
  if(TOKEN)options.headers['Authorization']='Bearer '+TOKEN;
  return fetch(url,options).then(function(res){
    if(res.status===401){localStorage.removeItem('uid');localStorage.removeItem('uname');localStorage.removeItem('token');TOKEN='';UID='';location.reload()}
    return res;
  });
}

function setAuthMode(m){AUTH_MODE=m;document.getElementById('tab-login').classList.toggle('active',m==='login');document.getElementById('tab-signup').classList.toggle('active',m==='signup')}
function doAuth(){
  var name=document.getElementById('auth-name').value.trim();
  var pass=document.getElementById('auth-pass').value;
  fetch(AUTH_MODE==='login'?'/login':'/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,password:pass})})
  .then(function(r){return r.json()}).then(function(d){
    if(!d.ok){document.getElementById('auth-err').textContent=d.error||'Failed';return}
    localStorage.setItem('uid',d.uid);localStorage.setItem('uname',d.user);localStorage.setItem('token',d.token||'');
    UID=d.uid;UNAME=d.user;TOKEN=d.token||'';enterApp();
  }).catch(function(){document.getElementById('auth-err').textContent='Server error'});
}
function doGuest(){
  fetch('/guest',{method:'POST'}).then(function(r){return r.json()}).then(function(d){
    localStorage.setItem('uid',d.uid);localStorage.setItem('uname',d.user);localStorage.setItem('token',d.token||'');
    UID=d.uid;UNAME=d.user;TOKEN=d.token||'';enterApp();
  });
}
function logout(){localStorage.removeItem('uid');localStorage.removeItem('uname');localStorage.removeItem('token');location.reload()}
function enterApp(){
  document.getElementById('auth-overlay').classList.add('hidden');
  document.getElementById('hero-name').textContent=UNAME.split(' ')[0];
  document.getElementById('user-name-side').textContent=UNAME;
  document.getElementById('user-avatar').textContent=(UNAME[0]||'U').toUpperCase();
  document.getElementById('user-plan').textContent=UID.indexOf('guest')===0?'Guest mode':'Free plan';
  loadConversation();refreshSidebar();refreshAnalytics();
}
function toggleSidebar(){
  var sb=document.querySelector('.sidebar'), bd=document.getElementById('side-backdrop');
  var isOpen=sb.classList.contains('open');
  sb.classList.toggle('open',!isOpen);bd.classList.toggle('open',!isOpen);
}
function showHero(){document.getElementById('hero').classList.remove('hidden');chatArea.classList.add('hidden');chatArea.innerHTML='';PSTORE=[];RSTORE=[]}
function startChatView(){document.getElementById('hero').classList.add('hidden');chatArea.classList.remove('hidden')}
function loadConversation(){
  apiFetch('/conversation?user_id='+encodeURIComponent(UID)).then(function(r){return r.json()}).then(function(c){
    if(c&&c.length){startChatView();c.forEach(function(m){addMsg(m.role,m.text||m.data,false)})}else{showHero()}
  }).catch(function(){showHero()});
}
function newChat(){apiFetch('/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:UID})}).then(function(){CHAT_LOG=[];showHero();refreshSidebar();toast('New chat started');if(window.innerWidth<860)toggleSidebar()})}
function refreshSidebar(){
  apiFetch('/history?user_id='+encodeURIComponent(UID)).then(function(r){return r.json()}).then(function(h){
    var el=document.getElementById('side-history');
    if(h&&h.length){
      el.innerHTML=h.map(function(x,i){return '<button class="side-item" data-i="'+i+'">'+esc('🕘 '+x)+'</button>'}).join('');
      el.querySelectorAll('.side-item').forEach(function(btn,idx){btn.addEventListener('click',function(){sendMessage(h[idx])})});
    }else{el.innerHTML='<div class="side-empty">No searches yet — ask anything!</div>'}
  });
}
function refreshAnalytics(){
  fetch('/analytics').then(function(r){return r.json()}).then(function(a){
    document.getElementById('live-badge').textContent='🟢 '+a.online+' online • '+a.chats+' chats';
    updateStats(a.stats);
  });
}
setInterval(refreshAnalytics,10000);
function updateStats(s){if(!s)return;document.getElementById('stats-badge').textContent='👍 '+s.score+'% helpful • '+s.total+' rating'+(s.total===1?'':'s')}
fetch('/stats').then(function(r){return r.json()}).then(updateStats);

function openAbout(){document.getElementById('about-overlay').classList.remove('hidden')}
function closeAbout(){document.getElementById('about-overlay').classList.add('hidden')}
function openGroup(){document.getElementById('gdrawer').classList.add('open')}
function closeGroup(){document.getElementById('gdrawer').classList.remove('open')}
function createRoom(){apiFetch('/room/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user:UID})}).then(function(r){return r.json()}).then(function(d){if(d.ok)joinRoomUI(d.code)})}
function joinRoom(){var code=document.getElementById('g-join-code').value.trim().toUpperCase();if(!code)return;apiFetch('/room/join',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:code,user:UID})}).then(function(r){return r.json()}).then(function(d){if(d.ok)joinRoomUI(code);else toast(d.error||'Room not found')})}
function joinRoomUI(code){ROOM.code=code;ROOM.joined=true;ROOM.lastTs=0;document.getElementById('g-code').textContent=code;document.getElementById('g-setup').classList.add('hidden');document.getElementById('g-chat').classList.remove('hidden');document.getElementById('g-msgs').innerHTML='';if(!ROOM.timer)ROOM.timer=setInterval(pollGroup,1800);pollGroup();toast('Joined room '+code)}
function pollGroup(){if(!ROOM.joined)return;apiFetch('/room/messages?code='+ROOM.code+'&since='+ROOM.lastTs).then(function(r){return r.json()}).then(function(d){d.messages.forEach(function(m){if(m.ts>ROOM.lastTs)ROOM.lastTs=m.ts;var el=document.getElementById('g-msgs');var div=document.createElement('div');div.className='g-msg'+(String(m.user).indexOf('ShopZen')===0?' g-ai':'');div.innerHTML='<div class="g-user">'+esc(m.user)+'</div>'+esc(m.text);el.appendChild(div);el.scrollTop=el.scrollHeight})})}
function sendGroup(){var t=document.getElementById('g-text').value.trim();if(!t||!ROOM.joined)return;apiFetch('/room/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:ROOM.code,user:UID,text:t})});document.getElementById('g-text').value=''}
function copyRoom(){if(!ROOM.code)return toast('Create or join a room first');navigator.clipboard.writeText('Join my ShopZen AI group chat! Room code: '+ROOM.code).then(function(){toast('Invite copied!')})}
function shareToGroup(){var p=window._modalProduct;if(!p)return;if(!ROOM.joined){toast('Open 👥 Group Chat & join a room first');openGroup();return}apiFetch('/room/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:ROOM.code,user:UID,text:'🛍️ '+p.name+' ≈ '+inr(p.price)+' (★'+p.rating+') — '+(p.ai_reason||'')})}).then(function(){toast('Shared to group 👥')})}

function fetchLive(idx){
  var p=PSTORE[idx];if(!p)return;
  apiFetch('/liveprices?name='+encodeURIComponent(p.name)).then(function(r){return r.json()}).then(function(d){
    var live=arr(d.results);if(!live.length)return;
    p.live_prices=live;
    var withPrice=live.filter(function(s){return s.price!=null}).sort(function(a,b){return a.price-b.price});
    if(withPrice.length){
      p.price=withPrice[0].price;
      var pe=document.getElementById('price-'+idx);
      if(pe)pe.innerHTML='≈ '+inr(withPrice[0].price)+' <span style="color:var(--green);font-size:9px;font-weight:800">LIVE</span>';
      var b=document.getElementById('best-'+idx);
      if(b)b.innerHTML='⚡ LIVE: '+inr(withPrice[0].price)+' on '+esc(withPrice[0].store);
      var bb=document.getElementById('buy-'+idx);
      if(bb){bb.href=withPrice[0].url;bb.innerHTML='🛒 Buy • '+esc(withPrice[0].store)+' — '+inr(withPrice[0].price)}
    }
    if(MODAL_IDX===idx){document.getElementById('m-price').textContent='≈ '+inr(p.price);document.getElementById('m-stores').innerHTML=renderStorePrices(p);document.getElementById('m-links').innerHTML=bestDealBar(p)}
  }).catch(function(){});
}
function drainLive(){while(LIVEQ.length)fetchLive(LIVEQ.shift())}

function bestDealBar(p){
  var live=arr(p.live_prices).filter(function(s){return s.price!=null&&s.url}).sort(function(a,b){return a.price-b.price});
  var bs=live.length?live[0]:(arr(p.store_prices).length?p.store_prices[0]:null);
  var html=bs?'<a class="buy-btn" target="_blank" rel="noopener noreferrer" href="'+bs.url+'">🛒 BUY AT BEST PRICE — '+esc(bs.store)+' • '+inr(bs.price)+'</a> ':'';
  return html+'<button class="shop-btn" onclick="shareToGroup()">👥 Share</button><button class="shop-btn" onclick="saveWish()">🔖 Wishlist</button>';
}

function renderStorePrices(p){
  var liveArr=arr(p.live_prices);
  var est=arr(p.store_prices);
  var merged;
  if(liveArr.length){
    merged=liveArr.map(function(s){
      var e=null;for(var i=0;i<est.length;i++){if(est[i].store===s.store){e=est[i];break}}
      return {store:s.store, price:(s.price!=null?s.price:(e?e.price:null)), url:(s.url||(e?e.url:'')), live:!!s.live};
    });
  }else{
    merged=est.map(function(s){return {store:s.store,price:s.price,url:s.url,live:false}});
  }
  merged.sort(function(a,b){
    if(a.live!==b.live)return a.live?-1:1;
    return (a.price==null?9e9:a.price)-(b.price==null?9e9:b.price);
  });
  var lowest=null;
  for(var i=0;i<merged.length;i++){if(merged[i].price!=null){lowest=merged[i];break}}
  var rows=merged.map(function(s){
    var isBest=lowest&&s.store===lowest.store&&s.price!=null;
    return '<tr'+(isBest?' style="background:rgba(52,211,153,.10)"':'')+'>'+
      '<td><b>'+esc(s.store)+'</b> '+(s.live
        ?'<span style="color:var(--green);font-size:9px;font-weight:800;border:1px solid rgba(52,211,153,.4);padding:1px 6px;border-radius:99px">LIVE</span>'
        :'<span style="color:var(--dim);font-size:9px;font-weight:700">AI CHECK</span>')+
      (isBest?' <span style="color:var(--green);font-size:10px;font-weight:800">BEST</span>':'')+'</td>'+
      '<td style="font-weight:700">'+(s.price!=null?inr(s.price):'—')+'</td>'+
      '<td><a class="shop-btn" target="_blank" rel="noopener noreferrer" href="'+s.url+'">Visit ↗</a></td></tr>';
  }).join('');
  if(!rows)return '';
  return '<div class="chart-box" style="margin:12px 0"><div class="chart-head"><h3>🛒 '+esc(p.name)+' — all platforms</h3>'+(lowest?'<span class="verdict verdict-BUYNOW">Lowest: '+inr(lowest.price)+'</span>':'')+'</div>'+
    '<table style="margin-top:4px"><tr><th>Store</th><th>Price</th><th>Exact Page</th></tr>'+rows+'</table>'+
    '<p class="range">Only the store YOU choose opens — one tap, one exact product page.</p></div>';
}

function trendBadge(t){
  if(t==='falling')return '<span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;background:rgba(52,211,153,.12);color:var(--green)">▼ falling</span>';
  if(t==='rising')return '<span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;background:rgba(248,113,113,.12);color:var(--red)">▲ rising</span>';
  return '<span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;background:var(--card-2);color:var(--dim)">● stable</span>';
}
function renderChart(pd){
  if(!pd||!arr(pd.history).length)return '';
  var W=600,H=210,PAD=34,all=arr(pd.history).concat(arr(pd.forecast));
  var min=Math.min.apply(null,all)*0.98,max=Math.max.apply(null,all)*1.02;
  if(max<=min)max=min+1;
  var n=all.length;
  var x=function(i){return PAD+i*(W-2*PAD)/(n-1)};
  var y=function(v){return H-PAD-(v-min)*(H-2*PAD)/(max-min)};
  var histPts=arr(pd.history).map(function(v,i){return x(i)+','+y(v)}).join(' ');
  var fcPts=[x(pd.history.length-1)+','+y(pd.history[pd.history.length-1])].concat(arr(pd.forecast).map(function(v,i){return x(pd.history.length+i)+','+y(v)})).join(' ');
  return '<svg viewBox="0 0 '+W+' '+H+'" class="chart">'+
    '<line x1="'+PAD+'" y1="'+y(max)+'" x2="'+(W-PAD)+'" y2="'+y(max)+'" stroke="var(--border-2)" stroke-width="1"/>'+
    '<line x1="'+PAD+'" y1="'+y(min)+'" x2="'+(W-PAD)+'" y2="'+y(min)+'" stroke="var(--border-2)" stroke-width="1"/>'+
    '<line x1="'+x(pd.history.length-1)+'" y1="'+(PAD*0.6)+'" x2="'+x(pd.history.length-1)+'" y2="'+(H-PAD)+'" stroke="var(--border-2)" stroke-width="1" stroke-dasharray="4 4"/>'+
    '<polyline points="'+histPts+'" class="line-hist"/>'+
    '<polyline points="'+fcPts+'" class="line-fc"/>'+
    '<circle cx="'+x(pd.history.length-1)+'" cy="'+y(pd.history[pd.history.length-1])+'" r="4.5" class="dot-now"/>'+
    '<text x="'+PAD+'" y="'+(H-10)+'" class="tick">'+(arr(pd.labels)[0]||'Start')+'</text>'+
    '<text x="'+x(pd.history.length-1)+'" y="'+(H-10)+'" text-anchor="middle" class="tick">Today</text>'+
    '<text x="'+(W-PAD)+'" y="'+(H-10)+'" text-anchor="end" class="tick">+4 weeks</text>'+
    '<text x="'+(W-PAD)+'" y="'+(y(max)-6)+'" text-anchor="end" class="tick">'+inr(max)+'</text>'+
    '<text x="'+(W-PAD)+'" y="'+(y(min)+14)+'" text-anchor="end" class="tick">'+inr(min)+'</text></svg>';
}
function openModal(idx){
  var p=PSTORE[idx]||{};window._modalProduct=p;MODAL_IDX=idx;
  document.getElementById('m-img').src=p.image_url||'';
  document.getElementById('m-brand').textContent=String(p.brand||'').toUpperCase();
  document.getElementById('m-name').textContent=p.name||'';
  document.getElementById('m-price').textContent='≈ '+inr(p.price);
  document.getElementById('m-rating').textContent='★ '+numSafe(p.rating)+' / 5';
  document.getElementById('m-reason').textContent='"'+(p.ai_reason||'')+'"';
  document.getElementById('m-links').innerHTML=bestDealBar(p);
  document.getElementById('m-stores').innerHTML=renderStorePrices(p);
  var pd=p.price_data||{};
  document.getElementById('m-chart').innerHTML=renderChart(pd);
  var v=document.getElementById('m-verdict');
  v.textContent=(pd.verdict==='WAIT')?'⏳ WAIT':' BUY NOW';
  v.className='verdict '+((pd.verdict==='WAIT')?'verdict-WAIT':'verdict-BUYNOW');
  document.getElementById('m-advice').textContent=(pd.advice||'')+(p.festival_tip?' 💡 '+p.festival_tip:'');
  var rangeTxt=pd.lowest?('12-week range: '+inr(pd.lowest)+' – '+inr(pd.highest)+'  •  Predicted in 4 weeks: '+inr(pd.predicted_price)):'';
  if(arr(p.price_range).length===2){rangeTxt+='  •  Store range: ₹'+Number(numSafe(p.price_range[0])).toLocaleString('en-IN')+' – ₹'+Number(numSafe(p.price_range[1])).toLocaleString('en-IN')}
  document.getElementById('m-range').textContent=rangeTxt;
  document.getElementById('m-specs').innerHTML=p.specs?Object.keys(p.specs).map(function(k){return '<span class="spec">'+esc(k)+': <b>'+esc(p.specs[k])+'</b></span>'}).join(''):'';
  document.getElementById('m-proscons').innerHTML=arr(p.pros).map(function(x){return '<div class="pros">✅ '+esc(x)+'</div>'}).join('')+arr(p.cons).map(function(x){return '<div class="cons">⚠️ '+esc(x)+'</div>'}).join('');
  document.getElementById('overlay').classList.remove('hidden');
}
function closeModal(){document.getElementById('overlay').classList.add('hidden');MODAL_IDX=-1}
function closeShare(){document.getElementById('share-overlay').classList.add('hidden')}
function closeWish(){document.getElementById('wish-overlay').classList.add('hidden')}
document.addEventListener('keydown',function(e){if(e.key==='Escape'){closeModal();closeShare();closeAbout();closeWish()}});

function saveWish(){var p=window._modalProduct;if(!p)return;apiFetch('/wishlist/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:UID,product:{name:p.name,brand:p.brand,price:p.price,rating:p.rating,image_url:p.image_url}})}).then(function(){toast('🔖 Saved to wishlist')})}
function openWish(){
  apiFetch('/wishlist').then(function(r){return r.json()}).then(function(list){
    var el=document.getElementById('w-list');window.WISH=arr(list);
    if(!window.WISH.length){el.innerHTML='<div style="color:var(--dim);text-align:center;padding:20px">Wishlist is empty. Save products from chat!</div>'}
    else{el.innerHTML=window.WISH.map(function(w){return '<div class="wish-row"><img src="'+(w.image_url||'')+'"><div class="wish-info"><b>'+esc(w.name)+'</b><span>'+esc(w.brand||'')+' • '+inr(w.price||0)+'</span></div><button class="icon-btn" data-wish-name="'+esc(w.name)+'">🗑</button></div>'}).join('');
    el.querySelectorAll('[data-wish-name]').forEach(function(btn){btn.addEventListener('click',function(){removeWish(btn.getAttribute('data-wish-name'))})})}
    document.getElementById('wish-overlay').classList.remove('hidden');
  });
}
function removeWish(name){apiFetch('/wishlist/remove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:UID,name:name})}).then(function(){openWish()})}

function openShare(idx){
  var text='🛍️ Try ShopZen AI — trusted real prices & one exact buy link!';
  if(idx!=null&&RSTORE[idx]&&RSTORE[idx].summary)text='🛍️ ShopZen AI says: '+RSTORE[idx].summary;
  var url=location.href.split('?')[0];var full=encodeURIComponent(text+' '+url);var eu=encodeURIComponent(url);
  var html='';
  if(navigator.share){html+='<button class="shop-btn" onclick="nativeShare()">📱 Native Share</button>'}
  html+='<a class="shop-btn" target="_blank" href="https://wa.me/?text='+full+'">🟢 WhatsApp</a>'+
    '<a class="shop-btn" target="_blank" href="https://t.me/share/url?url='+eu+'&text='+encodeURIComponent(text)+'">✈️ Telegram</a>'+
    '<a class="shop-btn" target="_blank" href="https://twitter.com/intent/tweet?text='+full+'">🐦 X / Twitter</a>'+
    '<a class="shop-btn" href="mailto:?subject='+encodeURIComponent('ShopZen AI')+'&body='+full+'">✉️ Email</a>'+
    '<button class="shop-btn" onclick="copyLink()">📋 Copy Link</button>';
  document.getElementById('share-links').innerHTML=html;window._shareText=text;
  document.getElementById('share-overlay').classList.remove('hidden');
}
function nativeShare(){navigator.share({title:'ShopZen AI',text:window._shareText||'',url:location.href.split('?')[0]}).then(function(){toast('Shared!')})}
function copyLink(){var txt=(window._shareText||'')+' '+location.href.split('?')[0];navigator.clipboard.writeText(txt).then(function(){toast('Link copied!')})}

function fbUp(idx){sendFeedback('up','',idx)}
function fbDown(idx){
  var el=document.getElementById('fb-'+idx);if(!el)return;
  var html='<span style="font-size:11px;color:var(--dim);margin-right:4px">What went wrong?</span>';
  ['Wrong price','Not relevant','Out of budget','Weak info'].forEach(function(r){html+='<button class="chip" data-reason="'+r+'">'+r+'</button>'});
  html+='<button class="chip" data-reason="">Skip</button>';el.innerHTML=html;
  el.querySelectorAll('[data-reason]').forEach(function(b){b.addEventListener('click',function(){sendFeedback('down',b.dataset.reason,idx)})});
}
function sendFeedback(rating,reason,idx){
  var summary=(RSTORE[idx]&&RSTORE[idx].summary)||'';
  apiFetch('/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rating:rating,reason:reason,summary:summary,user_id:UID})})
  .then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('fb-'+idx);
    if(el)el.innerHTML='<span style="font-size:12px;color:var(--green);font-weight:600">'+(rating==='up'?'👍 Thanks! Glad it helped.':'🙏 Noted — I will improve.')+'</span>';
    toast(rating==='up'?'Feedback recorded. Thank you!':'Thanks! I will do better next time.');updateStats(d.stats);
  });
}
function exportChat(){
  var txt='SHOPZEN AI — CONVERSATION EXPORT\n'+new Date().toLocaleString()+'\n'+'='.repeat(46)+'\n\n';
  CHAT_LOG.forEach(function(m){txt+=(m.role==='user'?'YOU: ':'SHOPZEN: ')+m.text+'\n\n'});
  var a=document.createElement('a');a.href=URL.createObjectURL(new Blob([txt],{type:'text/plain'}));a.download='shopzen-conversation.txt';a.click();
  toast('📥 Conversation exported');
}

function productCardHTML(p){
  p=p||{};PSTORE.push(p);var idx=PSTORE.length-1;LIVEQ.push(idx);
  var best=arr(p.store_prices).length?p.store_prices[0]:null;
  var buyUrl=best?best.url:directUrl('flipkart.com',p.name);
  var buyLabel=best?('🛒 Buy • '+esc(best.store)):'🛒 Buy';
  return '<div class="product-card">'+
    '<div class="img-wrap" onclick="openModal('+idx+')"><img src="'+(p.image_url||'')+'" alt="'+esc(p.name)+'"></div>'+
    '<div class="product-info">'+
      '<div style="display:flex;justify-content:space-between;align-items:center"><span class="brand">'+esc(p.brand)+'</span><span style="font-size:11px;color:var(--amber);font-weight:700">★ '+numSafe(p.rating)+'</span></div>'+
      '<div class="name" onclick="openModal('+idx+')">'+esc(p.name)+'</div>'+
      '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap"><span class="price" id="price-'+idx+'">≈ '+inr(p.price)+'</span>'+trendBadge(p.price_trend)+'</div>'+
      '<div class="bestline" id="best-'+idx+'">'+(best?('Best: '+inr(best.price)+' on '+esc(best.store)):'')+'</div>'+
      '<div class="reason">"'+esc(p.ai_reason)+'"</div>'+
      '<div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">'+
        '<a id="buy-'+idx+'" class="buy-btn" target="_blank" rel="noopener noreferrer" href="'+buyUrl+'">'+buyLabel+'</a>'+
        '<button class="icon-btn" onclick="openModal('+idx+')" style="flex:1">📊 Compare</button>'+
      '</div>'+
    '</div></div>';
}

function renderResponse(data){
  data=data||{};
  var html='<p>'+esc(data.summary||'')+'</p>';
  if(data.intent==='clarify'&&arr(data.questions).length){
    arr(data.questions).forEach(function(q){
      q=q||{};html+='<div class="cq">'+esc(q.q)+'</div><div class="chips">';
      arr(q.options).forEach(function(o){html+='<button class="chip" data-o="'+esc(o)+'">'+esc(o)+'</button>'});
      html+='</div>';
    });
  }
  if(data.intent==='search'&&arr(data.products).length){
    var prods=arr(data.products);
    if(data.personalized){
      html+='<div class="winner-card"><div class="winner-title">🎯 EXACT MATCH FOR YOU</div>'+productCardHTML(prods[0])+'</div>';
      if(prods.length>1)html+='<div class="cq">Alternatives you may also like 🙂</div><div class="products-grid">'+prods.slice(1).map(productCardHTML).join('')+'</div>';
    }else{
      html+='<div class="products-grid">'+prods.map(productCardHTML).join('')+'</div>';
    }
    html+='<div class="disclaimer">💯 Prices verified against real market data; LIVE store check confirms the exact current price.</div>';
  }
  if(data.intent==='decide'&&data.winner){
    html+='<div class="winner-card"><div class="winner-title">🏆 FINAL PICK — ONE DECISION</div>'+productCardHTML(data.winner)+
      (data.runner_up?'<div style="margin-top:10px;font-size:12px;color:var(--dim)">Runner-up: '+esc(data.runner_up)+'</div>':'')+'</div>';
  }
  if(data.intent==='timing'&&data.timing){
    var t=data.timing||{};
    html+='<div class="timing-card"><div class="timing-title">⏳ BEST TIME TO BUY — '+esc(t.product||'')+'</div>'+
      '<div class="chart-box" style="margin:8px 0">'+renderChart(t.price_data||null)+'</div>'+
      '<p class="advice"><b>'+esc(t.verdict||'')+'</b> • Now: '+(t.price_now?inr(t.price_now):'')+' → Predicted: '+(t.predicted_price?inr(t.predicted_price):'')+' ('+numSafe(t.expected_drop_pct)+'% drop)</p>'+
      '<p class="advice">🗓️ Best window: '+esc(t.best_window||'')+'</p>'+
      '<p class="range">'+esc(t.reason||'')+'</p></div>';
  }
  if(data.intent==='compare'&&(arr(data.products).length||arr(data.comparison).length)){
    var cprods=arr(data.products),crow=arr(data.comparison);
    html+='<table><tr><th>Feature</th>';
    cprods.forEach(function(p){html+='<th>'+esc(typeof p==='string'?p:((p&&p.name)||''))+'</th>'});
    html+='</tr>';
    crow.forEach(function(row){row=row||{};var vals=arr(row.values);html+='<tr><td><b>'+esc(row.feature||'')+'</b></td>';cprods.forEach(function(_,i){html+='<td>'+esc(vals[i]!=null?vals[i]:'-')+'</td>'});html+='</tr>'});
    html+='</table>';
  }
  if(data.intent==='review'){
    html+='<div class="panel"><h4>Trust Score: '+numSafe(data.trust_score)+'/100 | Fake Probability: '+numSafe(data.fake_pct)+'%</h4>';
    arr(data.reviews).forEach(function(r){r=r||{};
      html+='<div style="margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid var(--border);font-size:13px">'+
        '<span style="color:var(--amber);font-size:12px">'+stars(r.rating)+'</span>'+
        '<p style="margin:6px 0">"'+esc(r.text)+'"</p>'+
        (r.verified?'<span style="color:var(--green);font-size:10px;font-weight:700">✓ Verified Purchase</span>':'')+
        '</div>';
    });
    html+='</div>';
  }
  if(data.intent==='negotiate'){
    html+='<div class="panel"><h4>Negotiation Successful!</h4><p>Original: <s>'+inr(data.original_price)+'</s></p>'+
      '<div style="font-size:22px;font-weight:800;color:var(--green);margin:8px 0">Final: '+inr(data.final_price)+'</div>'+
      '<div style="background:var(--card-2);padding:12px;border-radius:12px;font-size:13px;margin-top:10px">';
    arr(data.script).forEach(function(s){var parts=String(s).split(':');html+='<p style="margin-bottom:6px"><b>'+esc(parts[0])+':</b>'+esc(parts.slice(1).join(':'))+'</p>'});
    html+='</div></div>';
  }
  return html;
}

function addMsg(role,dataOrText,fetchNow){
  if(fetchNow===undefined)fetchNow=true;
  startChatView();
  var msg=document.createElement('div');msg.className='msg '+role;
  var content=role==='user'?esc(dataOrText):renderResponse(dataOrText);
  if(role!=='user'){
    RSTORE.push(dataOrText);CHAT_LOG.push({role:'agent',text:(dataOrText&&dataOrText.summary)||''});
    speak((dataOrText&&dataOrText.summary)||'');
    var idx=RSTORE.length-1;
    content+='<div style="display:flex;gap:6px;align-items:center;margin-top:12px;padding-top:10px;border-top:1px dashed var(--border)" id="fb-'+idx+'">'+
      '<button class="icon-btn" data-fb="up">👍</button>'+
      '<button class="icon-btn" data-fb="down">👎</button>'+
      '<button class="icon-btn" data-share="1">🔗 Share</button></div>';
    if(dataOrText&&dataOrText.intent==='search'){
      content+='<div class="chips">'+
        '<button class="chip" data-o="which is the best one for me?">🏆 Pick the best one</button>'+
        '<button class="chip" data-o="when is the best time to buy?">⏳ Best time to buy?</button>'+
        '<button class="chip" data-o="Compare the top two">⚖️ Compare top 2</button>'+
        '<button class="chip" data-o="cheaper options">💸 Cheaper options</button></div>';
    }
  }else{CHAT_LOG.push({role:'user',text:dataOrText})}
  var avatarHtml=role==='user'
    ? '<div class="avatar user">'+esc((UNAME[0]||'U').toUpperCase())+'</div>'
    : '<div class="avatar ai"><svg width="20" height="20"><use href="#logo"/></svg></div>';
  msg.innerHTML=avatarHtml+'<div class="bubble">'+content+'</div>';
  chatArea.appendChild(msg);chatArea.scrollTop=chatArea.scrollHeight;
  if(role!=='user'){
    msg.querySelectorAll('[data-fb]').forEach(function(b){b.addEventListener('click',function(){if(b.dataset.fb==='up')fbUp(idx);else fbDown(idx)})});
    msg.querySelectorAll('[data-share]').forEach(function(b){b.addEventListener('click',function(){openShare(idx)})});
    if(fetchNow)drainLive();
  }
}

function showTyping(){sendBtn.disabled=true;var msg=document.createElement('div');msg.className='msg agent';msg.id='typing-indicator';msg.innerHTML='<div class="avatar ai"><svg width="20" height="20"><use href="#logo"/></svg></div><div class="bubble"><div class="typing"><span></span><span></span><span></span></div></div>';chatArea.appendChild(msg);chatArea.scrollTop=chatArea.scrollHeight}
function hideTyping(){sendBtn.disabled=false;var el=document.getElementById('typing-indicator');if(el)el.remove()}

function sendMessage(text){
  if(!text||!text.trim())return;
  startChatView();addMsg('user',text);input.value='';showTyping();
  apiFetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,user_id:UID})})
  .then(function(r){return r.json()}).then(function(data){hideTyping();addMsg('agent',data);if(data&&data.intent==='search')refreshSidebar()})
  .catch(function(){hideTyping();addMsg('agent',{intent:'chat',summary:'⚠️ Connection lost. Check backend.'})});
}
function send(){sendMessage(input.value)}
function startVoice(){
  var SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR)return alert('Voice not supported');
  var r=new SR();r.lang='en-IN';r.onresult=function(e){sendMessage(e.results[0][0].transcript)};r.start();
}

if(UID&&TOKEN){enterApp()}else{document.getElementById('auth-overlay').classList.remove('hidden')}
</script></body></html>"""

@app.get("/")
def home():
    return Response(content=HTML_PAGE, media_type="text/html", headers={"Cache-Control": "no-store"})

def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close(); return ip
    except Exception:
        return "127.0.0.1"

def pick_port(preferred):
    for p in [preferred, 8000, 8080, 6789, 5000, 9000, 4173, 3000]:
        try:
            t = socket.socket(); t.bind(("0.0.0.0", p)); t.close(); return p
        except OSError:
            continue
    return preferred

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "0")) or pick_port(8080)
    print("\n========== SHOPZEN AI - TRUSTED PRICE FINAL ==========")
    if client:
        try:
            client.chat.completions.create(model=MODELS[0], messages=[{"role": "user", "content": "READY"}], max_tokens=5)
            print("✅ Groq brain ONLINE")
        except Exception as e:
            print("⚠️ note:", str(e)[:60])
    else:
        print("❌ Run: py -m pip install openai")
    print("\n  LINK 1 (VS Code / this PC) : http://127.0.0.1:" + str(port))
    print("  LINK 2 (Mobile / WiFi)     : http://" + lan_ip() + ":" + str(port) + "\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
