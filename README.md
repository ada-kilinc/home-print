# Home Print

Print to your network printer from the Home Assistant dashboard, from anywhere you can reach your Home Assistant.

> **Status: early.** The integration and card are tested in code and against a real HP DeskJet 4670's responses, but not yet used day to day. Expect rough edges and please open an issue when something breaks.

[Türkçe açıklama aşağıda](#türkçe)

## What it does

- **Finds your printer** on the network (IPP / AirPrint), or you add it by IP.
- **Sensors** for printer status, ink/toner levels and problems (paper out, jam, cover open), plus the last job.
- **Prints PDF, JPEG and PNG.** If the printer doesn't take a format directly, Home Print converts it to PWG Raster, Apple Raster (URF) or JPEG first. Duplex, copies, colour/mono and page ranges are supported where the printer supports them.
- **Dashboard card** to pick a file or photo on your phone, choose options and follow the job until it's done.
- **`home_print.print_file` action** for automations.

Not yet: scanning, Word/ODF files (save as PDF first), very old or USB-only printers (a helper add-on with CUPS is planned).

## Install

1. In HACS, open the three-dot menu → **Custom repositories**, add `https://github.com/ada-kilinc/home-print` as an **Integration**, then download **Home Print** and restart Home Assistant.
2. **Settings → Devices & services**: your printer should show up as discovered. If not, **Add integration → Home Print** and enter the printer's IP address.
3. On a dashboard: **Edit → Add card → Home Print**. The card loads by itself; no resource setup needed.

Home Print works on every installation type (OS, Supervised, Container, Core). Nothing is exposed to the internet: printing goes through Home Assistant's own login, so remote use works with whatever remote access you already have (Tailscale, Nabu Casa, ...).

## Card

```yaml
type: custom:home-print-card
# all optional:
entry_id: <printer>   # the visual editor fills this in; default is the first printer
title: Printer
show_ink: true
```

## Options

Per printer (**Configure**): default duplex and colour mode, maximum file size (default 25 MB), polling interval, and "only admins can print".

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest -q          # Python tests
npm install && npm test      # card tests
```

`scripts/remote_check.py` checks a printer over the network without printing (and with `--print`, runs at most two small test jobs).

---

## Türkçe

Home Assistant ana sayfasından, Home Assistant'a ulaşabildiğin her yerden ağ yazıcına yazdırmanı sağlar.

> **Durum: erken sürüm.** Kod testlerden ve gerçek bir HP DeskJet 4670'in yanıtlarıyla yapılan denemelerden geçti, ama henüz günlük kullanımda denenmedi.

- Yazıcıyı ağda kendisi bulur ya da IP ile eklersin.
- Durum, mürekkep seviyesi ve sorun (kâğıt bitti, sıkıştı, kapak açık) sensörleri.
- PDF, JPEG ve PNG yazdırır. Yazıcı bir formatı doğrudan almıyorsa önce çevirir. Çift taraf, kopya, renkli/siyah-beyaz ve sayfa aralığı desteklenir.
- Telefondan dosya ya da fotoğraf seçip yazdırdığın, işin bitişini takip ettiğin bir kart.

**Kurulum:** HACS → üç nokta → **Custom repositories** → `https://github.com/ada-kilinc/home-print` (Integration) → **Home Print**'i indir, HA'yı yeniden başlat. Sonra **Ayarlar → Cihazlar ve Hizmetler**'den yazıcıyı ekle ve ana sayfaya **Home Print** kartını koy.

Word dosyalarını şimdilik önce PDF olarak kaydetmen gerekiyor. Tarama özelliği sonraki sürümde gelecek.
