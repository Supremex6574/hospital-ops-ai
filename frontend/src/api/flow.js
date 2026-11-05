import api from './client'

export const getFlow = (params) => api.get('/flow/overview', { params })
