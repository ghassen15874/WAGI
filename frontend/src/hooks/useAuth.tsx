import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { jwtDecode } from 'jwt-decode'
import axios from 'axios'

export interface User {
    id: string
    email: string
    role: string
    isActive: boolean
    githubConnected?: boolean
    githubUsername?: string
    planId?: string
    planName?: string
}

interface AuthContextType {
    user: User | null
    token: string | null
    loading: boolean
    login: (token: string, user: User) => void
    logout: () => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<User | null>(null)
    const [token, setToken] = useState<string | null>(null)
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        const storedToken = localStorage.getItem('access_token')
        if (storedToken) {
            try {
                const decoded: any = jwtDecode(storedToken)
                if (decoded.exp * 1000 < Date.now()) {
                    localStorage.removeItem('access_token')
                } else {
                    setToken(storedToken)
                    // Fetch user info
                    axios.get('/api/auth/me', {
                        headers: { Authorization: `Bearer ${storedToken}` }
                    }).then(res => {
                        setUser(res.data)
                        setLoading(false)
                    }).catch(() => {
                        localStorage.removeItem('access_token')
                        setToken(null)
                        setLoading(false)
                    })
                }
            } catch {
                localStorage.removeItem('access_token')
                setLoading(false)
            }
        } else {
            setLoading(false)
        }
    }, [])

    const login = (newToken: string, newUser: User) => {
        localStorage.setItem('access_token', newToken)
        setToken(newToken)
        setUser(newUser)
    }

    const logout = () => {
        localStorage.removeItem('access_token')
        setToken(null)
        setUser(null)
    }

    return (
        <AuthContext.Provider value={{ user, token, loading, login, logout }
        }>
            {children}
        </AuthContext.Provider>
    )
}

export function useAuth() {
    const context = useContext(AuthContext)
    if (context === undefined) {
        throw new Error('useAuth must be used within an AuthProvider')
    }
    return context
}
