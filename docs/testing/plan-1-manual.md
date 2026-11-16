# Plan 1: Evden uzakta, kağıda bakmadan test

Evde değilsin, çıkan kağıdı göremiyorsun. O yüzden bu test sadece yazıcının ve Home Assistant'ın ağ üzerinden söylediklerine bakıyor.

- Bu gece: hiçbir şey basılmaz. Yazıcıya sadece "bu işi basabilir miydin?" diye sorulur (Validate-Job), yazıcı iş oluşturmaz. Örnek bir PDF de Mac'te dönüştürülüp sayfaları sayılır, yazıcıya gitmez.
- Sabah: `--print` ile bütün baskı testleri tek seferde yapılır. 2 iş, en fazla 2 kağıt. Sonucu yine yazıcının kendi raporundan okursun.
- Her şeyi MacBook'ta Terminal'den yaparsın.

## 1. Kurulum (bir kere)

- Python 3.11 ya da üstü lazım (numpy 2.3.2 3.10'a kurulmuyor). Mac'teki Homebrew Python'u (`/opt/homebrew/bin/python3`, 3.14) yeter. Kontrol: `/opt/homebrew/bin/python3 --version`.
- O dosya yoksa Homebrew'la (`brew install python`) ya da python.org'dan 3.11+ kur.
- Repo'yu Mac'e al. Script tek başına yetmez, dönüştürme kodunu repo'dan okuyor (`scripts/` ile `custom_components/` yan yana durmalı).
  - Şimdilik: Claude sohbette repo'nun zip'ini gönderecek. İndir, `~/home-print` klasörüne aç:

```bash
mkdir -p ~/home-print && unzip ~/Downloads/home-print.zip -d ~/home-print
```

  - Zip'te dosyalar doğrudan en üstte, ayrı bir klasör yok: `~/home-print/scripts/remote_check.py` oluşmalı.
  - GitHub deposu açılınca: `git clone https://github.com/adakilinc/home-print.git ~/home-print`, sonraki güncellemeler için `git pull`.
- Ayrı bir sanal ortam kur. Paket sürümleri integration'ın manifest'iyle aynı:

```bash
/opt/homebrew/bin/python3 -m venv ~/homeprint-venv && ~/homeprint-venv/bin/pip install pyipp==0.17.0 aiohttp pypdfium2==5.15.2 Pillow==12.0.0 numpy==2.3.2
```

- Komutları repo klasöründe çalıştır: `cd ~/home-print`.
- `pyipp` ya da `aiohttp` eksikse script hiç başlamaz, hangi paketin eksik olduğunu ve pip satırını yazıp çıkar.
- Dönüştürme paketlerinden (`pypdfium2`, `Pillow`, `numpy`) biri eksikse script yine çalışır. 4m-4p, 6 ve 7b `⏭ ATLANDI` olur, yanında eksik paketin adı yazar.

## 2. Tailscale'i aç

- Mac'te Tailscale açık ve bağlı olsun.
- Yazıcının evdeki yerel IP'sine (örnek `192.168.68.x`) ulaşmak için evdeki subnet router route'unun açık ve onaylı olması lazım. Yoksa yazıcıya erişilemez, script 1. kontrolde kalır.
- Hızlı deneme: `nc -vz <yazıcı-ip> 631`. "succeeded" görürsen tamam.

## 3. Yazıcının IP'sini bul

Şunlardan biri yeter:

- **HA:** Ayarlar → Cihazlar ve Hizmetler → Home Print (ya da IPP) → yazıcı cihazı. Cihaz sayfasındaki "Cihazı ziyaret et" bağlantısı `http://<ip>:631/` şeklinde, IP orada.
- **Deco uygulaması:** Cihazlar/İstemciler listesinde HP DeskJet'e dokun, IP adresi yazıyor.
- **Router/Deco web sayfası:** bağlı cihazlar listesi.

## 4. Uzun ömürlü token al

- HA'da sol alttan profiline tıkla.
- **Güvenlik** sekmesine geç.
- En altta "Uzun ömürlü erişim token'ları" → **Token oluştur**.
- Ad ver (mesela `home-print-test`), oluştur, token'ı hemen kopyala. Bir daha gösterilmiyor.
- Yönetici hesabıyla oluştur. Yönetici olmayan token'la 5b (config entry) kontrolü ATLANDI olur.
- Token'ı kimseyle paylaşma, commit'leme. JSON çıktısına yazılmıyor. Testten sonra silebilirsin.
- Shell geçmişinde kalmasın diye önce bir değişkene oku:

```bash
read -s HA_TOKEN   # token'ı yapıştır, Enter
```

## 5. Bu geceki komut (baskı YOK)

```bash
cd ~/home-print
~/homeprint-venv/bin/python scripts/remote_check.py \
  --printer <yazıcı-ip> \
  --ha http://<ha-tailscale-ip>:8123 \
  --token "$HA_TOKEN" \
  --json ~/Desktop/homeprint-gece.json
```

- `<ha-tailscale-ip>`: HA'nın Tailscale adresi (`100.x.y.z`) ya da `ha.tailnet-adi.ts.net`. HTTPS kullanıyorsan `https://` yaz.
- Yazıcı ipps kullanıyorsa `--tls` ekle. Farklı port/yol için `--port`, `--path`.
- Tüm seçenekler: `~/homeprint-venv/bin/python scripts/remote_check.py --help`.

Ne kontrol ediliyor:

1. Yazıcının 631 portu 5 sn içinde açılıyor mu.
2. Get-Printer-Attributes: model, durum, iş kabul ediyor mu, formatlar, çift yüz, renk, sayfa aralığı, kopya, mürekkep seviyeleri.
3. eSCL tarayıcı var mı (sadece bilgi, Plan 4 için; asla KALDI olmaz).
4. Validate-Job, hiçbiri basılmaz:
   - 4a-4h: PDF düz, çift yüz, siyah-beyaz, renkli, sayfa 1-1, JPEG, PNG, PDF 2 kopya.
   - 4i-4l: JPEG çift yüz, siyah-beyaz, renkli, 2 kopya.
   - 4m-4p: PDF'in dönüştürüleceği format (senin DeskJet'te `image/pwg-raster`): düz, çift yüz, siyah-beyaz, renkli. Belge gönderilmez, sadece format ve ayar kabulü sorulur.
