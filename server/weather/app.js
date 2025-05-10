require('dotenv').config();
const express = require('express');
const cors = require('cors');
const app = express();

app.use(cors());
app.use(express.json());

const weatherRoutes = require('./weather');
app.use('/api/weather', weatherRoutes);

app.get('/', (req, res) => {
  res.send('Backend server running...');
});

const PORT = process.env.PORT || 5003;
app.listen(PORT, () => {
  console.log(`Server is running at http://localhost:${PORT}`);
});