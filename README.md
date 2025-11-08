# 🌾 AgriVerse – Smart Agriculture Assistant

**AgriVerse** is a full-stack AI-powered agriculture platform that helps farmers and researchers make intelligent decisions by analyzing key parameters like **plant diseases**, **pest attacks**, **soil fertility**, **crop suitability**, and **weather alerts** — all in one unified dashboard.

---

## 🚀 Features

### 🌱 AI-Powered Modules
- **Plant Disease Detection** → Identify crop diseases from leaf images using CNN.  
- **Pest Detection** → Detect common pests and their risk levels.  
- **Soil Fertility Prediction** → Predict fertility category using NPK, pH, EC, etc.  
- **Crop Recommendation** → Suggest ideal crop based on soil and climate conditions.  
- **Weather Monitoring** → Get real-time weather alerts using OpenWeather API.

### 💡 Highlights
- Modular **Flask-based microservices** for each AI model  
- **React frontend** for user interaction  
- **Node.js backend** for weather APIs  
- **S3 integration** for centralized model storage  
- Fully **CORS-enabled REST APIs**  
- Ready for **Docker / Kubernetes** deployment  

---

## 🧱 Architecture Overview

```
          ┌───────────────────────────┐
          │        React UI           │
          │ (frontend/src/components) │
          └────────────┬──────────────┘
                       │
      ┌────────────────┼────────────────┐
      │                │                │
┌────────────┐  ┌────────────┐  ┌────────────┐
│ Flask:5000 │  │ Flask:5001 │  │ Flask:5002 │
│ Disease    │  │ Soil        │  │ Crop        │
│ Prediction │  │ Fertility   │  │ Recommender │
└────────────┘  └────────────┘  └────────────┘
       │                │                │
       └────────────────┼────────────────┘
                        │
               ┌────────▼────────┐
               │ Flask:5004      │
               │ Pest Detection  │
               └────────┬────────┘
                        │
                ┌───────▼────────┐
                │ Node.js:5003   │
                │ Weather API    │
                └────────────────┘
```

---

## 🧠 Tech Stack

| Layer | Technology | Description |
|--------|-------------|-------------|
| **Frontend** | React.js | User interface for farmers/researchers |
| **Backend APIs** | Flask (Python) | AI model inference services |
| **Weather Service** | Node.js + Express | Fetches real-time weather data |
| **Machine Learning** | TensorFlow, Scikit-learn | Core ML models |
| **Cloud Storage** | AWS S3 | Model file hosting |
| **Deployment** | Docker / Kubernetes | Scalable deployment options |

---

## ⚙️ Local Setup

### 1️⃣ Clone the Repository
```bash
git clone https://github.com/<your-username>/AgriVerse.git
cd AgriVerse
```

### 2️⃣ Backend Setup (Python Services)

Each service (Flask app) runs independently.

#### Common dependencies
```bash
pip install flask flask-cors tensorflow scikit-learn pillow boto3 numpy
```

#### Start services
```bash
# Terminal 1 - Plant Disease Detection
python server/plant_disease_app.py   # runs on port 5000

# Terminal 2 - Soil Fertility
python server/soil_app.py            # runs on port 5001

# Terminal 3 - Crop Recommendation
python server/crop_recommendation_app.py   # runs on port 5002

# Terminal 4 - Pest Detection
python server/pest_app.py            # runs on port 5004
```

### 3️⃣ Weather Backend (Node.js)

```bash
cd backend
npm install
```

Add your OpenWeather API key in `.env`:
```
OPENWEATHER_API_KEY=<your_api_key_here>
PORT=5003
```

Then run:
```bash
node server.js
```

### 4️⃣ Frontend (React App)

```bash
cd frontend
npm install
npm start
```

The React app will start at **http://localhost:3000**

---

## 🌍 API Endpoints

| Service | Endpoint | Method | Port |
|----------|-----------|--------|------|
| **Plant Disease Detection** | `/predict` | `POST` (file) | 5000 |
| **Soil Fertility Prediction** | `/soil-predict` | `POST` (JSON) | 5001 |
| **Crop Recommendation** | `/recommend-crop` | `POST` (JSON) | 5002 |
| **Pest Detection** | `/detect-pest` | `POST` (file) | 5004 |
| **Weather Info** | `/api/weather?city=CityName` | `GET` | 5003 |

---

## 📦 Model Management

Models are stored in AWS S3 and automatically downloaded using:

```bash
python server/download_models.py
```

It fetches the following files:
```
crop_recommendation_model.pkl
plant_pest_detection_model.h5
plant_disease_prediction_model.h5
soil_encoder.pkl
soil_fertility_model.h5
```

---

## 📊 Example Predictions

### 🌿 Plant Disease
**Input:** Leaf image  
**Output:**
```json
{
  "predicted_class": "Leaf Blight",
  "confidence": 94.5
}
```

### 🌾 Crop Recommendation
**Input:**
```json
{
  "soil_type": "Clay",
  "temperature": 28.5,
  "rainfall": 140,
  "month": 7
}
```
**Output:**
```json
{
  "recommended_crop": "Rice"
}
```

---

## 🧩 Project Structure

```
AgriVerse/
├── backend/                # Node.js Weather Service
│   ├── routes/weather.js
│   └── server.js
│
├── frontend/               # React UI
│   ├── src/components/
│   ├── App.js
│   └── AppStyles.module.css
│
├── server/                 # Flask microservices
│   ├── crop_recommendation_app.py
│   ├── pest_app.py
│   ├── soil_app.py
│   ├── plant_disease_app.py
│   └── download_models.py
│
└── models/ (optional local cache)
```

---

## 🧩 Future Enhancements
- 🌾 Integration with IoT soil/moisture sensors  
- ☁️ Deploy models on AWS Lambda or Kubernetes  
- 📈 Add historical data tracking using MongoDB/PostgreSQL  
- 🗺️ Build a farm dashboard showing combined analytics  
- 🧠 Add NLP-based farm advisory chatbot  

---

## 🤝 Contributing

1. Fork this repository  
2. Create your feature branch (`git checkout -b feature-name`)  
3. Commit your changes (`git commit -m "Add new feature"`)  
4. Push to branch (`git push origin feature-name`)  
5. Open a Pull Request  

---

## 💚 Acknowledgments

- [TensorFlow](https://www.tensorflow.org/)  
- [Scikit-learn](https://scikit-learn.org/)  
- [Flask](https://flask.palletsprojects.com/)  
- [React.js](https://reactjs.org/)  
- [OpenWeather API](https://openweathermap.org/)  
- [AWS S3](https://aws.amazon.com/s3/)  

---

> **Developed with ❤️ by Nishit Saha**
