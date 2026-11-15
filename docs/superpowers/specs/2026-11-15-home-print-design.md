# Home Print — Tasarım Belgesi

Tarih: 2026-11-15 · Durum: onaylandı (Ada, 2026-11-15)
Ad: **Home Print** (domain: `home_print`). Ada seçti. Yayından önce GitHub/HACS'ta çakışma kontrolü yapılacak.

## 1. Amaç ve neden

Ada evden uzaktayken (yurt dışında, okulda) telefondan evdeki ağ yazıcısına (HP DeskJet, model belli değil) dosya gönderip yazdırmak istiyor. Babası da ara sıra aynı şekilde gönderiyor. Evde Home Assistant çalışıyor ve uzaktan erişim zaten Tailscale ile var, yani dışarıya port açmaya gerek yok.

Bu ihtiyacı herkesin kurabileceği açık kaynaklı bir projeye dönüştürüyoruz. Kod GitHub'da tek bir depoda duracak. Teknik bilgisi az olan bir kullanıcı da birkaç tıklamayla kurabilmeli.

Kullanıcı açısından sonuç şöyle: HA ana sayfasındaki bir karttan dosya seçilir, kopya / çift taraf / renk / sayfa aralığı ayarlanır ve "Yazdır"a basılır. Aynı kartta yazıcının durumu ve mürekkep seviyeleri de görünür.

## 2. Hedefler

- Telefondan, HA arayüzü içinden PDF ve fotoğraf (JPG/PNG) yazdırmak.
- Ayarlar → Cihazlar ve Hizmetler'den yazıcı eklemek: ağdaki yazıcılar otomatik bulunur, istenirse IP/URL ile elle eklenir.
- Her cihaz için sensörler: durum (boşta / yazdırıyor / hata), mürekkep/toner seviyeleri, uyarılar (kağıt yok, kapak açık gibi).
- Otomasyonlardan kullanılabilen bir servis: `home_print.print_file`.
- Eski ya da sürücü isteyen yazıcılar, eski/USB tarayıcılar (SANE) ve OCR için isteğe bağlı bir yardımcı sunucu (Home Print Server).
- **Tarama** (Ada ekledi): karttan tarama başlatmak, taranan belgenin ön izlemesini görmek ve dosyayı indirmek (telefona ya da bilgisayara). Ayrıntılar 7.5'te.
- Tek GitHub deposu. README'de tek tıkla kurulum düğmeleri ("My Home Assistant" bağlantıları).

## 3. Hedef dışı (ilk sürümde yok)

- Word/Excel gibi ofis belgelerini dönüştürmek. İlk sürümde yalnızca PDF ve görsel var.
- Kotalar, sayfa başı ücret, kullanıcı başına yazıcı izinleri.
- Yazdırma sayfasını HA dışında internete açmak (Funnel, port açma). Uzaktan erişim kullanıcının mevcut yöntemiyle sağlanır (Tailscale, Nabu Casa vb.).

## 4. Başarısız sayılacak durumlar

- Yazdırma sayfasının ya da yazıcının HA girişi olmadan erişilebilir hale gelmesi.
- Kurulumun terminal, YAML veya elle dosya kopyalama gerektirmesi.
- Yüklenen dosyaların diskte birikmesi (yazdırıldıktan sonra silinmeli).
- HA'nın kendi IPP entegrasyonuyla çakışıp aynı yazıcıyı iki kez, kafa karıştıracak şekilde göstermek. Belgelenmeli ve keşif akışında yönetilmeli (bkz. 9).

## 5. Kısıtlar

- HA'nın bütün kurulum tiplerinde (OS, Supervised, Container, Core) çalışmalı. Eklentiler (Supervisor) sadece OS ve Supervised'da var, o yüzden çekirdek parça bir **entegrasyon** olmalı. Yardımcı sunucu (Home Print Server) isteğe bağlı kalmalı.
- Ağ yazıcıları doğrudan IPP ile kullanılmalı. Modern ağ yazıcılarının çoğu PDF/JPEG'i doğrudan alıyor (IPP Everywhere / AirPrint).
- Dosya yükleme HA'nın kendi kimlik doğrulamasından geçmeli. Ayrı bir şifre sistemi kurulmayacak.
- Hem HACS hem HA eklenti mağazası aynı depodan okuyabilmeli (bkz. 7).

## 6. Değerlendirilen yaklaşımlar

