import api from './client'

export const getForecastExplanation = (params) => api.get('/explain/forecast', { params })
