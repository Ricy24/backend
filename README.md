# 💙 Senti — Backend

<div align="center">

![Django](https://img.shields.io/badge/Django-092E20?style=flat-square&logo=django&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)
![Django REST](https://img.shields.io/badge/Django%20REST-FF1745?style=flat-square)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-DC382D?style=flat-square&logo=redis&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-37B34E?style=flat-square)
![WebSocket](https://img.shields.io/badge/WebSocket-Channels-blue?style=flat-square)
![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat-square&logo=openai&logoColor=white)

</div>

> Backend en **Django REST** de **Senti**, plataforma de bienestar emocional que combina **Inteligencia Artificial** con profesionales de la psicología.

---

## 📋 Descripción

API que sostiene toda la plataforma Senti: autenticación con JWT, perfiles de usuarios y psicólogos, sesiones de terapia, comunidad, **chat con IA**, marketplace de paquetes, pagos, notificaciones y correos transaccionales — más integraciones con Google Calendar, Spotify, Telegram, WhatsApp y Cloudflare R2.

Está organizado como un conjunto de **apps modulares de Django**, cada una con sus modelos, serializers y rutas, lo que permite trabajar en cada módulo de forma independiente.

## ✨ Módulos

| App | Función |
|---|---|
| `api` | Usuarios, autenticación y API principal (JWT) |
| `user_profile` | Perfiles y configuración de cuenta |
| `psychologist` | Profesionales, agendas y gestión clínica |
| `therapy` | Sesiones, retos y seguimiento terapéutico |
| `plant` | Módulo de cuidado de plantas (gamificación) |
| `chat` | Chat en tiempo real con asistente de **IA** |
| `community` | Grupos y publicaciones de la comunidad |
| `notifications` | Notificaciones en tiempo real (Channels) |
| `pagos` | Pasarelas **PayU** y **Mercado Pago** |
| `packages` · `marketplace` | Paquetes de servicios y tienda |
| `emails` | Correos transaccionales (Brevo/Zoho) |
| `google_calendar` | Integración con Google Calendar |
| `spotify_insights` | Insights de Spotify para bienestar |
| `telegram_bot` · `whatsapp` | Bots y mensajería |
| `dashboard` | Métricas y panel de administración |
| `landing_api` · `invitations` | API pública del landing y invitaciones |

## 🛠️ Stack

- **Framework:** Django 4 · Django REST Framework · SimpleJWT
- **Tiempo real:** Channels (WebSocket) · Redis
- **Tareas asíncronas:** Celery
- **Base de datos:** PostgreSQL
- **Almacenamiento:** Cloudflare R2 (S3 / boto3)
- **IA:** Groq · OpenAI Whisper · Hugging Face · EdgeTTS
- **Documentos:** ReportLab (PDF)
- **Servidor ASGI:** Daphne / Uvicorn

## 🚀 Instalación

### Requisitos

- **Python 3.10+**
- **PostgreSQL 13+**
- **Redis**

### Pasos

```bash
git clone https://github.com/Ricy24/backend.git
cd backend

# Entorno virtual
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

# Dependencias
pip install -r requirements.txt
```

1. **Base de datos:** crea una base de datos en PostgreSQL (por ejemplo `psicologia`).

2. **Variables de entorno:** crea un archivo `.env` en la raíz (está en `.gitignore`):

```env
SECRET_KEY=tu-clave-secreta-larga
DEBUG=True

DB_NAME=psicologia
DB_USER=postgres
DB_PASSWORD=********
DB_HOST=localhost
DB_PORT=5432

FRONTEND_URL=http://localhost:5174
PUBLIC_BACKEND_URL=http://localhost:8000
```

3. **Migraciones y arranque:**

```bash
python manage.py migrate
python manage.py runserver
```

La API queda en `http://127.0.0.1:8000/` y el panel de administración en `http://127.0.0.1:8000/mY4dM1nP0rtal_92h!/`.

### Variables de entorno obligatorias

Se leen con `python-decouple` desde `.env`; **sin ellas la app no arranca**:

`GOOGLE_SECRET` · `GROQ_API_KEY` · `HUGGINGFACE_API_KEY` · `ZOHO_EMAIL_PASSWORD` · `BREVO_API_KEY` · `SPOTIFY_CLIENT_ID` · `SPOTIFY_CLIENT_SECRET` · `PAYU_ACCOUNT_ID` · `PAYU_API_KEY` · `PAYU_API_LOGIN` · `PAYU_MERCHANT_ID` · `PAYU_PUBLIC_KEY`

### Variables opcionales

`DEBUG` · `SECRET_KEY` · `DB_*` · `FRONTEND_URL` · `PUBLIC_BACKEND_URL` · `GOOGLE_CLIENT_ID` · `RECAPTCHA_PRIVATE_KEY` · `MP_PUBLIC_KEY` · `MP_ACCESS_TOKEN` · `ACTIVE_PAYMENT_PROVIDER` · `CLOUDFLARE_R2_*` · `TELEGRAM_BOT_TOKEN` · `TELEGRAM_WEBHOOK_SECRET` · `TELEGRAM_ADMIN_CHAT_ID` · `SPOTIFY_REDIRECT_URI` · `JITSI_JWT_SECRET` · `SECURE_*` · `SESSION_COOKIE_SECURE` · `CSRF_COOKIE_SECURE` · `BAILEYS_SERVICE_URL_ENV`

> El modelo de dependencias completo está en [`requirements2.txt`](requirements2.txt) y el de ML en [`requirements_ml.txt`](requirements_ml.txt).

## 📁 Estructura

```text
backend/
├── manage.py
├── backend/            # Proyecto Django (settings, urls, wsgi/asgi)
├── api/                # API principal y usuarios
├── therapy/ · psychologist/ · plant/   # Núcleo clínico
├── chat/               # Chat con IA
├── community/ · notifications/
├── pagos/ · packages/ · marketplace/
├── emails/ · google_calendar/ · spotify_insights/
├── telegram_bot/ · whatsapp/ · landing_api/
├── dashboard/ · user_profile/ · invitations/
├── model/              # Modelo de reconocimiento de voz (Kaldi/Whisper)
├── public/sounds/      # Audios de relajación
├── requirements.txt
├── .env                # ⚠️ Variables reales (NO se sube a git)
└── .gitignore
```

## 🔐 Seguridad

- **Ninguna credencial vive en el código**: todas se leen de `.env`, que está en `.gitignore`.
- Los archivos de servicio (`credentials*.json`, `serviceAccountKey.json`, `*.key`) fueron eliminados del repositorio y de su historial; si trabajas en local, vuelve a generarlos y guárdalos **fuera del repo**.
- Si alguna clave estuvo expuesta previamente, **rotala** antes de desplegar.

## 📄 Licencia

Proyecto desarrollado con **fines académicos**.
