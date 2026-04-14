"""
Facebook Marketplace Scraper - Kota Subulussalam, Aceh
Versi 4.0 — Fix parsing "Baru terdaftar" + fetch detail halaman
"""

import asyncio
import json
import csv
import re
import random
from datetime import datetime
from pathlib import Path

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("Playwright belum terinstall. Jalankan:")
    print("   pip install playwright && playwright install chromium")
    exit(1)


# ─────────────────────────────────────────────
# KONFIGURASI
# ─────────────────────────────────────────────
CONFIG = {
    "base_url": "https://www.facebook.com/marketplace/subulussalam/",
    "category": "",

    # Filter lokasi — hanya simpan listing dari area ini
    "filter_lokasi": [
        "subulussalam",
        "subulusalam",
    ],

    "max_scrolls": 25,
    "scroll_delay_min": 2.0,
    "scroll_delay_max": 3.5,
    "scroll_pixel": 800,

    "output_json": "marketplace_subulussalam.json",
    "output_csv":  "marketplace_subulussalam.csv",
    "headless": False,
    "cookies_file": "fb_cookies.json",

    # Fetch halaman detail untuk item yang judulnya kosong/"Baru terdaftar"
    # True = lebih akurat tapi lebih lambat
    "fetch_detail_for_missing_title": True,
    "detail_concurrency": 3,       # Berapa listing di-fetch paralel
    "detail_delay": 1.5,           # Jeda antar fetch detail (detik)
}

# Label generik yang BUKAN judul asli
GENERIC_LABELS = re.compile(
    r"^(baru terdaftar|new listing|baru ditambahkan|newly listed|"
    r"sponsored|iklan berbayar|iklan|listing baru)$",
    re.IGNORECASE
)

# Kata kunci lokasi Indonesia
LOC_PATTERN = re.compile(
    r"(aceh|sumatera|indonesia|km\s*\d|\d+\s*km|jakarta|medan|"
    r"singkil|subulussalam|subulusalam|tapanuli|sidikalang|"
    r"labuhanhaji|blangkejeren|kutacane|kota |kabupaten )",
    re.IGNORECASE
)

SUBULUSSALAM_RE = re.compile(r"subulu?s+alam", re.IGNORECASE)


# ─────────────────────────────────────────────
# COOKIES & LOGIN
# ─────────────────────────────────────────────

async def save_cookies(context, filepath):
    cookies = await context.cookies()
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)
    print(f"[+] Cookies disimpan: {filepath}")


async def load_cookies(context, filepath) -> bool:
    if not Path(filepath).exists():
        return False
    try:
        with open(filepath, encoding="utf-8") as f:
            await context.add_cookies(json.load(f))
        print(f"[+] Cookies dimuat: {filepath}")
        return True
    except Exception as e:
        print(f"[!] Gagal muat cookies: {e}")
        return False


async def is_logged_in(page) -> bool:
    url = page.url
    if any(x in url for x in ["login", "checkpoint", "recover"]):
        return False
    try:
        await page.wait_for_selector('div[role="main"]', timeout=5000)
        return True
    except Exception:
        return False


async def do_login(page, context):
    print("\n" + "="*55)
    print("  LOGIN FACEBOOK DIPERLUKAN")
    print("="*55)
    print("  1. Login di browser yang terbuka")
    print("  2. Tunggu masuk ke beranda Facebook")
    print("  3. Kembali ke terminal dan tekan ENTER")
    print("="*55 + "\n")
    await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=30000)
    input("  >> Tekan ENTER setelah login: ")
    print()
    await save_cookies(context, CONFIG["cookies_file"])


# ─────────────────────────────────────────────
# SCROLL
# ─────────────────────────────────────────────