| Yaklaşım | Artı | Eksi | Karar |
|---|---|---|---|
| A. HA dışında bağımsız web sayfası + Tailscale Funnel | HA'ya bağımlı değil, babanın Tailscale kurmasına gerek yok | Ayrı şifre sistemi lazım, internete açık bir yüzey var, HA ile bütünleşmiyor | Reddedildi |
| B. HA Tailscale eklentisinin Funnel'ı | Kurulumu kolay | HA'nın tamamını internete açıyor | Reddedildi |
| C. Entegrasyon + kart, doğrudan IPP; CUPS eklentisi isteğe bağlı | Her HA kurulumunda çalışır, HA girişini kullanır, dışarıya bir şey açılmaz | Çok eski yazıcılar CUPS eklentisi ister | **Seçildi** |
| D. Entegrasyon + zorunlu CUPS eklentisi | Neredeyse her yazıcı çalışır | Container/Core kurulumlarında çalışmaz, kurulum iki parça olur | Reddedildi |

Ada iki parçanın (entegrasyon ve yardımcı sunucu) birlikte geliştirilip tek depoda yayınlanmasını istedi. Amaç teknik bilgisi az olan kullanıcıların da kurabilmesi.

## 7. Yapı

### 7.1 Depo düzeni (tek depo)

```
home-print/
├── custom_components/home_print/   # HACS entegrasyonu (Python)
│   ├── __init__.py, manifest.json, config_flow.py, sensor.py, binary_sensor.py,
│   ├── services.yaml, http.py (yükleme ucu), coordinator.py
│   ├── translations/ (tr, en)
│   └── frontend/home-print-card.js   # entegrasyonla birlikte gelen kart
├── server/                        # isteğe bağlı HA eklentisi + bağımsız Docker imajı (CUPS, SANE, OCR)
│   ├── config.yaml, Dockerfile, run.sh, DOCS.md
├── repository.yaml                # HA eklenti mağazası için
├── hacs.json
├── docs/
└── README.md (tr + en)
```

Bu iki yapının aynı depoda sorunsuz durabildiği uygulamada doğrulanacak. HACS'ın entegrasyon dosyalarını yalnızca `custom_components/<ad>/` altında aramasını bekliyoruz. Olmazsa yedek plan iki ayrı depo açıp README'yi tek tutmak.

### 7.2 Entegrasyon (`home_print`)

**Yazıcı ekleme (config flow)**
- Zeroconf ile otomatik keşif: `_ipp._tcp`, `_ipps._tcp`. Bulunan yazıcı "Keşfedildi" olarak görünür, kullanıcı tek tıkla ekler.
- Elle ekleme: IP veya ana makine adı, port (varsayılan 631), yol (varsayılan `/ipp/print`), TLS açık/kapalı. Ekleme sırasında Get-Printer-Attributes ile bağlantı test edilir.
- CUPS kuyrukları da IPP yazıcısı olarak görünür. Ayrı bir kod yolu olmaz. `ipp://<cups>:631/printers/<kuyruk>`.
- Ayarlar (options flow): varsayılan çift taraf / renk, en fazla dosya boyutu (varsayılan 25 MB), yazıcı durumunun ne sıklıkla kontrol edileceği.

**Yazıcı yetenekleri**
Yazıcıdan alınır (`document-format-supported`, `sides-supported`, `print-color-mode-supported`, `copies-supported`, `page-ranges-supported`). Kart yalnızca yazıcının desteklediği seçenekleri gösterir. Desteklenmeyen bir dosya türü gelirse açık bir hata verilir.

**Varlıklar (entity)**
- `sensor.<yazıcı>_durum`: boşta / yazdırıyor / durdu, özellik olarak durum nedenleri.
- `sensor.<yazıcı>_<renk>_mürekkep`: her sarf malzemesi için yüzde (`marker-levels`).
- `binary_sensor.<yazıcı>_sorun`: kağıt yok, sıkışma, kapak açık gibi durumlar.
- `sensor.<yazıcı>_son_iş`: son işin adı, durumu, kimin gönderdiği.

**Servis: `home_print.print_file`**
Alanlar: hedef yazıcı, dosya (HA medya yolu ya da `/config` altındaki bir yol), kopya, çift taraf, renk modu, sayfa aralığı. Otomasyonlarda da kullanılabilir.

**Yükleme ucu**
`POST /api/home_print/upload/<entry_id>`, HA'nın oturum belirtecini ister (`requires_auth=True`). Dosya ve seçenekler birlikte gelir. Ucun yaptıkları sırasıyla:
1. Boyutu ve türü kontrol eder (içerikten, sadece uzantıdan değil).
2. Dosyayı geçici bir klasöre yazar.
3. IPP Print-Job ile gönderir. Gönderen kullanıcının HA adı `requesting-user-name` olarak eklenir.
4. Geçici dosyayı siler.
5. İş numarasını ve durumu döndürür.

