# Home Print — Plan 2b: Baskı geçmişi ve tek dosya seçme düğmesi

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ada'nın kart istekleri (2026-11-16):
1. Kartın altındaki "Son iş" satırı kalkar. Bunun yerine durum satırının en sağında bir saat simgesi olur. Basınca açılan pencerede geçmiş baskılar listelenir ve her satır çöp kutusu simgesiyle silinebilir.
2. "Dosya seç" ve "Fotoğraf seç" tek düğmede birleşir. iOS'ta düğme doğrudan sistemin üç seçenekli menüsünü açar (Fotoğraf Arşivi / Fotoğraf Çek / Dosya Seç). Diğer cihazlarda kart aynı üç seçeneği kendisi gösterir: "Dosyadan seç", "Fotoğraf seç", "Fotoğraf çek".
3. Tarama düğmesi bu planda yok.
4. (Ada, 13:56) Son 7 günün dosyaları saklanır. Süre ayarlardan değiştirilebilir. Daha eski dosya ve kayıtlar kendiliğinden silinir. Çöp kutusu kaydı ve dosyayı birlikte siler. Kayda dokununca ikinci bir pencere açılır, dosyanın ön izlemesi aşağı doğru kaydırılabilir şekilde görünür.

**Architecture:** Geçmiş backend'de, her yazıcı girişi için HA `Store` ile tutulur (`home_print.history.<entry_id>`, en fazla 50 kayıt, en yeni önde). Yazdırılan dosyaların kendisi saklanmaz, yalnızca kayıt tutulur. Kayıt `printing.async_report_result` içinde eklenir. İşin son durumu `home_print/job` komutu bitmiş bir durum gördüğünde güncellenir. Kart yeni WS komutlarıyla (`home_print/history`, `home_print/history/delete`) geçmişi okur ve siler. Pencere kartın kendi shadow DOM'unda, HA iç bileşeni kullanmadan çizilir.

**Spec:** `docs/superpowers/specs/2026-11-15-home-print-design.md` §7.3 + bu belgedeki Ada istekleri.

## Global Constraints

- Kart tek dosya, derleme yok, harici bağımlılık yok. Dinamik metin yalnızca `textContent` ile eklenir. Stil yalnızca HA tema değişkenleriyle yapılır. Dokunma alanları ≥ 44 px. Metinler tr+en STRINGS tablosunda, Türkçe sade ve "sen" dilinde.
- Simgeler kart içinde satır içi SVG olarak çizilir (Material Design Icons yolları: `mdi:history`, `mdi:delete-outline`, `mdi:close`, `mdi:paperclip`, `mdi:image-multiple`, `mdi:camera`). `ha-icon` kullanılmaz.
- Geçmiş kaydı: `{"id": str (uuid4 hex), "time": ISO8601 UTC, "file_name": str, "user": str|None, "job_id": int|None, "state": "sent"|"completed"|"aborted"|"canceled"|"error", "pages": int|None, "converted_to": str|None, "error": str|None}`. Kayıt dosya içeriği taşımaz.
- En fazla 50 kayıt. Fazlası en eskiden silinir. Store yazımı `async_delay_save` ile (1 sn) yapılır, event loop'ta disk erişimi olmaz.
- WS `{"type":"home_print/history","entry_id"}` → `{"entries":[...]}` (en yeni önde). WS `{"type":"home_print/history/delete","entry_id","history_id"}` → `{"deleted": bool}` (alan adı `history_id`, çünkü `id` HA WS mesaj kimliği için ayrılmış). Bilinmeyen giriş → `not_found`. Silme, giriş `admin_only` ise yalnızca yöneticiye açıktır (`unauthorized`). Okuma oturum açmış herkese açıktır.
- Giriş kaldırılınca (`async_remove_entry`) store dosyası silinir.
- iOS tespiti: `/iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)`. iOS'ta tek bir gizli input kullanılır: `accept="application/pdf,image/jpeg,image/png,.pdf,.jpg,.jpeg,.png"`. Diğer cihazlarda düğme küçük bir menü açar: "Dosyadan seç" (aynı accept), "Fotoğraf seç" (`accept="image/jpeg,image/png"`), "Fotoğraf çek" (`accept="image/*" capture="environment"`). Üç yol da aynı `_onFile` doğrulamasından geçer.
- Pencere: kartın üstünde tam ekran yarı saydam arka plan, telefonda alttan açılan bir sayfa (bottom sheet), geniş ekranda ortalanmış en fazla 480 px. Kapatma yolları: X düğmesi, arka plana dokunma, Escape. Açıkken arkadaki sayfa kaymaz. Liste boşsa "Henüz baskı yok." yazar.
- Yazıcı değişince ya da kart yeniden bağlanınca pencere kapanır.

## Ek: dosya saklama ve ön izleme (Ada, 13:56)

