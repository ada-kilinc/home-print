# Plan 1: Evdeki yazıcıyla gerçek test

Bu listeyi sen kendi Home Assistant'ında ve DeskJet'inde adım adım uygulayacaksın.

- Her adımın altında boş bir **Sonuç** satırı var. Dolduracağın yer orası.
- Bir adım takılırsa dur, hatayı Sonuç'a yaz, sonraki adıma geç.
- Bitince dosyayı kaydet ve en alttaki commit komutunu çalıştır.

Başlamadan önce elinde şunlar olsun:

- Tek sayfalık bir test PDF'i (`test.pdf`).
- Telefonda Tailscale açık, HA'ya Tailscale üzerinden ulaşabiliyorsun.
- HP Smart uygulaması (mürekkep karşılaştırması için).

## Adım 0: Yazıcıyı sorgula, fixture'ı kaydet

Bunu repo'nun olduğu bilgisayarda yap. Bilgisayar Tailscale ile eve bağlı olmalı.

- Yazıcının Tailscale ağındaki IP'sini bul (subnet router ile erişiyorsan evdeki yerel IP'si).
- Repo kökünde çalıştır:

```bash
python scripts/probe_printer.py <yazıcı-ip> --save
```

- Varsayılanlar: port `631`, yol `/ipp/print`, TLS kapalı. Yazıcın ipps kullanıyorsa `--tls` ekle. Farklı yol için `--path`, farklı port için `--port` ver.
- Çıktıda şunlara bak: `document-format-supported`, `sides-supported`, `print-color-mode-supported`, `marker-levels`.
- `document-format-supported` içinde `application/pdf` var mı? Not al (aşağıda "Bilinen konular"a bak).
- Komut `tests/fixtures/printer_<model>.json` dosyasını yazar. Dosya adını çıktıdaki "Saved full response to ..." satırında görürsün.
- Fixture'ı commit'le:

```bash
git add tests/fixtures
git commit -m "test: gerçek DeskJet fixture'ı"
```

**Sonuç:**

## Adım 1: Entegrasyonu HA'ya kur

- `custom_components/home_print` klasörünü HA'daki `config/custom_components/` içine kopyala.
- Sonunda şu yol olmalı: `config/custom_components/home_print/manifest.json`.
- Ya da HACS'ta özel depo olarak ekleyebilirsin.
- HA'yı yeniden başlat (Ayarlar → Sistem → Yeniden başlat).
- Günlükte `home_print` ile ilgili hata var mı? (Ayarlar → Sistem → Günlükler)

**Sonuç:**

## Adım 2: Yazıcıyı ekle