async def scroll_and_load(page) -> int:
    max_scrolls = CONFIG["max_scrolls"]
    print(f"\n[*] Scroll {max_scrolls}x untuk muat listing...")
    prev_count = 0
    stagnant = 0

    for i in range(max_scrolls):
        if i > 0 and i % 8 == 0:
            try:
                await page.evaluate("window.scrollBy({ top: -1200, behavior: 'smooth' })")
                await asyncio.sleep(1.5)
            except Exception:
                pass

        try:
            await page.evaluate(
                f"window.scrollBy({{ top: {CONFIG['scroll_pixel']}, behavior: 'smooth' }})"
            )
        except Exception:
            try:
                await page.keyboard.press("PageDown")
            except Exception:
                pass

        delay = random.uniform(CONFIG["scroll_delay_min"], CONFIG["scroll_delay_max"])
        await asyncio.sleep(delay)

        items = await page.query_selector_all('a[href*="/marketplace/item/"]')
        curr = len(items)
        print(f"    [{i+1:02d}/{max_scrolls}] {curr} item | {delay:.1f}s")

        # Tutup popup
        for label in ["Close", "Tutup", "Not Now", "Nanti"]:
            try:
                btn = page.locator(f'[aria-label="{label}"]').first
                if await btn.is_visible(timeout=200):
                    await btn.click()
                    break
            except Exception:
                pass

        if curr == prev_count:
            stagnant += 1
            if stagnant >= 5:
                print("    [!] Tidak ada item baru 5x berturut — stop scroll.")
                break
        else:
            stagnant = 0
        prev_count = curr

    return prev_count


# ─────────────────────────────────────────────
# PARSE CARD TEXT
# ─────────────────────────────────────────────

def parse_card(lines: list) -> dict:
    """
    Parsing teks card listing.

    Facebook menampilkan beberapa format tergantung badge:
    FORMAT A (normal):
        Rp999.000
        Nama Produk
        Kota, Provinsi, Indonesia

    FORMAT B (dengan badge "Baru terdaftar"):
        Baru terdaftar
        Rp999.000
        Nama Produk
        Kota, Provinsi, Indonesia

    Parser ini menangani kedua format dan membuang label generik.
    """
    result = {"harga": "", "judul": "", "lokasi": "", "has_badge": False}

    # Tandai dan buang label generik
    clean = []
    for line in lines:
        if GENERIC_LABELS.match(line):
            result["has_badge"] = True  # Tandai bahwa item ini punya badge
        else:
            clean.append(line)

    if not clean:
        return result

    # Cari harga
    harga_idx = -1
    for idx, line in enumerate(clean):
        if re.search(r"Rp[\s\.]?[\d\.,]+|IDR\s*[\d\.,]+|free|gratis", line, re.IGNORECASE):
            result["harga"] = line.strip()
            harga_idx = idx
            break

    # Sisihkan harga
    rest = [l for i, l in enumerate(clean) if i != harga_idx]

    # Cari lokasi — baris yang cocok pola kota/provinsi
    lokasi_idx = -1
    for idx, line in enumerate(rest):
        if LOC_PATTERN.search(line):
            result["lokasi"] = line.strip()
            lokasi_idx = idx
            break

    # Judul = sisa yang bukan harga & bukan lokasi
    judul_candidates = [l for i, l in enumerate(rest) if i != lokasi_idx and len(l) > 2]
    if judul_candidates:
        # Ambil baris terpanjang sebagai judul (paling deskriptif)
        result["judul"] = max(judul_candidates, key=len)

    return result


# ─────────────────────────────────────────────
# FETCH DETAIL HALAMAN
# ─────────────────────────────────────────────

