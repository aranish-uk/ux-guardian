"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { products, type Product } from "../lib/products";

const CART_KEY = "ux-guardian-demo-cart";
type Cart = Record<string, number>;

function readCart(): Cart {
  try {
    const data: unknown = JSON.parse(localStorage.getItem(CART_KEY) ?? "{}");
    if (!data || typeof data !== "object" || Array.isArray(data)) return {};
    return Object.fromEntries(Object.entries(data).filter(([id, qty]) =>
      products.some(product => product.id === id) && Number.isInteger(qty) && qty > 0 && qty <= 99));
  } catch { return {}; }
}

export function AddToCart({ product }: { product: Product }) {
  const [added, setAdded] = useState(false);
  function add() {
    const cart = readCart();
    cart[product.id] = Math.min(99, (cart[product.id] ?? 0) + 1);
    localStorage.setItem(CART_KEY, JSON.stringify(cart));
    setAdded(true);
  }
  return <><button type="button" onClick={add}>Add to cart</button>
    {added && <p role="status">Added to your cart. <Link href="/cart">View cart</Link></p>}</>;
}

export function CartContents() {
  const [cart, setCart] = useState<Cart>({});
  const [loaded, setLoaded] = useState(false);
  useEffect(() => { setCart(readCart()); setLoaded(true); }, []);
  const items = products.filter(product => cart[product.id]);
  return <section className="narrow"><p className="eyebrow">ONE STEP CLOSER</p><h1>Your cart</h1>
    {!loaded ? <p role="status">Loading your cart…</p> : items.length ? <>
      {items.map(product => <div className="cart-row" key={product.id}><span>{product.name}</span>
        <span>Qty {cart[product.id]} · ${product.price * cart[product.id]}</span></div>)}
      <p className="total">Total ${items.reduce((sum, product) => sum + product.price * cart[product.id], 0)}</p>
    </> : <p>Your cart is empty. <Link href="/products/everyday-tote">Find an Everyday tote</Link>.</p>}
    <Link className="button" href="/checkout">Checkout</Link>
  </section>;
}
