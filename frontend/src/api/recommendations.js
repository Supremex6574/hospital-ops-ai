import api from './client'

export const getRecommendations = (params) => api.get('/recommendations', { params })
export const refreshRecommendations = () => api.post('/recommendations/refresh')
export const setRecommendationStatus = (id, status) => api.patch(`/recommendations/${id}`, { status })