Bu ek, yukarıdaki "dosyanın kendisi saklanmaz" kuralının yerine geçer. Spec'teki "yüklenen dosyalar diskte birikmez" ilkesinden bilinçli bir sapmadır (Ruling V).
- Yeni seçenek `CONF_HISTORY_DAYS` (options flow, varsayılan 7, aralık 0–90 gün; 0 = dosya saklanmaz, yalnızca kayıt tutulur ve o da 7 günde silinir). tr/en etiket: "Dosyaları sakla (gün)" / "Keep files (days)".
- Dosyalar `hass.config.path("home_print", entry_id, f"{id}{ext}")` altında, yazdırılan **orijinal** dosya olarak (dönüştürülmüş hali değil) saklanır. Disk işi executor'da yapılır. Toplam üst sınır her giriş için 500 MB'dır, aşılırsa en eski dosyalar silinir (kayıt kalır, `file: false` olur).
- Kayıt alanlarına `file: bool` (dosya hâlâ duruyor mu), `size: int|None`, `mime: str|None` eklenir. Kayıtların en fazla sayısı 50'den 200'e çıkar.
- Temizlik: kurulumda, her yeni kayıttan sonra ve günde bir kez (`async_track_time_interval`, 6 saatte bir yeterli) süresi dolan kayıtlar ve dosyalar silinir.
- `home_print/history/delete` dosyayı da siler.
- Ön izleme ucu: `GET /api/home_print/history/<entry_id>/<id>/page/<n>` (1 tabanlı). PDF için ilgili sayfa 100 dpi'de render edilip JPEG (kalite 80, en fazla 1200 px genişlik) olarak döner. Görsel için `n=1` küçültülmüş JPEG döner. Yanıt `Cache-Control: private, max-age=300`. Kimlik doğrulama zorunlu (`requires_auth=True`). Kart `<img>` için `hass.callWS({type:"auth/sign_path", path, expires: 300})` ile imzalı yol alır. Dosya yoksa 404. Sayfa yoksa 404. Render executor'da yapılır, mevcut `convert/render.py` kullanılır.
- `home_print/history` her kayıtta `pages` (bilinmiyorsa dosyadan sayılır, önbelleğe alınır) ve `file` alanını döndürür.
- Kart: kayda dokununca ikinci pencere (`data-role="preview-dialog"`) açılır. İçinde başlıkta dosya adı ve kapatma düğmesi, gövdede sayfalar alt alta `<img loading="lazy">` olarak, dikey kaydırmalı. `file:false` ise "Bu dosya artık saklanmıyor." yazar. Ön izleme açıkken arkadaki geçmiş penceresi açık kalır, kapatınca ona dönülür.

## Review Focus

1. **Silinen kayıt tekrar görünmemeli:** silme sonrası liste yenilenince de, HA yeniden başlayınca da (store diske yazılmış olmalı).
2. **Uzun Türkçe dosya adları ve 50 kayıt:** pencere telefonda taşmaz, liste kendi içinde kayar.
3. **Kart açıkken yeni baskı:** pencere açıksa yeni kayıt listeye en üstten eklenir (yeniden çekilir).
4. **iOS'ta çift menü yok:** iOS'ta kartın kendi menüsü hiç açılmaz.
5. **Geçmiş backend'e ulaşılamıyor:** pencere hata metni gösterir, kart çökmez, konsolda hata yok.
6. **Süresi dolan dosya:** 7 günden eski kayıt ve dosya listeden ve diskten kalkar. Süre ayarı değişince bir sonraki temizlikte uygulanır.
7. **Ön izleme ucu güvenliği:** başka girişin kaydına, `..` içeren id'lere ve kimliği doğrulanmamış isteklere erişilemez. id yalnızca 32 haneli onaltılık değer olabilir.

---

### Task 1: Backend — geçmiş deposu ve WS komutları

**Files:**
- Create: `custom_components/home_print/history.py`
- Modify: `custom_components/home_print/__init__.py` (`HomePrintData.history`, `async_setup_entry` içinde yükleme, `async_remove_entry`), `printing.py` (`async_report_result` kayıt ekler), `websocket.py` (iki yeni komut; `ws_job` bitmiş durumda kaydı günceller)
- Test: `tests/test_history.py`, `tests/test_websocket.py`, `tests/test_printing.py`

**Interfaces:**
- `class PrintHistory`: `async_load()`, `entries() -> list[dict]` (kopya, en yeni önde), `add(*, file_name, user, job_id, state, pages, converted_to, error) -> dict`, `update_state(job_id: int, state: str) -> bool`, `delete(entry_id: str) -> bool`, `async_remove()`. Store anahtarı `f"{DOMAIN}.history.{config_entry.entry_id}"`, sürüm 1.
- `HomePrintData.history: PrintHistory`.
- `async_report_result` başarıda `state="sent"`, hatada `state="error"` ve hata anahtarı ile kayıt ekler.
- `ws_job`, `completed/aborted/canceled` gördüğünde `history.update_state(job_id, state)` çağırır. `job_gone` durumunda kayıt `"completed"` sayılmaz, olduğu gibi kalır.
- [ ] **Step 1: Failing tests:** ekleme ve sıralama; 50 sınırı; silme; diske yazılıp yeniden yüklenme (`hass_storage` fixture); `update_state`; `async_report_result` başarı ve hata kaydı; WS history listesi; WS delete (var olan → true, olmayan → false); bilinmeyen giriş → not_found; admin_only + yönetici değil → delete unauthorized, okuma serbest; `ws_job` completed → kayıt completed; giriş kaldırılınca store silinir.
- [ ] **Step 2:** FAIL. **Step 3:** Uygula. **Step 4:** PASS (pytest + ruff).
- [ ] **Step 5: Commit** `feat: print history store and websocket commands`

