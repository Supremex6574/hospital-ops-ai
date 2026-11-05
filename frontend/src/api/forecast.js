import api from './client'

export const getForecast = (params) => api.get('/forecast/overview', { params })
export const retrainForecast = (params) => api.post('/forecast/retrain', null, { params })
