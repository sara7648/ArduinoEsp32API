from flask import Flask, request, jsonify
import requests
import os
from datetime import datetime
import time # נדרש עבור פקודת ה-sleep

app = Flask(__name__)

# ===== CONFIGURATION =====
# Arduino Cloud API Configuration
ARDUINO_CLIENT_ID = os.environ.get('ARDUINO_CLIENT_ID', 'your_client_id')
ARDUINO_CLIENT_SECRET = os.environ.get('ARDUINO_CLIENT_SECRET', 'your_client_secret')
ARDUINO_THING_ID = os.environ.get('ARDUINO_THING_ID', 'your_thing_id')

# Google Sheets Configuration
# הגדר משתנה סביבה זה ב-Render/Railway!
GOOGLE_SCRIPT_URL = os.environ.get('GOOGLE_SCRIPT_URL', 'https://script.google.com/macros/s/XXXXX/exec')

# Variable names from your Arduino Cloud Thing
RELAY_VARIABLE = "relayStatus" # שם המשתנה מתוך thingProperties.h
DISTANCE_VARIABLE = "distance_cm"

# מנגנון שמירת טוקן זמנית
_arduino_token = {"value": None, "expiry": 0} 


# ===== ARDUINO CLOUD API FUNCTIONS =====

def get_arduino_token():
    """Get OAuth2 token from Arduino Cloud (cached)"""
    global _arduino_token
    
    # בדיקה אם הטוקן עדיין בתוקף
    if _arduino_token["value"] and _arduino_token["expiry"] > time.time():
        return _arduino_token["value"]

    # אם לא, נדרש טוקן חדש
    url = "https://api2.arduino.cc/iot/v1/clients/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": ARDUINO_CLIENT_ID,
        "client_secret": ARDUINO_CLIENT_SECRET,
        "audience": "https://api2.arduino.cc/iot"
    }
    try:
        response = requests.post(url, json=data)
        response.raise_for_status() # Raise an exception for bad status codes
        
        token_data = response.json()
        token = token_data['access_token']
        expires_in = token_data.get('expires_in', 3600) # 1 hour default
        
        # שמירת הטוקן עם פקיעה של 5 דקות פחות מהזמן האמיתי
        _arduino_token["value"] = token
        _arduino_token["expiry"] = time.time() + expires_in - 300 
        
        return token
    except requests.exceptions.RequestException as e:
        print(f"Error getting Arduino token: {e}")
        return None

def get_arduino_property(property_name):
    """Get current value of an Arduino Cloud property"""
    token = get_arduino_token()
    if not token: return None
    
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://api2.arduino.cc/iot/v2/things/{ARDUINO_THING_ID}/properties/{property_name}"
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json().get('value', response.json().get('last_value'))
    except requests.exceptions.RequestException as e:
        print(f"Error getting property {property_name}: {e}")
        return None

def set_arduino_property(property_name, value):
    """Set value of an Arduino Cloud property"""
    token = get_arduino_token()
    if not token: return False
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    # שימוש ב-publish כדי להבטיח שהארדואינו יגיב מיד
    url = f"https://api2.arduino.cc/iot/v2/things/{ARDUINO_THING_ID}/properties/{property_name}/publish"
    
    data = {"value": value}
    try:
        response = requests.put(url, json=data, headers=headers)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error setting property {property_name}: {e}")
        return False

# ===== GOOGLE SHEETS FUNCTIONS =====

def get_allowed_users_from_sheet():
    """Fetch the list of allowed users from Google Sheets via Apps Script API."""
    try:
        response = requests.get(GOOGLE_SCRIPT_URL)
        response.raise_for_status() # Raise an exception for bad status codes
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from Google Sheets: {e}")
        return []

# ===== YEMOT API HELPERS =====
def is_authorized(phone):
    """Check if phone number is authorized based on Google Sheet data"""
    users = get_allowed_users_from_sheet()
    
    # ניקוי פורמט הטלפון (מומלץ)
    cleaned_phone = phone.strip().replace('-', '').replace(' ', '')
    
    for user in users:
        # 1. ניקוי פורמט הטלפון בגיליון
        sheet_phone = user.get('phone', '').strip().replace('-', '').replace(' ', '')
        
        # 2. בדיקת התאמה (כולל מקרה בו ימות המשיח שולח 05X והגיליון 9725X)
        is_match = (cleaned_phone == sheet_phone or cleaned_phone.endswith(sheet_phone) or sheet_phone.endswith(cleaned_phone))
        
        # 3. בדיקת הרשאה (נדרש שהערך יהיה TRUE בגיליון)
        is_allowed = user.get('allowed') == True
        
        if is_match and is_allowed:
            return user # מחזיר את כל אובייקט המשתמש (כולל שם)
            
    return None # לא מורשה

