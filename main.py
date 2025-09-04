import requests
import time
import json
import sqlite3
import os
from datetime import datetime
from flask import Flask, request, jsonify
from threading import Thread

# ==================== CONFIGURAZIONE ====================
BOT_TOKEN = os.environ['BOT_TOKEN']
GHL_WEBHOOK_OUTBOUND_URL = "https://services.leadconnectorhq.com/hooks/Eop4pFJeMvQJHw7j4mRx/webhook-trigger/c90cf2cb-9343-4d03-8777-bea4ebbac702"
DB_FILE = "moduli_inviati.db"

GHL_API_KEY = os.environ.get('GHL_API_KEY', '')
GHL_LOCATION_ID = os.environ.get('GHL_LOCATION_ID', '')
# ========================================================

app = Flask(__name__)

# ==================== ROUTE PRINCIPALI ====================
@app.route('/')
def home():
    return "🤖 Bot Telegram GHL è online! Usa /webhook/ricevi_moduli per i webhook."

@app.route('/health')
def health_check():
    return jsonify({"status": "online", "timestamp": datetime.now().isoformat()})

@app.route('/webhook/ricevi_moduli', methods=['POST'])
def webhook_ricevi_moduli():
    """Endpoint che riceve i moduli da GHL"""
    try:
        data = request.json
        print(f"📨 WEBHOOK RICEVUTO: {json.dumps(data, indent=2)}")
        
        # Estrazione dati
        submission_id = data.get('submissionId') or data.get('id', f"modulo_{int(time.time())}")
        form_name = data.get('formName') or 'Modulo Sconosciuto'
        
        # Estrazione email cliente
        contact_email = None
        if data.get('contact') and data['contact'].get('email'):
            contact_email = data['contact']['email']
        elif data.get('email'):
            contact_email = data['email']
        
        # Estrazione nome cliente
        contact_name = 'Cliente'
        if data.get('contact') and data['contact'].get('name'):
            contact_name = data['contact']['name']
        elif data.get('name'):
            contact_name = data['name']
        
        if not contact_email:
            return jsonify({"status": "error", "message": "Email non trovata"}), 400
        
        # Salvataggio automatico
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        c.execute('''INSERT OR IGNORE INTO moduli_disponibili 
                    (submission_id, form_name, contact_email, contact_name, data_ricezione)
                    VALUES (?, ?, ?, ?, ?)''',
                 (submission_id, form_name, contact_email, contact_name, datetime.now()))
        
        conn.commit()
        print(f"✅ Modulo ricevuto: {form_name} - Cliente: {contact_email}")
        
        # TENTATIVO IMMEDIATO DI ASSEGNAZIONE AUTOMATICA
        assegna_modulo_disponibile()
        
        conn.close()
        return jsonify({"status": "success", "message": "Modulo ricevuto correttamente"}), 200
            
    except Exception as e:
        print(f"❌ Errore nel webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==================== FUNZIONI DATABASE ====================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS moduli_inviati
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  submission_id TEXT UNIQUE,
                  chat_id TEXT,
                  data_invio TIMESTAMP,
                  email_richiedente TEXT,
                  nome_modulo TEXT,
                  link_modulo TEXT,
                  email_cliente TEXT,
                  stato TEXT DEFAULT 'inviato')''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS richieste_attive
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  chat_id TEXT,
                  email_richiedente TEXT,
                  nome_richiedente TEXT,
                  data_richiesta TIMESTAMP,
                  stato TEXT DEFAULT 'attiva')''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS moduli_disponibili
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  submission_id TEXT UNIQUE,
                  form_name TEXT,
                  contact_email TEXT,
                  contact_name TEXT,
                  data_ricezione TIMESTAMP,
                  stato TEXT DEFAULT 'disponibile')''')
    
    conn.commit()
    conn.close()
    print("✅ Database inizializzato")

def assegna_modulo_disponibile():
    """Assegna automaticamente moduli disponibili ai richiedenti"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Trova il primo modulo disponibile
        c.execute('''SELECT submission_id, form_name, contact_email, contact_name 
                     FROM moduli_disponibili 
                     WHERE stato = 'disponibile' 
                     ORDER BY data_ricezione 
                     LIMIT 1''')
        modulo = c.fetchone()
        
        if not modulo:
            conn.close()
            return False
        
        submission_id, form_name, contact_email, contact_name = modulo
        
        # Trova il primo richiedente in attesa
        c.execute('''SELECT chat_id, email_richiedente, nome_richiedente 
                    FROM richieste_attive 
                    WHERE stato = 'attiva' 
                    ORDER BY data_richiesta 
                    LIMIT 1''')
        richiedente = c.fetchone()
        
        if not richiedente:
            conn.close()
            return False
        
        chat_id, email_richiedente, nome_richiedente = richiedente
        link_modulo = f"https://app.gohighlevel.com/submission/{submission_id}"
        
        # Invia il modulo
        messaggio = f"✅ **MODULO INVIATO A {nome_richiedente}!**\n\n"
        messaggio += f"📄 **Tipo:** {form_name}\n"
        messaggio += f"🔗 **Link:** {link_modulo}\n\n"
        messaggio += f"👤 **Cliente:** {contact_name}\n"
        messaggio += f"📧 **Email cliente:** {contact_email}\n"
        messaggio += f"💡 Salva questo link! Contiene i dati del cliente."
        
        if send_message(chat_id, messaggio):
            c.execute('''INSERT INTO moduli_inviati 
                        (submission_id, chat_id, data_invio, email_richiedente, nome_modulo, link_modulo, email_cliente)
                        VALUES (?, ?, ?, ?, ?, ?, ?)''',
                     (submission_id, chat_id, datetime.now(), email_richiedente, form_name, link_modulo, contact_email))
            
            c.execute('''UPDATE richieste_attive SET stato = 'completata' WHERE chat_id = ?''', (chat_id,))
            c.execute('''UPDATE moduli_disponibili SET stato = 'assegnato' WHERE submission_id = ?''', (submission_id,))
            
            conn.commit()
            print(f"✅ Modulo assegnato a {email_richiedente}")
            
            # Dopo aver assegnato un modulo, controlla se ce ne sono altri
            assegna_modulo_disponibile()
            
        else:
            print(f"❌ Errore invio messaggio a {chat_id}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Errore in assegna_modulo_disponibile: {e}")
        return False

def aggiungi_richiesta_attiva(chat_id, email_richiedente, nome_richiedente):
    """Aggiunge una richiesta e tenta immediatamente l'assegnazione"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('''INSERT OR REPLACE INTO richieste_attive 
                 (chat_id, email_richiedente, nome_richiedente, data_richiesta)
                 VALUES (?, ?, ?, ?)''', 
             (chat_id, email_richiedente.lower(), nome_richiedente, datetime.now()))
    
    conn.commit()
    conn.close()
    print(f"✅ Richiesta attiva aggiunta: {email_richiedente}")
    
    # TENTATIVO IMMEDIATO DI ASSEGNAZIONE AUTOMATICA
    assegna_modulo_disponibile()

def conta_richieste_in_attesa():
    """Conta le richieste in attesa"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''SELECT COUNT(*) FROM richieste_attive WHERE stato = 'attiva' ''')
    count = c.fetchone()[0]
    conn.close()
    return count

