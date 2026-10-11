"use client";

import { useState } from "react";

export default function Checkout() {
  const [payment, setPayment] = useState(false);
  return <section className="narrow"><p className="eyebrow">CHECKOUT · {payment ? "STEP 2 OF 2" : "STEP 1 OF 2"}</p>
    {payment ? <><h1>Payment</h1><p>Payments are disabled in this demo.</p>
      <button type="button" disabled>Place order</button></> : <><h1>Where should it go?</h1>
      <form onSubmit={event => { event.preventDefault(); setPayment(true); }}>
        <label htmlFor="full-name">Full name</label><input id="full-name" autoComplete="name" required />
        <label htmlFor="street">Street address</label><input id="street" autoComplete="street-address" required />
        <label htmlFor="city">City</label><input id="city" autoComplete="address-level2" required />
        <label htmlFor="postal">Postal code</label><input id="postal" autoComplete="postal-code" required />
        <button type="submit">Continue to payment</button>
      </form></>}
  </section>;
}
