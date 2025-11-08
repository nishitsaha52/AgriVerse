// backend/routes/weather.js
const express = require('express');
const axios = require('axios');
const router = express.Router();

const OPENWEATHER_API_KEY = '<Replace it with real key>';

// GET /api/weather?city=Mumbai
router.get('/', async (req, res) => {
  const { city } = req.query;
  if (!city) return res.status(400).json({ error: 'City is required' });

  try {
    const response = await axios.get(
      `https://api.openweathermap.org/data/2.5/weather?q=${city}&appid=${OPENWEATHER_API_KEY}&units=metric`
    );
    res.json(response.data);
  } catch (error) {
    console.error(error.message);
    res.status(500).json({ error: 'Failed to fetch weather' });
  }
});

module.exports = router;