def conta_moduli_disponibili():
    """Conta i moduli disponibili"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''SELECT COUNT(*) FROM moduli_disponibili WHERE stato = 'disponibile' ''')
    count = c.fetchone()[0]
    conn.close()
    return count

# ==================== FUNZIONI TELEGRAM ====================
def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 30, "offset": offset}
    try:
        response = requests.get(url, params=params, timeout=35)
        return response.json()
    except Exception as e:
        print(f"⚠️ Timeout/Errore getUpdates: {e}")
        return {"result": []}

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=params, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Errore sendMessage: {e}")
        return False

def send_to_ghl(chat_id, email, nome):
    """Invia dati a GHL"""
    payload = {
        "telegram_chat_id": str(chat_id),
        "contact_email": email.lower(),
        "contact_name": nome,
        "location_id": GHL_LOCATION_ID
    }
    
    try:
        response = requests.post(GHL_WEBHOOK_OUTBOUND_URL, json=payload, timeout=15)
        print(f"📤 Webhook a GHL inviato - Status: {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Errore connessione GHL: {e}")
        return False

def process_update(update):
    if "message" not in update or "text" not in update["message"]:
        return
    
    chat_id = update["message"]["chat"]["id"]
    text = update["message"]["text"].strip()
    user_name = update["message"]["chat"].get("first_name", "Utente")
    
    print(f"📩 Richiesta da {user_name} ({chat_id}): {text}")
    
    if text == "/start":
        welcome_msg = f"👋 Ciao {user_name}! Sono il tuo assistente moduli 🤖\n\n"
        welcome_msg += "Scegli un'opzione:\n\n"
        welcome_msg += "📋 /richiedi - Richiedi un modulo compilato\n"
        welcome_msg += "📊 /stato - Verifica stato richieste\n"
        welcome_msg += "📞 /assistenza - Supporto tecnico"
        
        send_message(chat_id, welcome_msg)
    
    elif text == "/richiedi":
        send_message(chat_id, "📧 Inviami la tua email per registrare la richiesta:")
    
    elif text == "/stato":
        richieste_attive = conta_richieste_in_attesa()
        moduli_disponibili = conta_moduli_disponibili()
        
        messaggio = f"📊 **STATO SISTEMA**\n\n"
        messaggio += f"👥 Richieste attive: {richieste_attive}\n"
        messaggio += f"📦 Moduli disponibili: {moduli_disponibili}\n\n"
        
        if richieste_attive > 0:
            messaggio += f"⏳ Sei in posizione {richieste_attive} nella coda\n"
        else:
            messaggio += f"✅ Nessuna richiesta in attesa\n"
            
        send_message(chat_id, messaggio)
    
    elif text == "/assistenza":
        assistenza_msg = "📞 **ASSISTENZA TECNICA**\n\n"
        assistenza_msg += "• 📧 Email: metodospartano@wealthyenterprises.com\n"
        assistenza_msg += "• ⏰ Orari: Lun-Ven 9:00-18:00\n"
        assistenza_msg += "• 🚀 Supporto prioritario per clienti"
        send_message(chat_id, assistenza_msg)
    
    elif "@" in text and "." in text:
        email_richiedente = text.strip().lower()
        
        if send_to_ghl(chat_id, email_richiedente, user_name):
            aggiungi_richiesta_attiva(chat_id, email_richiedente, user_name)
            richieste_attive = conta_richieste_in_attesa()
            
            messaggio = f"✅ **RICHIESTA REGISTRATA!**\n\n"
            messaggio += f"👤 **Richiedente:** {user_name}\n"
            messaggio += f"📧 **Email:** {email_richiedente}\n"
            messaggio += f"📊 **Posizione in coda:** {richieste_attive}\n\n"
            messaggio += f"⏳ Appena arriva un nuovo modulo, te lo invierò automaticamente!"
            
            send_message(chat_id, messaggio)
        else:
            send_message(chat_id, "❌ Errore durante la registrazione. Riprova più tardi.")
    
    else:
        send_message(chat_id, "❌ Comando non riconosciuto. Usa /start per vedere le opzioni.")

def poll_telegram_updates():
    """Polling per gli aggiornamenti Telegram"""
    print("🤖 Avvio polling Telegram...")
    last_update_id = None
    
    while True:
        try:
            updates = get_updates(last_update_id)
            
            if "result" in updates and updates["result"]:
                for update in updates["result"]:
                    last_update_id = update["update_id"] + 1
                    process_update(update)
            
            time.sleep(1)
            
        except Exception as e:
            print(f"❌ Errore polling: {e}")
            time.sleep(5)

def main():
    init_db()
    
    print("🤖 Bot Moduli GHL AVVIATO!")
    print("📍 Location ID:", GHL_LOCATION_ID)
    print("🔑 API Key:", GHL_API_KEY[:10] + "..." if GHL_API_KEY else "Non impostata")
    print("🌐 Webhook attivo: /webhook/ricevi_moduli")
    print("🏠 Home page: /")
    print("❤️ Health check: /health")
    print("📩 Polling Telegram attivo")
    
    # Avvia Flask in thread separato
    flask_thread = Thread(target=lambda: app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False))
    flask_thread.daemon = True
    flask_thread.start()
    
    # Avvia polling Telegram
    poll_telegram_updates()

if __name__ == "__main__":
    main()
