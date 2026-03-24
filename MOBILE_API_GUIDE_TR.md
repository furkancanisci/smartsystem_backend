# Akilli Sulama Mobil API Rehberi

Bu dokuman, mobil ekibin backend API'sine hizli ve dogru sekilde baglanabilmesi icin hazirlanmistir.

## 1) Genel Bilgiler

- Protokol: HTTP/HTTPS (REST)
- Veri formati: JSON
- Kimlik dogrulama: Yok (token/JWT yok)
- Sunucu: Render uzerinde calisan FastAPI
- MQTT komut kanali: `smart_irrigation/commands`
- MQTT sensor kanali: `smart_irrigation/sensors`

Not:
- Mobil taraf sadece REST API'yi kullanir.
- Cihaz ile sunucu arasindaki veri akisinda MQTT kullanilir.

## 2) Base URL

Ornek:

```text
https://<render-service-name>.onrender.com
```

Tum endpoint cagrilari bu URL uzerinden yapilmalidir.

## 3) Ortak Hata Davranislari

Backend tipik olarak su HTTP kodlarini dondurur:

- `200 OK`: Basarili
- `400 Bad Request`: Gecersiz komut/veri
- `401 Unauthorized`: Hatali sifre (login endpointi)
- `404 Not Found`: Cihaz bulunamadi
- `422 Unprocessable Entity`: Eksik/yanlis body format
- `500 Internal Server Error`: Sunucu hatasi

Hata govdesi genelde:

```json
{
  "detail": "..."
}
```

## 4) Endpointler (Detayli)

## 4.1 Saglik Kontrolu

### GET /
Sunucunun ayakta oldugunu dogrulamak icin.

Ornek yanit:

```json
{
  "message": "Advanced Smart Irrigation Server is Active!"
}
```

## 4.2 Login / Kayit

### POST /api/login
Bu endpointte kullanici yoksa otomatik olusturulur, varsa sifre kontrolu yapilir.

Request body:

```json
{
  "kullanici_adi": "furkan",
  "sifre": "123456"
}
```

Basarili yanit (yeni kullanici):

```json
{
  "message": "New user registered and logged in.",
  "kullanici_id": 1,
  "status": "success"
}
```

Basarili yanit (mevcut kullanici):

```json
{
  "message": "Login successful.",
  "kullanici_id": 1,
  "status": "success"
}
```

Hata:
- `401`: Yanlis sifre

Mobil notu:
- Ayrica token donmedigi icin `kullanici_id` degerini uygulama tarafinda saklayin.

## 4.3 Kullaniciya Ait Bolgeler

### GET /api/kullanici/{kullanici_id}/bolgeler
Kullanici bolgelerini listeler.

Ornek yanit:

```json
[
  { "id": 10, "bolge_adi": "Sera-1" },
  { "id": 11, "bolge_adi": "Bahce" }
]
```

## 4.4 Kullaniciya Ait Cihazlar

### GET /api/kullanici/{kullanici_id}/cihazlar
Kullanicinin bolgelerine atanmis cihazlarin ozet listesini dondurur.

Ornek yanit:

```json
[
  {
    "cihaz_id": "esp32_01",
    "bolge_adi": "Sera-1",
    "toprak_nemi_yuzde": 42.5,
    "valf_durumu": "KAPALI"
  }
]
```

## 4.5 Cihaz Detay (Tam Durum)

### GET /api/cihaz/{cihaz_id}/tam_durum
Tek bir cihazin detayli anlik durumunu dondurur.

Ornek yanit:

```json
{
  "cihaz_id": "esp32_01",
  "bolge": "Sera-1",
  "bitki_turu": "Domates",
  "toprak_nemi_yuzde": 39.2,
  "valf_durumu": "KAPALI",
  "otomatik_sulama": true,
  "hedef_nem_esigi": 45.0,
  "son_guncelleme": "23-03-2026 21:45:12"
}
```

Hata:
- `404`: Device not found.

## 4.6 Cihaz Gecmisi

### GET /api/cihaz/{cihaz_id}/gecmis?limit=50
Cihazin nem/valf gecmisini getirir.

Query parametreleri:
- `limit` (opsiyonel, varsayilan: 50)

Ornek yanit:

```json
[
  { "nem": 41.0, "valf": "KAPALI", "zaman": "21:40" },
  { "nem": 39.5, "valf": "ACIK", "zaman": "21:35" }
]
```

Not:
- Liste yeni kayittan eskiye dogru gelir.

## 4.7 Cihaz Ayarlari

### POST /api/cihaz/{cihaz_id}/ayarlar
Otomatik sulama aktifligi ve manuel nem esigi ayari.

Request body:

```json
{
  "otomatik_sulama_aktif": true,
  "nem_esigi": 40.0
}
```

Basarili yanit:

```json
{
  "message": "Device settings updated successfully."
}
```

Hata:
- `404`: Device not found.

## 4.8 Cihaz Atama (Bolge + Bitki Profili)

### POST /api/cihaz/{cihaz_id}/ata
Cihazi bir bolgeye ve bitki profiline baglar.

Request body:

```json
{
  "bolge_id": 10,
  "bitki_profili_id": 2
}
```

Basarili yanit:

```json
{
  "message": "Device successfully assigned to region and plant profile."
}
```

Hata:
- `404`: Device not found.

## 4.9 Bolge Ekleme

### POST /api/bolge/ekle
Yeni bolge olusturur.

Request body:

```json
{
  "kullanici_id": 1,
  "bolge_adi": "Sera-2"
}
```

Basarili yanit:

