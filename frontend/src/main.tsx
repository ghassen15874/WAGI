import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { AuthProvider } from './hooks/useAuth'
import { ThemeProvider } from './hooks/useTheme'
import { AppErrorBoundary } from './components/AppErrorBoundary'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
        <ThemeProvider>
            <AppErrorBoundary>
                <AuthProvider>
                    <BrowserRouter>
                        <App />
                    </BrowserRouter>
                </AuthProvider>
            </AppErrorBoundary>
        </ThemeProvider>
    </React.StrictMode>
)
