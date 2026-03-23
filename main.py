import json
import threading
import uvicorn
import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship
import os

# --- Settings ---
MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883
TOPIC_SENSORS = "smart_irrigation/sensors"
TOPIC_COMMANDS = "smart_irrigation/commands"

# --- Render PostgreSQL Database Settings ---
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("CRITICAL ERROR: DATABASE_URL environment variable not found! Please add it from the Render.com panel.")

# SQLAlchemy expects 'postgresql://' instead of 'postgres://' provided by Render.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Database Engine Setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Database Tables (Expanded Architecture) ---

class Kullanici(Base):
    __tablename__ = "kullanicilar"
    id = Column(Integer, primary_key=True, index=True)
    kullanici_adi = Column(String, unique=True, index=True)
    sifre = Column(String)
    
    # Relationships
    bolgeler = relationship("Bolge", back_populates="sahip", cascade="all, delete-orphan")
    bildirimler = relationship("Bildirim", back_populates="kullanici", cascade="all, delete-orphan")

class Bolge(Base):
    __tablename__ = "bolgeler"
    id = Column(Integer, primary_key=True, index=True)
    kullanici_id = Column(Integer, ForeignKey("kullanicilar.id"))
    bolge_adi = Column(String) 
    
    # Relationships
    sahip = relationship("Kullanici", back_populates="bolgeler")
    cihazlar = relationship("CihazDurumu", back_populates="bolge")

class BitkiProfili(Base):
    __tablename__ = "bitki_profilleri"
    id = Column(Integer, primary_key=True, index=True)
    bitki_adi = Column(String, unique=True)
    ideal_nem_esigi = Column(Float)
    maksimum_nem = Column(Float)
    
    # Relationships
    cihazlar = relationship("CihazDurumu", back_populates="bitki_profili")

class CihazDurumu(Base):
    __tablename__ = "cihaz_durumu"
    id = Column(Integer, primary_key=True, index=True)
    cihaz_id = Column(String, unique=True, index=True)
    bolge_id = Column(Integer, ForeignKey("bolgeler.id"), nullable=True)
    bitki_profili_id = Column(Integer, ForeignKey("bitki_profilleri.id"), nullable=True)
    
    toprak_nemi_yuzde = Column(Float, default=0.0)
    valf_durumu = Column(String, default="KAPALI")
    otomatik_sulama_aktif = Column(Boolean, default=False)
    manuel_nem_esigi = Column(Float, default=30.0) 
    son_guncelleme = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    bolge = relationship("Bolge", back_populates="cihazlar")
    bitki_profili = relationship("BitkiProfili", back_populates="cihazlar")
    gecmis_veriler = relationship("SensorGecmisi", back_populates="cihaz", cascade="all, delete-orphan")
    sulama_programlari = relationship("SulamaProgrami", back_populates="cihaz", cascade="all, delete-orphan")

class SensorGecmisi(Base):
    __tablename__ = "sensor_gecmisi"
    id = Column(Integer, primary_key=True, index=True)
    cihaz_id = Column(String, ForeignKey("cihaz_durumu.cihaz_id"))
    toprak_nemi_yuzde = Column(Float)
    valf_durumu = Column(String)
    kayit_zamani = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    cihaz = relationship("CihazDurumu", back_populates="gecmis_veriler")

class SulamaProgrami(Base):
    __tablename__ = "sulama_programlari"
    id = Column(Integer, primary_key=True, index=True)
    cihaz_id = Column(String, ForeignKey("cihaz_durumu.cihaz_id"))
    calisma_saati = Column(String) 
    calisma_suresi_dakika = Column(Integer, default=10)
    aktif_mi = Column(Boolean, default=True)
    
    # Relationships
    cihaz = relationship("CihazDurumu", back_populates="sulama_programlari")

class Bildirim(Base):
    __tablename__ = "bildirimler"
    id = Column(Integer, primary_key=True, index=True)
    kullanici_id = Column(Integer, ForeignKey("kullanicilar.id"))
    baslik = Column(String)
    mesaj = Column(Text)
    okundu_mu = Column(Boolean, default=False)
    olusturulma_zamani = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    kullanici = relationship("Kullanici", back_populates="bildirimler")

