import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles.css'
import './ui.css'

const root = document.getElementById('root')
if (!root) throw new Error('Finance AI root element was not found.')

ReactDOM.createRoot(root).render(
  <React.StrictMode><App /></React.StrictMode>,
)