- Ayarlar → Cihazlar ve Hizmetler'e git.
- DeskJet "Keşfedildi" olarak görünüyor mu? Görünüyorsa **Ekle**'ye bas ve onayla.
- Görünmüyorsa elle ekle: **Entegrasyon ekle** → Home Print.
- Formda şunları doldur: Adres (yazıcı IP'si), Port (`631`), Yol (`/ipp/print`), "TLS kullan (ipps)" ve "Sertifikayı doğrula".
- Elle eklediğini ve nedenini (keşfedilmedi) Sonuç'a yaz.
- "Yazıcıya bağlanılamadı" hatası çıkarsa adresi ve yazıcının açık olduğunu kontrol et.
- Sertifika hatası alırsan "Bilinen konular"a bak.

**Sonuç:** (Keşfedildi mi, elle mi eklendi?)

## Adım 3: Sensörleri kontrol et

Home Print cihaz sayfasını aç. Şunlar olmalı:

- **Durum** sensörü: Boşta / Yazdırıyor / Durdu. Şu an doğru mu?
- **Mürekkep** sensörleri: her kartuş için bir yüzde. HP Smart'taki yüzdelerle karşılaştır.
- **Sorun** sensörü: yazıcıda hata yokken kapalı olmalı.
- **Son iş** sensörü: henüz iş yok, boş görünebilir.

| Sensör | HA'daki değer | HP Smart'taki değer |
| --- | --- | --- |
| Siyah mürekkep | | |
| Renkli mürekkep | | |
| Durum | | |
| Sorun | | |

**Sonuç:**

## Adım 4: print_file servisiyle yazdır

Önce dosyayı HA'nın okuyabildiği yere koy.

- `test.pdf`'i HA'daki medya klasörüne (`/media`) kopyala. Örnek yol: `/media/test.pdf`.
- Medya klasörünü HA zaten okuyabiliyor, ek ayar gerekmez. Dosyayı başka bir klasöre koyarsan o klasör HA'nın okuyabildiği bir yer olmalı (örneğin `allowlist_external_dirs` altına eklenmiş). Değilse servis "Home Assistant'ın ... yolunu okuma izni yok" der (`path_not_allowed`).

Şimdi servisi çalıştır: Geliştirici Araçları → Eylemler → **Dosya yazdır** (`home_print.print_file`). YAML moduna geçip yapıştırabilirsin. `config_entry_id` için aşağıdaki "entry_id nasıl bulunur" kısmına bak, ya da arayüzden yazıcıyı seçebilirsin.

### 4a: Düz baskı

```yaml
action: home_print.print_file
data:
  config_entry_id: <entry_id>
  path: /media/test.pdf
```

- Sayfa çıktı mı? Doğru mu çıktı?

**Sonuç:**

### 4b: Çift taraf

```yaml
action: home_print.print_file
data:
  config_entry_id: <entry_id>
  path: /media/test.pdf
  sides: two-sided-long-edge
```

- Yazıcı çift yüz desteklemiyorsa `option_not_supported` hatası gelir. Bunu not al.

**Sonuç:**

### 4c: Siyah-beyaz

```yaml
action: home_print.print_file
data:
  config_entry_id: <entry_id>
  path: /media/test.pdf
  color_mode: monochrome
```

- Çıktı siyah-beyaz mı?

**Sonuç:**

### 4d: İkisi birlikte

```yaml
action: home_print.print_file
data:
  config_entry_id: <entry_id>
  path: /media/test.pdf
  sides: two-sided-long-edge
  color_mode: monochrome
  copies: 1
```

**Sonuç:**

Servisin diğer alanları: `copies` (1-99), `sides` (`one-sided`, `two-sided-long-edge`, `two-sided-short-edge`), `color_mode` (`auto`, `color`, `monochrome`), `page_ranges` (örnek `1-3,5`).

## Adım 5: Telefondan, Tailscale üzerinden yükle

### Hazırlık

**entry_id nasıl bulunur:**

- Ayarlar → Cihazlar ve Hizmetler → Home Print kartına tıkla.
- Adres çubuğundaki URL'ye bak: `.../config/integrations/integration/home_print#config_entry/<entry_id>` ya da giriş sayfasının URL'sinde `<entry_id>` uzun bir harf-rakam dizisidir.
- Bulamazsan Geliştirici Araçları → Eylemler'de `home_print.print_file` seçip YAML moduna geç. Yazıcıyı seçince `config_entry_id` değeri YAML'da görünür.

**Uzun ömürlü token nasıl alınır:**

- HA'da sol alttan profiline tıkla (Profil).
- **Güvenlik** sekmesine git.
- En altta "Uzun ömürlü erişim token'ları" → **Token oluştur**.
- Ad ver (mesela `home-print-test`), oluştur ve token'ı hemen kopyala. Bir daha gösterilmez.
- Token'ı kimseyle paylaşma, commit'leme. Testten sonra silebilirsin.

### Komut

```bash
curl -H "Authorization: Bearer <token>" \
  -F file=@test.pdf \
  https://<ha-adresi>/api/home_print/upload/<entry_id>
```

- `<ha-adresi>`: Tailscale üzerinden HA'ya girdiğin adres (örnek `ha.tailnet-adi.ts.net:8123`; HTTP kullanıyorsan `http://` yaz).
- Sayfa aralığı, kopya ve yüz gibi seçenekleri ek alan olarak gönderebilirsin. İzin verilen alanlar: `copies`, `sides`, `color_mode`, `page_ranges`.

```bash
curl -H "Authorization: Bearer <token>" \
  -F file=@test.pdf \
  -F sides=two-sided-long-edge \
  -F color_mode=monochrome \
  -F copies=1 \
  https://<ha-adresi>/api/home_print/upload/<entry_id>
```

- Başarılı olursa şu gelir: `{"job_id": 123}`, ve sayfa çıkar.
- Telefonda curl için Termux ya da iSH kullanabilirsin.

### Hata cevapları

Hata olursa cevap `{"error": "<anahtar>", "message": "<Türkçe mesaj>"}` biçiminde gelir. Mesaj dili `Accept-Language` başlığına göre seçilir; yoksa HA dili kullanılır.

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
| 422 | `format_not_supported` | Yazıcı bu dosya biçimini kabul etmiyor. |
| 422 | `option_not_supported` | Yazıcı istediğin ayarı (örnek çift yüz) desteklemiyor. |
| 422 | `printer_rejected` | Yazıcı işi reddetti, mesajda durum kodu var. |
| 502 | `printer_unavailable` | Yazıcıya ulaşılamıyor (kapalı, uykuda ya da ağda değil). |
| 502 | `print_failed` | Yazıcıda beklenmedik hata. HA günlüğüne bak. |

**Sonuç:** (HTTP kodu, gelen JSON, sayfa çıktı mı?)

## Adım 6: Yazıcı uykudayken yazdır

- Yazıcıyı uyku moduna geçmesi için bir süre boşta bırak (ya da kapat).
- Önce Durum sensörüne bak, ne gösteriyor?
- Adım 4a'daki servisi tekrar çalıştır.
- Sonra Adım 5'teki curl'ü tekrar çalıştır.
- Ne oldu?
  - İş gitti ve yazıcı uyandı mı? Kaç saniye sürdü?
  - Yoksa açık bir hata mı döndü? Hangisi: `printer_unavailable` (502) mi, başka bir şey mi?
- Hata mesajı anlaşılır mıydı?

**Sonuç:**

## Bilinen konular

- **PDF desteklemeyen yazıcılar:** `document-format-supported` listesinde `application/pdf` olmayan yazıcılarda PDF yazdırınca `format_not_supported` ile **422** döner. Bu, Plan 3'te (dönüştürme) çözülecek. Adım 0'daki çıktıda PDF yoksa bu hatayı bekle; hata sayılmaz, buraya not et.
- **Elle eklenen yazıcıda kendinden imzalı sertifika:** Yazıcıyı elle ve ipps (TLS) ile eklediysen ve sertifika kendinden imzalıysa bağlantı kurulamaz. Çözüm: ekleme formunda **"Sertifikayı doğrula"** seçeneğini kapat. Varsayılan olarak açıktır.

## Özet ve commit

- Bulduğun sorunları buraya kısaca yaz:

**Genel sonuç:**

- Sonra commit'le:

```bash
git add docs/testing/plan-1-manual.md
git commit -m "test: plan 1 gerçek cihaz sonuçları"
```
