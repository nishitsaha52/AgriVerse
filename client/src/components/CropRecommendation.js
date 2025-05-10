import React, { useState } from 'react';
import axios from 'axios';
import styles from '../AppStyles.module.css';

function CropRecommendation() {
  const [soilType, setSoilType] = useState('');
  const [temperature, setTemperature] = useState('');
  const [rainfall, setRainfall] = useState('');
  const [month, setMonth] = useState('');
  const [recommendation, setRecommendation] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    setLoading(true);
    setRecommendation('');
    try {
      const res = await axios.post('http://localhost:5002/recommend-crop', {
        soil_type: soilType,
        temperature: parseFloat(temperature),
        rainfall: parseFloat(rainfall),
        month: parseInt(month),
      });
      setRecommendation(res.data.recommended_crop);
    } catch (error) {
      console.error('Error recommending crop:', error);
      setRecommendation('Failed to get recommendation.');
    }
    setLoading(false);
  };

  return (
    <div className={styles.card}>
      <h2 className={styles.title}>Crop Recommendation</h2>

      <input
        placeholder="Soil Type"
        className={styles.input}
        value={soilType}
        onChange={(e) => setSoilType(e.target.value)}
      />
      <input
        placeholder="Temperature (°C)"
        className={styles.input}
        value={temperature}
        type="number"
        onChange={(e) => setTemperature(e.target.value)}
      />
      <input
        placeholder="Rainfall (mm)"
        className={styles.input}
        value={rainfall}
        type="number"
        onChange={(e) => setRainfall(e.target.value)}
      />
      <input
        placeholder="Month (1-12)"
        className={styles.input}
        value={month}
        type="number"
        onChange={(e) => setMonth(e.target.value)}
      />

      <button className={styles.button} onClick={handleSubmit}>
        Get Crop
      </button>

      {loading && <p className={styles.loading}>🔄 Fetching recommendation...</p>}

      {!loading && recommendation && (
        <div className={styles.result}>
          <h3 className={styles.resultHeader}>🌾 Recommended Crop</h3>
          <p><strong>{recommendation}</strong></p>
        </div>
      )}
    </div>
  );
}

export default CropRecommendation;