async def fetch_item_detail(context, url: str) -> dict:
    """
    Buka halaman detail listing dan ambil judul + deskripsi asli.
    Dipakai untuk item yang judulnya kosong atau generik.
    """
    detail = {"judul": "", "deskripsi": "", "lokasi_detail": ""}
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(2)

        # Judul — biasanya di <h1> atau elemen dengan data-testid
        title_selectors = [
            'h1[class*="title"]',
            'span[class*="title"]',
            'div[data-testid="marketplace-pdp-title"] span',
            'h1',
        ]
        for sel in title_selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    txt = (await el.inner_text()).strip()
                    if txt and not GENERIC_LABELS.match(txt) and len(txt) > 2:
                        detail["judul"] = txt
                        break
            except Exception:
                continue

        # Lokasi detail
        loc_selectors = [
            'div[data-testid="marketplace-pdp-location"] span',
            'a[href*="marketplace"][href*="city"] span',
        ]
        for sel in loc_selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    txt = (await el.inner_text()).strip()
                    if txt:
                        detail["lokasi_detail"] = txt
                        break
            except Exception:
                continue

        # Fallback: cari dari meta og:title
        if not detail["judul"]:
            try:
                og = await page.evaluate(
                    "() => document.querySelector('meta[property=\"og:title\"]')?.content || ''"
                )
                og = og.strip()
                if og and "facebook" not in og.lower() and "marketplace" not in og.lower():
                    detail["judul"] = og
            except Exception:
                pass

    except Exception as e:
        pass
    finally:
        await page.close()

    return detail


async def enrich_missing_titles(context, listings: list) -> list:
    """
    Untuk listing yang judulnya kosong/generik, fetch halaman detailnya.
    Dilakukan secara paralel dengan batas concurrency.
    """
    need_detail = [i for i, x in enumerate(listings) if not x["judul"] or GENERIC_LABELS.match(x["judul"])]

    if not need_detail:
        return listings

    print(f"\n[*] {len(need_detail)} listing perlu fetch detail (judul kosong/generik)...")

    sem = asyncio.Semaphore(CONFIG["detail_concurrency"])

    async def fetch_one(idx):
        item = listings[idx]
        async with sem:
            print(f"    -> Fetch detail: {item['url'][:60]}...")
            detail = await fetch_item_detail(context, item["url"])
            await asyncio.sleep(CONFIG["detail_delay"])
        if detail["judul"]:
            listings[idx]["judul"] = detail["judul"]
        if detail["lokasi_detail"] and not listings[idx]["lokasi"]:
            listings[idx]["lokasi"] = detail["lokasi_detail"]
        return idx

    tasks = [fetch_one(i) for i in need_detail]
    for coro in asyncio.as_completed(tasks):
        await coro

    still_missing = sum(1 for i in need_detail if not listings[i]["judul"])
    print(f"[+] Selesai enrich. Masih kosong: {still_missing}")
    return listings


# ─────────────────────────────────────────────
# EKSTRAK LISTING DARI HALAMAN
# ─────────────────────────────────────────────

async def extract_listings(page) -> list:
    print("\n[*] Mengekstrak data listing dari halaman...")

    items = await page.query_selector_all('a[href*="/marketplace/item/"]')
    if not items:
        print("[!] Tidak ada listing ditemukan. Menyimpan debug...")
        await page.screenshot(path="debug_screenshot.png")
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(await page.content())
        print(f"    URL: {page.url}")
        return []

    print(f"    {len(items)} elemen raw ditemukan...")
    listings = []
    seen = set()

    for item in items:
        try:
            href = await item.get_attribute("href") or ""
            if "/marketplace/item/" not in href:
                continue

            url = href.split("?")[0]
            if url.startswith("/"):
                url = "https://www.facebook.com" + url
            if url in seen:
                continue
            seen.add(url)

            item_id = (re.search(r"/item/(\d+)", url) or type("", (), {"group": lambda s, x: ""})()).group(1)

            try:
                raw = await item.inner_text()
            except Exception:
                raw = ""
            lines = [l.strip() for l in raw.splitlines() if l.strip()]

            parsed = parse_card(lines)

            try:
                img = await item.query_selector("img")
                gambar = (await img.get_attribute("src") or "") if img else ""
            except Exception:
                gambar = ""

            listings.append({
                "id": item_id,
                "judul": parsed["judul"],
                "harga": parsed["harga"],
                "lokasi": parsed["lokasi"],
                "url": url,
                "gambar": gambar,
                "has_badge": parsed["has_badge"],
                "scraped_at": datetime.now().isoformat(),
            })

        except Exception:
            continue

    print(f"[+] Diekstrak: {len(listings)} listing unik")
    return listings


