# Home Print — Plan 1: Çekirdek entegrasyon

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HA'ya ağ yazıcısı ekleyen (keşif + elle), durum/mürekkep sensörleri oluşturan ve PDF/JPEG/PNG dosyalarını doğrudan IPP ile yazdıran bir `home_print` özel entegrasyonu.

**Architecture:** `custom_components/home_print/` altında bir HA entegrasyonu. IPP iletişimi tek bir istemci modülünde (`client.py`, `pyipp` üzerinde) toplanır. Config flow, coordinator, entity'ler, servis ve yükleme ucu yalnızca bu istemciyi kullanır. Yazdırma mantığı (`printing.py`) servis ve yükleme ucu arasında ortaktır.

**Tech Stack:** Python (HA'nın güncel sürümünün istediği sürüm), Home Assistant custom integration API, `pyipp`, `pytest-homeassistant-custom-component`, `aioresponses`/mock.

**Spec:** `docs/superpowers/specs/2026-11-15-home-print-design.md`

## Global Constraints

- Domain `home_print`, görünen ad "Home Print". Event adı `home_print_job`. Servis `home_print.print_file`.
- Yükleme ucu: `POST /api/home_print/upload/<entry_id>`, HA kimlik doğrulaması zorunlu (`requires_auth=True`).
- HA'nın bütün kurulum tiplerinde çalışmalı (OS, Supervised, Container, Core). Supervisor'a bağımlılık yok.
- Bağımlılıklar yalnızca hazır wheel'i olan paketler. HA imajı Alpine/musl tabanlı: her bağımlılık için musllinux wheel ya da HA wheel deposu doğrulanmalı.
- Elle eklemede varsayılanlar: port `631`, yol `/ipp/print`, TLS kapalı, sertifika doğrulama açık.
- Varsayılan en fazla dosya boyutu: `25` MB. Bu planda desteklenen türler: `application/pdf`, `image/jpeg`, `image/png` (yazıcı desteklemiyorsa açık hata; dönüştürme Plan 3'te).
- Tür kontrolü dosya içeriğinden yapılır, uzantıdan değil.
- Yüklenen dosyalar diske birikmez.
- Arayüz metinleri (config flow, hatalar, servis açıklamaları) `translations/en.json` ve `translations/tr.json` içinde.
- Dışarıya hiçbir port açılmaz. Entegrasyon yalnızca yazıcıya giden istek yapar.
- Aynı yazıcı HA Print'te zaten ekliyse keşif onu tekrar önermez (unique ID = yazıcı UUID'si).

## Review Focus

1. **Yazıcı uykuda veya kapalı** (DeskJet'ler uykuya geçiyor): sensörler `unavailable` olmalı, entegrasyon çökmemeli, yazdırma `cannot_connect` benzeri açık bir hata döndürmeli. → Task 4 ve Task 5'e test eklendi.
2. **Yazıcının IP'si değişir (DHCP):** keşif aynı UUID'yi yeni adreste görünce mevcut kaydın host'unu güncellemeli, yeni kayıt açmamalı. → Task 3.
3. **Aynı yazıcı hem `_ipp._tcp` hem `_ipps._tcp` ile yayın yapar:** tek kayıt oluşmalı. → Task 3.
4. **Çok büyük yükleme:** sınırı aşan dosya tamamı belleğe okunmadan reddedilmeli (HTTP 413). → Task 5.
5. **Türkçe karakterli dosya adı** (`öğrenci_belgesi.pdf`): iş adı yazıcıya bozulmadan gitmeli, yükleme ve event düzgün çalışmalı. → Task 5.

---

### Task 1: Depo iskeleti, geliştirme ortamı ve keşif betikleri

**Files:**
- Create: `custom_components/home_print/__init__.py`, `manifest.json`, `const.py`
- Create: `hacs.json`, `requirements_test.txt`, `pyproject.toml` (pytest + ruff ayarları), `.gitignore`
- Create: `scripts/probe_printer.py`, `scripts/check_wheels.sh`
- Test: `tests/__init__.py`, `tests/conftest.py`, `tests/test_init.py`

**Interfaces:**
- Produces: `const.py` → `DOMAIN = "home_print"`, `DEFAULT_PORT = 631`, `DEFAULT_PATH = "/ipp/print"`, `DEFAULT_MAX_FILE_MB = 25`, `DEFAULT_SCAN_INTERVAL = 60`, `EVENT_JOB = "home_print_job"`, `CONF_BASE_PATH`, `CONF_VERIFY_SSL`, `CONF_MAX_FILE_MB`, `CONF_ADMIN_ONLY`, `CONF_DEFAULT_SIDES`, `CONF_DEFAULT_COLOR_MODE`.
- Produces: `tests/conftest.py` → `auto_enable_custom_integrations` fixture'ı otomatik kullanılır, `mock_client` fixture'ı (Task 2'nin `HomePrintClient`'ını patch'ler).

- [ ] **Step 1:** `manifest.json` yaz: `domain`, `name: "Home Print"`, `config_flow: true`, `iot_class: "local_polling"`, `zeroconf: ["_ipp._tcp.local.", "_ipps._tcp.local."]`, `requirements: ["pyipp==<HA core'un kullandığı sürüm>"]`, `dependencies: ["http"]`, `after_dependencies: ["zeroconf"]`, `version: "0.1.0"`, `codeowners`, `documentation`, `issue_tracker`.
- [ ] **Step 2:** `hacs.json`: `{"name": "Home Print", "render_readme": true}`. HA'nın min sürümünü `homeassistant` alanına yaz.
- [ ] **Step 3: Failing test** `tests/test_init.py::test_manifest_valid`: manifest'i yükler, `domain == "home_print"` ve iki zeroconf tipinin de bulunduğunu doğrular.
- [ ] **Step 4:** Çalıştır: `pytest tests/test_init.py -v` → önce FAIL, sonra manifest ile PASS.
- [ ] **Step 5:** `scripts/probe_printer.py <host> [--port 631] [--path /ipp/print] [--tls]`: `pyipp` ile Get-Printer-Attributes çağırır ve şunları yazdırır: `printer-make-and-model`, `printer-uuid`, `document-format-supported`, `sides-supported`, `print-color-mode-supported`, `page-ranges-supported`, `copies-supported`, `marker-names/levels/colors/types`, `urf-supported`, `pwg-raster-document-resolution-supported`. Ayrıca `http://<host>/eSCL/ScannerCapabilities` adresini dener ve var/yok bilgisini basar (Plan 4 için). Tam yanıtı `tests/fixtures/printer_<model>.json` olarak kaydetme seçeneği `--save` olsun.
- [ ] **Step 6:** `scripts/check_wheels.sh`: `python:3.x-alpine` imajında `pip install --only-binary=:all: pyipp pypdfium2 Pillow` dener ve sonucu raporlar. Çalıştır, sonucu PR açıklamasına yaz. `pypdfium2` musl'da kurulmuyorsa **dur ve Ada'ya bildir** (Plan 3'ün yaklaşımı değişir).
- [ ] **Step 7:** Ada'dan evdeki yazıcıda `python scripts/probe_printer.py <yazıcı-ip> --save` çalıştırmasını iste (Tailscale üzerinden). Çıkan fixture'ı commit'le. Yazıcı PDF'i kabul etmiyorsa bunu not et (Plan 3 önceliği yükselir).
- [ ] **Step 8: Commit** `chore: repo iskeleti, probe ve wheel kontrolü`

### Task 2: IPP istemcisi

**Files:**
- Create: `custom_components/home_print/client.py`, `custom_components/home_print/models.py`
- Test: `tests/test_client.py`, `tests/fixtures/printer_generic.json` (IPP Everywhere yazıcı yanıtı)

**Interfaces:**
- Produces (`models.py`, frozen dataclass'lar):
  - `Marker(name: str, color: str | None, level: int | None, kind: str)` — `level` 0-100, yazıcı `-1/-2/-3` dönerse `None`.
  - `Capabilities(document_formats: frozenset[str], sides: frozenset[str], color_modes: frozenset[str], copies_max: int, page_ranges: bool)`
  - `PrinterInfo(uuid: str, make_model: str, serial: str | None, state: str, state_reasons: tuple[str, ...], markers: tuple[Marker, ...], capabilities: Capabilities)` — `state` ∈ `"idle" | "processing" | "stopped"`.
  - `PrintOptions(copies: int = 1, sides: str = "one-sided", color_mode: str | None = None, page_ranges: str | None = None)` — `page_ranges` biçimi `"1-3,5"`.
  - `JobResult(job_id: int, state: str)`
- Produces (`client.py`):
  - `class HomePrintClient(host: str, port: int, base_path: str, tls: bool, verify_ssl: bool, session: aiohttp.ClientSession)`
  - `async def get_printer(self) -> PrinterInfo`
  - `async def print_job(self, data: bytes, *, document_format: str, job_name: str, user_name: str, options: PrintOptions) -> JobResult`
  - Hatalar: `HomePrintError` (taban), `CannotConnect`, `PrinterRejected(status: str)`, `UnsupportedOption(name: str)`.

- [ ] **Step 1: Failing tests** `tests/test_client.py`:
  - `test_get_printer_parses_fixture`: fixture'dan `make_model`, `uuid` (`urn:uuid:` öneki atılmış), `state == "idle"`, `capabilities.document_formats` içinde `"application/pdf"` ve marker seviyeleri.
  - `test_marker_unknown_level_is_none`: seviye `-3` → `level is None`.
  - `test_print_job_sends_attributes`: `pyipp` `execute` mock'lanır. `PRINT_JOB` çağrısında `document-format`, `job-name`, `requesting-user-name`, `copies`, `sides`, `print-color-mode`, (`page_ranges` verildiyse) `page-ranges` ve `data` bulunduğu doğrulanır. Dönüş `JobResult(job_id=42, state="pending")`.
  - `test_print_job_skips_unsupported_option`: yazıcı `page-ranges` desteklemiyorsa ve istenmişse `UnsupportedOption("page_ranges")` fırlatılır (Plan 3 bunu dönüştürmeyle çözecek).
  - `test_connection_error_raises_cannot_connect`: `pyipp.IPPConnectionError` → `CannotConnect`.
  - `test_ipp_error_status_raises_rejected`: IPP status `client-error-document-format-not-supported` → `PrinterRejected`.
- [ ] **Step 2:** Çalıştır `pytest tests/test_client.py -v` → FAIL.
- [ ] **Step 3:** `client.py` ve `models.py`'yi yaz. URI `ipp(s)://host:port/base_path`. `pyipp.IPP` örneğini dışarıdan verilen `session` ile oluştur. Print-Job için `IppOperation.PRINT_JOB`, job template özellikleri `job-attributes-tag` grubunda.
- [ ] **Step 4:** Çalıştır → PASS.
- [ ] **Step 5: Commit** `feat: IPP istemcisi ve modeller`

### Task 3: Config flow (keşif + elle) ve options flow

**Files:**
- Create: `custom_components/home_print/config_flow.py`, `strings.json`, `translations/en.json`, `translations/tr.json`
- Test: `tests/test_config_flow.py`

**Interfaces:**
- Consumes: `HomePrintClient.get_printer()`, `CannotConnect`.
- Produces: config entry `data = {CONF_HOST, CONF_PORT, CONF_BASE_PATH, CONF_SSL, CONF_VERIFY_SSL}`, `unique_id = PrinterInfo.uuid`, `title = PrinterInfo.make_model`. Options: `CONF_DEFAULT_SIDES` (vars. `"one-sided"`), `CONF_DEFAULT_COLOR_MODE` (vars. `None` = yazıcı varsayılanı), `CONF_MAX_FILE_MB` (vars. 25, aralık 1-200), `CONF_SCAN_INTERVAL` (vars. 60, aralık 15-3600 sn), `CONF_ADMIN_ONLY` (vars. `False`).

- [ ] **Step 1: Failing tests:**
  - `test_user_flow_creates_entry`: host girilir, varsayılan port/yol uygulanır, entry oluşur, `unique_id` UUID'dir.
  - `test_user_flow_cannot_connect`: `errors == {"base": "cannot_connect"}`, form tekrar gösterilir.
  - `test_zeroconf_discovery_confirm`: `_ipp._tcp` bilgisi (TXT `rp=ipp/print`, `UUID=...`) → onay formu → entry. `rp` TXT değeri `base_path` olarak kullanılır.
  - `test_zeroconf_ipps_sets_tls`: `_ipps._tcp` → `CONF_SSL=True`.
  - `test_zeroconf_same_uuid_both_types_single_entry` (Review Focus 3): aynı UUID ile `_ipp` sonra `_ipps` → ikincisi `already_configured`.
  - `test_zeroconf_updates_host_on_ip_change` (Review Focus 2): mevcut entry, aynı UUID yeni IP → abort `already_configured` ve entry'nin host'u güncellenmiş.
  - `test_options_flow_saves_values`.
- [ ] **Step 2:** Çalıştır → FAIL.
- [ ] **Step 3:** `config_flow.py`'yi yaz. TXT'de UUID yoksa `get_printer().uuid` kullanılır. Hata anahtarları: `cannot_connect`, `unknown`. Türkçe çeviriler sade dille: "Yazıcıya bağlanılamadı. Adresi ve yazıcının açık olduğunu kontrol et."
- [ ] **Step 4:** Çalıştır → PASS.
- [ ] **Step 5: Commit** `feat: config flow, zeroconf keşfi ve ayarlar`

### Task 4: Coordinator ve entity'ler

**Files:**
- Create: `custom_components/home_print/coordinator.py`, `entity.py`, `sensor.py`, `binary_sensor.py`
- Modify: `custom_components/home_print/__init__.py` (setup/unload, `runtime_data`)
- Test: `tests/test_sensor.py`, `tests/test_binary_sensor.py`, `tests/test_init.py`

**Interfaces:**
- Consumes: `HomePrintClient`, `PrinterInfo`, `Marker`.
- Produces:
  - `type HomePrintConfigEntry = ConfigEntry[HomePrintData]`; `HomePrintData(client: HomePrintClient, coordinator: HomePrintCoordinator, last_job: LastJob | None)`
  - `LastJob(file_name: str, job_id: int | None, state: str, user: str | None, time: datetime)`
  - `HomePrintCoordinator(DataUpdateCoordinator[PrinterInfo])`, aralık = `CONF_SCAN_INTERVAL`. `CannotConnect` → `UpdateFailed` (entity'ler `unavailable`).
  - `def async_set_last_job(self, job: LastJob) -> None` (coordinator'da; dinleyicileri günceller).
  - Entity'ler (`has_entity_name=True`, cihaz = yazıcı UUID'si):
    - `sensor` `status`: değer `idle|processing|stopped` (enum, çevirili), özellik `reasons`.
    - `sensor` marker başına bir tane: `unique_id = f"{uuid}_marker_{index}"`, birim `%`, özellikler `color`, `kind`.
    - `binary_sensor` `problem` (`device_class=problem`): `state_reasons` içinde `media-empty`, `media-jam`, `door-open`, `cover-open`, `marker-supply-empty`, `toner-empty` öneklerinden biri varsa açık. `none` ve `-report` son ekliler sayılmaz.
    - `sensor` `last_job`: değer dosya adı, özellikler `state`, `user`, `time`.

- [ ] **Step 1: Failing tests:**
  - `test_status_and_marker_sensors_created`: fixture'daki her marker için sensör, doğru yüzde.
  - `test_problem_binary_sensor_on_media_empty`: `state_reasons=("media-empty-error",)` → `on`; `("none",)` → `off`.
  - `test_entities_unavailable_when_printer_offline` (Review Focus 1): ilk yükleme sonrası `get_printer` `CannotConnect` → yenilemeden sonra tüm entity'ler `unavailable`, entry `loaded` kalır.
  - `test_setup_fails_retry_when_offline_at_start`: kurulumda yazıcı kapalı → `ConfigEntryNotReady` (HA tekrar dener).
  - `test_unload_entry`.
- [ ] **Step 2:** Çalıştır → FAIL.
- [ ] **Step 3:** Uygula. `__init__.py` platformlar: `sensor`, `binary_sensor`.
- [ ] **Step 4:** Çalıştır → PASS.
- [ ] **Step 5: Commit** `feat: durum, mürekkep ve sorun sensörleri`

### Task 5: Ortak yazdırma, `print_file` servisi ve yükleme ucu

**Files:**
- Create: `custom_components/home_print/printing.py`, `services.py`, `services.yaml`, `http.py`
- Modify: `__init__.py` (servisi `async_setup`'ta, view'u bir kez kaydet), `strings.json` ve çeviriler (servis alanları, hata mesajları)
- Test: `tests/test_printing.py`, `tests/test_services.py`, `tests/test_http.py`

**Interfaces:**
- Consumes: `HomePrintConfigEntry`, `HomePrintClient.print_job`, `PrintOptions`, `JobResult`, `async_set_last_job`, `EVENT_JOB`.
- Produces:
  - `printing.py`:
    - `def sniff_format(data: bytes) -> str | None` — `%PDF-` → `application/pdf`, `FF D8 FF` → `image/jpeg`, `89 50 4E 47 0D 0A 1A 0A` → `image/png`, aksi `None`.
    - `async def async_print(hass: HomeAssistant, entry: HomePrintConfigEntry, data: bytes, *, file_name: str, options: PrintOptions, user: User | None) -> JobResult`
    - Hatalar (`HomeAssistantError` alt sınıfları, çeviri anahtarlı): `FileTooLarge`, `UnsupportedFileType`, `FormatNotSupportedByPrinter`, `PrinterUnavailable`.
    - Başarı ya da hata, her durumda `EVENT_JOB` fırlatılır: `{"entry_id", "file_name", "user_id", "user_name", "job_id", "result": "sent" | "error", "error": str | None}`. Ardından `last_job` güncellenir.
  - `home_print.print_file` servisi: alanlar `config_entry_id` (zorunlu, entegrasyon seçici), `path` (zorunlu, `hass.config.is_allowed_path` ile kontrol), `copies`, `sides`, `color_mode`, `page_ranges`. Yanıt döndürür (`SupportsResponse.OPTIONAL`): `{"job_id": int}`.
  - `HomePrintUploadView`: `url = "/api/home_print/upload/{entry_id}"`, `name = "api:home_print:upload"`, `requires_auth = True`. Multipart alanlar: `file` (zorunlu), `copies`, `sides`, `color_mode`, `page_ranges`. Yanıtlar: `200 {"job_id": int}`, `400` (geçersiz alan / tür), `401` (HA tarafından), `403` (`CONF_ADMIN_ONLY` açık ve kullanıcı yönetici değil), `404` (entry yok), `413` (boyut), `502` (yazıcıya ulaşılamadı), `422` (yazıcı formatı desteklemiyor). Hata gövdesi `{"error": <çeviri anahtarı>, "message": <metin>}`.

- [ ] **Step 1: Failing tests** `tests/test_printing.py`:
  - `test_sniff_format` (pdf/jpeg/png/bilinmeyen; `.pdf` adlı ama içeriği PNG olan dosya PNG çıkar).
  - `test_async_print_rejects_too_large`: `CONF_MAX_FILE_MB=1`, 1 MB + 1 bayt → `FileTooLarge`, event `result="error"`.
  - `test_async_print_rejects_format_not_supported_by_printer`: yazıcı yalnızca `image/urf` destekliyor, PDF gönderilir → `FormatNotSupportedByPrinter`.
  - `test_async_print_offline_raises_unavailable` (Review Focus 1): `CannotConnect` → `PrinterUnavailable`.
  - `test_async_print_fires_event_and_sets_last_job`.
  - `test_async_print_turkish_file_name` (Review Focus 5): `öğrenci_belgesi.pdf` → `job_name` ve event'te aynen.
- [ ] **Step 2: Failing tests** `tests/test_services.py`: izinli bir yoldan yazdırma ve `job_id` yanıtı; izin verilmeyen yol → `ServiceValidationError`.
- [ ] **Step 3: Failing tests** `tests/test_http.py` (`hass_client` ve `hass_client_no_auth` fixture'larıyla):
  - `test_upload_requires_auth` → 401.
  - `test_upload_prints_pdf` → 200 ve `job_id`.
  - `test_upload_admin_only_blocks_non_admin` → 403.
  - `test_upload_unknown_entry` → 404.
  - `test_upload_too_large_rejected_without_full_read` (Review Focus 4): `Content-Length` sınırın üstündeyse okumadan 413. `Content-Length` yoksa akış okunurken sınır aşıldığı anda 413. Okunan bayt sayısı sınır + bir parça boyutunu geçmez.
  - `test_upload_printer_offline` → 502.
- [ ] **Step 4:** Çalıştır → FAIL.
- [ ] **Step 5:** Uygula. Dosya bellekte (`bytes`) tutulur ve diske yazılmaz. Böylece spec'teki "dosyalar birikmez" şartı kendiliğinden sağlanır. Multipart okuma parça parça yapılır, sayaç sınırı aşınca durur. `user` = `request["hass_user"]`.
- [ ] **Step 6:** Çalıştır `pytest -v` (tüm suite) → PASS. `ruff check .` temiz.
- [ ] **Step 7: Commit** `feat: print_file servisi ve kimlik doğrulamalı yükleme ucu`

### Task 6: Evdeki yazıcıyla gerçek test

**Files:**
- Create: `docs/testing/plan-1-manual.md` (adımlar ve sonuçlar)

- [ ] **Step 1:** Ada'nın HA'sına `custom_components/home_print` klasörünü kopyala (ya da HACS'a özel depo olarak ekle), HA'yı yeniden başlat.
- [ ] **Step 2:** Ayarlar → Cihazlar ve Hizmetler: DeskJet "Keşfedildi" olarak görünüyor mu? Ekle. Görünmüyorsa elle IP ile ekle ve bunu not et.
- [ ] **Step 3:** Durum, mürekkep ve sorun sensörleri doğru mu? (Mürekkep yüzdeleri HP Smart uygulamasıyla karşılaştırılır.)
- [ ] **Step 4:** Geliştirici Araçları → Eylemler: `home_print.print_file` ile `/media` altındaki tek sayfalık bir PDF'i yazdır. Ardından çift taraf ve siyah-beyaz seçenekleriyle tekrar dene.
- [ ] **Step 5:** Telefondan, Tailscale üzerinden `curl -H "Authorization: Bearer <uzun ömürlü token>" -F file=@test.pdf https://<ha>/api/home_print/upload/<entry_id>` ile yazdır.
- [ ] **Step 6:** Yazıcı uykudayken yazdır: iş gidiyor mu, yoksa açık bir hata mı dönüyor? Sonucu not et.
- [ ] **Step 7:** Sonuçları `docs/testing/plan-1-manual.md`'ye yaz. **Commit** `test: plan 1 gerçek cihaz sonuçları`