Ayrıca bir olay tetiklenir: `home_print_job` (kim, hangi dosya, sonuç). Kayıt ve otomasyonlar bunu kullanabilir.

**IPP kütüphanesi:** `pyipp`. HA'nın kendi IPP entegrasyonu da bunu kullanıyor ve `execute(IppOperation.PRINT_JOB, …)` ile iş gönderebiliyor. Yetersiz kalırsa `ippx`'e geçilir.

### 7.3 Kart (`home-print-card`)

- Entegrasyonla birlikte gelir. Entegrasyon JS dosyasını yayınlar ve dashboard kaynağı olarak kendisi kaydeder, kullanıcı elle kaynak eklemez.
- Kart düzenleyicide görsel ayarlar: hangi yazıcı, hangi seçenekler görünsün, başlık.
- Görünüm (telefon öncelikli, büyük dokunma alanları):

```
🖨 DeskJet — Hazır
Siyah ████░ 70%   Renkli ██░░░ 40%
[  Dosya seç  ]  rapor.pdf (3 sayfa)
Kopya [1]   Çift taraf [✓]   Renkli [ ]
Sayfalar [hepsi]
[         YAZDIR         ]
Son: rapor.pdf ✓ 16:52 — Ada
```

- Telefonda dosya seçici galeriyi ve dosyaları açar.
- Yazdırma bitene kadar ilerleme gösterir (gönderildi → yazdırılıyor → tamamlandı / hata).
- Arayüz metinleri Türkçe ve İngilizce. HA'nın dili hangisiyse o kullanılır.

### 7.4 İsteğe bağlı yardımcı sunucu: Home Print Server (`server/`)

HA eklentisi olarak gelir, bağımsız bir Docker imajı olarak da çalışır. İçinde CUPS, SANE köprüsü ve OCR ucu var.


- CUPS + `cups-filters` (PDF/görsel dönüştürme) + HPLIP (HP yazıcılar) + Gutenprint (genel sürücüler).
- Yazıcıların eklendiği CUPS web arayüzü HA yan menüsünde (Ingress) açılır.
- Kuyruklarını mDNS ile yayınlar, böylece entegrasyon onları kendiliğinden bulur.
- Ayarlar ve kuyruklar kalıcı klasörde tutulur ve HA yedeklerine dahil olur.
- USB yazıcı desteği (cihaz geçirme), çünkü bazı kullanıcılar yazıcıyı doğrudan HA kutusuna takıyor.
- Hedef mimariler: amd64 ve aarch64.

### 7.5 Tarama

**Protokol: eSCL (AirScan).** Ağa bağlı çok işlevli yazıcıların çoğu (HP DeskJet/ENVY/OfficeJet dahil) bunu destekliyor. HTTP ve XML üzerinden çalıştığı için saf Python ile yazılır, her HA kurulumunda çalışır, sürücü gerekmez.