def filter_subulussalam(listings: list) -> list:
    if not CONFIG["filter_lokasi"]:
        return listings
    result = [x for x in listings if SUBULUSSALAM_RE.search(x.get("lokasi", ""))]
    print(f"[+] Setelah filter Subulussalam: {len(result)} dari {len(listings)}")
    return result


# ─────────────────────────────────────────────
# SIMPAN
# ─────────────────────────────────────────────

def save_results(listings: list, suffix=""):
    if not listings:
        print("[!] Tidak ada data untuk disimpan.")
        return

    # Hapus field internal sebelum simpan
    clean = [{k: v for k, v in x.items() if k != "has_badge"} for x in listings]

    json_out = CONFIG["output_json"].replace(".json", f"{suffix}.json")
    csv_out  = CONFIG["output_csv"].replace(".csv",  f"{suffix}.csv")

    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    print(f"[+] JSON: {json_out} ({len(clean)} item)")

    fields = ["id", "judul", "harga", "lokasi", "url", "gambar", "scraped_at"]
    with open(csv_out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(clean)
    print(f"[+] CSV : {csv_out} ({len(clean)} item)")


def print_preview(listings, label="PREVIEW", n=5):
    if not listings:
        return
    print(f"\n{'='*65}")
    print(f"  {label} — {min(n, len(listings))} dari {len(listings)}")
    print("="*65)
    for i, item in enumerate(listings[:n], 1):
        badge = " [BADGE]" if item.get("has_badge") else ""
        print(f"\n  [{i}]{badge} {item.get('judul') or '(judul kosong)'}")
        print(f"       Harga  : {item.get('harga') or '-'}")
        print(f"       Lokasi : {item.get('lokasi') or '-'}")
        print(f"       URL    : {item.get('url','')[:70]}")
    print("="*65)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

async def main():
    print("="*65)
    print("  FB Marketplace Scraper v4 — Subulussalam, Aceh")
    print("="*65)

    target_url = CONFIG["base_url"]
    if CONFIG["category"]:
        target_url += CONFIG["category"] + "/"

    print(f"  Target        : {target_url}")
    print(f"  Filter        : {CONFIG['filter_lokasi'] or 'semua'}")
    print(f"  Fetch detail  : {CONFIG['fetch_detail_for_missing_title']}\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=CONFIG["headless"],
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            locale="id-ID",
        )
        page = await context.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )

        await load_cookies(context, CONFIG["cookies_file"])

        # Buka marketplace
        print("[*] Membuka Marketplace Subulussalam...")
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
        except PlaywrightTimeout:
            print("[!] Timeout, lanjut...")
        try:
            await page.wait_for_selector("body", timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(4)

        # Login jika perlu
        if not await is_logged_in(page):
            await do_login(page, context)
            try:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_selector("body", timeout=15000)
            except Exception:
                pass
            await asyncio.sleep(5)
        else:
            print("[+] Sudah login!")

        # Scroll
        await scroll_and_load(page)

        # Ekstrak
        all_listings = await extract_listings(page)

        # Enrich judul yang kosong/generik via fetch detail
        if CONFIG["fetch_detail_for_missing_title"] and all_listings:
            all_listings = await enrich_missing_titles(context, all_listings)

        await save_cookies(context, CONFIG["cookies_file"])
        await browser.close()

    # Filter & simpan
    filtered = filter_subulussalam(all_listings)

    save_results(all_listings, suffix="_semua")
    save_results(filtered,     suffix="")

    print_preview(filtered, label="LISTING SUBULUSSALAM (TERFILTER)")

    print(f"\n{'='*65}")
    print(f"  SELESAI")
    print(f"  Total scrape   : {len(all_listings)}")
    print(f"  Subulussalam   : {len(filtered)}")
    print(f"  Output utama   : {CONFIG['output_json']} & {CONFIG['output_csv']}")
    print(f"  Output semua   : *_semua.json & *_semua.csv")
    print("="*65)

    if not filtered and all_listings:
        print("\n[?] Filter terlalu ketat? Cek kolom 'lokasi' di file _semua.json")


if __name__ == "__main__":
    asyncio.run(main())
