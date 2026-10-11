# Etsy Dijital Ürün Botu

Her sabah Etsy için **4 dijital ürün** hazırlar. Ürünler Telegram'a **✅ Onayla / ❌ Reddet** butonlarıyla gelir. Onayladığınız ürün birkaç dakika içinde Etsy'de yayınlanır.

Sistemin kullandığı servislerin hepsi ücretsiz:

| Parça | Servis | Ücret |
|---|---|---|
| Çalıştığı yer | GitHub Actions | Ücretsiz (depo herkese açık olduğu için dakika sınırı yok) |
| Metinler ve pazar araştırması | Google Gemini (yedek: Cloudflare) + Etsy arama verisi | Ücretsiz |
| Görseller | Cloudflare Workers AI – FLUX (yedek: Pollinations) | Ücretsiz (günlük 10.000 "neuron") |
| Onay | Telegram botu | Ücretsiz |
| Panel | GitHub Pages (şifreli) | Ücretsiz |

> Depo herkese açık olsa da **tüm ürün verileri, dosyalar ve Etsy anahtarları şifrelidir**. Dışarıdan bakan biri sadece kodu görebilir.

## Ürettiği ürün türleri
- **Duvar sanatı (3'lü set):** 5 farklı oranda, 300 DPI JPG. Oda mockup'ı dahil.
- **Boyama sayfaları:** 8 sayfa, US Letter ve A4 PDF.
- **Clipart:** 12 adet şeffaf arka planlı PNG.
- **Dijital kağıt:** 10 adet kesintisiz (seamless) desen, 12x12 inç.
- **Tumbler sublimasyon baskısı:** 20 oz skinny, 2 tasarım, PNG.

Her ürün için bot sırasıyla şunları yapar: Etsy arama verisiyle niş seçer, İngilizce SEO başlığı yazar, 13 etiket ve açıklama hazırlar, fiyatı belirler, ilan için 4-7 görsel üretir ve teslimat dosyalarını paketler (her dosya 20 MB'tan küçük). Etsy'de yasak olan ürün türlerinden (AI prompt paketleri vb.) ve marka/karakter isimlerinden otomatik olarak kaçınır.

---

## Kurulum (bir kerelik, yaklaşık 30 dakika)

### 1. GitHub deposu
1. [github.com](https://github.com) üzerinde ücretsiz hesap açın.
2. Sağ üstteki **+** menüsünden **New repository** seçin. Ad olarak `etsy-bot` yazın ve **Public** seçeneğini işaretleyin. Ardından **Create repository** butonuna basın.
3. Açılan sayfada **uploading an existing file** linkine tıklayın. Bu klasördeki **tüm dosya ve klasörleri** sürükleyip bırakın, sonra **Commit changes** deyin.
   - ⚠️ `.github` klasörü de mutlaka yüklenmeli. Mac'te gizli dosyaları görmek için Finder'da `Cmd + Shift + .` tuşlarına basın.
4. **Settings → Actions → General** sayfasının en altındaki *Workflow permissions* bölümünde **Read and write permissions** seçin ve kaydedin.
5. **Settings → Pages** sayfasında *Source* olarak **GitHub Actions** seçin.

### 2. Ücretsiz yapay zekâ anahtarları
- **Gemini:** [aistudio.google.com/apikey](https://aistudio.google.com/apikey) adresinde **Create API key** deyin ve anahtarı kopyalayın.
- **Cloudflare (görseller için):**
  1. [dash.cloudflare.com](https://dash.cloudflare.com) üzerinde ücretsiz hesap açın.
  2. Sol menüden **AI → Workers AI** sayfasına gidin ve **Use REST API** seçin.
  3. **Create a Workers AI API Token** ile token oluşturun ve kopyalayın.
  4. Aynı sayfadaki **Account ID** değerini de kopyalayın.

### 3. Telegram ve Etsy bilgileri
- **Telegram bot token:** Telegram'da @BotFather'a yazın, `/mybots` → mevcut botunuz → **API Token** yolunu izleyin.
- **Chat ID:** `6251307799` (eski sistemde kullanılan, sizin Telegram ID'niz).
- **Etsy:** [etsy.com/developers/your-apps](https://www.etsy.com/developers/your-apps) sayfasından uygulamanızı açın.
  - **Keystring** ve **Shared secret** değerlerini kopyalayın.
  - **Callback URLs** alanına şunu ekleyin: `https://KULLANICI-ADINIZ.github.io/etsy-bot/callback.html`. Buradaki KULLANICI-ADINIZ, GitHub kullanıcı adınızın küçük harfli yazımıdır.
  - Uygulama durumu "Pending" görünüyorsa Etsy'nin onaylamasını beklemeniz gerekir.

### 4. Gizli anahtarları GitHub'a girin
Deponuzda **Settings → Secrets and variables → Actions → New repository secret** yolunu izleyin ve aşağıdaki anahtarları tek tek ekleyin:

| Ad | Değer |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather'dan aldığınız token |
| `TELEGRAM_CHAT_ID` | `6251307799` |
| `ETSY_KEYSTRING` | Etsy keystring |
| `ETSY_SHARED_SECRET` | Etsy shared secret |
| `GEMINI_API_KEY` | Gemini anahtarı |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare Account ID |
| `CLOUDFLARE_API_TOKEN` | Cloudflare token |
| `STATE_KEY` | Uzun, rastgele bir şifre (en az 30 karakter). Verileriniz bununla şifrelenir. **Sonradan değiştirmeyin.** |
| `PANEL_PASSWORD` | Web paneline girerken kullanacağınız şifre |

### 5. Test ve Etsy bağlantısı
1. **Actions** sekmesinde **Kurulum testi** işini seçin ve **Run workflow** deyin. Yaklaşık 1 dakika sonra Telegram'a ✅/❌ listesi gelir. ❌ olan satırları düzeltin. "Etsy mağaza bağlantısı" satırının bu aşamada ❌ olması normaldir.
2. Telegram'da botunuza `/etsy` yazın, gelen butona basın ve Etsy'de **Allow access** deyin.
3. Açılan sayfada **Kopyala** butonuna basın ve kopyaladığınız metni Telegram'a gönderin. Daha hızlı bir yol da var: **Actions → Etsy bağla → Run workflow** açıp adresi oraya yapıştırın.
4. "🟢 Etsy bağlandı" mesajı gelince kurulum tamamdır.

### 6. İlk üretim
**Actions → Günlük ürün üretimi → Run workflow** ile hemen ürün üretebilirsiniz. Telegram'a `/uret` yazmak da aynı işi görür. Bundan sonra bot her sabah **09:23'te** kendiliğinden çalışır.

---

## Günlük kullanım
- Ürünler Telegram'a gelir. **✅ Onayla ve yayınla** butonuna bastığınızda ürün, bot bir sonraki kontrolünde (en geç ~10-20 dakika içinde) Etsy'de yayınlanır ve link size gelir.
- **❌ Reddet** butonu ürünü siler.
- Telegram komutları: `/durum`, `/bekleyen`, `/uret`, `/uret 2`, `/etsy`, `/panel`, `/yardim`
- Web paneli `https://KULLANICI-ADINIZ.github.io/etsy-bot/` adresindedir ve `PANEL_PASSWORD` ile açılır.

## Ayarlar (`settings.json`)
- `products_per_day`: Günlük ürün sayısı (varsayılan 4).
- `publish_mode`: `"active"` onaylanan ürünü hemen yayınlar. `"draft"` seçerseniz ürün Etsy'de taslak olarak bekler.
- `product_types`: Hangi türlerin hangi sıklıkla seçileceği. Bir türü kapatmak için listeden silin.
- `price_ranges_usd`: Tür başına fiyat aralığı (USD). Mağazanız TL ile çalışıyorsa fiyat güncel kurla çevrilir.

## Eski Abacus ürünlerini taşıma (isteğe bağlı)
1. `ABACUS_DATABASE_URL` adında bir secret ekleyin. Değeri, eski projedeki `shared/.env` dosyasında yazan `DATABASE_URL` değeridir.
2. **Actions → Abacus ürünlerini içe aktar → Run workflow** deyin. Aktarılan ürünler onay için Telegram'a gelir.

Yasak veya yanıltıcı olan ürünler aktarılmaz. Bunlar: AI prompt paketi, gerçek SVG olmadığı hâlde "SVG/Cricut" diye satılan ürün, "GoodNotes" marka adı geçen planlayıcı.

Taşıma tamamlanınca Abacus'taki zamanlanmış görevi durdurun ve aboneliği iptal edin.

## Bilinmesi gerekenler
- Etsy'de her yayınlanan ilan için Etsy **0,20 $ listeleme ücreti** alır. Bu ücret Etsy'nin kendi ücretidir, bot ek bir masraf çıkarmaz.
- Açıklamalara Etsy kurallarının gerektirdiği "AI araçları yardımıyla tasarlandı" notu otomatik eklenir.
- Görseller yaklaşık 1900 piksel üretilip baskı boyutuna büyütülür. Büyük baskılar (24x36 inç gibi) yaklaşık 200 DPI kalitesine denk gelir; normal izleme mesafesinde iyi görünür.
- GitHub, zamanlanmış işleri bazen birkaç dakika geç başlatabilir.
