import * as React from 'react'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api, ApiError } from '@/lib/api'
import { setToken } from '@/lib/auth'

/** Shape of the token payload returned by POST /api/v1/auth/login. */
interface LoginResponse {
  access_token: string
  token_type: string
}

/**
 * Public sign-in page. Collects email + password, exchanges them for a bearer
 * token, persists it, and routes to the app home. A 401 is surfaced inline as
 * an invalid-credentials message; any other failure shows the server message.
 */
export default function Login() {
  const navigate = useNavigate()
  const [email, setEmail] = React.useState('')
  const [password, setPassword] = React.useState('')

  const login = useMutation({
    mutationFn: () =>
      api.post<LoginResponse>('/api/v1/auth/login', { email, password }),
    onSuccess: (data) => {
      setToken(data.access_token)
      navigate('/', { replace: true })
    },
  })

  const errorMessage = resolveErrorMessage(login.error)

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (login.isPending) return
    login.mutate()
  }

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <div className="text-2xl font-bold tracking-tight text-foreground">
            Frigo<span className="text-[var(--sidebar-accent)]">Loco</span>
          </div>
          <div className="mt-1 text-xs text-muted-foreground">Forecasting &amp; Operations</div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Sign in</CardTitle>
            <CardDescription>Enter your credentials to access the planner.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="username"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  disabled={login.isPending}
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  disabled={login.isPending}
                />
              </div>

              {errorMessage ? (
                <p className="text-sm text-destructive" role="alert">
                  {errorMessage}
                </p>
              ) : null}

              <Button type="submit" className="mt-1 w-full" disabled={login.isPending}>
                {login.isPending ? 'Signing in…' : 'Sign in'}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

/** Map a login failure to a user-facing message (401 => invalid credentials). */
function resolveErrorMessage(error: unknown): string | null {
  if (!error) return null
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Invalid email or password'
    return error.message || 'Sign in failed. Please try again.'
  }
  return 'Sign in failed. Please try again.'
}