5. HA: API çalışıyor mu, Home Print kaydı `loaded` mı, sensörler ve mürekkep yüzdeleri, yükleme ucu token'sız isteği 401 ile, dosyasız isteği 400 ile reddediyor mu. Bunlar da hiçbir şey bastırmaz.
6. Dönüştürme denemesi: 3 sayfalık örnek PDF Mac'te dönüştürülür (siyah-beyaz, çift yüz). Boyut ve süre yazılır, çıktı çözülüp sayfalar sayılır. Çift yüzde tek sayıda sayfanın arkasına boş sayfa eklendiği için 4 sayfa beklenir. Yazıcıya hiçbir şey gitmez.
7. Gerçek baskı: `--print` yoksa ATLANDI.

Çıktıyı okumak:

- Her kontrol bir satır: `✅ GEÇTİ`, `❌ KALDI` ya da `⏭ ATLANDI`, yanında kısa açıklama.
- En altta özet satırı var. Hiç `❌` yoksa çıkış kodu 0, varsa 1.
- Bu gece en önemlileri 4f, 4i-4p ve 6. Sabahki işler bunlarla aynı formatı ve ayarları kullanıyor.
- 4a-4e, 4g, 4h `⏭ ATLANDI (yazıcı bu formatı desteklemiyor — Plan 3)` olabilir: DeskJet PDF ve PNG almıyor. Hata değil, bu yüzden dönüştürme var.
- `yazıcı Validate-Job uygulamıyor`: bazı yazıcılarda bu işlem yok. Hata değil, sadece 4. adım bu yazıcıda bir şey söylemiyor demek.
- 6'da `❌` görürsen sabah `--print` kullanma, önce JSON'u Claude'a gönder.

## 6. Sabahki komut (2 iş, en fazla 2 kağıt)

Aynı komut, sonuna `--print` ekle, JSON adını değiştir:

