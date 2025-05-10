import React, { useState, useEffect } from 'react';
import axios from 'axios';
import styles from '../AppStyles.module.css'; // ✅ Using shared styles

function WeatherComponent() {
  const [city, setCity] = useState('');
  const [weather, setWeather] = useState(null);
  const [alert, setAlert] = useState('');
  const [loading, setLoading] = useState(false);

  const fetchWeather = async () => {
    if (!city) return;

    setLoading(true);
    setAlert('');
    try {
      const response = await axios.get(`http://localhost:5003/api/weather?city=${city}`);
      setWeather(response.data);
      checkWeatherAlert(response.data);
    } catch (error) {
      console.error('Error fetching weather:', error);
    }
    setLoading(false);
  };

  const checkWeatherAlert = (data) => {
    if (!data || !data.weather || data.weather.length === 0) return;

    const condition = data.weather[0].main.toLowerCase();
    const temp = data.main.temp;
    const humidity = data.main.humidity;
    const windSpeed = data.wind.speed;
    const alerts = [];

    if (condition.includes('rain')) {
      alerts.push('⚠️ Rain expected! Prepare for harvesting.');
    }
    if (condition.includes('snow') || temp < 3) {
      alerts.push('❄️ Frost alert! Protect your crops.');
    }
    if (temp > 35) {
      alerts.push('☀️ Heatwave warning! Irrigate sufficiently.');
    }
    if (condition.includes('haze') || condition.includes('mist') || condition.includes('fog')) {
      alerts.push('🌫️ Low visibility due to haze/fog! Take caution.');
    }
    if (humidity > 85) {
      alerts.push('⚠️ High humidity! Risk of fungal diseases on crops.');
    }
    if (windSpeed > 10) {
      alerts.push('💨 Strong winds expected! Secure your farm equipment.');
    }

    setAlert(alerts.join(' '));
  };

  useEffect(() => {
    const interval = setInterval(() => {
      if (city) {
        fetchWeather();
      }
    }, 10 * 60 * 1000); // every 10 minutes

    return () => clearInterval(interval);
  }, [city]);

  return (
    <div className={styles.container}>
      <h2 className={styles.title}>🌦 Weather</h2>
      
      <input
        type="text"
        placeholder="Enter City"
        value={city}
        onChange={(e) => setCity(e.target.value)}
        className={styles.input}
      />

      <button onClick={fetchWeather} className={styles.button}>
        {loading ? 'Loading...' : 'Get Weather'}
      </button>

      {alert && <div className={styles.alert}>{alert}</div>}

      {weather && (
        <div className={styles.card}>
          <h3>{weather.name}, {weather.sys.country}</h3>
          <p><strong>Temperature:</strong> {weather.main.temp} °C</p>
          <p><strong>Condition:</strong> {weather.weather[0].main} ({weather.weather[0].description})</p>
          <p><strong>Humidity:</strong> {weather.main.humidity}%</p>
          <p><strong>Wind Speed:</strong> {weather.wind.speed} m/s</p>
        </div>
      )}
    </div>
  );
}

export default WeatherComponent;
