import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = { title: "Everyday — UX Guardian demo", description: "Simple things, thoughtfully made." };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>
    <header><Link className="brand" href="/">everyday<span>®</span></Link>
      <nav aria-label="Main navigation"><Link href="/search">Shop</Link><Link href="/login">Sign in</Link><Link href="/cart">Cart ↗</Link></nav>
    </header>
    <main>{children}</main>
    <footer><span>Small things. Good days.</span><span>Demo store · No real orders or payments</span></footer>
  </body></html>;
}
