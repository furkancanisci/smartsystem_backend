import json
import threading
import uvicorn
import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
import os

# --- Ayarlar ---
MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883
TOPIC_SENSORS = "smart_irrigation/sensors"
TOPIC_COMMANDS = "smart_irrigation/commands"

# --- Render PostgreSQL Veritabanı Ayarları ---
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("KRİTİK HATA: DATABASE_URL ortam değişkeni bulunamadı! Lütfen Render.com panelinden ekleyin.")

# SQLAlchemy, Render'ın verdiği 'postgres://' linkini 'postgresql://' olarak bekler. Bu düzeltmeyi otomatik yapıyoruz.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Veritabanı Motoru (Sadece PostgreSQL)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Veritabanı Tabloları ---
class CihazDurumu(Base):
    __tablename__ = "cihaz_durumu"
    id = Column(Integer, primary_key=True, index=True)
    cihaz_id = Column(String, unique=True, index=True)
    toprak_nemi_yuzde = Column(Float, default=0.0)
    valf_durumu = Column(String, default="BİLİNMİYOR")
    son_guncelleme = Column(DateTime, default=datetime.utcnow)

class Kullanici(Base):
    __tablename__ = "kullanicilar"
    id = Column(Integer, primary_key=True, index=True)
    kullanici_adi = Column(String, unique=True, index=True)
    sifre = Column(String)

# Tabloları veritabanında oluştur
Base.metadata.create_all(bind=engine)

# --- FastAPI Uygulaması ---
app = FastAPI(title="Akıllı Sulama Sunucusu (Canlı Ortam)")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Veri Modelleri ---
class ValfKomutu(BaseModel):
    komut: str

class LoginIstegi(BaseModel):
    kullanici_adi: str
    sifre: str

# --- 1. MQTT İSTEMCİSİ (IoT Cihazı Dinleme) ---
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="FastAPI_Render_Canli_Sunucu")

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("✅ Sunucu MQTT Broker'a bağlandı. Cihazlar dinleniyor...")
        client.subscribe(TOPIC_SENSORS)
    else:
        print(f"❌ MQTT Bağlantı hatası, kod: {reason_code}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
        cihaz_id = payload.get("cihaz_id")
        nem = payload.get("toprak_nemi_yuzde", 0)
        valf = payload.get("valf_durumu", "BİLİNMİYOR")
        
        db = SessionLocal()
        cihaz = db.query(CihazDurumu).filter(CihazDurumu.cihaz_id == cihaz_id).first()
        if not cihaz:
            cihaz = CihazDurumu(cihaz_id=cihaz_id, toprak_nemi_yuzde=nem, valf_durumu=valf, son_guncelleme=datetime.utcnow())
            db.add(cihaz)
        else:
            cihaz.toprak_nemi_yuzde = nem
            cihaz.valf_durumu = valf
            cihaz.son_guncelleme = datetime.utcnow()
        db.commit()
        db.close()
        
        print(f"📥 [DB KAYDEDİLDİ] {cihaz_id}: Nem %{nem} | Valf: {valf}")
    except Exception as e:
        print(f"Hatalı veri paketi: {e}")

def mqtt_baslat():
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_forever()

threading.Thread(target=mqtt_baslat, daemon=True).start()

# --- 2. REST API UÇ NOKTALARI (Mobil Uygulama İçin) ---

@app.get("/")
def ana_sayfa():
    return {"mesaj": "Sunucu Aktif ve Çalışıyor!"}

@app.post("/api/login")
def login_yap(istek: LoginIstegi, db: Session = Depends(get_db)):
    kullanici = db.query(Kullanici).filter(Kullanici.kullanici_adi == istek.kullanici_adi).first()
    
    if not kullanici:
        yeni_kullanici = Kullanici(kullanici_adi=istek.kullanici_adi, sifre=istek.sifre)
        db.add(yeni_kullanici)
        db.commit()
        return {"mesaj": "Yeni kayıt oluşturuldu ve giriş yapıldı", "durum": "basarili"}
    
    if kullanici.sifre != istek.sifre:
        raise HTTPException(status_code=401, detail="Hatalı şifre girdiniz.")
        
    return {"mesaj": "Giriş başarılı", "durum": "basarili"}

@app.get("/api/cihaz/{cihaz_id}/durum")
def cihaz_durumu_getir(cihaz_id: str, db: Session = Depends(get_db)):
    cihaz = db.query(CihazDurumu).filter(CihazDurumu.cihaz_id == cihaz_id).first()
    if not cihaz:
        raise HTTPException(status_code=404, detail="Cihaz henüz veri göndermedi veya bulunamadı.")
    
    return {
        "cihaz_id": cihaz.cihaz_id,
        "toprak_nemi_yuzde": cihaz.toprak_nemi_yuzde,
        "valf_durumu": cihaz.valf_durumu,
        "son_guncelleme": cihaz.son_guncelleme.strftime("%d-%m-%Y %H:%M:%S")
    }

@app.post("/api/cihaz/{cihaz_id}/kontrol")
def cihaza_komut_gonder(cihaz_id: str, komut_verisi: ValfKomutu, db: Session = Depends(get_db)):
    cihaz = db.query(CihazDurumu).filter(CihazDurumu.cihaz_id == cihaz_id).first()
    if not cihaz:
        raise HTTPException(status_code=404, detail="Cihaz bulunamadı.")
    
    if komut_verisi.komut not in ["VALF_AC", "VALF_KAPAT"]:
        raise HTTPException(status_code=400, detail="Geçersiz komut.")

    mqtt_client.publish(TOPIC_COMMANDS, komut_verisi.komut)
    print(f"📤 [KOMUT İLETİLDİ] Cihaz: {cihaz_id} | Komut: {komut_verisi.komut}")
    
    return {"mesaj": f"Komut başarıyla cihaza iletildi: {komut_verisi.komut}"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Sunucu Başlatılıyor (Port: {port})...")
    uvicorn.run(app, host="0.0.0.0", port=port)