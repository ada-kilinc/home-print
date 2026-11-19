# Home Print — Yol haritası

Spec: `docs/superpowers/specs/2026-11-15-home-print-design.md`

Spec birbirinden bağımsız test edilebilen birkaç alt sistemi kapsıyor. Bu yüzden iş, her biri kendi başına çalışan yazılım üreten ayrı planlara bölündü. Her plan bir öncekinin bittiğini varsayar. Bir sonraki plan, öncekinin gerçekte nasıl çıktığı görüldükten sonra yazılır.

| # | Plan | Sonunda elde olan | Spec bölümleri |
|---|---|---|---|
| 1 | Çekirdek entegrasyon: yazıcı ekleme, sensörler, doğrudan IPP yazdırma | Ayarlar'dan yazıcı eklenir, durum ve mürekkep görünür, `home_print.print_file` ve yükleme ucu PDF/JPEG yazdırır | 5, 7.1, 7.2, 8, 9, 12 |
| 2 | Kart: Yazdır sekmesi | Ana sayfa kartından telefonla yazdırma | 7.3 |
| 3 | Dönüştürme | Raster yazıcılar, sayfa aralığı, fotoğrafı sayfaya sığdırma | 13 |
| 4 | Tarama: eSCL, arşiv, Yazdır'ın altında Tara düğmesi; geçmişte Taramalar sekmesi | Tarama, ön izleme, indirme, geçmişte Taramalar sekmesi, `home_print.scan` | 7.5 |
| 5 | Home Print Server: CUPS + SANE köprüsü + OCR | Eski/USB cihazlar ve aranabilir PDF; HA eklentisi ve bağımsız Docker imajı | 7.4, 7.5 (SANE/OCR) |
| 6 | Yayın | İsim çakışma kontrolü, README (tr+en, tek tık düğmeleri), CI (hassfest, HACS, eklenti derlemesi), ilk sürüm | 10, 11, 12 |

## Durum notu (2026-11-16)

Plan 4 (tarama) uygulandı: eSCL istemcisi, arşiv, `home_print.scan`, kartta Tara düğmesi ve geçmişte Taramalar sekmesi, `scripts/remote_check.py --scan-info/--scan`, sürüm 0.3.0. Ertelenenler: yalnızca tarayıcı olan cihazlar (ayrı giriş türü) ve `_uscan._tcp` keşfi. Gerçek yazıcının eSCL yanıtı henüz alınmadı, fixture'lar sentetik.

## Durum notu (2026-11-19)

- Plan 6'nın kod tarafı bitti: CI (ruff, pytest, vitest, hassfest, ignore'suz HACS doğrulaması), tag ile release, sadece İngilizce kısa README, yeni ekran görüntüleri, tanılama dosyası. README artık tr+en değil, sadece İngilizce.
- eSCL fixture'ları gerçek DeskJet 4670 dökümlerinden geliyor. Çift taraflı besleyici ve siyah-beyaz için tek sentetik dosya kaldı.
- Kart `frontend/src/` altında modüllere bölündü, esbuild ile tek dosyaya derleniyor (ADR 1).
- Tarayıcı keşfi (`_uscan`/`_uscans`) ve yazıcısı olmayan tarayıcılar eklendi (#10).
- Kâğıt boyutu seçimi yerine taramadan sonra sayfa sayfa kırpma geldi: kenarlar otomatik bulunuyor, kırpılan kısım dosyadan gerçekten siliniyor, geçmişteki taramalarda da çalışıyor (#9).
- Kalanlar: HACS varsayılan listesine kabul ve Android'de gerçek cihaz testi (#4), Plan 5 (#5).
