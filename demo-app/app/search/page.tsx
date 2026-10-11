import ProductGrid from "../../components/product-grid";
import { products } from "../../lib/products";

export default async function Search({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const { q = "" } = await searchParams;
  const matches = products.filter(product => product.name.toLowerCase().includes(q.toLowerCase()));
  return <section><p className="eyebrow">THE COLLECTION</p><h1>Find your everyday.</h1>
    <form action="/search" className="search-form"><label htmlFor="q">Search products</label>
      <div className="inline"><input id="q" name="q" type="search" defaultValue={q} placeholder="Try tote, cup, or notebook" />
      <button type="submit">Search</button></div></form>
    {matches.length ? <ProductGrid items={matches} /> : <p role="status">No products found. Try another search.</p>}
  </section>;
}
