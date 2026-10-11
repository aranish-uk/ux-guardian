export default async function Login({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return <section className="narrow"><p className="eyebrow">GOOD TO SEE YOU</p><h1>Welcome back.</h1>
    <p>Sign in to your everyday account.</p>
    {error && <p role="alert">Unable to sign in with those details.</p>}
    <form action="/api/login" method="post"><label htmlFor="email">Email</label>
      <input id="email" name="email" type="email" autoComplete="username" required />
      <label htmlFor="password">Password</label><input id="password" name="password" type="password" autoComplete="current-password" required />
      <button type="submit">Sign in</button></form>
  </section>;
}
