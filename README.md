# 🛒 Facebook Marketplace Scraper — Subulussalam, Aceh

Script Python untuk mengambil data listing dari Facebook Marketplace
khusus kota **Subulussalam, Aceh** menggunakan Playwright.

---

## 📦 Instalasi

```bash
pip install playwright
playwright install chromium
```

---

## 🚀 Cara Pakai

```bash
python fb_marketplace_scraper.py
```

1. Browser akan terbuka otomatis
2. Login ke akun Facebook Anda secara manual
3. Tekan **ENTER** di terminal setelah login berhasil
4. Script akan scrape listing & simpan hasilnya

> Setelah login pertama, cookies disimpan di `fb_cookies.json`.
> Jalankan selanjutnya tidak perlu login ulang (selama cookies belum kadaluarsa).

---

## ⚙️ Konfigurasi (di dalam script)

| Parameter | Default | Keterangan |
|---|---|---|
| `category` | `""` | Kategori: `vehicles`, `electronics`, dll (kosong = semua) |
| `max_scrolls` | `10` | Jumlah scroll untuk muat listing |
| `headless` | `False` | `True` = tanpa tampilkan browser |
| `output_json` | `marketplace_subulussalam.json` | File output JSON |
| `output_csv` | `marketplace_subulussalam.csv` | File output CSV |

---

## 📁 Output

- **JSON**: `marketplace_subulussalam.json`
- **CSV**: `marketplace_subulussalam.csv`

Setiap listing mengandung:
- `id` — ID unik listing
- `judul` — Nama produk
- `harga` — Harga listing
- `lokasi` — Lokasi penjual
- `url` — Link langsung ke listing
- `gambar` — URL thumbnail gambar
- `scraped_at` — Waktu scraping

---

## ⚠️ Catatan Penting

- Gunakan akun Facebook yang aktif dan tidak melanggar ToS
- Jangan scrape terlalu sering untuk menghindari pemblokiran
- Facebook sering mengubah struktur DOM-nya — selector mungkin perlu disesuaikan
- Script ini hanya untuk keperluan riset/edukasi pribadi