def yemot_response(actions):
    """Format response for Yemot Hamashiach (INI format)"""
    # Yemot expects response in format: action1=value1&action2=value2
    # נחזיר כאן קובץ INI פשוט (Text/Plain)
    response_lines = []
    
    for k, v in actions.items():
        response_lines.append(f"{k}={v}")
    
    return '\n'.join(response_lines)

# ===== YEMOT API ENDPOINTS =====
@app.route('/yemot/control', methods=['GET', 'POST'])
def yemot_control():
    """Main endpoint for Yemot Hamashiach control menu"""
    
    phone = request.args.get('ApiPhone', '')
    digits = request.args.get('ApiDIGITS', '')
    call_id = request.args.get('ApiCallId', '')
    
    print(f"[{datetime.now()}] Call from {phone}, Digits: {digits}")
    
    # 1. Check authorization against Google Sheets
    user = is_authorized(phone)
    
    if not user:
        return yemot_response({
            't-say-text': 'מספרך אינו מורשה. להתראות.',
            'go_to_folder': '/0'
        })
    
    # 2. Authorization Granted - Welcome Message / Menu
    
    # Main menu - no digits yet
    if not digits:
        welcome_message = f't-say-text=שלום {user["name"]}. לחץ 1 לשליטה בממסר, 2 לקריאת מרחק, 9 לניתוק.'
        return yemot_response({
            'read': welcome_message,
            'id_list_visible': '1,2,9',
            'id_list_tap_go': f'1={request.base_url}/relay,2={request.base_url}/distance,9=go_to_folder=/0'
        })
        
    return yemot_response({'go_to_folder': '/0'})

@app.route('/yemot/relay', methods=['GET', 'POST'])
def yemot_relay():
    """Relay control submenu: Toggles the relay for 3 seconds (simulating gate pulse)"""
    
    phone = request.args.get('ApiPhone', '')
    
    # בדיקת הרשאה (מיותרת אם מגיעים רק מ-/yemot/control אבל מומלץ לאבטחה)
    if not is_authorized(phone):
        return yemot_response({'go_to_folder': '/0'})
        
    # 1. הפעלת הממסר ל-3 שניות
    # שולח פקודה True
    set_arduino_property(RELAY_VARIABLE, 1) # 1 for True in Arduino
    
    # משך זמן ההפעלה: לא ניתן לבצע sleep כאן (יחסום את השרת), 
    # לכן נסתמך על קוד הארדואינו שיכבה את עצמו לאחר 3 שניות (פונקציה onRelayStatusChange() בארדואינו).
    # במקרה שאין כיבוי אוטומטי בארדואינו, נדרש שירות ענן נוסף (Worker) לכיבוי. 
    # כרגע נניח כיבוי עצמי בארדואינו.

    # 2. החזרת תשובה לימות המשיח
    return yemot_response({
        't-say-text': 'מפעיל את הממסר למשך שלוש שניות. להתראות.',
        'go_to_folder': '/0'
    })


@app.route('/yemot/distance', methods=['GET', 'POST'])
def yemot_distance():
    """Get distance sensor reading and read it back to the user"""
    
    phone = request.args.get('ApiPhone', '')
    
    if not is_authorized(phone):
        return yemot_response({'go_to_folder': '/0'})
    
    distance = get_arduino_property(DISTANCE_VARIABLE)
    
    if distance is not None:
        # Yemot supports reading numbers with n- prefix
        # We assume distance is an integer for reading
        return yemot_response({
            't-say-text': f'המרחק הנמדד הוא. n-{int(distance)}. סנטימטרים.',
            'go_to_folder': '/0'
        })
    else:
        return yemot_response({
            't-say-text': 'שגיאה בקריאת נתונים מהארדואינו.',
            'go_to_folder': '/0'
        })


# ===== MONITORING AND HEALTH CHECK ENDPOINTS =====
@app.route('/monitor', methods=['GET'])
def monitor():
    """Monitor endpoint to check Arduino connection"""
    
    relay_status = get_arduino_property(RELAY_VARIABLE)
    distance = get_arduino_property(DISTANCE_VARIABLE)
    
    return jsonify({
        "status": "online",
        "relay_status": relay_status,
        "distance_cm": distance,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/', methods=['GET'])
def home():
    """Health check endpoint"""
    return jsonify({
        "status": "running",
        "service": "Yemot-Arduino Sheets Integration",
        "endpoints": {
            "control": "/yemot/control",
            "monitor": "/monitor"
        }
    })

if __name__ == '__main__':
    # Use gunicorn or similar server in production. For local testing:
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
