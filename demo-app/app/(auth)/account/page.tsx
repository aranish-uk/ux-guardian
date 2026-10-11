import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import Link from "next/link";
import { validSession } from "../../../lib/session";

export default async function Account() {
  if (!validSession((await cookies()).get("ux-session")?.value)) redirect("/login");
  return <section className="narrow"><p className="eyebrow">WELCOME HOME</p><h1>Your account</h1>
    <p>You’re signed in. Find something that makes your day a little better.</p>
    <Link className="button" href="/search">Explore the collection ↗</Link></section>;
}
