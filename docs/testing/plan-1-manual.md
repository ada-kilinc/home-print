# Plan 1: Evden uzakta, kağıda bakmadan test

Evde değilsin, çıkan kağıdı göremiyorsun. O yüzden bu test sadece yazıcının ve Home Assistant'ın ağ üzerinden söylediklerine bakıyor.

- Bu gece: hiçbir şey basılmaz. Yazıcıya sadece "bu işi basabilir miydin?" diye sorulur (Validate-Job). Yazıcı iş oluşturmaz.
- Sabah istersen: `--print` ile tek sayfalık tek bir iş gönderirsin. Sonucu yine yazıcının kendi raporundan okursun.
- Her şeyi MacBook'ta Terminal'den yaparsın.

## 1. Kurulum (bir kere)

- Python 3.10 ya da üstü lazım. Kontrol: `python3 --version`.
- Ayrı bir sanal ortam kur:

```bash
python3 -m venv ~/homeprint-venv && ~/homeprint-venv/bin/pip install pyipp==0.17.0 aiohttp
```

- `scripts/remote_check.py` dosyasını Mac'e al. Repo'yu `git pull` ile güncelle ya da GitHub'dan sadece bu dosyayı indir.
- Komutların hepsi bu dosyanın olduğu klasörde çalışıyor varsayıyor. Değilse dosyanın tam yolunu yaz.

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
~/homeprint-venv/bin/python remote_check.py \
  --printer <yazıcı-ip> \
  --ha http://<ha-tailscale-ip>:8123 \
  --token "$HA_TOKEN" \
  --json ~/Desktop/homeprint-gece.json
```

- `<ha-tailscale-ip>`: HA'nın Tailscale adresi (`100.x.y.z`) ya da `ha.tailnet-adi.ts.net`. HTTPS kullanıyorsan `https://` yaz.
- Yazıcı ipps kullanıyorsa `--tls` ekle. Farklı port/yol için `--port`, `--path`.
- Tüm seçenekler: `~/homeprint-venv/bin/python remote_check.py --help`.

Ne kontrol ediliyor:

1. Yazıcının 631 portu 5 sn içinde açılıyor mu.
2. Get-Printer-Attributes: model, durum, formatlar, çift yüz, renk, sayfa aralığı, kopya, mürekkep seviyeleri.
3. eSCL tarayıcı var mı (sadece bilgi, Plan 4 için; asla KALDI olmaz).
4. Validate-Job, 8 durum: PDF düz, çift yüz, siyah-beyaz, renkli, sayfa 1-1, JPEG, PNG, 2 kopya. Hiçbiri basılmaz.
5. HA: API çalışıyor mu, Home Print kaydı `loaded` mı, sensörler ve mürekkep yüzdeleri, yükleme ucu token'sız isteği 401 ile, dosyasız isteği 400 ile reddediyor mu. Bunlar da hiçbir şey bastırmaz.
6. Gerçek baskı: `--print` yoksa ATLANDI.

Çıktıyı okumak:

- Her kontrol bir satır: `✅ GEÇTİ`, `❌ KALDI` ya da `⏭ ATLANDI`, yanında kısa açıklama.
- En altta özet satırı var. Hiç `❌` yoksa çıkış kodu 0, varsa 1.
- `⏭ ATLANDI (yazıcı bu formatı desteklemiyor — Plan 3)`: hata değil, not al yeter (aşağıda "Bilinen konular").
- `yazıcı Validate-Job uygulamıyor`: bazı yazıcılarda bu işlem yok. Hata değil, sadece 4. adım bu yazıcıda bir şey söylemiyor demek.

## 6. Sabahki komut (TEK sayfa basar)

Aynı komut, sonuna `--print` ekle, JSON adını değiştir:

```bash
~/homeprint-venv/bin/python remote_check.py \
  --printer <yazıcı-ip> \
  --ha http://<ha-tailscale-ip>:8123 \
  --token "$HA_TOKEN" \
  --print \
  --json ~/Desktop/homeprint-sabah.json
```

- Basmadan önce `⚠️ DİKKAT` satırı çıkar. Soru sormaz, hemen gönderir.
- Tek sayfalık küçük bir PDF gider, iş adı "Home Print uzaktan test".
- Script her 3 sn'de işin durumunu sorar, en fazla 180 sn bekler.
- Sadece yazıcı `completed` derse GEÇTİ. `aborted`, `canceled` ya da süre dolarsa KALDI.
- KALDI olursa komutu hemen tekrar çalıştırma. İş yine de basılmış olabilir, önce çıktıdaki `job-state-reasons`'a bak.

## 7. Claude'a ne yapıştıracaksın

- `homeprint-gece.json` (sabah da `homeprint-sabah.json`) dosyasının tamamını yapıştır.
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
| 422 | `format_not_supported` | Yazıcı bu dosya biçimini kabul etmiyor. |
| 422 | `option_not_supported` | Yazıcı istediğin ayarı (örnek çift yüz) desteklemiyor. |
| 422 | `printer_rejected` | Yazıcı işi reddetti, mesajda durum kodu var. |
| 502 | `printer_unavailable` | Yazıcıya ulaşılamıyor (kapalı, uykuda ya da ağda değil). |
| 502 | `print_failed` | Yazıcıda beklenmedik hata. HA günlüğüne bak. |

Script'in 5d ve 5e kontrolleri bu tablonun 401 ve 400 satırlarını kullanıyor.

## Bilinen konular

- **PDF desteklemeyen yazıcılar:** `document-format-supported` listesinde `application/pdf` olmayan yazıcılarda PDF yazdırınca `format_not_supported` ile **422** döner. Bu, Plan 3'te (dönüştürme) çözülecek. Script'in 2. kontrolünde "PDF: YOK" görürsen bunu bekle; hata sayılmaz.
- **Elle eklenen yazıcıda kendinden imzalı sertifika:** Yazıcıyı elle ve ipps (TLS) ile eklediysen ve sertifika kendinden imzalıysa HA bağlantı kuramaz. Çözüm: ekleme formunda **"Sertifikayı doğrula"** seçeneğini kapat. Varsayılan olarak açıktır. (Script yazıcı sertifikasını zaten doğrulamıyor, o yüzden script'te bu sorun görünmez.)
- **Yazıcı uykudaysa:** 1. ya da 2. kontrol zaman aşımına düşebilir. Birkaç dakika sonra tekrar dene; ilk istek çoğu zaman yazıcıyı uyandırır.
