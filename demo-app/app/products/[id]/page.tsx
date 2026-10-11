import { notFound } from "next/navigation";
import { AddToCart } from "../../../components/storefront";
import { products } from "../../../lib/products";

export default async function ProductPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const product = products.find(product => product.id === id);
  if (!product) notFound();
  return <section className="product-detail"><div className={`product-art ${product.color}`} aria-hidden="true">{product.icon}</div>
    <div><p className="eyebrow">{product.category}</p><h1>{product.name}</h1><p>{product.description}</p>
      <p className="price">${product.price}</p><AddToCart product={product} /></div></section>;
}
