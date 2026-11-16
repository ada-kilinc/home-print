# Home Print — Plan 2b: Baskı geçmişi ve tek dosya seçme düğmesi

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ada'nın kart istekleri (2026-11-16):
1. Kartın altındaki "Son iş" satırı kalkar. Bunun yerine durum satırının en sağında bir saat simgesi olur. Basınca açılan pencerede geçmiş baskılar listelenir ve her satır çöp kutusu simgesiyle silinebilir.
2. "Dosya seç" ve "Fotoğraf seç" tek düğmede birleşir. iOS'ta düğme doğrudan sistemin üç seçenekli menüsünü açar (Fotoğraf Arşivi / Fotoğraf Çek / Dosya Seç). Diğer cihazlarda kart aynı üç seçeneği kendisi gösterir: "Dosyadan seç", "Fotoğraf seç", "Fotoğraf çek".
3. Tarama düğmesi bu planda yok.

**Architecture:** Geçmiş backend'de, her yazıcı girişi için HA `Store` ile tutulur (`home_print.history.<entry_id>`, en fazla 50 kayıt, en yeni önde). Yazdırılan dosyaların kendisi saklanmaz, yalnızca kayıt tutulur. Kayıt `printing.async_report_result` içinde eklenir. İşin son durumu `home_print/job` komutu bitmiş bir durum gördüğünde güncellenir. Kart yeni WS komutlarıyla (`home_print/history`, `home_print/history/delete`) geçmişi okur ve siler. Pencere kartın kendi shadow DOM'unda, HA iç bileşeni kullanmadan çizilir.

**Spec:** `docs/superpowers/specs/2026-11-15-home-print-design.md` §7.3 + bu belgedeki Ada istekleri.

## Global Constraints

- Kart tek dosya, derleme yok, harici bağımlılık yok. Dinamik metin yalnızca `textContent` ile eklenir. Stil yalnızca HA tema değişkenleriyle yapılır. Dokunma alanları ≥ 44 px. Metinler tr+en STRINGS tablosunda, Türkçe sade ve "sen" dilinde.
- Simgeler kart içinde satır içi SVG olarak çizilir (Material Design Icons yolları: `mdi:history`, `mdi:delete-outline`, `mdi:close`, `mdi:paperclip`, `mdi:image-multiple`, `mdi:camera`). `ha-icon` kullanılmaz.
- Geçmiş kaydı: `{"id": str (uuid4 hex), "time": ISO8601 UTC, "file_name": str, "user": str|None, "job_id": int|None, "state": "sent"|"completed"|"aborted"|"canceled"|"error", "pages": int|None, "converted_to": str|None, "error": str|None}`. Kayıt dosya içeriği taşımaz.
- En fazla 50 kayıt. Fazlası en eskiden silinir. Store yazımı `async_delay_save` ile (1 sn) yapılır, event loop'ta disk erişimi olmaz.
- WS `{"type":"home_print/history","entry_id"}` → `{"entries":[...]}` (en yeni önde). WS `{"type":"home_print/history/delete","entry_id","id"}` → `{"deleted": bool}`. Bilinmeyen giriş → `not_found`. Silme, giriş `admin_only` ise yalnızca yöneticiye açıktır (`unauthorized`). Okuma oturum açmış herkese açıktır.
- Giriş kaldırılınca (`async_remove_entry`) store dosyası silinir.
- iOS tespiti: `/iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)`. iOS'ta tek bir gizli input kullanılır: `accept="application/pdf,image/jpeg,image/png,.pdf,.jpg,.jpeg,.png"`. Diğer cihazlarda düğme küçük bir menü açar: "Dosyadan seç" (aynı accept), "Fotoğraf seç" (`accept="image/jpeg,image/png"`), "Fotoğraf çek" (`accept="image/*" capture="environment"`). Üç yol da aynı `_onFile` doğrulamasından geçer.
- Pencere: kartın üstünde tam ekran yarı saydam arka plan, telefonda alttan açılan bir sayfa (bottom sheet), geniş ekranda ortalanmış en fazla 480 px. Kapatma yolları: X düğmesi, arka plana dokunma, Escape. Açıkken arkadaki sayfa kaymaz. Liste boşsa "Henüz baskı yok." yazar.
- Yazıcı değişince ya da kart yeniden bağlanınca pencere kapanır.

## Review Focus

1. **Silinen kayıt tekrar görünmemeli:** silme sonrası liste yenilenince de, HA yeniden başlayınca da (store diske yazılmış olmalı).
2. **Uzun Türkçe dosya adları ve 50 kayıt:** pencere telefonda taşmaz, liste kendi içinde kayar.
3. **Kart açıkken yeni baskı:** pencere açıksa yeni kayıt listeye en üstten eklenir (yeniden çekilir).
4. **iOS'ta çift menü yok:** iOS'ta kartın kendi menüsü hiç açılmaz.
5. **Geçmiş backend'e ulaşılamıyor:** pencere hata metni gösterir, kart çökmez, konsolda hata yok.

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

### Task 2: Kart — saat simgesi, geçmiş penceresi, tek seçme düğmesi

**Files:**
- Modify: `custom_components/home_print/frontend/home-print-card.js`, `tests/frontend/card.test.js`, `tests/frontend/fake-hass.js`, `docs/testing/plan-1-manual.md` (kart bölümü), `README.md` (kart özelliği bir cümle)

**Interfaces:**
- Kaldırılır: alttaki `last` satırı, ayrı `photo` düğmesi.
- Eklenir: başlık satırının sağında `data-role="history-button"` (saat SVG, `aria-label` tr "Geçmiş" / en "History"); pencere `data-role="history-dialog"` (listede her satır `data-role="history-item"`, içinde ad, tarih-saat yerel biçimde, kullanıcı, sayfa sayısı, durum simgesi ✓/✗/…, `data-role="history-delete"` çöp düğmesi `aria-label` "Sil"/"Delete"); tek düğme `data-role="pick"`; iOS dışında menü `data-role="pick-menu"` ve seçenekler `data-option="file|photo|camera"`; inputlar `data-role="input-file"`, `input-photo`, `input-camera`.
- Yardımcılar (`HomePrintCard.helpers`): `isIOS(nav)`, `formatHistoryTime(lang, iso)`, `historyStateIcon(state)`.
- [ ] **Step 1: Failing tests:** saat düğmesi pencereyi açar, `home_print/history` çağrılır, satırlar doğru; çöp → `home_print/history/delete` ve satır kaybolur, liste yeniden çekilince de yok; X, arka plan ve Escape kapatır; boş liste metni; history çağrısı hata verince pencerede hata metni, konsolda hata yok; uzun ad ellipsis; pencere açıkken başarılı yükleme sonrası liste yenilenir; alttaki son iş satırı artık yok; iOS taklidinde `pick` tek inputu tıklar ve menü açılmaz; iOS dışında `pick` menüyü açar, üç seçenek doğru inputu tıklar, inputların accept/capture değerleri doğru; üç yoldan seçilen dosya aynı doğrulamadan geçer; markup içeren dosya adı ve kullanıcı adı metin olarak kalır.
- [ ] **Step 2:** FAIL. **Step 3:** Uygula. **Step 4:** PASS (npm test + pytest + ruff).
- [ ] **Step 5:** Belgeleri güncelle. **Step 6: Commit** `feat(card): history popup and single file picker`
