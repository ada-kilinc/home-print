# Home Print — Plan 3: Dönüştürme

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Yazıcının doğrudan kabul etmediği PDF ve PNG dosyalarını, yazıcının desteklediği formata (PWG Raster, Apple Raster/URF ya da JPEG) çevirerek yazdırmak. Ada'nın HP DeskJet 4670'i PDF ve PNG'yi kabul etmiyor.

**Architecture:** Dönüştürme kodu Home Assistant'tan bağımsız saf modüllerde durur: `convert/render.py` (PDF/görsel → sayfa görüntüleri), `convert/pwg.py`, `convert/urf.py` (raster kodlayıcılar), `convert/pipeline.py` (hangi yolun seçileceği). `printing.async_print` pipeline'ı executor'da çalıştırır. HA'yı import etmeyen bu modüller `scripts/remote_check.py` tarafından da yüklenebilir, böylece sabahki tek seferlik baskı testi gerçek dönüştürme kodunu kullanır.

**Tech Stack:** Python, `pypdfium2` (PDF render), `Pillow`, `numpy` (raster sıkıştırmayı hızlandırmak için), pyipp 0.17.0.

**Spec:** `docs/superpowers/specs/2026-11-15-home-print-design.md` (bölüm 13)

**Gerçek yazıcı verisi:** `tests/fixtures/printer_hp_deskjet_4670.json` (Ada'nın yazıcısının gizlenmiş Get-Printer-Attributes yanıtı).

## Global Constraints

- Bağımlılıklar yalnızca hazır wheel'i olan paketler. amd64 + aarch64 için musllinux wheel'i doğrulanmış olmalı (`scripts/check_wheels.sh`'ye `numpy` eklenir). Derleme gerektiren paket yok.
- `custom_components/home_print/convert/` altındaki modüller `homeassistant` import etmez.
- Dönüştürme CPU-yoğun: HA event loop'unda değil, `hass.async_add_executor_job` ile çalışır.
- Bellek: sayfalar tek tek render edilip kodlanır. Aynı anda bellekte en fazla bir sayfanın ham görüntüsü bulunur.
- Yazıcının desteklediği bir format varsa dosya olduğu gibi gider (dönüştürme yapılmaz).
- PDF hedef sırası: `application/pdf` → `image/pwg-raster` → `image/urf` → (yoksa) `FormatNotSupportedByPrinter`.
- PNG hedef sırası: `image/png` → `image/jpeg` (alfa beyaza düzleştirilir) → `image/pwg-raster` → `image/urf`.
- JPEG: yazıcının `jpeg-x/y-dimension-supported` ve `jpeg-k-octets-supported` sınırlarını aşan JPEG küçültülüp yeniden kodlanır. Aşmıyorsa olduğu gibi gider.
- Çözünürlük: yazıcının desteklediği raster çözünürlüklerinden 300 dpi'ye en yakın olanı. DeskJet 4670 için 300×300.
- Kağıt: `media-default` (DeskJet için `iso_a4_210x297mm`) ve `media-col-default` kenar boşlukları. Sayfa içeriği oranı korunarak yazdırılabilir alana sığdırılır ve ortalanır. Yatay sayfalar dikey kağıda 90° döndürülerek sığdırılır.
- Renk: `color_mode="monochrome"` (ya da `process-monochrome`/`auto-monochrome`) → gri tonlama (`sgray_8` / URF `W8`). Diğerleri → `srgb_8` / URF `SRGB24`.
- Sayfa aralığı: dönüştürülen işlerde sayfalar entegrasyonda seçilir ve yazıcıya `page-ranges` gönderilmez. Dönüştürülmeyen işlerde eskisi gibi yazıcıya bırakılır.
- Çift taraf: raster başlığında `Duplex`/`Tumble` alanları ve yazıcının `pwg-raster-document-sheet-back` (URF'de `DM1..DM4`) değerine göre arka sayfa yönü. `sides` IPP özelliği de gönderilir.
- Kopya: `copies` IPP özelliği gönderilir (sayfalar kopyalanmaz).
- Varsayılan en fazla sayfa: 200. Fazlası `invalid_option`/yeni anahtar `too_many_pages` ile reddedilir.
- Bu plan baskı yapmaz. Gerçek yazıcıda baskı testi Ada'nın sabahki tek seferlik testinde `remote_check.py --print` ile yapılır.

## Review Focus

1. **Çok sayfalı, karışık yönlü PDF** (dikey + yatay sayfalar): her sayfa doğru döndürülüp sığdırılmalı, sayfa sayısı ve sırası korunmalı. → Task 2 testi.
2. **Şifreli ya da bozuk PDF:** çökme yok. Kullanıcıya açık bir hata (`invalid_document`, HTTP 400) gösterilmeli. → Task 2 ve Task 5.
3. **Saydam PNG:** saydam alan siyah değil beyaz çıkmalı. → Task 2.
4. **Çift taraf + tek sayıda sayfa** (ör. 3 sayfa): son arka yüz boş kalmalı, sayfa kayması olmamalı. Arka yüz yönü yazıcının sheet-back değerine uymalı. → Task 3 ve Task 4.
5. **Büyük PDF** (ör. 150 sayfa): bellek tek sayfa ile sınırlı kalmalı, 200 sayfa sınırı çalışmalı, iş 300 sn zaman aşımına sığmalı (ya da açık hata vermeli). → Task 5.

---

### Task 1: Gerçek yazıcı verisi ve genişletilmiş yetenekler

**Files:**
- Modify: `custom_components/home_print/models.py`, `custom_components/home_print/client.py`
- Add (already in tree): `tests/fixtures/printer_hp_deskjet_4670.json`
- Modify: `scripts/check_wheels.sh` (numpy), `custom_components/home_print/manifest.json` (requirements: `pypdfium2==<musl wheel'i olan güncel sürüm>`, `Pillow` → HA'nın pinlediği sürümle aynı, `numpy` → HA'nın pinlediği sürümle aynı), `requirements_test.txt`
- Test: `tests/test_client.py`

**Interfaces:**
- Produces (`models.py`):
  - `RasterCaps(pwg_types: frozenset[str], pwg_resolutions: tuple[int, ...], pwg_sheet_back: str | None, urf: frozenset[str])`. `pwg_resolutions` dpi listesi (x=y olanlar). `urf` ham `urf-supported` anahtarları (`"W8"`, `"SRGB24"`, `"RS300"`, `"DM3"` ...; virgülle ayrılmış `"W8-16"` gibi değerler olduğu gibi tutulur).
  - `MediaCaps(default_name: str, width_hmm: int, height_hmm: int, margins_hmm: tuple[int, int, int, int])`. Kenar boşlukları üst, sağ, alt, sol sırasıyla, yüzde-mm (1/100 mm).
  - `JpegLimits(max_x: int | None, max_y: int | None, max_kb: int | None)`
  - `Capabilities` alanlarına eklenir (varsayılanlı, eski çağrılar kırılmaz): `raster: RasterCaps | None = None`, `media: MediaCaps | None = None`, `jpeg: JpegLimits | None = None`.
- Consumes: `client.parse_printer` içinde yeni alanların doldurulması.

- [ ] **Step 1: Failing tests** `tests/test_client.py`:
  - `test_parse_deskjet_4670_fixture`: `make_model == "HP DeskJet 4670 series"`. `document_formats` içinde `image/pwg-raster`, `image/urf`, `image/jpeg` var, `application/pdf` yok. `raster.pwg_types` ⊇ {`sgray_8`, `srgb_8`}. `raster.pwg_resolutions == (300,)`. `raster.pwg_sheet_back == "rotated"`. `"DM3"` ve `"W8-16"` ve `"SRGB24"` `raster.urf` içinde. `media == MediaCaps("iso_a4_210x297mm", 21000, 29700, (296, 296, 296, 296))`. `jpeg == JpegLimits(8192, 8192, 12288)`. İki marker seviyesi 20 ve 40.
  - `test_parse_generic_fixture_still_works`: eski fixture'da yeni alanlar `None` olabilir, mevcut testler geçer.
- [ ] **Step 2:** Çalıştır → FAIL. **Step 3:** Uygula (`media-col-default` iç içe `media-size` ve kenar boşlukları; `pwg-raster-document-resolution-supported` `[300, 300, 3]` gibi düz listeler ya da liste listeleri olabilir; `jpeg-*-supported` `[min, max]`). **Step 4:** PASS.
- [ ] **Step 5:** `scripts/check_wheels.sh` listesine `numpy` ekle, pinli sürümlerle çalıştır. Sonucu rapora yaz. pypdfium2/numpy/Pillow'dan biri musl wheel'i vermiyorsa **BLOCKED** bildir.
- [ ] **Step 6: Commit** `feat: raster, media and jpeg capabilities (DeskJet 4670 fixture)`

### Task 2: Render — PDF ve görselleri sayfa görüntülerine çevirme

**Files:**
- Create: `custom_components/home_print/convert/__init__.py` (boş), `custom_components/home_print/convert/render.py`, `custom_components/home_print/convert/errors.py`
- Test: `tests/convert/test_render.py`, `tests/convert/samples.py` (testte üretilen örnek PDF/PNG/JPEG: pypdfium2 ya da Pillow ile; repo'ya binary koyma)

**Interfaces:**
- Produces:
  - `errors.py`: `ConvertError(Exception)` (taban), `InvalidDocument(ConvertError)` (bozuk/şifreli/boş), `TooManyPages(ConvertError)` (`count: int`, `limit: int`).
  - `@dataclass(frozen=True) class PageSpec: width_px: int, height_px: int, dpi: int, margins_px: tuple[int, int, int, int], gray: bool` — kağıdın tam boyutu (kenar boşlukları dahil).
  - `def page_spec_for(media: MediaCaps | None, dpi: int, gray: bool) -> PageSpec` — media yoksa A4 ve 3 mm kenar boşluğu.
  - `def count_pages(data: bytes) -> int` — PDF için sayfa sayısı, görsel için 1. Bozuk/şifreli PDF → `InvalidDocument`.
  - `def iter_pages(data: bytes, fmt: str, spec: PageSpec, pages: list[int] | None, max_pages: int = 200) -> Iterator[PIL.Image.Image]` — `fmt` ∈ {`application/pdf`, `image/png`, `image/jpeg`}. `pages` 1 tabanlı sayfa numaraları (sıralı, tekrarsız), `None` = hepsi. Her çıktı `spec` boyutunda tam sayfa (`L` ya da `RGB` modunda) bir görüntüdür: beyaz zemin, içerik yazdırılabilir alana oran korunarak sığdırılmış ve ortalanmış, yatay içerik dikey kağıtta 90° döndürülmüş. Sayfalar tembel üretilir (generator), bir anda tek sayfa.
  - `def parse_page_ranges(value: str | None, page_count: int) -> list[int] | None` — `"1-3,5"` → `[1, 2, 3, 5]`. Aralığın dışı kırpılır, boş kalırsa `InvalidDocument("no_pages")`.
  - `def png_to_jpeg(data: bytes, quality: int = 90) -> bytes` (alfa → beyaz zemin) ve `def fit_jpeg(data: bytes, limits: JpegLimits | None) -> bytes` (sınırı aşmıyorsa aynı baytlar).

- [ ] **Step 1: Failing tests:**
  - `test_count_pages_pdf_and_image`.
  - `test_iter_pages_size_and_mode`: A4 300 dpi → 2480×3508. `gray=True` → mod `L`, değilse `RGB`.
  - `test_landscape_page_rotated_to_fit` (Review Focus 1): 1 dikey + 1 yatay sayfalık PDF. Yataydaki içerik döndürülmüş (örnek sayfada sol üste konmuş renkli bir kare doğru köşede bulunur), iki sayfa da sırayla gelir.
  - `test_content_fits_inside_margins`: kenar boşluğu bölgesi tamamen beyaz.
  - `test_page_selection`: `pages=[2]` → sadece 2. sayfa.
  - `test_encrypted_or_corrupt_pdf_raises_invalid_document` (Review Focus 2): rastgele baytlar ve parola korumalı PDF.
  - `test_too_many_pages`: 201 sayfalık PDF → `TooManyPages`.
  - `test_png_alpha_becomes_white` (Review Focus 3).
  - `test_fit_jpeg_respects_limits`: 9000×100 px JPEG → genişlik ≤ 8192. Sınır içindeki JPEG → baytlar aynen döner.
  - `test_parse_page_ranges`.
  - `test_iter_pages_is_lazy`: generator, ilk sayfayı aldıktan sonra ikinci sayfa render edilmemiş (pypdfium2 render çağrısı sayılarak).
- [ ] **Step 2:** FAIL. **Step 3:** Uygula. pypdfium2 ile `page.render(scale=dpi/72)`. Şifreli PDF'te parola deneme yok, doğrudan `InvalidDocument`. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: render PDF and images to print pages`

### Task 3: PWG Raster kodlayıcı

**Files:**
- Create: `custom_components/home_print/convert/pwg.py`
- Test: `tests/convert/test_pwg.py`, `tests/convert/pwg_decoder.py` (testler için spec'ten bağımsız yazılmış basit çözücü)

**Interfaces:**
- Produces:
  - `def encode_pwg(pages: Iterable[PIL.Image.Image], spec: PageSpec, *, duplex: bool, tumble: bool, sheet_back: str | None, copies: int = 1) -> Iterator[bytes]` — önce `b"RaS2"` sync word'ünü, sonra her sayfa için 1796 baytlık başlık + sıkıştırılmış veri üretir (stream). Çift taraf ve tek sayıda sayfa varsa sona boş beyaz bir arka sayfa ekler (Review Focus 4).
  - Başlık alanları PWG 5102.4'e göre (big-endian): `MediaClass`/`MediaType` boş olabilir; `PageSize` pt cinsinden; `HWResolution`; `Duplex`; `Tumble`; `cupsWidth`; `cupsHeight`; `cupsBitsPerColor=8`; `cupsBitsPerPixel` 8 (gri) / 24 (renk); `cupsBytesPerLine`; `cupsColorOrder=0`; `cupsColorSpace` 18 (sgray) / 19 (srgb); `cupsNumColors` 1/3; `TotalPageCount`; `CrossFeedTransform`/`FeedTransform` arka sayfa yönü için; `ImageBoxLeft/Top/Right/Bottom`; `PrintContentType`/`PrintQuality` boş/0 olabilir; `PrintRenderingIntent` boş; `PageSizeName` media adı.
  - Sıkıştırma: her satır başında satır tekrar sayısı (0–255, "bu satırdan n+1 tane"). Sonra piksel grupları: kontrol baytı 0–127 → sonraki piksel n+1 kez tekrar, 129–255 → 257−n farklı piksel düz yazılır, 128 → satırın kalanı beyaz (PWG raster'da beyaz dolgu). numpy ile satır karşılaştırma ve run tespiti hızlandırılır.
  - Arka sayfa (`sheet_back`): `normal` → dönüşüm yok. `flipped` / `rotated` / `manual-tumble` → PWG 5102.4 ve CUPS `cups-filters`'taki tablo izlenir (long-edge/short-edge × sheet-back). Uygulayıcı kaynağı (PWG 5102.4 Tablo ve CUPS `ppd-cache`/`pwgtoraster` mantığı) okuyup testte tabloyu açıkça yazar.

- [ ] **Step 1: Failing tests:**
  - `test_header_fields`: A4 300 dpi renk tek sayfa → sync `RaS2`. Çözülen başlıkta `cupsWidth=2480`, `cupsHeight=3508`, `HWResolution=(300,300)`, `cupsColorSpace=19`, `cupsNumColors=3`, `cupsBytesPerLine=7440`, `PageSize=(595,842)`, `TotalPageCount=1`.
  - `test_roundtrip_gray_and_color`: rastgele desenli küçük ve tam boy görüntüler kodlanıp `pwg_decoder` ile çözülünce piksel piksel aynı.
  - `test_compression_white_page_is_small`: boş A4 sayfası < 20 KB.
  - `test_duplex_odd_pages_adds_blank_back` (Review Focus 4): 3 sayfa + duplex → 4 sayfa çıkar, 4.'sü beyaz, `TotalPageCount=4`.
  - `test_back_side_transform_table`: `sheet_back` × `tumble` için arka sayfaların `CrossFeedTransform/FeedTransform` değerleri ya da piksel yönü tablodaki gibi. `rotated` + long-edge (`tumble=False`) DeskJet durumu açıkça test edilir.
  - `test_encode_is_streaming`: generator. Girdi sayfaları tembel tüketilir.
  - `test_encode_speed`: tipik metin sayfası (siyah satırlar, beyaz zemin) A4 300 dpi tek sayfa < 2 sn (CI için `@pytest.mark.slow` değil, sınır gevşek tutulur).
- [ ] **Step 2:** FAIL. **Step 3:** Uygula. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: PWG raster encoder`

### Task 4: Apple Raster (URF) kodlayıcı

**Files:**
- Create: `custom_components/home_print/convert/urf.py`
- Test: `tests/convert/test_urf.py`, `tests/convert/urf_decoder.py`

**Interfaces:**
- Produces: `def encode_urf(pages: Iterable[PIL.Image.Image], spec: PageSpec, *, duplex: bool, tumble: bool, copies: int = 1) -> Iterator[bytes]`. Dosya başlığı `b"UNIRAST\0"` + sayfa sayısı (uint32 BE). Her sayfa için 32 baytlık sayfa başlığı: bpp (8/24), colorspace (0 = sGray/W, 1 = sRGB), duplex (1 = yok, 2 = short-edge, 3 = long-edge), quality, genişlik, yükseklik, dpi. Ardından PWG ile aynı sıkıştırma ailesi (satır tekrarı + piksel run'ları, `0x80` = satır sonu beyaz). Sıkıştırma çekirdeği Task 3'ten paylaşılır (`pwg.py`'de `_encode_line`/`_encode_bitmap` olarak dışa açılır, URF bunu kullanır; tekrar yazılmaz).
- Consumes: `PageSpec`, Task 3'ün sıkıştırma yardımcıları.

- [ ] **Step 1: Failing tests:** `test_urf_header`, `test_urf_roundtrip_gray_color`, `test_urf_duplex_odd_pages_adds_blank_back`.
- [ ] **Step 2:** FAIL. **Step 3:** Uygula. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: Apple raster (URF) encoder`

### Task 5: Pipeline ve yazdırmaya bağlama

**Files:**
- Create: `custom_components/home_print/convert/pipeline.py`
- Modify: `custom_components/home_print/printing.py`, `custom_components/home_print/client.py` (`print_job` stream/bytes kabul eder; `page_ranges` dönüştürülmüş işte gönderilmez), `strings.json`, `translations/en.json`, `translations/tr.json`
- Test: `tests/convert/test_pipeline.py`, `tests/test_printing.py`, `tests/test_http.py`

**Interfaces:**
- Produces (`pipeline.py`):
  - `@dataclass(frozen=True) class PreparedJob: data: bytes, document_format: str, send_page_ranges: bool, page_count: int | None`
  - `def choose_target(src_fmt: str, caps: Capabilities) -> str | None` — Global Constraints'teki sıralar.
  - `def prepare(data: bytes, src_fmt: str, caps: Capabilities, options: PrintOptions, max_pages: int = 200) -> PreparedJob` — hedef `src_fmt` ise passthrough (`send_page_ranges=True`, JPEG için `fit_jpeg` uygulanır). Değilse render + encode, `send_page_ranges=False`. `ConvertError` alt sınıflarını yukarı fırlatır. Hedef yoksa `None` dönmez, `NoConversionRoute(ConvertError)` fırlatır.
- `printing.async_print`:
  - Tür kontrolünü (`FormatNotSupportedByPrinter`) artık `choose_target` yapar.
  - `prepare` `hass.async_add_executor_job` ile çağrılır. Hatalar şöyle eşlenir: `InvalidDocument` → yeni `InvalidDocumentError` (HTTP 400, anahtar `invalid_document`); `TooManyPages` → yeni `TooManyPagesError` (HTTP 400, `too_many_pages`, mesajda limit); `NoConversionRoute` → mevcut `FormatNotSupportedByPrinter` (422).
  - Event payload'a `converted_to` (str | None) ve `pages` (int | None) eklenir.
  - `coordinator.data` yoksa (yazıcı kapalı) önce `PrinterUnavailable` döner (dönüştürme denenmez).
- Türkçe hata metinleri sade ve "sen" dilinde. Örnek: "Dosya açılamadı. Bozuk ya da parola korumalı olabilir." ve "Bu belge çok uzun. En fazla {limit} sayfa yazdırabilirsin."

- [ ] **Step 1: Failing tests** `tests/convert/test_pipeline.py` (DeskJet fixture'ı ile):
  - `test_choose_target_deskjet`: PDF → `image/pwg-raster`, PNG → `image/jpeg`, JPEG → `image/jpeg`.
  - `test_choose_target_pdf_native_printer` (generic fixture): PDF → `application/pdf`.
  - `test_choose_target_urf_only_printer`: yalnızca `image/urf` → PDF ve PNG → `image/urf`.
  - `test_choose_target_none`: yalnızca `application/vnd.hp-PCL` → `NoConversionRoute`.
  - `test_prepare_pdf_to_pwg_gray_duplex_pages`: 3 sayfalık PDF, `monochrome`, `two-sided-long-edge`, `page_ranges="2-3"` → `document_format == "image/pwg-raster"`, `send_page_ranges is False`, çözülen sayfa sayısı 2, gri.
  - `test_prepare_passthrough_jpeg_keeps_page_ranges_flag`.
- [ ] **Step 2: Failing tests** `tests/test_printing.py` / `tests/test_http.py`:
  - DeskJet fixture'ıyla PDF yükleme → client `print_job` `document_format="image/pwg-raster"` ile çağrılır ve `page_ranges` gönderilmez.
  - Bozuk PDF → 400 `invalid_document`. 201 sayfa → 400 `too_many_pages`. Event'te `converted_to` ve `pages` var.
  - `prepare` executor'da çalışır (`hass.async_add_executor_job` patch'lenip çağrıldığı doğrulanır).
  - Review Focus 5: 150 sayfalık basit PDF uçtan uca (`prepare` gerçek, client sahte) hata vermeden tamamlanır. Süre makul (< 60 sn, gevşek sınır) ve tepe bellek `tracemalloc` ile bir sayfanın ham boyutunun 3 katını aşmaz (çıktı tamponu hariç).
- [ ] **Step 3:** FAIL. **Step 4:** Uygula. **Step 5:** PASS (tüm suite + ruff).
- [ ] **Step 6: Commit** `feat: convert documents the printer can't take directly`

### Task 6: Sabahki tek seferlik baskı testi için `remote_check.py`

**Files:**
- Modify: `scripts/remote_check.py`, `tests/test_remote_check.py`, `docs/testing/plan-1-manual.md`

**Interfaces:**
- Consumes: `convert/render.py`, `convert/pwg.py`, `convert/urf.py`, `convert/pipeline.py`. Bunlar `importlib` ile dosya yolundan yüklenir, `custom_components/home_print/__init__.py` çalıştırılmaz. Çalışma zamanı bağımlılıkları artık `pyipp==0.17.0 aiohttp pypdfium2 Pillow numpy`. Betik repo içinden (`scripts/` ile `custom_components/` kardeş klasör olarak) çalıştırılır. Tek dosya olarak indirilirse dönüştürme testleri `⏭ ATLANDI (convert modülleri bulunamadı)` olur.
- Validate-Job genişletmesi (baskısız): JPEG için de çift taraf / siyah-beyaz / renkli / 2 kopya durumları. Dönüştürülmüş hedef format için (`choose_target`'ın PDF'e verdiği format, DeskJet'te `image/pwg-raster`): varsayılan, çift taraf, siyah-beyaz, renkli. Validate-Job doküman baytı göndermez, yalnızca format/özellik kabulünü ölçer.
- Ek baskısız kontrol: örnek 3 sayfalık PDF gerçekten dönüştürülür (`prepare`). Çıktı boyutu ve süresi raporlanır, çözülüp sayfa sayısı doğrulanır.
- `--print` (TEK seferde bütün baskı testleri; varsayılan kapalı):
  1. JPEG tek sayfa ("Home Print test 1/2 — JPEG").
  2. 2 sayfalık örnek PDF, dönüştürülmüş, `two-sided-long-edge` (yazıcı destekliyorsa), siyah-beyaz, tek kağıt ("Home Print test 2/2 — PDF çift taraf").
  - Her iş için Get-Job-Attributes ile durum takibi: completed / aborted / canceled, `job-state-reasons`, `job-impressions-completed`. Çift tarafta beklenen 2 baskı yüzü.
  - Toplam en fazla 2 kağıt. Başlamadan önce Türkçe uyarı satırı basılır: kaç iş, kaç kağıt.
  - İş adları sabit kalır, kâğıtta okunabilsin diye örnek sayfalarda büyük yazıyla "Home Print test 1/2" ve "2/2 — ön yüz / arka yüz" metni bulunur (Pillow ile çizilir; arka yüzün ters çıkıp çıkmadığı evdeki biri bakarsa anlaşılsın diye "↑ ÜST" oku).
- [ ] **Step 1: Failing tests:** `--print` yokken hiçbir PRINT_JOB yok (mevcut test korunur). `--print` ile tam 2 PRINT_JOB: biri `image/jpeg`, diğeri DeskJet fixture'ında `image/pwg-raster` ve `sides=two-sided-long-edge`. Validate-Job JPEG varyantları. Convert modülleri yoksa ATLANDI.
- [ ] **Step 2:** FAIL. **Step 3:** Uygula. **Step 4:** PASS (tüm suite + ruff). `--help` ve 127.0.0.1:1 çalıştırması temiz.
- [ ] **Step 5:** `docs/testing/plan-1-manual.md`'yi güncelle (Türkçe, "sen", kısa maddeler): Ada repo'yu Mac'e nasıl alacak (zip olarak indirme ya da `git clone`, GitHub deposu yoksa sohbetten gönderilen zip), yeni pip satırı, bu geceki gibi baskısız komut, sabahki `--print` komutu (2 iş, en fazla 2 kağıt), sonuçların nasıl okunacağı.
- [ ] **Step 6: Commit** `feat: remote_check covers conversion and the single morning print run`
