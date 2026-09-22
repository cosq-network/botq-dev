import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { getSession, login as loginRequest, logout as logoutRequest, type Session } from './api'

type Auth = { session: Session | null; loading: boolean; signIn: (payload: { email: string; password: string; organization?: string }) => Promise<void>; signOut: () => Promise<void>; hasScope: (scope: string) => boolean }
const AuthContext = createContext<Auth | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => { getSession().then(setSession).catch(() => setSession(null)).finally(() => setLoading(false)) }, [])
  const value = useMemo<Auth>(() => ({ session, loading, signIn: async (payload) => setSession(await loginRequest(payload)), signOut: async () => { await logoutRequest().catch(() => undefined); setSession(null); window.location.assign('/login') }, hasScope: (scope) => Boolean(session?.scopes.includes(scope) || session?.scopes.includes('*')) }), [session, loading])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
export const useAuth = () => { const value = useContext(AuthContext); if (!value) throw new Error('useAuth must be used within AuthProvider'); return value }