```json
{
  "message": "Region 'Sera-2' created successfully."
}
```

## 4.10 Bitki Profili Ekleme

### POST /api/bitki_profili/ekle
Yeni bitki profili olusturur.

Request body:

```json
{
  "bitki_adi": "Domates",
  "ideal_nem_esigi": 45.0,
  "maksimum_nem": 70.0
}
```

Basarili yanit:

```json
{
  "message": "Plant profile 'Domates' added successfully."
}
```

## 4.11 Bitki Profilleri Listeleme

### GET /api/bitki_profilleri
Tum bitki profillerini getirir.

Ornek yanit:

```json
[
  { "id": 1, "bitki_adi": "Domates", "ideal_nem_esigi": 45.0 },
  { "id": 2, "bitki_adi": "Biber", "ideal_nem_esigi": 40.0 }
]
```

## 4.12 Sulama Programi Ekleme

### POST /api/cihaz/{cihaz_id}/program_ekle
Cihaza sulama zamani ekler.

Request body:

```json
{
  "calisma_saati": "08:30",
  "calisma_suresi_dakika": 10
}
```

Basarili yanit:

```json
{
  "message": "Irrigation schedule added successfully."
}
```

## 4.13 Sulama Programlarini Listeleme

### GET /api/cihaz/{cihaz_id}/programlar
Cihaza ait programlari getirir.

Ornek yanit:

```json
[
  { "id": 1, "calisma_saati": "08:30", "sure": 10, "aktif": true }
]
```

## 4.14 Kullanici Bildirimleri

### GET /api/kullanici/{kullanici_id}/bildirimler
Kullanicinin son 20 bildirimini getirir (yeniden eskiye).

Ornek yanit:

```json
[
  {
    "baslik": "Otomatik Sulama Basladi",
    "mesaj": "Nem orani %28 seviyesine dustu. Valf otomatik olarak acildi.",
    "zaman": "23-03-2026 21:44"
  }
]
```

## 4.15 Manuel Valf Kontrolu

### POST /api/cihaz/{cihaz_id}/kontrol
Valfi ac/kapat komutu yollar.

Request body:

```json
{
  "komut": "VALF_AC"
}
```

Alternatif:

```json
{
  "komut": "VALF_KAPAT"
}
```

Basarili yanit:

```json
{
  "message": "Command VALF_AC sent to device."
}
```

Hata:
- `400`: Invalid command.
- `404`: Device not found.

Onemli teknik not:
- Komut MQTT'de ortak topic'e (`smart_irrigation/commands`) yayinlaniyor.
- Komut paketinde `cihaz_id` filtre bilgisi yok.
- Birden fazla cihaz ayni komut topic'ini dinliyorsa hepsi etkilenebilir.

## 5) Mobil Entegrasyon Akisi (Onerilen)

1. Uygulama acilisinda `POST /api/login` ile giris yapin.
2. Donen `kullanici_id` degerini saklayin.
3. Ana ekranda:
   - `GET /api/kullanici/{kullanici_id}/bolgeler`
   - `GET /api/kullanici/{kullanici_id}/cihazlar`
4. Cihaz detay ekraninda:
   - `GET /api/cihaz/{cihaz_id}/tam_durum`
   - `GET /api/cihaz/{cihaz_id}/gecmis?limit=50`
   - `GET /api/cihaz/{cihaz_id}/programlar`
5. Ayarlar ekraninda:
   - `POST /api/cihaz/{cihaz_id}/ayarlar`
   - `POST /api/cihaz/{cihaz_id}/ata`
6. Manuel kontrol butonlarinda:
   - `POST /api/cihaz/{cihaz_id}/kontrol`
7. Bildirim ekraninda:
   - `GET /api/kullanici/{kullanici_id}/bildirimler`

## 6) cURL Ornekleri

## Login

```bash
curl -X POST "https://<render-service-name>.onrender.com/api/login" \
  -H "Content-Type: application/json" \
  -d '{"kullanici_adi":"furkan","sifre":"123456"}'
```

## Cihaz Detay

```bash
curl "https://<render-service-name>.onrender.com/api/cihaz/esp32_01/tam_durum"
```

## Valf Ac

```bash
curl -X POST "https://<render-service-name>.onrender.com/api/cihaz/esp32_01/kontrol" \
  -H "Content-Type: application/json" \
  -d '{"komut":"VALF_AC"}'
```

## 7) Mobil Taraf Icin Kritik Notlar

- Ekran yenileme:
  - Cihaz listesi ve cihaz detayini periyodik (ornegin 5-10 saniye) yenileyin.
- Komut sonrasi dogrulama:
  - Komut gonderdikten sonra cihaz durumunu tekrar cekip (`tam_durum`) UI'yi dogrulayin.
- Dayaniklilik:
  - `404`, `401`, `422` durumlari icin anlamli hata mesaji gosterin.
- Guvenlik (mevcut durumda eksik):
  - API'de auth yok. Uretim icin JWT tabanli yetkilendirme eklenmesi onerilir.

## 8) Backend Davranis Ozeti (Mobil icin onemli)

- Cihaz sensor verisi MQTT ile geldiginde backend:
  - `cihaz_durumu` tablosunu gunceller,
  - `sensor_gecmisi` kaydi ekler,
  - otomatik sulama kosulu tutarsa `VALF_AC` komutu yollar,
  - kullaniciya bildirim olusturur.

Bu nedenle mobil tarafta "anlik" gorunumler REST ile alinmali, tutarlilik icin periyodik yenileme kullanilmalidir.
