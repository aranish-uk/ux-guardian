import Link from "next/link";
import { products } from "../lib/products";
import ProductGrid from "../components/product-grid";

export default function Home() {
  return <><section className="hero"><p className="eyebrow">LESS, BUT BETTER</p>
    <h1>Made for<br />your everyday.</h1><p>Useful things. Thoughtful details. A little joy in the ordinary.</p>
    <Link className="button" href="/search">Explore the collection ↗</Link>
  </section><section><div className="section-heading"><h2>The essentials</h2><span>Three good things to start with</span></div>
    <ProductGrid items={products} /></section></>;
}