# Create all tables in the database
Base.metadata.create_all(bind=engine)

# --- FastAPI Application ---
app = FastAPI(title="Advanced Smart Irrigation Server")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Data Models for API ---
class ValfKomutu(BaseModel):
    komut: str

class LoginIstegi(BaseModel):
    kullanici_adi: str
    sifre: str

class CihazAyarIstegi(BaseModel):
    otomatik_sulama_aktif: bool
    nem_esigi: float

class BolgeEkleIstegi(BaseModel):
    kullanici_id: int
    bolge_adi: str

class BitkiProfiliEkleIstegi(BaseModel):
    bitki_adi: str
    ideal_nem_esigi: float
    maksimum_nem: float

class CihazAtamaIstegi(BaseModel):
    bolge_id: int
    bitki_profili_id: int

class SulamaProgramiEkleIstegi(BaseModel):
    calisma_saati: str
    calisma_suresi_dakika: int

# --- 1. MQTT CLIENT ---
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="FastAPI_Render_Advanced_Server")

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("✅ Server connected to MQTT Broker. Listening to devices...")
        client.subscribe(TOPIC_SENSORS)
    else:
        print(f"❌ MQTT Connection error, code: {reason_code}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
        gelen_cihaz_id = payload.get("cihaz_id")
        nem = payload.get("toprak_nemi_yuzde", 0)
        valf = payload.get("valf_durumu", "BİLİNMİYOR")
        
        db = SessionLocal()
        cihaz = db.query(CihazDurumu).filter(CihazDurumu.cihaz_id == gelen_cihaz_id).first()
        
        if not cihaz:
            cihaz = CihazDurumu(cihaz_id=gelen_cihaz_id, toprak_nemi_yuzde=nem, valf_durumu=valf, son_guncelleme=datetime.utcnow())
            db.add(cihaz)
            db.commit()
            db.refresh(cihaz)
        else:
            cihaz.toprak_nemi_yuzde = nem
            cihaz.valf_durumu = valf
            cihaz.son_guncelleme = datetime.utcnow()
            db.commit()
            
        # Log data to history table for charts
        gecmis_kayit = SensorGecmisi(cihaz_id=gelen_cihaz_id, toprak_nemi_yuzde=nem, valf_durumu=valf, kayit_zamani=datetime.utcnow())
        db.add(gecmis_kayit)
        
        # Determine the active threshold (from plant profile or manual setting)
        aktif_esik = cihaz.bitki_profili.ideal_nem_esigi if cihaz.bitki_profili else cihaz.manuel_nem_esigi
        
        # Trigger automatic irrigation if needed
        if cihaz.otomatik_sulama_aktif and nem < aktif_esik and valf == "KAPALI":
            mqtt_client.publish(TOPIC_COMMANDS, "VALF_AC")
            print(f"💧 [AUTO IRRIGATION] Moisture below threshold. Opening valve for {gelen_cihaz_id}")
            
            # Create a notification for the user
            if cihaz.bolge and cihaz.bolge.kullanici_id:
                yeni_bildirim = Bildirim(
                    kullanici_id=cihaz.bolge.kullanici_id, 
                    baslik="Otomatik Sulama Başladı", 
                    mesaj=f"Nem oranı %{nem} seviyesine düştü. Valf otomatik olarak açıldı."
                )
                db.add(yeni_bildirim)
                
        db.commit()
        db.close()
        print(f"📥 [SAVED] {gelen_cihaz_id}: Moisture %{nem} | Valve: {valf}")
    except Exception as e:
        print(f"Invalid data packet: {e}")

def mqtt_baslat():
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_forever()

threading.Thread(target=mqtt_baslat, daemon=True).start()

# --- 2. REST API ENDPOINTS ---

@app.get("/")
def ana_sayfa():
    return {"message": "Advanced Smart Irrigation Server is Active!"}

@app.post("/api/login")
def login_yap(istek: LoginIstegi, db: Session = Depends(get_db)):
    kullanici = db.query(Kullanici).filter(Kullanici.kullanici_adi == istek.kullanici_adi).first()
    if not kullanici:
        yeni_kullanici = Kullanici(kullanici_adi=istek.kullanici_adi, sifre=istek.sifre)
        db.add(yeni_kullanici)
        db.commit()
        db.refresh(yeni_kullanici)
        return {"message": "New user registered and logged in.", "kullanici_id": yeni_kullanici.id, "status": "success"}
    
    if kullanici.sifre != istek.sifre:
        raise HTTPException(status_code=401, detail="Invalid password.")
    
    return {"message": "Login successful.", "kullanici_id": kullanici.id, "status": "success"}

# --- NEW API: Get all devices belonging to a user ---
@app.get("/api/kullanici/{kullanici_id}/cihazlar")
def kullanici_cihazlarini_getir(kullanici_id: int, db: Session = Depends(get_db)):
    bolgeler = db.query(Bolge).filter(Bolge.kullanici_id == kullanici_id).all()
    cihazlar = []
    for bolge in bolgeler:
        for cihaz in bolge.cihazlar:
            cihazlar.append({
                "cihaz_id": cihaz.cihaz_id,
                "bolge_adi": bolge.bolge_adi,
                "toprak_nemi_yuzde": cihaz.toprak_nemi_yuzde,
                "valf_durumu": cihaz.valf_durumu
            })
    return cihazlar

# --- NEW API: Get all regions belonging to a user ---
@app.get("/api/kullanici/{kullanici_id}/bolgeler")
def kullanici_bolgelerini_getir(kullanici_id: int, db: Session = Depends(get_db)):
    bolgeler = db.query(Bolge).filter(Bolge.kullanici_id == kullanici_id).all()
    return [{"id": b.id, "bolge_adi": b.bolge_adi} for b in bolgeler]

@app.get("/api/cihaz/{cihaz_id}/tam_durum")
def cihaz_tam_durum_getir(cihaz_id: str, db: Session = Depends(get_db)):
    cihaz = db.query(CihazDurumu).filter(CihazDurumu.cihaz_id == cihaz_id).first()
    if not cihaz:
        raise HTTPException(status_code=404, detail="Device not found.")
    
    return {
        "cihaz_id": cihaz.cihaz_id,
        "bolge": cihaz.bolge.bolge_adi if cihaz.bolge else "Atanmamış",
        "bitki_turu": cihaz.bitki_profili.bitki_adi if cihaz.bitki_profili else "Özel Ayar",
        "toprak_nemi_yuzde": cihaz.toprak_nemi_yuzde,
        "valf_durumu": cihaz.valf_durumu,
        "otomatik_sulama": cihaz.otomatik_sulama_aktif,
        "hedef_nem_esigi": cihaz.bitki_profili.ideal_nem_esigi if cihaz.bitki_profili else cihaz.manuel_nem_esigi,
        "son_guncelleme": cihaz.son_guncelleme.strftime("%d-%m-%Y %H:%M:%S")
    }

@app.get("/api/cihaz/{cihaz_id}/gecmis")
def cihaz_gecmisi_getir(cihaz_id: str, limit: int = 50, db: Session = Depends(get_db)):
    gecmis = db.query(SensorGecmisi).filter(SensorGecmisi.cihaz_id == cihaz_id).order_by(SensorGecmisi.kayit_zamani.desc()).limit(limit).all()
    if not gecmis:
        return []
    
    return [{"nem": kayit.toprak_nemi_yuzde, "valf": kayit.valf_durumu, "zaman": kayit.kayit_zamani.strftime("%H:%M")} for kayit in gecmis]

@app.post("/api/cihaz/{cihaz_id}/ayarlar")
def cihaz_ayarlarini_guncelle(cihaz_id: str, ayarlar: CihazAyarIstegi, db: Session = Depends(get_db)):
    cihaz = db.query(CihazDurumu).filter(CihazDurumu.cihaz_id == cihaz_id).first()
    if not cihaz:
        raise HTTPException(status_code=404, detail="Device not found.")
        
    cihaz.otomatik_sulama_aktif = ayarlar.otomatik_sulama_aktif
    cihaz.manuel_nem_esigi = ayarlar.nem_esigi
    db.commit()
    return {"message": "Device settings updated successfully."}

# --- NEW API: Assign device to a region and plant profile ---
@app.post("/api/cihaz/{cihaz_id}/ata")
def cihaz_ata(cihaz_id: str, atama: CihazAtamaIstegi, db: Session = Depends(get_db)):
    cihaz = db.query(CihazDurumu).filter(CihazDurumu.cihaz_id == cihaz_id).first()
    if not cihaz:
        raise HTTPException(status_code=404, detail="Device not found.")
        
    cihaz.bolge_id = atama.bolge_id
    cihaz.bitki_profili_id = atama.bitki_profili_id
    db.commit()
    return {"message": "Device successfully assigned to region and plant profile."}

@app.post("/api/bolge/ekle")
def bolge_ekle(istek: BolgeEkleIstegi, db: Session = Depends(get_db)):
    yeni_bolge = Bolge(kullanici_id=istek.kullanici_id, bolge_adi=istek.bolge_adi)
    db.add(yeni_bolge)
    db.commit()
    return {"message": f"Region '{istek.bolge_adi}' created successfully."}

# --- NEW API: Add a new plant profile ---
@app.post("/api/bitki_profili/ekle")
def bitki_profili_ekle(istek: BitkiProfiliEkleIstegi, db: Session = Depends(get_db)):
    yeni_profil = BitkiProfili(bitki_adi=istek.bitki_adi, ideal_nem_esigi=istek.ideal_nem_esigi, maksimum_nem=istek.maksimum_nem)
    db.add(yeni_profil)
    db.commit()
    return {"message": f"Plant profile '{istek.bitki_adi}' added successfully."}

# --- NEW API: Get all plant profiles ---
@app.get("/api/bitki_profilleri")
def bitki_profilleri_getir(db: Session = Depends(get_db)):
    profiller = db.query(BitkiProfili).all()
    return [{"id": p.id, "bitki_adi": p.bitki_adi, "ideal_nem_esigi": p.ideal_nem_esigi} for p in profiller]

# --- NEW API: Add an irrigation schedule ---
@app.post("/api/cihaz/{cihaz_id}/program_ekle")
def sulama_programi_ekle(cihaz_id: str, istek: SulamaProgramiEkleIstegi, db: Session = Depends(get_db)):
    yeni_program = SulamaProgrami(cihaz_id=cihaz_id, calisma_saati=istek.calisma_saati, calisma_suresi_dakika=istek.calisma_suresi_dakika)
    db.add(yeni_program)
    db.commit()
    return {"message": "Irrigation schedule added successfully."}

# --- NEW API: Get irrigation schedules for a device ---
@app.get("/api/cihaz/{cihaz_id}/programlar")
def sulama_programlari_getir(cihaz_id: str, db: Session = Depends(get_db)):
    programlar = db.query(SulamaProgrami).filter(SulamaProgrami.cihaz_id == cihaz_id).all()
    return [{"id": p.id, "calisma_saati": p.calisma_saati, "sure": p.calisma_suresi_dakika, "aktif": p.aktif_mi} for p in programlar]

@app.get("/api/kullanici/{kullanici_id}/bildirimler")
def kullanici_bildirimleri_getir(kullanici_id: int, db: Session = Depends(get_db)):
    bildirimler = db.query(Bildirim).filter(Bildirim.kullanici_id == kullanici_id).order_by(Bildirim.olusturulma_zamani.desc()).limit(20).all()
    return [{"baslik": b.baslik, "mesaj": b.mesaj, "zaman": b.olusturulma_zamani.strftime("%d-%m-%Y %H:%M")} for b in bildirimler]

@app.post("/api/cihaz/{cihaz_id}/kontrol")
def cihaza_komut_gonder(cihaz_id: str, komut_verisi: ValfKomutu, db: Session = Depends(get_db)):
    cihaz = db.query(CihazDurumu).filter(CihazDurumu.cihaz_id == cihaz_id).first()
    if not cihaz:
        raise HTTPException(status_code=404, detail="Device not found.")
    if komut_verisi.komut not in ["VALF_AC", "VALF_KAPAT"]:
        raise HTTPException(status_code=400, detail="Invalid command.")

    mqtt_client.publish(TOPIC_COMMANDS, komut_verisi.komut)
    return {"message": f"Command {komut_verisi.komut} sent to device."}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Advanced Server Starting (Port: {port})...")
    uvicorn.run(app, host="0.0.0.0", port=port)