### Task 1b: Dosya saklama, süre ayarı, temizlik ve ön izleme ucu

**Files:**
- Modify: `history.py`, `printing.py` (orijinal dosya baytlarını geçmişe verir), `config_flow.py` (seçenek), `const.py`, `strings.json` + çeviriler, `__init__.py` (zamanlayıcı)
- Create: `custom_components/home_print/preview.py` (HTTP view)
- Test: `tests/test_history.py`, `tests/test_preview.py`, `tests/test_config_flow.py`

**Interfaces:**
- `PrintHistory.add(..., data: bytes | None, mime: str | None)`: `CONF_HISTORY_DAYS > 0` ise dosyayı yazar.
- `PrintHistory.file_path(id) -> Path | None`, `async_cleanup(now=None)`.
- `HomePrintPreviewView`: `url = "/api/home_print/history/{entry_id}/{record_id}/page/{page}"`, `requires_auth = True`.
- [ ] **Step 1: Failing tests:** dosya yazılır ve kayıtta `file: true`; `CONF_HISTORY_DAYS=0` → dosya yazılmaz; 8 günlük kayıt temizlikte dosyasıyla silinir; 500 MB sınırı (küçük sınırla yamalanarak) en eski dosyayı siler; delete dosyayı siler; ön izleme: PDF sayfa 1 ve 2 JPEG döner, sayfa 3 → 404, kimliksiz → 401, başka girişin id'si → 404, geçersiz id → 404; options flow yeni alanı kaydeder.
- [ ] **Step 2:** FAIL. **Step 3:** Uygula. **Step 4:** PASS. **Step 5: Commit** `feat: keep printed files for a configurable number of days, with previews`

### Task 2: Kart — saat simgesi, geçmiş penceresi, tek seçme düğmesi

**Files:**
- Modify: `custom_components/home_print/frontend/home-print-card.js`, `tests/frontend/card.test.js`, `tests/frontend/fake-hass.js`, `docs/testing/plan-1-manual.md` (kart bölümü), `README.md` (kart özelliği bir cümle)

**Interfaces:**
- Kaldırılır: alttaki `last` satırı, ayrı `photo` düğmesi.
- Eklenir: başlık satırının sağında `data-role="history-button"` (saat SVG, `aria-label` tr "Geçmiş" / en "History"); pencere `data-role="history-dialog"` (listede her satır `data-role="history-item"`, içinde ad, tarih-saat yerel biçimde, kullanıcı, sayfa sayısı, durum simgesi ✓/✗/…, `data-role="history-delete"` çöp düğmesi `aria-label` "Sil"/"Delete"); tek düğme `data-role="pick"`; iOS dışında menü `data-role="pick-menu"` ve seçenekler `data-option="file|photo|camera"`; inputlar `data-role="input-file"`, `input-photo`, `input-camera`.
- Yardımcılar (`HomePrintCard.helpers`): `isIOS(nav)`, `formatHistoryTime(lang, iso)`, `historyStateIcon(state)`.
- [ ] **Step 1: Failing tests:** (ek) kayda dokununca ön izleme penceresi açılır, `auth/sign_path` çağrılır, sayfa sayısı kadar `<img>` oluşur, pencere dikey kayar, `file:false` metni, kapatınca geçmiş penceresine dönülür; saat düğmesi pencereyi açar, `home_print/history` çağrılır, satırlar doğru; çöp → `home_print/history/delete` ve satır kaybolur, liste yeniden çekilince de yok; X, arka plan ve Escape kapatır; boş liste metni; history çağrısı hata verince pencerede hata metni, konsolda hata yok; uzun ad ellipsis; pencere açıkken başarılı yükleme sonrası liste yenilenir; alttaki son iş satırı artık yok; iOS taklidinde `pick` tek inputu tıklar ve menü açılmaz; iOS dışında `pick` menüyü açar, üç seçenek doğru inputu tıklar, inputların accept/capture değerleri doğru; üç yoldan seçilen dosya aynı doğrulamadan geçer; markup içeren dosya adı ve kullanıcı adı metin olarak kalır.
- [ ] **Step 2:** FAIL. **Step 3:** Uygula. **Step 4:** PASS (npm test + pytest + ruff).
- [ ] **Step 5:** Belgeleri güncelle. **Step 6: Commit** `feat(card): history popup and single file picker`