- Keşif: `_uscan._tcp` ve `_uscans._tcp`. Aynı cihazın yazıcı ve tarayıcı tarafı tek bir HA cihazı altında birleşir (eşleştirme UUID'ye, olmazsa ana makine adına göre yapılır). Sadece tarayıcı olan cihazlar da eklenebilir.
- Elle eklemede tarayıcı adresi (`http(s)://<ip>/eSCL`) isteğe bağlı bir alan olarak sorulur. Boş bırakılırsa yazıcının adresinde denenir.
- Yetenekler `ScannerCapabilities`'ten okunur: kaynak (cam / ADF / çift taraflı ADF), renk modu, çözünürlük, en büyük alan, desteklenen formatlar. Kart yalnızca desteklenenleri gösterir.
- Akış: tarama işi oluşturulur (`ScanJobs`) → sayfalar `NextDocument` ile alınır → ADF'de sayfa kalmayana kadar devam edilir → iş kapatılır.
- Çıktı: tek sayfa JPEG/PNG ya da çok sayfalı PDF. Tarayıcı PDF vermiyorsa sayfalar entegrasyonda PDF'e birleştirilir.
- Sensör: `sensor.<cihaz>_tarayıcı_durumu` (boşta / tarıyor / ADF'de kağıt var).
- Servis: `home_print.scan` (kaynak, renk, çözünürlük, format, hedef klasör). Böylece otomasyonlar da tarama yapabilir, örneğin bir düğmeye basınca tarayıp kaydetmek gibi.

**Kartta tarama**

Kartta "Yazdır" ve "Tara" diye iki sekme olur:

```
[ Yazdır ] [ Tara ]
Kaynak [Cam ▾]  Renk [Renkli ▾]  Çözünürlük [300 dpi ▾]
Format [PDF ▾]
[          TARA          ]
┌──────────────┐
│  ön izleme   │  Sayfa 1/2  ‹ ›
└──────────────┘
[ İndir ]  [ Sayfa ekle ]  [ Sil ]
```

- Tarama bitince ilk sayfa ön izlemede görünür, çok sayfalılarda sayfalar arasında geçiş yapılır.
- "Sayfa ekle" camdan bir sayfa daha tarayıp aynı belgeye ekler.
- "İndir" dosyayı tarayıcının indirme özelliğiyle verir. Bilgisayarda Downloads klasörüne, telefonda dosyalara/paylaş menüsüne gider.
- İndirme ve ön izleme kimlik doğrulamalı bir uçtan gelir: `GET /api/home_print/scan/<id>`.

**Saklama (Ada): HA'da arşivlenir.**
- Taramalar HA'nın Medya klasörüne kaydedilir (`/media/home_print/scans/YYYY-MM/`), böylece HA'nın Medya bölümünden de açılabilir.
- Kartta "Son taramalar" listesi olur. Her satırda ad, tarih, kimin taradığı, sayfa sayısı ve İndir / Ön izle / Sil düğmeleri bulunur.
- Silme süresi ayarlardan değişir (varsayılan 30 gün, "hiç silme" de seçilebilir). İsteğe bağlı bir toplam boyut sınırı da konur, aşılırsa en eskiler silinir.
- Dosya adı varsayılan olarak `tarama_2026-11-15_1652.pdf` biçiminde olur, kartta değiştirilebilir.

**SANE ve OCR ilk sürümde var (Ada).** İkisi de yerel (native) programlara dayanıyor: SANE sürücüleri, Tesseract. HA'nın Python ortamına pip ile kurulamıyorlar. Benim kararım bunları **yardımcı sunucuda** çalıştırmak (bkz. 7.4, artık "Home Print Server"):
- **SANE:** Sunucu SANE ile gördüğü tarayıcıları (USB veya eski ağ tarayıcıları) eSCL olarak ağa yayınlar (AirSane benzeri bir köprü). Entegrasyon bunları sıradan eSCL tarayıcısı gibi bulur. Böylece entegrasyonda tek bir tarama kod yolu kalır.
- **OCR:** Sunucu `ocrmypdf` + Tesseract ile çalışan küçük bir yerel HTTP ucu sunar. Varsayılan diller Türkçe ve İngilizce, diğer diller ayarlardan eklenir. Entegrasyon sunucuyu bulursa kartta "Aranabilir PDF (OCR)" seçeneği görünür. Sunucu yoksa seçenek gizlenir.
- Docker/Core kullanıcıları için aynı sunucu imajı tek bir `docker run` komutuyla bağımsız çalıştırılabilir. README'de buna bir bölüm ayrılır.

## 8. Güvenlik

- Dosya yükleme ve servis yalnızca HA'da oturum açmış kullanıcılar içindir. İsteğe bağlı olarak "sadece yöneticiler yazdırabilir" ayarı.
- Dosya boyutu sınırı, izin verilen türler listesi, dosya türü içerikten kontrol edilir.
- Geçici dosyalar iş bittiğinde ya da hata olduğunda silinir. Açılışta eski artıklar temizlenir.
- Yazıcıya TLS (`ipps`) varsa o tercih edilir. Kendinden imzalı sertifikalara izin verilip verilmeyeceği yazıcı bazında bir ayardır.
- Sunucunun yönetim arayüzü yalnızca Ingress üzerinden açılır. OCR ucu ve eSCL köprüsü yalnızca yerel ağı dinler, OCR ucu entegrasyonla paylaşılan bir anahtar ister.
- Arşivdeki taramalar yalnızca HA'da oturum açmış kullanıcılara servis edilir. Medya klasörü HA'nın kendi izinlerine tabidir.

## 9. HA'nın kendi IPP entegrasyonuyla ilişki

HA'nın yerleşik IPP entegrasyonu aynı yazıcıları keşfeder ve mürekkep sensörleri oluşturur. Ada'nın isteği mürekkep seviyelerinin bu tek entegrasyonda toplanması. Bu yüzden Home Print kendi sensörlerini oluşturur. README'de kullanıcıya yerleşik IPP entegrasyonunu kaldırabileceği ya da yazıcıyı orada yok sayabileceği anlatılır. Bir yazıcı zaten Home Print'te ekliyse keşif akışı onu tekrar önermez.

## 10. Kurulum deneyimi (teknik olmayan kullanıcı için)

README'de sırasıyla:
1. "HACS'a ekle" düğmesi → İndir → HA'yı yeniden başlat.
2. "Entegrasyonu ekle" düğmesi → keşfedilen yazıcıyı seç.
3. Ana sayfaya "Home Print Kartı" ekle.
4. (Yazıcı/tarayıcı tanınmazsa ya da OCR isteniyorsa) "Eklenti deposunu ekle" düğmesi → Home Print Server'ı kur → yan menüden cihazı ekle → 2. adıma dön.

Her adım için ekran görüntüsü, Türkçe ve İngilizce.

## 11. Test

- Birim testleri: `pytest-homeassistant-custom-component` ile config flow, yükleme ucu (yetkisiz istek, büyük dosya, yanlış tür) ve servis.
- IPP tarafı sahte bir yazıcıyla test edilir (CUPS'ın `ippeveprinter`'ı ya da kayıtlı yanıtlar).
- eSCL tarafı kayıtlı tarayıcı yanıtlarıyla test edilir. Gerçek tarama da Ada'nın DeskJet'iyle denenir (cihazda tarayıcı varsa).
- Gerçek test: Ada'nın evindeki DeskJet ile hem doğrudan IPP hem Home Print Server üzerinden; tarama ve OCR da denenir.
- CI: HACS doğrulaması, hassfest, eklenti için derleme.

## 12. Ada'nın yazıcısı ve isim

- Yazıcı ağa bağlı (USB değil). Modeli bilinmiyor. Planın ilk adımı yazıcıdan Get-Printer-Attributes ve (varsa) eSCL ScannerCapabilities dökümü almak: model, `document-format-supported`, `sides-supported`, `page-ranges-supported`. Yazıcı sadece raster (URF / PWG) kabul ediyorsa 13. bölümdeki karar Ada için de önem kazanır.
- Ad **Home Print / `home_print`** (Ada seçti). Yayından önce çakışma kontrolü yapılır. Domain; varlık adlarına, servise, olaya ve README bağlantılarına işlendiği için yayından sonra değiştirilmez.

## 13. Yazıcı dosyayı kabul etmezse: dönüştürme

**Karar (Ada): entegrasyon dosyayı kendisi dönüştürür.** Böylece her HA kurulum tipinde, raster isteyen yazıcılar da CUPS olmadan çalışır.

- Gönderimden önce yazıcının `document-format-supported` listesine bakılır. PDF/JPEG destekleniyorsa dosya olduğu gibi gider.
- Desteklenmiyorsa PDF sayfaları, yazıcının bildirdiği çözünürlükte (`pwg-raster-document-resolution-supported` / `urf-supported`) görüntüye çevrilir. Görüntüler PWG Raster (`image/pwg-raster`) ya da Apple Raster (`image/urf`) olarak kodlanır.
- Fotoğraflar sayfaya sığdırılır ve döndürülür. Kenar boşlukları yazıcının bildirdiği değerlere göre ayarlanır.
- Yazıcı sayfa aralığını desteklemiyorsa sayfalar entegrasyon tarafında seçilir. Kartta gösterilen sayfa sayısı da entegrasyonda hesaplanır.
- Bağımlılıklar yalnızca hazır wheel'i olan paketlerden seçilir (amd64 + aarch64, ör. `pypdfium2`, `Pillow`). Derleme gerektiren bir paket kullanılmaz. **Dikkat:** HA'nın resmi imajı Alpine (musl) tabanlı. Her bağımlılığın musllinux wheel'i olduğu ya da HA'nın kendi wheel deposunda bulunduğu planlamanın başında doğrulanmalı.
- Çift tarafı desteklemeyen yazıcıda seçenek kartta gizlenir. Elle çevirerek çift taraf yazdırma ilk sürümde yok.
- Bu iş ayrı bir iş kalemi olarak planlanır ve kayıtlı yazıcı yanıtlarıyla test edilir.

## 14. Uygulayıcıya bırakılanlar

- Dosya ve sınıf adları, kod yapısının ayrıntıları.
- Durum kontrolünün varsayılan sıklığı (öneri: 60 sn, iş sürerken daha sık).
- Kartın görsel ayrıntıları (HA tema değişkenlerine uyulacak).
- Print-Job ile Create-Job/Send-Document arasındaki seçim (yazıcı desteğine göre).
- Home Print Server'ın hangi temel imajla yapılacağı.
