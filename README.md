# Home Print

Print to your network printer from the Home Assistant dashboard, from anywhere you can reach your Home Assistant.

> **Status: early.** The integration and card are tested in code and against a real HP DeskJet 4670's responses, but not yet used day to day. Expect rough edges and please open an issue when something breaks.

[Türkçe açıklama aşağıda](#türkçe)

## What it does

- **Finds your printer** on the network (IPP / AirPrint), or you add it by IP.
- **Sensors** for printer status, ink/toner levels and problems (paper out, jam, cover open), plus the last job.
- **Prints PDF, JPEG and PNG.** If the printer doesn't take a format directly, Home Print converts it to PWG Raster, Apple Raster (URF) or JPEG first. Duplex, copies, colour/mono and page ranges are supported where the printer supports them. Large phone photos are shrunk automatically (JPEG up to 175 MP, PNG up to 50 MP).
- **Dashboard card** to pick a file or photo on your phone, choose options and follow the job until it's done.
- **`home_print.print_file` action** for automations.
- **Scans** with the printer's scanner (eSCL / AirScan): a **Scan** button on the card, an archive in the Media panel and a `home_print.scan` action. See [Scanning](#scanning).

Not yet: Word/ODF files (save as PDF first), very old or USB-only printers (a helper add-on with CUPS is planned).

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

The clock icon in the card's header opens the print history, where you can delete an entry or tap it to scroll through a preview of the kept file; **Choose file** opens the iPhone/iPad system sheet, or on other devices a small menu (from files, photo library, take photo).

## Options

Per printer (**Configure**): default duplex and colour mode, maximum file size (default 25 MB), polling interval, "only admins can print", and **Keep files (days)** (default 7, 0–90; 0 keeps no files, only the history entries).

**Privacy:** the original of every printed file is kept for that many days under `<config>/home_print/<entry_id>/`, so the history can show a preview. These files are included in Home Assistant backups, and deleting an entry from the history doesn't remove it from backups already taken. Any logged-in Home Assistant user can see the history list and the previews: "only admins can print" limits printing and deleting, not viewing. Set **Keep files (days)** to 0 to keep no files.

## Scanning

If your printer has a scanner, Home Print finds it on the printer's own address (eSCL, also known as AirScan). Nothing extra to set up.

- **Card:** the **Scan** button sits under **Print**. It opens the scan panel: pick glass or document feeder (single or double-sided), colour mode, resolution and PDF or JPEG, then start. While it runs, **Cancel** stops it. When it's done you can preview, download, rename or delete the scan, or add another page to it. The scanner status sensor shows idle, scanning, paper in the feeder or stopped.
- **History:** the clock icon in the card header opens a window with two tabs, **Prints** and **Scans**.
- **Where files go:** every scan is saved as `home_print/scans/YYYY-MM/<name>.pdf` (or `.jpg`) in the default media root (`/media` on Home Assistant OS) and shows up in Home Assistant's **Media** panel. The scan covers the whole glass; there is no paper size picker yet.
- **Options** (per printer, **Configure**):
  - **Scanner address:** leave empty to find it automatically, or enter an address like `http://192.168.1.20/eSCL` if the scanner isn't found (`http://` and `/eSCL` are added when left out). If no scanner answers at start-up (printer asleep), Home Print looks again after 1, 5 and 30 minutes, then hourly for a day (forever if you typed an address). Reloading the integration starts the search over.
  - **Keep scans (days):** default 30, 0 keeps them forever.
  - **Max space for scans (MB):** default 2000, 0 means no limit. When it's exceeded, the oldest scans are deleted.
- **HTTPS certificate:** if the printer was added over plain IPP, the scanner's https address (HP printers use a self-signed certificate) is used without checking its certificate; for printers added over IPPS the **verify SSL** setting applies.
- **Sensor:** `Scanner status` on the printer's device.
- **Action** for automations:

```yaml
action: home_print.scan
data:
  config_entry_id: <printer entry id>
  source: platen        # platen | adf | adf_duplex
  color_mode: gray      # color | gray | bw
  resolution: 300
  format: pdf           # pdf | jpeg
  file_name: invoice    # optional, date and time if empty
  folder: /media/documents   # optional extra copy; must be a folder HA may write to
response_variable: scan
# scan.path, scan.copy, scan.name, scan.pages
```

Not yet: scanner-only devices without a printer entry, SANE for old USB scanners and OCR (searchable PDF) come with the Home Print Server in a later release.

**Privacy:** scans are visible to every logged-in Home Assistant user (list, preview and download). "Only admins can print" limits starting, renaming and deleting scans, not viewing them. The files live in your media folder, so they are included in Home Assistant backups if you back up media, and deleting a scan doesn't remove it from backups already taken. Removing the printer entry deletes the archive records but leaves the files in the media folder alone. Set **Keep scans (days)** low if you scan sensitive documents.

## Contributing

This started as a small weekend project to print at home from a phone, and it would be great to see it grow. If you have a printer that behaves differently, an idea for a feature, or a fix (big or tiny), please open an issue or send a pull request. You don't need to ask first. Typos, translations and "this didn't work on my printer" reports are just as welcome as code.

If you're adding a feature, a short note in the PR about what you tested on (printer model, HA version) helps a lot. The test commands are below.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest -q          # Python tests
npm install && npm test      # card tests
```

`scripts/remote_check.py` checks a printer over the network without printing (and with `--print`, runs at most two small test jobs). `--scan-info` finds the scanner and prints what it can do without using paper, and `--scan` also makes one 75 dpi grayscale test scan from the glass (`scan_test.jpg`) and prints the scanner's raw answers (status codes, `Location` header). Run it from the repo folder. The saved `escl_*.xml` files contain device identifiers (serial number, UUID); don't post them publicly.

---

## Türkçe

Home Assistant ana sayfasından, Home Assistant'a ulaşabildiğin her yerden ağ yazıcına yazdırmanı sağlar.

> **Durum: erken sürüm.** Kod testlerden ve gerçek bir HP DeskJet 4670'in yanıtlarıyla yapılan denemelerden geçti, ama henüz günlük kullanımda denenmedi.

- Yazıcıyı ağda kendisi bulur ya da IP ile eklersin.
- Durum, mürekkep seviyesi ve sorun (kâğıt bitti, sıkıştı, kapak açık) sensörleri.
- PDF, JPEG ve PNG yazdırır. Yazıcı bir formatı doğrudan almıyorsa önce çevirir. Çift taraf, kopya, renkli/siyah-beyaz ve sayfa aralığı desteklenir. Telefonla çekilmiş büyük fotoğraflar otomatik küçültülür (JPEG 175 MP'ye, PNG 50 MP'ye kadar).
- Telefondan dosya ya da fotoğraf seçip yazdırdığın, işin bitişini takip ettiğin bir kart.
- Yazıcının tarayıcısıyla tarama (eSCL / AirScan): kartta **Tara** düğmesi, Medya bölümünde arşiv ve `home_print.scan` servisi. Ayrıntı aşağıda, [Tarama](#tarama).

**Kurulum:** HACS → üç nokta → **Custom repositories** → `https://github.com/ada-kilinc/home-print` (Integration) → **Home Print**'i indir, HA'yı yeniden başlat. Sonra **Ayarlar → Cihazlar ve Hizmetler**'den yazıcıyı ekle ve ana sayfaya **Home Print** kartını koy.

**Ayarlar:** Her yazıcının **Yapılandır** ekranında varsayılan çift taraf ve renk, en büyük dosya boyutu, yoklama aralığı, "yalnızca yöneticiler yazdırabilir" ve **Dosyaları sakla (gün)** var. Sonuncusu varsayılan olarak 7 gün, 0 ile 90 arası olabilir. 0 seçersen dosya saklanmaz, yalnızca geçmiş kaydı tutulur.

**Gizlilik:** Ön izleme gösterebilmek için yazdırılan her dosyanın aslı bu süre boyunca `<config>/home_print/<entry_id>/` altında durur. Bu dosyalar Home Assistant yedeklerine de girer. Geçmişten sildiğin bir kayıt, önceden alınmış yedeklerde kalır. Geçmiş listesini ve ön izlemeleri Home Assistant'a giriş yapan herkes görebilir. "Yalnızca yöneticiler yazdırabilir" seçeneği görmeyi değil, yazdırmayı ve silmeyi kısıtlar. Hiç dosya saklanmasın istiyorsan **Dosyaları sakla (gün)** değerini 0 yap.

Word dosyalarını şimdilik önce PDF olarak kaydetmen gerekiyor.

### Tarama

Yazıcının tarayıcısı varsa Home Print onu yazıcının kendi adresinde bulur (eSCL, diğer adıyla AirScan). Ayrıca kurulum gerekmez.

- **Kart:** **Tara** düğmesi **Yazdır**'ın altında. Basınca tarama paneli açılır: cam ya da belge besleyici (tek veya çift yüzlü), renk, çözünürlük ve PDF/JPEG seçip başlatırsın. Sürerken **İptal** ile durdurabilirsin. Bitince taramayı görüntüleyebilir, indirebilir, adını değiştirebilir, silebilir ya da ona sayfa ekleyebilirsin. Tarayıcı durumu sensörü boşta, taranıyor, besleyicide kâğıt var ve durdu durumlarını gösterir.
- **Geçmiş:** Kartın başlığındaki saat simgesi **Baskılar** ve **Taramalar** diye iki sekmeli bir pencere açar.
- **Dosyalar nerede:** Her tarama varsayılan medya klasöründe (Home Assistant OS'ta `/media`) `home_print/scans/YYYY-MM/<ad>.pdf` (ya da `.jpg`) olarak kaydolur ve Home Assistant'ın **Medya** bölümünde görünür. Tarama camın tamamını kapsar, kâğıt boyutu seçimi henüz yok.
- **Ayarlar** (her yazıcının **Yapılandır** ekranında):
  - **Tarayıcı adresi:** boş bırakırsan otomatik bulunur, bulunamazsa `http://192.168.1.20/eSCL` gibi elle yaz (`http://` ve `/eSCL` yazmazsan eklenir). Açılışta tarayıcı yanıt vermezse (yazıcı uykudaysa) Home Print 1, 5 ve 30 dakika sonra, ardından bir gün boyunca saatte bir yeniden bakar (adresi elle yazdıysan aramayı hiç bırakmaz). Entegrasyonu yeniden yüklersen arama baştan başlar.
  - **Taramaları sakla (gün):** varsayılan 30, 0 hiç silme demek.
  - **Taramalar için en fazla alan (MB):** varsayılan 2000, 0 sınırsız demek. Aşılırsa en eski taramalar silinir.
- **HTTPS sertifikası:** Yazıcı düz IPP ile eklendiyse tarayıcının https adresi (HP yazıcılar kendinden imzalı sertifika kullanır) sertifikası kontrol edilmeden kullanılır. IPPS ile eklenen yazıcılarda **SSL doğrula** ayarı geçerlidir.
- **Sensör:** Yazıcı cihazında `Tarayıcı durumu`.
- **Servis** (otomasyonlar için):

```yaml
action: home_print.scan
data:
  config_entry_id: <yazıcı girişi>
  source: platen        # platen | adf | adf_duplex
  color_mode: gray      # color | gray | bw
  resolution: 300
  format: pdf           # pdf | jpeg
  file_name: fatura     # isteğe bağlı, boşsa tarih ve saat
  folder: /media/belgeler   # isteğe bağlı ek kopya; HA'nın yazabildiği bir klasör olmalı
response_variable: tarama
# tarama.path, tarama.copy, tarama.name, tarama.pages
```

Henüz yok: yazıcı girişi olmayan, yalnızca tarayıcı olan cihazlar, eski USB tarayıcılar için SANE ve OCR (aranabilir PDF). Bunlar sonraki sürümde Home Print Server ile gelecek.

**Tarama gizliliği:** Taramaları (liste, ön izleme, indirme) Home Assistant'a giriş yapan herkes görebilir. "Yalnızca yöneticiler yazdırabilir" seçeneği taramayı başlatmayı, adını değiştirmeyi ve silmeyi kısıtlar, görmeyi kısıtlamaz. Dosyalar medya klasöründe durur, medyayı yedekliyorsan Home Assistant yedeklerine de girer. Sildiğin tarama önceden alınmış yedeklerde kalır. Yazıcı girişini silersen arşiv kayıtları gider ama medya klasöründeki dosyalara dokunulmaz. Hassas belge tarıyorsan **Taramaları sakla (gün)** değerini düşük tut.

Uzaktan kontrol scripti `scripts/remote_check.py` ile `--scan-info` tarayıcıyı bulup yeteneklerini yazdırır (kâğıt harcamaz), `--scan` ise camdan 75 dpi gri tek sayfa deneme taraması yapıp `scan_test.jpg` kaydeder ve tarayıcının ham yanıtlarını (durum kodları, `Location` başlığı) yazdırır. Repo klasöründen çalıştır. Kaydedilen `escl_*.xml` dosyaları cihaz kimlikleri (seri no, UUID) içerir, herkese açık yerde paylaşma.

### Katkı

Bu proje evdeki yazıcıya telefondan yazdırmak için küçük bir hafta sonu işi olarak başladı. Büyüdüğünü görmek beni çok mutlu eder. Yazıcın farklı davranıyorsa, aklında bir özellik varsa ya da büyük küçük bir düzeltme yaptıysan issue açmaktan ya da pull request göndermekten çekinme. Önceden sormana gerek yok. Yazım hatası, çeviri ya da "benim yazıcımda çalışmadı" bildirimi de kod kadar değerli.
