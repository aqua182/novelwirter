import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'
import './fixes.css'
import './iteration.css'
import './runs.css'
import './models.css'
createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