```bash
cd ~/home-print
~/homeprint-venv/bin/python scripts/remote_check.py \
  --printer <yazıcı-ip> \
  --ha http://<ha-tailscale-ip>:8123 \
  --token "$HA_TOKEN" \
  --print \
  --json ~/Desktop/homeprint-sabah.json
```

- Gece yapılan bütün kontroller yine baştan yapılır, baskılar en sonda gelir.
- Basmadan önce `⚠️ DİKKAT: ... 2 iş, en fazla 2 kağıt` satırı çıkar. Soru sormaz, hemen gönderir.
- İşler bu sırayla gider (çıktıda önce 7b, sonra 7a görürsün):
  - 7b: 2 sayfalık örnek PDF, dönüştürülmüş (DeskJet'te `image/pwg-raster`), çift yüz (uzun kenar), siyah-beyaz, tek kağıt. İş adı "Home Print test 1/2 — PDF çift taraf".
  - 7a: JPEG tek sayfa, iş adı "Home Print test 2/2 — JPEG". Sadece 7b'nin 1 kağıt kullandığı kesinse gider.
  - İki işte de `copies: 1` açıkça gönderilir.
- Her işten önce yazıcının boşta olduğuna ve iş kabul ettiğine bakılır. Meşgulse en fazla 60 sn beklenir. Durmuşsa, iş kabul etmiyorsa ya da Validate-Job o işin ayarlarını reddederse iş hiç gönderilmez, `⏭ ATLANDI` olur.
- Script her 3 sn'de işin durumunu sorar, iş başına en fazla 180 sn bekler.
- Sadece yazıcı `completed` derse GEÇTİ. `aborted`, `canceled` ya da süre dolarsa KALDI.
- 7b'de `impressions: 2` görmen lazım: kağıdın iki yüzüne de basıldı demek. Farklıysa satırda `FARKLI` yazar.
- Toplam asla 2 kağıdı geçmez. Yazıcı çift yüz bildirmiyorsa ya da Validate-Job `sides`'ı yok saydığını söylerse 7b sadece ön yüzü basar (1 kağıt). Satırda `sadece ön yüz, 1 kağıt` ve nedeni yazar, beklenen impressions 1 olur.
- 7b bitince script kaç kağıt kullandığına bakar (`job-media-sheets-completed`; yazıcı bunu vermezse tek yüzlü işte impressions). 1 kağıtsa 7a gider. 2 kağıt çıktıysa (yazıcı çift yüzü sessizce tek yüze çevirdiyse) ya da sayı belli değilse 7a gönderilmez, `⏭ ATLANDI` olur ve satırda nedeni yazar.
- KALDI olursa komutu hemen tekrar çalıştırma. İş yine de basılmış olabilir, önce çıktıdaki `job-state-reasons`'a bak.
- Evde biri varsa kağıtlara bakabilir ama gerekmiyor: her sayfada büyük harfle test numarası ve üstte "↑ ÜST" oku var.

## 7. Claude'a ne göndereceksin

- `homeprint-gece.json` dosyasını (sabah da `homeprint-sabah.json`) sohbete ekle ya da içeriğini yapıştır.
- İçinde bütün sonuçlar ve yazıcının ham özellikleri var. Seri numarası, `printer-location` ve `printer-uuid` `<gizlendi>` ile değiştiriliyor. Token hiç yazılmıyor.
- Terminal çıktısını da yapıştırırsan iyi olur, şart değil.

## Hata cevapları (yükleme ucu)

Telefondan ya da panelden `POST /api/home_print/upload/<entry_id>` isteği atınca hata olursa cevap `{"error": "<anahtar>", "message": "<Türkçe mesaj>"}` biçiminde gelir. Mesaj dili `Accept-Language` başlığına göre seçilir; yoksa HA dili kullanılır.

| HTTP | `error` | Anlamı |
| --- | --- | --- |
| 400 | `invalid_request` | İstek `multipart/form-data` değil, bozuk ya da birden fazla `file` var. |
| 400 | `missing_file` | `file` alanı gelmedi. |
| 400 | `invalid_option` | Bilinmeyen alan ya da geçersiz değer (örnek `copies` sayı değil). |
| 400 | `unsupported_file_type` | Dosya PDF, JPEG ya da PNG değil. |
| 401 | (HA'dan gelir) | Token yok, yanlış ya da silinmiş. |
| 403 | `admin_required` | Yazıcı "Sadece yöneticiler yazdırabilsin" modunda, token sahibi yönetici değil. |
| 404 | `entry_not_found` | `entry_id` yanlış ya da yazıcı henüz yüklenmedi. |
| 413 | `file_too_large` | Dosya sınırı aştı (varsayılan 25 MB, seçeneklerden değişir). |
| 400 | `invalid_document` | Dosya bozuk, şifreli ya da boş; ya da seçilen sayfa aralığı geçersiz. |
| 400 | `too_many_pages` | Dönüştürülecek sayfa sayısı sınırı aşıyor. |
| 422 | `format_not_supported` | Yazıcı ne bu biçimi ne de dönüştürülebilecek bir biçimi (PDF, PWG raster, URF, JPEG) alıyor. PDF almayan yazıcıya PDF artık dönüştürülüp gönderiliyor, bu hata o durumda çıkmaz. |
| 422 | `option_not_supported` | Yazıcı istediğin ayarı (örnek çift yüz) desteklemiyor. |
| 422 | `printer_rejected` | Yazıcı işi reddetti, mesajda durum kodu var. |
| 502 | `printer_unavailable` | Yazıcıya ulaşılamıyor (kapalı, uykuda ya da ağda değil). |
| 502 | `print_failed` | Yazıcıda beklenmedik hata. HA günlüğüne bak. |
| 504 | `print_timeout` | Yazıcı işe zamanında cevap vermedi. İş yine de basılmış olabilir. |

Script'in 5d ve 5e kontrolleri bu tablonun 401 ve 400 satırlarını kullanıyor.

## Kartı ana sayfaya ekle

En kolayı görsel düzenleyici, YAML yazman gerekmez:

- Ana sayfa (Dashboard) → sağ üstten **Düzenle** → **Kart ekle** → arama kutusuna "Home Print" yaz, kartı seç.
- Düzenleyicide yazıcıyı listeden seç. Boş bırakırsan ("Otomatik") ilk yazıcı kullanılır. İstersen başlık yaz, mürekkep seviyelerini göstermek ya da gizlemek için anahtarı kullan.
- `entry_id`'yi bilmen gerekmez: listeden yazıcı seçince düzenleyici onu kendisi yazar. Tek yazıcın varsa hiç seçmesen de olur.

YAML ile eklemek istersen hepsi isteğe bağlı:

```yaml
type: custom:home-print-card
entry_id: <yazıcının entry_id değeri>  # yoksa ilk yazıcı
title: Ofis yazıcısı
show_ink: true
```

- Kart entegrasyonla birlikte kendiliğinden yüklenir, ayrıca bir kaynak (resource) eklemen gerekmez.
- Entegrasyonu güncelledikten sonra kart eski haliyle görünürse tarayıcıda sayfayı sert yenile (Ctrl+Shift+R, telefonda uygulamayı kapatıp aç).

## Bilinen konular

- **PDF desteklemeyen yazıcılar:** `document-format-supported` listesinde `application/pdf` yoksa PDF, PWG raster ya da URF'ye dönüştürülerek gönderilir (Plan 3). Script'in 2. kontrolünde "PDF: YOK" görürsen bunu bekle; hata sayılmaz. 4m-4p ve 6 dönüştürmenin çalıştığını gösterir.
- **Elle eklenen yazıcıda kendinden imzalı sertifika:** Yazıcıyı elle ve ipps (TLS) ile eklediysen ve sertifika kendinden imzalıysa HA bağlantı kuramaz. Çözüm: ekleme formunda **"Sertifikayı doğrula"** seçeneğini kapat. Varsayılan olarak açıktır. (Script yazıcı sertifikasını zaten doğrulamıyor, o yüzden script'te bu sorun görünmez.)
- **Yazıcı uykudaysa:** 1. ya da 2. kontrol zaman aşımına düşebilir. Birkaç dakika sonra tekrar dene; ilk istek çoğu zaman yazıcıyı uyandırır.
