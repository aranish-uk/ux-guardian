import Link from "next/link";
import type { Product } from "../lib/products";

export default function ProductGrid({ items }: { items: readonly Product[] }) {
  return <div className="grid">{items.map(product => <article key={product.id}>
    <Link href={`/products/${product.id}`} aria-label={product.name}>
      <div className={`product-art ${product.color}`} aria-hidden="true">{product.icon}</div>
      <div className="product-label"><h3>{product.name}</h3><span>${product.price}</span></div>
    </Link><p className="muted">{product.category}</p>
  </article>)}</div>;
}
