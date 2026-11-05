import api from './client'

export const getSimulationBaseline = () => api.get('/simulation/baseline')
// 60 s: the first run also fits the waiting-time model for each department
export const runSimulation = (body) => api.post('/simulation/run', body, { timeout: 60000 })
export const getSimulationHistory = () => api.get('/simulation/history')
export const getSimulationRun = (id) => api.get(`/simulation/history/${id}`)
export const deleteSimulationRun = (id) => api.delete(`/simulation/history/${id}`)
